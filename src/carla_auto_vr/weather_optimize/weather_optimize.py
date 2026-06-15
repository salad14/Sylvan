#!/usr/bin/env python3
# -*- coding: utf-8 -*- 
"""
CARLA + YOLO + Optuna 完整闭环（远程桥接模式版本）

运行模式：
通过 TCP 连接 `carla_bridge_server.py`（Python 3.7）获取图像，
在高版本 Python (3.10+) 环境中运行 YOLO 和 Optuna，解决版本冲突。

支持两种训练模式：
- maximize: 正向筛选，提高YOLO识别置信度（让车辆更清晰）
- minimize: 反向筛选，降低YOLO识别置信度（让车辆难以识别）

用法：
  # 步骤1：在 Python 3.7 环境启动桥接服务
  python yolo/carla_bridge_server.py --port 5555

  # 步骤2：在 Python 3.10+ 环境运行优化
  # 正向训练（最大化置信度）
  python yolo/weather_optimize.py --mode maximize --trials 20 --weights yolo12x.pt

  # 反向训练（最小化置信度）
  python yolo/weather_optimize.py --mode minimize --trials 20 --weights yolo12x.pt
"""

from __future__ import annotations

# Fix OpenMP library conflict (must be set before importing numpy/matplotlib)
import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

import argparse
import base64
import json
import os
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import optuna
import pygame
import cv2
from optuna.samplers import TPESampler
from ultralytics import YOLO

# Set matplotlib backend for non-interactive plotting
plt.switch_backend('Agg')


# -----------------------------------------------------------------------------
# Data holders
# -----------------------------------------------------------------------------

@dataclass
class FrameData:
    frame_id: int
    bgr: np.ndarray  # (H, W, 3) uint8
    rgb: np.ndarray  # (H, W, 3) uint8


@dataclass
class TrialRecord:
    """Record for each trial during optimization."""
    trial_number: int
    score: float
    params: Dict[str, float]
    timestamp: float


@dataclass
class Detection:
    """Compact detection record for saved paper artifacts."""
    class_id: int
    class_name: str
    confidence: float
    xyxy: Tuple[float, float, float, float]


@dataclass
class ImageQuality:
    """Image-level validity metrics used to reject trivial dark/flat frames."""
    mean_luma: float
    std_luma: float
    valid: bool


@dataclass
class ObjectiveBreakdown:
    """Components of the optimization objective."""
    objective: float
    confidence: float
    iou: float
    bbox_quality: float
    mean_luma: float
    std_luma: float
    image_valid: bool
    weather_severity: float = 0.0


@dataclass
class TrainingHistory:
    """Training history for visualization."""
    records: List[TrialRecord] = field(default_factory=list)
    best_scores: List[float] = field(default_factory=list)
    mode: str = "maximize"
    
    def add_record(self, trial_number: int, score: float, params: Dict[str, float]) -> None:
        record = TrialRecord(
            trial_number=trial_number,
            score=score,
            params=params,
            timestamp=time.time()
        )
        self.records.append(record)
        
        # Update best score
        if not self.best_scores:
            self.best_scores.append(score)
        else:
            if self.mode == "maximize":
                self.best_scores.append(max(self.best_scores[-1], score))
            else:
                self.best_scores.append(min(self.best_scores[-1], score))


# -----------------------------------------------------------------------------
# CARLA environment manager (远程桥接模式)
# -----------------------------------------------------------------------------


class RemoteEnv:
    """远程模式：通过 TCP 与 carla_bridge_server 通信，获取图像。"""

    def __init__(
        self,
        host: str,
        port: int,
        width: int,
        height: int,
    ) -> None:
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.sock: Optional[socket.socket] = None
        self.buf = b""

    def __enter__(self) -> "RemoteEnv":
        self.sock = socket.create_connection((self.host, self.port), timeout=5.0)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def apply_weather(self, params: Dict[str, float]) -> None:
        # 远程模式在 capture 时一起处理，这里无需动作
        return

    def capture_frame(self, params: Dict[str, float], timeout: float = 5.0) -> Optional[FrameData]:
        """发送天气参数，请求一帧图像。"""
        if not self.sock:
            raise RuntimeError("远程连接未建立")
        req = {
            "cmd": "apply_and_capture",
            "weather": params,
            "width": self.width,
            "height": self.height,
        }
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))

        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buf += chunk
            if b"\n" not in self.buf:
                continue
            line, self.buf = self.buf.split(b"\n", 1)
            if not line.strip():
                continue
            resp = json.loads(line.decode("utf-8"))
            if not resp.get("ok"):
                return None
            bgr_bytes = base64.b64decode(resp["bgr_b64"])
            bgr = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape(
                (resp["height"], resp["width"], 3)
            )
            rgb = bgr[:, :, ::-1]
            return FrameData(frame_id=resp["frame"], bgr=bgr, rgb=rgb)
        return None


# -----------------------------------------------------------------------------
# YOLO scoring
# -----------------------------------------------------------------------------


class YOLOScorer:
    """YOLO 置信度计算器，仅关注车辆/卡车类别。"""

    def __init__(self, weights: str, device: Optional[str] = None) -> None:
        self.model = YOLO(weights)
        self.device = device

    def score(self, bgr_image: np.ndarray) -> float:
        score, _ = self.predict(bgr_image)
        return score

    def predict(self, bgr_image: np.ndarray) -> Tuple[float, List[Detection]]:
        results = self.model.predict(
            source=bgr_image,
            imgsz=max(bgr_image.shape[0], bgr_image.shape[1]),
            device=self.device,
            verbose=False,
        )
        max_conf = 0.0
        detections: List[Detection] = []
        names = getattr(self.model, "names", {})
        for res in results:
            if res.boxes is None:
                continue
            for box in res.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in (2, 7):  # 2:car, 7:truck
                    continue
                conf = float(box.conf[0])
                xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
                detections.append(
                    Detection(
                        class_id=cls_id,
                        class_name=str(names.get(cls_id, cls_id)),
                        confidence=conf,
                        xyxy=xyxy,
                    )
                )
                if conf > max_conf:
                    max_conf = conf
        detections.sort(key=lambda item: item.confidence, reverse=True)
        return max_conf, detections


# -----------------------------------------------------------------------------
# Pygame display helper
# -----------------------------------------------------------------------------


class Display:
    """Pygame 实时显示试验结果。"""

    def __init__(self, width: int, height: int, max_fps: int = 30) -> None:
        pygame.init()
        pygame.font.init()
        self.surface = pygame.display.set_mode((width, height))
        pygame.display.set_caption("CARLA Weather YOLO Optimizer")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 20)
        self.max_fps = max_fps

    def render(
        self,
        frame_rgb: np.ndarray,
        trial_number: int,
        score: float,
        params: Dict[str, float],
        mode: str = "maximize",
        best_score: float = 0.0,
    ) -> None:
        pygame.event.pump()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise KeyboardInterrupt

        surface = pygame.surfarray.make_surface(frame_rgb.swapaxes(0, 1))
        self.surface.blit(surface, (0, 0))

        mode_label = "MAX" if mode == "maximize" else "MIN"
        info_text = (
            f"[{mode_label}] Trial {trial_number} | Score: {score:.3f} | Best: {best_score:.3f} | "
            f"SunAz {params['sun_azimuth_angle']:.1f} "
            f"SunAlt {params['sun_altitude_angle']:.1f} "
            f"Cloud {params['cloudiness']:.1f} Wet {params['wetness']:.1f}"
        )
        text_surf = self.font.render(info_text, True, (255, 255, 255))
        self.surface.blit(text_surf, (10, 10))

        pygame.display.flip()
        self.clock.tick(self.max_fps)


# -----------------------------------------------------------------------------
# Visualization and Output
# -----------------------------------------------------------------------------


class ResultVisualizer:
    """Generate publication-quality visualizations for training results."""

    def __init__(self, output_dir: Path, mode: str) -> None:
        self.output_dir = output_dir
        self.mode = mode
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set publication-quality defaults
        plt.rcParams.update({
            'font.size': 12,
            'axes.titlesize': 14,
            'axes.labelsize': 12,
            'xtick.labelsize': 10,
            'ytick.labelsize': 10,
            'legend.fontsize': 10,
            'figure.titlesize': 16,
            'figure.dpi': 150,
            'savefig.dpi': 300,
            'savefig.bbox': 'tight',
        })

    def plot_convergence_curve(
        self, 
        history: TrainingHistory,
        study: optuna.Study
    ) -> None:
        """Plot convergence curve showing best value over trials."""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        trials = range(1, len(history.best_scores) + 1)
        ax.plot(trials, history.best_scores, 'b-', linewidth=2, label='Best Value')
        
        # Plot all trial values
        all_scores = [r.score for r in history.records]
        ax.scatter(trials, all_scores, c='lightblue', alpha=0.5, s=30, label='Trial Values')
        
        ax.set_xlabel('Trial Number')
        mode_label = "Maximization" if self.mode == "maximize" else "Minimization"
        ax.set_ylabel('YOLO Confidence Score')
        ax.set_title(f'Convergence Curve ({mode_label} Mode)')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        # Add final best value annotation
        final_best = history.best_scores[-1] if history.best_scores else 0
        ax.axhline(y=final_best, color='r', linestyle='--', alpha=0.5, label=f'Final Best: {final_best:.4f}')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'convergence_curve.png')
        plt.savefig(self.output_dir / 'convergence_curve.pdf')
        plt.close()

    def plot_optimization_history(self, study: optuna.Study) -> None:
        """Plot optimization history with trial values and best values."""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        trial_numbers = [t.number for t in study.trials if t.value is not None]
        trial_values = [t.value for t in study.trials if t.value is not None]
        
        if not trial_numbers:
            plt.close()
            return
        
        # Calculate running best
        running_best = []
        current_best = trial_values[0]
        for val in trial_values:
            if self.mode == "maximize":
                current_best = max(current_best, val)
            else:
                current_best = min(current_best, val)
            running_best.append(current_best)
        
        ax.scatter(trial_numbers, trial_values, c='cornflowerblue', alpha=0.6, 
                   s=50, label='Objective Value', zorder=2)
        ax.plot(trial_numbers, running_best, 'r-', linewidth=2, 
                label='Best Value', zorder=3)
        
        ax.set_xlabel('Trial Number')
        ax.set_ylabel('Objective Value (YOLO Confidence)')
        mode_label = "Maximization" if self.mode == "maximize" else "Minimization"
        ax.set_title(f'Optimization History ({mode_label})')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'optimization_history.png')
        plt.savefig(self.output_dir / 'optimization_history.pdf')
        plt.close()

    def plot_parameter_importance(self, study: optuna.Study) -> None:
        """Plot parameter importance using fANOVA."""
        try:
            importance = optuna.importance.get_param_importances(study)
            if not importance:
                return
            
            fig, ax = plt.subplots(figsize=(10, 6))
            
            params = list(importance.keys())
            values = list(importance.values())
            
            # Sort by importance
            sorted_indices = np.argsort(values)[::-1]
            params = [params[i] for i in sorted_indices]
            values = [values[i] for i in sorted_indices]
            
            colors = plt.cm.Blues(np.linspace(0.4, 0.9, len(params)))[::-1]
            bars = ax.barh(params, values, color=colors)
            
            # Add value labels
            for bar, val in zip(bars, values):
                ax.text(val + 0.01, bar.get_y() + bar.get_height()/2, 
                        f'{val:.3f}', va='center', fontsize=9)
            
            ax.set_xlabel('Importance')
            ax.set_ylabel('Parameter')
            ax.set_title('Hyperparameter Importance (fANOVA)')
            ax.set_xlim(0, max(values) * 1.15)
            
            plt.tight_layout()
            plt.savefig(self.output_dir / 'parameter_importance.png')
            plt.savefig(self.output_dir / 'parameter_importance.pdf')
            plt.close()
        except Exception as e:
            print(f"Warning: Could not generate parameter importance plot: {e}")

    def plot_parallel_coordinates(self, study: optuna.Study) -> None:
        """Plot parallel coordinates for parameter relationships."""
        try:
            completed_trials = [t for t in study.trials if t.value is not None]
            if len(completed_trials) < 2:
                return
            
            fig = optuna.visualization.matplotlib.plot_parallel_coordinate(study)
            fig.set_size_inches(14, 8)
            plt.title('Parallel Coordinate Plot of Parameters')
            plt.tight_layout()
            plt.savefig(self.output_dir / 'parallel_coordinates.png')
            plt.savefig(self.output_dir / 'parallel_coordinates.pdf')
            plt.close()
        except Exception as e:
            print(f"Warning: Could not generate parallel coordinates plot: {e}")

    def plot_parameter_distributions(self, study: optuna.Study) -> None:
        """Plot parameter value distributions."""
        completed_trials = [t for t in study.trials if t.value is not None]
        if not completed_trials:
            return
        
        param_names = list(completed_trials[0].params.keys())
        n_params = len(param_names)
        n_cols = 2
        n_rows = (n_params + n_cols - 1) // n_cols
        
        fig, axes_grid = plt.subplots(n_rows, n_cols, figsize=(9, 12), sharey=True)
        axes = axes_grid.flatten() if n_rows * n_cols > 1 else [axes_grid]
        fig.subplots_adjust(
            left=0.08,
            right=0.84,
            bottom=0.06,
            top=0.94,
            wspace=0.28,
            hspace=0.55,
        )
        cax = fig.add_axes([0.875, 0.14, 0.022, 0.72])
        scatter = None
        
        for i, param_name in enumerate(param_names):
            ax = axes[i]
            values = [t.params[param_name] for t in completed_trials]
            objectives = [t.value for t in completed_trials]
            trial_numbers = [t.number for t in completed_trials]
            
            scatter = ax.scatter(values, objectives, c=trial_numbers,
                                cmap='viridis', alpha=0.75, s=18, edgecolors='none')
            ax.set_xlabel(param_name)
            ax.set_ylabel('Objective Value')
            ax.set_title(param_name)
            ax.grid(True, alpha=0.3)
            ax.set_ylim(-0.03, 1.03)
        
        # Hide unused subplots
        for j in range(i + 1, len(axes)):
            axes[j].set_visible(False)
        
        if scatter is not None:
            cbar = fig.colorbar(scatter, cax=cax)
            cbar.set_label('Trial Number (Optimization Order)')
        
        fig.suptitle('Weather Parameter Values vs YOLO Objective Value', fontsize=14, y=0.982)
        plt.savefig(self.output_dir / 'parameter_distributions.png')
        plt.savefig(self.output_dir / 'parameter_distributions.pdf')
        plt.close()

    def plot_objective_distribution(self, study: optuna.Study) -> None:
        """Plot distribution of objective values."""
        trial_values = [t.value for t in study.trials if t.value is not None]
        if not trial_values:
            return
        
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        
        # Histogram
        axes[0].hist(trial_values, bins=30, color='steelblue', edgecolor='white', alpha=0.7)
        axes[0].axvline(np.mean(trial_values), color='red', linestyle='--', 
                        label=f'Mean: {np.mean(trial_values):.3f}')
        axes[0].axvline(np.median(trial_values), color='orange', linestyle='--', 
                        label=f'Median: {np.median(trial_values):.3f}')
        axes[0].set_xlabel('Objective Value')
        axes[0].set_ylabel('Frequency')
        axes[0].set_title('Distribution of Objective Values')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Box plot
        bp = axes[1].boxplot(trial_values, vert=True, patch_artist=True)
        bp['boxes'][0].set_facecolor('steelblue')
        bp['boxes'][0].set_alpha(0.7)
        axes[1].set_ylabel('Objective Value')
        axes[1].set_title('Box Plot of Objective Values')
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / 'objective_distribution.png')
        plt.savefig(self.output_dir / 'objective_distribution.pdf')
        plt.close()

    def plot_contour(self, study: optuna.Study) -> None:
        """Plot contour plots for top important parameter pairs."""
        try:
            importance = optuna.importance.get_param_importances(study)
            if len(importance) < 2:
                return
            
            # Get top 2 important parameters
            top_params = list(importance.keys())[:2]
            
            fig = optuna.visualization.matplotlib.plot_contour(study, params=top_params)
            fig.set_size_inches(10, 8)
            plt.title(f'Contour Plot: {top_params[0]} vs {top_params[1]}')
            plt.tight_layout()
            plt.savefig(self.output_dir / 'contour_plot.png')
            plt.savefig(self.output_dir / 'contour_plot.pdf')
            plt.close()
        except Exception as e:
            print(f"Warning: Could not generate contour plot: {e}")

    def plot_slice(self, study: optuna.Study) -> None:
        """Plot slice plot for each parameter."""
        try:
            fig = optuna.visualization.matplotlib.plot_slice(study)
            fig.set_size_inches(14, 10)
            plt.suptitle('Slice Plot of Parameters', fontsize=14)
            plt.tight_layout()
            plt.savefig(self.output_dir / 'slice_plot.png')
            plt.savefig(self.output_dir / 'slice_plot.pdf')
            plt.close()
        except Exception as e:
            print(f"Warning: Could not generate slice plot: {e}")

    def save_results_summary(
        self, 
        study: optuna.Study, 
        history: TrainingHistory,
        args: argparse.Namespace
    ) -> None:
        """Save text summary of optimization results."""
        summary_path = self.output_dir / 'results_summary.txt'
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("WEATHER OPTIMIZATION RESULTS SUMMARY\n")
            f.write("=" * 70 + "\n\n")
            
            # Configuration
            f.write("CONFIGURATION\n")
            f.write("-" * 40 + "\n")
            f.write(f"Mode: {args.mode} ({'Maximize' if args.mode == 'maximize' else 'Minimize'} YOLO Confidence)\n")
            f.write(f"Total Trials: {args.trials}\n")
            f.write(f"Completed Trials: {len([t for t in study.trials if t.value is not None])}\n")
            f.write(f"YOLO Weights: {args.weights}\n")
            f.write(f"Objective Mode: {args.objective_mode}\n")
            f.write(f"Sun Altitude Range: [{args.sun_altitude_min}, {args.sun_altitude_max}]\n")
            f.write(
                "Image Quality Gate: "
                f"{'enabled' if args.enforce_image_quality else 'disabled'} "
                f"(policy={args.image_quality_policy}, penalty_weight={args.image_quality_penalty_weight}, "
                f"mean luma {args.min_mean_luma}-{args.max_mean_luma}, "
                f"std >= {args.min_luma_std})\n"
            )
            f.write(
                "Weather Emphasis: "
                f"weight={args.weather_emphasis_weight}, fog={args.fog_emphasis_weight}, "
                f"rain={args.rain_emphasis_weight}, wet={args.wetness_emphasis_weight}, "
                f"cloud={args.cloud_emphasis_weight}, mie={args.mie_emphasis_weight}, "
                f"rayleigh={args.rayleigh_emphasis_weight}\n"
            )
            f.write(f"Image Size: {args.width}x{args.height}\n")
            f.write(f"Random Seed: {args.seed}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Best result
            try:
                best = study.best_trial
                f.write("BEST RESULT\n")
                f.write("-" * 40 + "\n")
                f.write(f"Best Trial Number: {best.number}\n")
                f.write(f"Best Objective Value: {best.value:.6f}\n\n")
                
                f.write("Best Weather Parameters:\n")
                for k, v in best.params.items():
                    f.write(f"  {k}: {v:.4f}\n")
                f.write("\n")
            except (ValueError, AttributeError):
                f.write("No valid trials completed.\n\n")
            
            # Statistics
            trial_values = [t.value for t in study.trials if t.value is not None]
            if trial_values:
                f.write("STATISTICS\n")
                f.write("-" * 40 + "\n")
                f.write(f"Mean Objective: {np.mean(trial_values):.6f}\n")
                f.write(f"Std Objective: {np.std(trial_values):.6f}\n")
                f.write(f"Min Objective: {np.min(trial_values):.6f}\n")
                f.write(f"Max Objective: {np.max(trial_values):.6f}\n")
                f.write(f"Median Objective: {np.median(trial_values):.6f}\n\n")
            
            # Parameter importance
            try:
                importance = optuna.importance.get_param_importances(study)
                f.write("PARAMETER IMPORTANCE\n")
                f.write("-" * 40 + "\n")
                for param, imp in sorted(importance.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  {param}: {imp:.4f}\n")
            except Exception:
                pass
            
            f.write("\n" + "=" * 70 + "\n")
            f.write("Generated files:\n")
            f.write("  - convergence_curve.png/pdf\n")
            f.write("  - optimization_history.png/pdf\n")
            f.write("  - parameter_importance.png/pdf\n")
            f.write("  - parameter_distributions.png/pdf\n")
            f.write("  - objective_distribution.png/pdf\n")
            f.write("  - parallel_coordinates.png/pdf\n")
            f.write("  - contour_plot.png/pdf\n")
            f.write("  - slice_plot.png/pdf\n")
            f.write("  - best_params.json\n")
            f.write("  - all_trials.csv\n")
            f.write("=" * 70 + "\n")

    def save_best_params_json(self, study: optuna.Study, args: argparse.Namespace) -> None:
        """Save best parameters as JSON file."""
        try:
            best = study.best_trial
            data = {
                "mode": args.mode,
                "best_value": best.value,
                "best_trial_number": best.number,
                "best_params": best.params,
                "timestamp": datetime.now().isoformat(),
                "config": {
                    "trials": args.trials,
                    "weights": args.weights,
                    "seed": args.seed,
                    "objective_mode": args.objective_mode,
                    "sun_altitude_min": args.sun_altitude_min,
                    "sun_altitude_max": args.sun_altitude_max,
                    "enforce_image_quality": args.enforce_image_quality,
                    "image_quality_policy": args.image_quality_policy,
                    "image_quality_penalty_weight": args.image_quality_penalty_weight,
                    "min_mean_luma": args.min_mean_luma,
                    "max_mean_luma": args.max_mean_luma,
                    "min_luma_std": args.min_luma_std,
                    "weather_emphasis_weight": args.weather_emphasis_weight,
                    "fog_emphasis_weight": args.fog_emphasis_weight,
                    "rain_emphasis_weight": args.rain_emphasis_weight,
                    "wetness_emphasis_weight": args.wetness_emphasis_weight,
                    "cloud_emphasis_weight": args.cloud_emphasis_weight,
                    "mie_emphasis_weight": args.mie_emphasis_weight,
                    "rayleigh_emphasis_weight": args.rayleigh_emphasis_weight,
                }
            }
            with open(self.output_dir / 'best_params.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except (ValueError, AttributeError):
            pass

    def save_trials_csv(self, study: optuna.Study) -> None:
        """Save all trials to CSV file."""
        import csv
        
        completed_trials = [t for t in study.trials if t.value is not None]
        if not completed_trials:
            return
        
        param_names = list(completed_trials[0].params.keys())
        
        with open(self.output_dir / 'all_trials.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            attr_names = [
                "raw_confidence",
                "iou_to_reference",
                "bbox_quality",
                "mean_luma",
                "std_luma",
                "image_valid",
                "weather_severity",
            ]
            header = ['trial_number', 'objective_value'] + attr_names + param_names
            writer.writerow(header)
            
            for trial in completed_trials:
                row = [trial.number, trial.value]
                row.extend([trial.user_attrs.get(name, "") for name in attr_names])
                row.extend([trial.params[p] for p in param_names])
                writer.writerow(row)

    def generate_all_plots(
        self, 
        study: optuna.Study, 
        history: TrainingHistory,
        args: argparse.Namespace
    ) -> None:
        """Generate all visualization plots and save results."""
        print("\n" + "=" * 50)
        print("Generating visualization plots...")
        print("=" * 50)
        
        print("  [1/9] Generating convergence curve...")
        self.plot_convergence_curve(history, study)
        
        print("  [2/9] Generating optimization history...")
        self.plot_optimization_history(study)
        
        print("  [3/9] Generating parameter importance...")
        self.plot_parameter_importance(study)
        
        print("  [4/9] Generating parameter distributions...")
        self.plot_parameter_distributions(study)
        
        print("  [5/9] Generating objective distribution...")
        self.plot_objective_distribution(study)
        
        print("  [6/9] Generating parallel coordinates...")
        self.plot_parallel_coordinates(study)
        
        print("  [7/9] Generating contour plot...")
        self.plot_contour(study)
        
        print("  [8/9] Generating slice plot...")
        self.plot_slice(study)
        
        print("  [9/9] Saving results summary and data files...")
        self.save_results_summary(study, history, args)
        self.save_best_params_json(study, args)
        self.save_trials_csv(study)
        
        print(f"\nAll results saved to: {self.output_dir}")
        print("=" * 50)


# -----------------------------------------------------------------------------
# Weather optimizer
# -----------------------------------------------------------------------------


class WeatherOptimizer:
    """天气参数优化主类（远程桥接模式）。"""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.mode = args.mode
        self.env = RemoteEnv(
            host=args.remote_host,
            port=args.remote_port,
            width=args.width,
            height=args.height,
        )

        self.display = Display(width=args.width, height=args.height)
        self.yolo = YOLOScorer(weights=args.weights, device=args.device)
        
        # Set optimization direction based on mode
        direction = "maximize" if self.mode == "maximize" else "minimize"
        self.study = optuna.create_study(
            direction=direction,
            sampler=TPESampler(seed=args.seed),
        )
        
        # Initialize training history
        self.history = TrainingHistory(mode=self.mode)
        
        # Setup output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path(args.output_dir) / f"{self.mode}_{timestamp}"
        self.visualizer = ResultVisualizer(self.output_dir, self.mode)
        self.frames_dir = self.output_dir / "frames"
        self.artifact_trials = self._parse_artifact_trials(args.artifact_trials)
        self.reference_bbox = self._parse_bbox(args.reference_bbox)
        self.reference_area = self._bbox_area(self.reference_bbox) if self.reference_bbox else 0.0

    @staticmethod
    def _parse_artifact_trials(value: str) -> set[int]:
        trials: set[int] = set()
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                trials.add(int(part))
            except ValueError:
                print(f"Warning: ignoring invalid artifact trial '{part}'")
        return trials

    @staticmethod
    def _parse_bbox(value: str) -> Optional[Tuple[float, float, float, float]]:
        if not value:
            return None
        parts = [float(part.strip()) for part in value.split(",") if part.strip()]
        if len(parts) != 4:
            raise ValueError("--reference-bbox must contain four comma-separated numbers: x1,y1,x2,y2")
        x1, y1, x2, y2 = parts
        if x2 <= x1 or y2 <= y1:
            raise ValueError("--reference-bbox must satisfy x2>x1 and y2>y1")
        return (x1, y1, x2, y2)

    @staticmethod
    def _bbox_area(box: Optional[Tuple[float, float, float, float]]) -> float:
        if box is None:
            return 0.0
        x1, y1, x2, y2 = box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    @classmethod
    def _bbox_iou(
        cls,
        a: Optional[Tuple[float, float, float, float]],
        b: Optional[Tuple[float, float, float, float]],
    ) -> float:
        if a is None or b is None:
            return 1.0
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = cls._bbox_area(a) + cls._bbox_area(b) - inter
        return inter / union if union > 0 else 0.0

    @staticmethod
    def _center_consistency(
        box: Optional[Tuple[float, float, float, float]],
        ref: Optional[Tuple[float, float, float, float]],
        width: int,
        height: int,
    ) -> float:
        if box is None or ref is None:
            return 1.0
        x1, y1, x2, y2 = box
        rx1, ry1, rx2, ry2 = ref
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        rcx = (rx1 + rx2) / 2.0
        rcy = (ry1 + ry2) / 2.0
        diag = (width ** 2 + height ** 2) ** 0.5
        dist = ((cx - rcx) ** 2 + (cy - rcy) ** 2) ** 0.5
        return float(np.clip(1.0 - dist / (0.35 * diag), 0.0, 1.0))

    def _image_quality(self, bgr_image: np.ndarray) -> ImageQuality:
        # ITU-R BT.601 luma approximation in BGR channel order.
        luma = (
            0.114 * bgr_image[:, :, 0].astype(np.float32)
            + 0.587 * bgr_image[:, :, 1].astype(np.float32)
            + 0.299 * bgr_image[:, :, 2].astype(np.float32)
        )
        mean_luma = float(luma.mean())
        std_luma = float(luma.std())
        valid = (
            mean_luma >= self.args.min_mean_luma
            and mean_luma <= self.args.max_mean_luma
            and std_luma >= self.args.min_luma_std
        )
        return ImageQuality(mean_luma=mean_luma, std_luma=std_luma, valid=valid)

    def _image_quality_penalty(self, quality: ImageQuality) -> float:
        """Return a [0, 1] penalty for dark/flat/overexposed frames."""
        low_luma_gap = max(0.0, self.args.min_mean_luma - quality.mean_luma) / max(self.args.min_mean_luma, 1e-6)
        high_luma_gap = max(0.0, quality.mean_luma - self.args.max_mean_luma) / max(255.0 - self.args.max_mean_luma, 1e-6)
        contrast_gap = max(0.0, self.args.min_luma_std - quality.std_luma) / max(self.args.min_luma_std, 1e-6)
        return float(np.clip(max(low_luma_gap, high_luma_gap, contrast_gap), 0.0, 1.0))

    def _apply_quality_policy(self, objective: float, quality: ImageQuality) -> float:
        if self.args.image_quality_policy == "off" or quality.valid:
            return objective

        if self.args.image_quality_policy == "hard":
            return 0.0 if self.mode == "maximize" else 1.0

        penalty = self._image_quality_penalty(quality) * self.args.image_quality_penalty_weight
        if self.mode == "maximize":
            return float(np.clip(objective * (1.0 - penalty), 0.0, 1.0))
        return float(np.clip(objective + penalty, 0.0, 1.0))

    def _weather_severity(self, params: Dict[str, float]) -> float:
        components = [
            (params.get("fog_density", 0.0) / 40.0, self.args.fog_emphasis_weight),
            (params.get("precipitation", 0.0) / 30.0, self.args.rain_emphasis_weight),
            (params.get("wetness", 0.0) / 100.0, self.args.wetness_emphasis_weight),
            (params.get("cloudiness", 0.0) / 100.0, self.args.cloud_emphasis_weight),
            (params.get("mie_scattering_scale", 0.0) / 1.0, self.args.mie_emphasis_weight),
            (params.get("rayleigh_scattering_scale", 0.0) / 3.0, self.args.rayleigh_emphasis_weight),
        ]
        total_weight = sum(max(0.0, weight) for _, weight in components)
        if total_weight <= 0.0:
            return 0.0
        severity = sum(float(np.clip(value, 0.0, 1.0)) * max(0.0, weight) for value, weight in components) / total_weight
        return float(np.clip(severity, 0.0, 1.0))

    def _apply_weather_emphasis(self, objective: float, weather_severity: float) -> float:
        if self.args.weather_emphasis_weight <= 0.0:
            return objective
        delta = self.args.weather_emphasis_weight * weather_severity
        if self.mode == "maximize":
            return float(np.clip(objective + delta, 0.0, 1.0))
        return float(np.clip(objective - delta, 0.0, 1.0))

    def _reference_weather(self) -> Dict[str, float]:
        return {
            "sun_azimuth_angle": 0.0,
            "sun_altitude_angle": max(45.0, self.args.sun_altitude_min),
            "cloudiness": 0.0,
            "fog_density": 0.0,
            "precipitation": 0.0,
            "wetness": 0.0,
            "rayleigh_scattering_scale": 0.0331,
            "mie_scattering_scale": 0.03,
        }

    def _initialize_reference_bbox(self) -> None:
        if self.args.objective_mode != "composite" or self.reference_bbox is not None:
            return

        print("\nInitializing reference target bbox from clear daytime scene...")
        frame = self.env.capture_frame(self._reference_weather())
        if frame is None:
            print("Warning: could not capture reference frame; IoU/bbox terms will be disabled.")
            return

        _, detections = self.yolo.predict(frame.bgr)
        if not detections:
            print("Warning: no reference vehicle detected; IoU/bbox terms will be disabled.")
            return

        self.reference_bbox = detections[0].xyxy
        self.reference_area = self._bbox_area(self.reference_bbox)
        print(
            "Reference bbox initialized: "
            f"({self.reference_bbox[0]:.1f}, {self.reference_bbox[1]:.1f}, "
            f"{self.reference_bbox[2]:.1f}, {self.reference_bbox[3]:.1f}), "
            f"conf={detections[0].confidence:.3f}"
        )

    def _score_detection(
        self,
        detection: Detection,
        width: int,
        height: int,
    ) -> Tuple[float, float, float]:
        iou = self._bbox_iou(detection.xyxy, self.reference_bbox)

        area = self._bbox_area(detection.xyxy)
        if self.reference_bbox is None or self.reference_area <= 0.0:
            area_consistency = 1.0
        else:
            ratio = area / max(self.reference_area, 1e-6)
            area_consistency = float(np.clip(min(ratio, 1.0 / max(ratio, 1e-6)), 0.0, 1.0))

        center_consistency = self._center_consistency(detection.xyxy, self.reference_bbox, width, height)
        bbox_quality = float((area_consistency * center_consistency) ** 0.5)

        if self.args.objective_mode == "confidence" or self.reference_bbox is None:
            objective = detection.confidence
        else:
            objective = (
                detection.confidence ** self.args.confidence_weight
                * max(iou, 1e-6) ** self.args.iou_weight
                * max(bbox_quality, 1e-6) ** self.args.bbox_weight
            )
        return float(objective), float(iou), float(bbox_quality)

    def _compute_objective(
        self,
        bgr_image: np.ndarray,
        detections: List[Detection],
        params: Dict[str, float],
    ) -> ObjectiveBreakdown:
        quality = self._image_quality(bgr_image)
        weather_severity = self._weather_severity(params)
        if self.args.enforce_image_quality and self.args.image_quality_policy == "hard" and not quality.valid:
            invalid_score = self._apply_quality_policy(0.0, quality)
            invalid_score = self._apply_weather_emphasis(invalid_score, weather_severity)
            return ObjectiveBreakdown(
                objective=invalid_score,
                confidence=0.0,
                iou=0.0,
                bbox_quality=0.0,
                mean_luma=quality.mean_luma,
                std_luma=quality.std_luma,
                image_valid=False,
                weather_severity=weather_severity,
            )

        if not detections:
            objective = self._apply_quality_policy(0.0, quality) if self.args.enforce_image_quality else 0.0
            objective = self._apply_weather_emphasis(objective, weather_severity)
            return ObjectiveBreakdown(
                objective=objective,
                confidence=0.0,
                iou=0.0,
                bbox_quality=0.0,
                mean_luma=quality.mean_luma,
                std_luma=quality.std_luma,
                image_valid=quality.valid,
                weather_severity=weather_severity,
            )

        height, width = bgr_image.shape[:2]
        best = None
        for detection in detections:
            objective, iou, bbox_quality = self._score_detection(detection, width, height)
            candidate = ObjectiveBreakdown(
                objective=self._apply_weather_emphasis(
                    self._apply_quality_policy(objective, quality) if self.args.enforce_image_quality else objective,
                    weather_severity,
                ),
                confidence=detection.confidence,
                iou=iou,
                bbox_quality=bbox_quality,
                mean_luma=quality.mean_luma,
                std_luma=quality.std_luma,
                image_valid=quality.valid,
                weather_severity=weather_severity,
            )
            if best is None or candidate.objective > best.objective:
                best = candidate

        return best if best is not None else ObjectiveBreakdown(
            self._apply_weather_emphasis(0.0, weather_severity),
            0.0,
            0.0,
            0.0,
            quality.mean_luma,
            quality.std_luma,
            quality.valid,
            weather_severity,
        )

    @staticmethod
    def _draw_detections(
        bgr_image: np.ndarray,
        detections: List[Detection],
        score: float,
        params: Dict[str, float],
        trial_number: int,
        mode: str,
    ) -> np.ndarray:
        canvas = bgr_image.copy()
        color = (0, 180, 0) if score > 0.5 else (0, 0, 220)

        for det in detections:
            x1, y1, x2, y2 = [int(round(v)) for v in det.xyxy]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            label = f"{det.class_name} {det.confidence:.2f}"
            cv2.putText(
                canvas,
                label,
                (x1, max(22, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
                cv2.LINE_AA,
            )

        overlay = canvas.copy()
        cv2.rectangle(overlay, (0, 0), (canvas.shape[1], 86), (0, 0, 0), -1)
        canvas = cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0)
        header = f"{mode.upper()} trial {trial_number} | Objective score {score:.3f}"
        weather = (
            f"sun alt {params['sun_altitude_angle']:.1f}, fog {params['fog_density']:.1f}, "
            f"rain {params['precipitation']:.1f}, wet {params['wetness']:.1f}"
        )
        cv2.putText(canvas, header, (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, weather, (18, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (235, 235, 235), 2, cv2.LINE_AA)

        if not detections:
            cv2.putText(
                canvas,
                "No car/truck detection",
                (18, 118),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.85,
                (0, 0, 230),
                2,
                cv2.LINE_AA,
            )
        return canvas

    def _save_frame_artifact(
        self,
        trial_number: int,
        score: float,
        params: Dict[str, float],
        bgr_image: np.ndarray,
        detections: List[Detection],
        tag: str,
    ) -> None:
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{tag}_trial_{trial_number:04d}_score_{score:.4f}"
        raw_path = self.frames_dir / f"{stem}_raw.png"
        annotated_path = self.frames_dir / f"{stem}_annotated.png"
        metadata_path = self.frames_dir / f"{stem}.json"

        annotated = self._draw_detections(bgr_image, detections, score, params, trial_number, self.mode)
        cv2.imwrite(str(raw_path), bgr_image)
        cv2.imwrite(str(annotated_path), annotated)

        metadata = {
            "mode": self.mode,
            "trial_number": trial_number,
            "score": score,
            "params": params,
            "raw_image": raw_path.name,
            "annotated_image": annotated_path.name,
            "detections": [
                {
                    "class_id": det.class_id,
                    "class_name": det.class_name,
                    "confidence": det.confidence,
                    "xyxy": det.xyxy,
                }
                for det in detections
            ],
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        if tag == "best":
            cv2.imwrite(str(self.frames_dir / "best_latest_raw.png"), bgr_image)
            cv2.imwrite(str(self.frames_dir / "best_latest_annotated.png"), annotated)
            with open(self.frames_dir / "best_latest.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _maybe_save_frame_artifacts(
        self,
        trial_number: int,
        score: float,
        old_best: Optional[float],
        params: Dict[str, float],
        bgr_image: np.ndarray,
        detections: List[Detection],
    ) -> None:
        if not self.args.save_frames:
            return

        is_new_best = old_best is None
        if old_best is not None:
            is_new_best = score >= old_best if self.mode == "maximize" else score <= old_best

        if is_new_best:
            self._save_frame_artifact(trial_number, score, params, bgr_image, detections, "best")

        if self.args.frame_interval > 0 and trial_number % self.args.frame_interval == 0:
            self._save_frame_artifact(trial_number, score, params, bgr_image, detections, "interval")

        if trial_number in self.artifact_trials:
            self._save_frame_artifact(trial_number, score, params, bgr_image, detections, "selected")

    def suggest_params(self, trial: optuna.Trial) -> Dict[str, float]:
        """Optuna 采样空间，覆盖 init.md 提到的关键天气参数。"""
        return {
            "sun_azimuth_angle": trial.suggest_float("sun_azimuth_angle", 0.0, 360.0),
            "sun_altitude_angle": trial.suggest_float(
                "sun_altitude_angle", self.args.sun_altitude_min, self.args.sun_altitude_max
            ),
            "cloudiness": trial.suggest_float("cloudiness", 0.0, 100.0),
            "fog_density": trial.suggest_float("fog_density", 0.0, 40.0),
            "precipitation": trial.suggest_float("precipitation", 0.0, 30.0),
            "wetness": trial.suggest_float("wetness", 0.0, 100.0),
            "rayleigh_scattering_scale": trial.suggest_float(
                "rayleigh_scattering_scale", 0.0, 3.0
            ),
            "mie_scattering_scale": trial.suggest_float(
                "mie_scattering_scale", 0.0, 1.0
            ),
        }

    def objective(self, trial: optuna.Trial) -> float:
        """单次 trial：设定天气 -> 抓取图像 -> YOLO 打分。"""
        params = self.suggest_params(trial)
        frame = self.env.capture_frame(params)
        if frame is None:
            return 0.0 if self.mode == "maximize" else 1.0
        
        old_best = self.history.best_scores[-1] if self.history.best_scores else None
        _, detections = self.yolo.predict(frame.bgr)
        breakdown = self._compute_objective(frame.bgr, detections, params)
        score = breakdown.objective
        trial.set_user_attr("raw_confidence", breakdown.confidence)
        trial.set_user_attr("iou_to_reference", breakdown.iou)
        trial.set_user_attr("bbox_quality", breakdown.bbox_quality)
        trial.set_user_attr("mean_luma", breakdown.mean_luma)
        trial.set_user_attr("std_luma", breakdown.std_luma)
        trial.set_user_attr("image_valid", breakdown.image_valid)
        trial.set_user_attr("weather_severity", breakdown.weather_severity)
        
        # Record history
        self.history.add_record(trial.number, score, params)
        self._maybe_save_frame_artifacts(trial.number, score, old_best, params, frame.bgr, detections)
        
        # Get current best for display
        best_score = self.history.best_scores[-1] if self.history.best_scores else score
        
        self.display.render(frame.rgb, trial.number, score, params, self.mode, best_score)
        return score

    def run(self) -> None:
        mode_label = "MAXIMIZE (Enhance Detection)" if self.mode == "maximize" else "MINIMIZE (Evade Detection)"
        print("\n" + "=" * 60)
        print(f"Starting Weather Optimization")
        print(f"Mode: {mode_label}")
        print(f"Trials: {self.args.trials}")
        print(f"Output Directory: {self.output_dir}")
        print("=" * 60 + "\n")
        
        with self.env:
            try:
                self._initialize_reference_bbox()
                self.study.optimize(self.objective, n_trials=self.args.trials)
            except KeyboardInterrupt:
                print("\n用户中断。正在保存结果...")
            finally:
                # Print results
                self._print_results()
                
                # Generate visualizations
                if len([t for t in self.study.trials if t.value is not None]) > 0:
                    self.visualizer.generate_all_plots(
                        self.study, 
                        self.history, 
                        self.args
                    )
                
                pygame.quit()

    def _print_results(self) -> None:
        """Print optimization results to console."""
        print("\n" + "=" * 60)
        print("OPTIMIZATION RESULTS")
        print("=" * 60)
        
        try:
            best = self.study.best_trial
            mode_desc = "最高" if self.mode == "maximize" else "最低"
            print(f"\n{mode_desc}置信度: {best.value:.6f}")
            print("\n最佳天气参数:")
            for k, v in best.params.items():
                print(f"  {k}: {v:.4f}")
        except (ValueError, AttributeError):
            print("未得到有效 trial。")
        
        print("\n" + "=" * 60)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CARLA 天气优化 + YOLO (远程桥接模式)",
        epilog="注意：需要先在 Python 3.7 环境中启动 carla_bridge_server.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    # Training mode
    parser.add_argument(
        "--mode",
        type=str,
        choices=["maximize", "minimize"],
        default="maximize",
        help="Training mode: 'maximize' to enhance detection (increase confidence), "
             "'minimize' to evade detection (decrease confidence). Default: maximize"
    )
    
    # Network settings
    parser.add_argument(
        "--remote-host", 
        default="127.0.0.1", 
        help="CARLA 桥接服务地址 (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--remote-port", 
        type=int, 
        default=5555, 
        help="CARLA 桥接服务端口 (default: 5555)"
    )
    
    # Training settings
    parser.add_argument(
        "--trials", 
        type=int, 
        default=10, 
        help="Number of optimization trials. Use small values (e.g., 20) for testing, "
             "larger values (e.g., 10000) for final results. Default: 10"
    )
    parser.add_argument(
        "--seed", 
        type=int, 
        default=42, 
        help="Random seed for reproducibility (default: 42)"
    )
    
    # Image settings
    parser.add_argument(
        "--width", 
        type=int, 
        default=1280, 
        help="Camera image width (default: 1280)"
    )
    parser.add_argument(
        "--height", 
        type=int, 
        default=720, 
        help="Camera image height (default: 720)"
    )
    
    # YOLO settings
    parser.add_argument(
        "--weights", 
        default="yolo12x.pt",
        help="Ultralytics YOLO weights file path (default: yolo12x.pt; compatible with yolov8x.pt)"
    )
    parser.add_argument(
        "--device", 
        default=None, 
        help="YOLO inference device (e.g., 'cuda:0' or 'cpu'). Auto-detect if not specified."
    )

    # Objective settings
    parser.add_argument(
        "--objective-mode",
        choices=["confidence", "composite"],
        default="composite",
        help="Objective function: confidence uses max YOLO confidence only; composite adds reference IoU, bbox stability, and image-quality gating."
    )
    parser.add_argument(
        "--reference-bbox",
        default="",
        help="Optional reference bbox x1,y1,x2,y2. If omitted, a clear daytime frame is captured and YOLO initializes the reference bbox."
    )
    parser.add_argument(
        "--confidence-weight",
        type=float,
        default=1.0,
        help="Composite objective exponent for YOLO confidence."
    )
    parser.add_argument(
        "--iou-weight",
        type=float,
        default=0.7,
        help="Composite objective exponent for IoU to the reference bbox."
    )
    parser.add_argument(
        "--bbox-weight",
        type=float,
        default=0.3,
        help="Composite objective exponent for bbox area/center consistency."
    )
    parser.add_argument(
        "--sun-altitude-min",
        type=float,
        default=0.0,
        help="Lower bound for sun altitude search. Use >=0 to avoid trivial night/dark solutions."
    )
    parser.add_argument(
        "--sun-altitude-max",
        type=float,
        default=90.0,
        help="Upper bound for sun altitude search."
    )
    parser.add_argument(
        "--enforce-image-quality",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply image-quality handling to trivial dark/flat frames."
    )
    parser.add_argument(
        "--image-quality-policy",
        choices=["hard", "soft", "off"],
        default="soft",
        help="Image-quality handling. hard rejects invalid frames; soft penalizes them; off ignores image quality."
    )
    parser.add_argument(
        "--image-quality-penalty-weight",
        type=float,
        default=0.6,
        help="Penalty strength for --image-quality-policy soft. Larger values discourage dark/flat frames more strongly."
    )
    parser.add_argument(
        "--min-mean-luma",
        type=float,
        default=55.0,
        help="Minimum acceptable mean image luminance on a 0-255 scale."
    )
    parser.add_argument(
        "--max-mean-luma",
        type=float,
        default=230.0,
        help="Maximum acceptable mean image luminance on a 0-255 scale."
    )
    parser.add_argument(
        "--min-luma-std",
        type=float,
        default=18.0,
        help="Minimum acceptable luminance standard deviation; filters nearly flat low-contrast frames."
    )
    parser.add_argument(
        "--weather-emphasis-weight",
        type=float,
        default=0.0,
        help="Objective shaping strength for visible weather severity. For minimize, larger weather severity lowers the objective."
    )
    parser.add_argument(
        "--fog-emphasis-weight",
        type=float,
        default=2.0,
        help="Relative contribution of fog density to weather severity."
    )
    parser.add_argument(
        "--rain-emphasis-weight",
        type=float,
        default=2.0,
        help="Relative contribution of precipitation to weather severity."
    )
    parser.add_argument(
        "--wetness-emphasis-weight",
        type=float,
        default=1.0,
        help="Relative contribution of wetness to weather severity."
    )
    parser.add_argument(
        "--cloud-emphasis-weight",
        type=float,
        default=0.7,
        help="Relative contribution of cloudiness to weather severity."
    )
    parser.add_argument(
        "--mie-emphasis-weight",
        type=float,
        default=0.5,
        help="Relative contribution of Mie scattering scale to weather severity."
    )
    parser.add_argument(
        "--rayleigh-emphasis-weight",
        type=float,
        default=0.2,
        help="Relative contribution of Rayleigh scattering scale to weather severity."
    )
    
    # Output settings
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./optimization_results",
        help="Directory to save results and visualizations (default: ./optimization_results)"
    )
    parser.add_argument(
        "--save-frames",
        action="store_true",
        help="Save raw and YOLO-annotated CARLA frames for new best trials and selected intervals."
    )
    parser.add_argument(
        "--frame-interval",
        type=int,
        default=0,
        help="When --save-frames is enabled, also save every Nth trial. Use 0 to disable interval snapshots."
    )
    parser.add_argument(
        "--artifact-trials",
        default="",
        help="Comma-separated trial numbers to save as visual artifacts, e.g. '0,10,50,100'."
    )
    
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.sun_altitude_min >= args.sun_altitude_max:
        raise ValueError("--sun-altitude-min must be smaller than --sun-altitude-max")
    
    # Print configuration
    print("\n" + "=" * 60)
    print("CARLA Weather + YOLO Optimization System")
    print("=" * 60)
    print(f"Mode: {args.mode}")
    print(f"Trials: {args.trials}")
    print(f"Output: {args.output_dir}")
    print("=" * 60 + "\n")
    
    optimizer = WeatherOptimizer(args)
    optimizer.run()


if __name__ == "__main__":
    main()
