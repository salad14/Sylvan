#!/usr/bin/env python3
"""Cost-aligned optimizer comparison for CARLA + YOLO weather search.

This script separates three concepts that were previously mixed together:

1. Perception score S in [0, 1]
   - confidence mode: S = best YOLO confidence
   - composite mode: S = confidence^wc * IoU^wi * bbox_quality^wb

2. Optimizer cost C, always minimized
   - favorable methods: C = 1 - S
   - boundary method:   C = S

3. Plotted y value, always a perception score
   - favorable methods plot cumulative max S, so curves should rise
   - boundary method plots cumulative min S, so the curve should fall

The scene is kept stationary within a run. If target_offset_fraction is used,
it is a fixed setting, not a per-iteration drift. This keeps the optimization
objective stable for Optuna and makes convergence curves interpretable.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import matplotlib.pyplot as plt
import numpy as np
import optuna
import pygame
from optuna.samplers import NSGAIISampler, RandomSampler, TPESampler
from ultralytics import YOLO

plt.switch_backend("Agg")


PARAM_NAMES = [
    "sun_azimuth_angle",
    "sun_altitude_angle",
    "cloudiness",
    "fog_density",
    "precipitation",
    "wetness",
    "rayleigh_scattering_scale",
    "mie_scattering_scale",
]


PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "sun_azimuth_angle": (0.0, 360.0),
    "sun_altitude_angle": (-30.0, 90.0),
    "cloudiness": (0.0, 100.0),
    "fog_density": (0.0, 40.0),
    "precipitation": (0.0, 30.0),
    "wetness": (0.0, 100.0),
    "rayleigh_scattering_scale": (0.0, 3.0),
    "mie_scattering_scale": (0.0, 1.0),
}


WEATHER_PRESETS: Dict[str, Dict[str, float]] = {
    "ClearNoon": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": 45.0,
        "cloudiness": 0.0,
        "fog_density": 0.0,
        "precipitation": 0.0,
        "wetness": 0.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
    "CloudyNoon": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": 45.0,
        "cloudiness": 80.0,
        "fog_density": 0.0,
        "precipitation": 0.0,
        "wetness": 0.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
    "WetNoon": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": 45.0,
        "cloudiness": 20.0,
        "fog_density": 0.0,
        "precipitation": 0.0,
        "wetness": 80.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
    "SoftRainNoon": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": 45.0,
        "cloudiness": 90.0,
        "fog_density": 5.0,
        "precipitation": 25.0,
        "wetness": 45.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
    "HardRainNoon": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": 45.0,
        "cloudiness": 100.0,
        "fog_density": 10.0,
        "precipitation": 30.0,
        "wetness": 90.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
    "DustStorm": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": 35.0,
        "cloudiness": 100.0,
        "fog_density": 40.0,
        "precipitation": 0.0,
        "wetness": 0.0,
        "rayleigh_scattering_scale": 0.2,
        "mie_scattering_scale": 1.0,
    },
    "WetNight": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": -20.0,
        "cloudiness": 60.0,
        "fog_density": 5.0,
        "precipitation": 0.0,
        "wetness": 80.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
    "HardRainNight": {
        "sun_azimuth_angle": 0.0,
        "sun_altitude_angle": -20.0,
        "cloudiness": 100.0,
        "fog_density": 10.0,
        "precipitation": 30.0,
        "wetness": 90.0,
        "rayleigh_scattering_scale": 0.0331,
        "mie_scattering_scale": 0.03,
    },
}


METHODS = [
    "Random Search",
    "Manual Sampling",
    "Genetic Algorithm",
    "PSO",
    "SA",
    "SA-TPE Favorable",
]

METHOD_ROLES = {
    "Random Search": "favorable",
    "Manual Sampling": "favorable",
    "Genetic Algorithm": "favorable",
    "PSO": "favorable",
    "SA": "favorable",
    "SA-TPE Favorable": "favorable",
}


@dataclass
class FrameData:
    frame_id: int
    bgr: np.ndarray
    rgb: np.ndarray


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    xyxy: Tuple[float, float, float, float]


@dataclass
class TrialRecord:
    method: str
    role: str
    iteration: int
    score: float
    cost: float
    plotted_best_score: float
    confidence: float
    iou: float
    bbox_quality: float
    params: Dict[str, float]
    preset_name: str = ""


class MethodHistory:
    def __init__(self, method: str, role: str) -> None:
        self.method = method
        self.role = role
        self.records: List[TrialRecord] = []
        self.best_costs: List[float] = []
        self.plotted_best_scores: List[float] = []

    @staticmethod
    def score_to_cost(score: float, role: str) -> float:
        if role == "boundary":
            return float(score)
        return float(1.0 - score)

    @staticmethod
    def cost_to_plotted_score(cost: float, role: str) -> float:
        if role == "boundary":
            return float(cost)
        return float(1.0 - cost)

    def add_record(
        self,
        iteration: int,
        score: float,
        confidence: float,
        iou: float,
        bbox_quality: float,
        params: Dict[str, float],
        preset_name: str = "",
    ) -> None:
        cost = self.score_to_cost(score, self.role)
        best_cost = cost if not self.best_costs else min(self.best_costs[-1], cost)
        plotted_best_score = self.cost_to_plotted_score(best_cost, self.role)
        self.best_costs.append(best_cost)
        self.plotted_best_scores.append(plotted_best_score)
        self.records.append(
            TrialRecord(
                method=self.method,
                role=self.role,
                iteration=iteration,
                score=score,
                cost=cost,
                plotted_best_score=plotted_best_score,
                confidence=confidence,
                iou=iou,
                bbox_quality=bbox_quality,
                params=params,
                preset_name=preset_name,
            )
        )


class RemoteEnv:
    def __init__(self, host: str, port: int, width: int, height: int, target_offset_fraction: float) -> None:
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.target_offset_fraction = target_offset_fraction
        self.sock: Optional[socket.socket] = None
        self.buf = b""

    def __enter__(self) -> "RemoteEnv":
        self.sock = socket.create_connection((self.host, self.port), timeout=5.0)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.sock:
            self.sock.close()

    def capture_frame(self, params: Dict[str, float], timeout: float = 5.0) -> Optional[FrameData]:
        if not self.sock:
            return None
        request = {
            "cmd": "apply_and_capture",
            "weather": params,
            "target_offset_fraction": self.target_offset_fraction,
            "width": self.width,
            "height": self.height,
        }
        self.sock.sendall((json.dumps(request) + "\n").encode("utf-8"))

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
            response = json.loads(line.decode("utf-8"))
            if not response.get("ok"):
                return None
            bgr_bytes = base64.b64decode(response["bgr_b64"])
            bgr = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((response["height"], response["width"], 3))
            return FrameData(frame_id=int(response["frame"]), bgr=bgr, rgb=bgr[:, :, ::-1])
        return None


class YOLOScorer:
    def __init__(self, weights: str, device: Optional[str]) -> None:
        self.model = YOLO(weights)
        self.device = device

    def predict(self, bgr_image: np.ndarray) -> List[Detection]:
        results = self.model.predict(
            source=bgr_image,
            imgsz=max(bgr_image.shape[:2]),
            device=self.device,
            verbose=False,
        )
        detections: List[Detection] = []
        names = getattr(self.model, "names", {})
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in (2, 7):
                    continue
                detections.append(
                    Detection(
                        class_id=cls_id,
                        class_name=str(names.get(cls_id, cls_id)),
                        confidence=float(box.conf[0]),
                        xyxy=tuple(float(v) for v in box.xyxy[0].tolist()),
                    )
                )
        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections


class CostAlignedComparison:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.env = RemoteEnv(args.remote_host, args.remote_port, args.width, args.height, args.target_offset_fraction)
        self.yolo = YOLOScorer(args.weights, args.device)
        self.reference_bbox = self.parse_bbox(args.reference_bbox)
        self.reference_area = self.bbox_area(self.reference_bbox)
        self.histories: Dict[str, MethodHistory] = {}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path(args.output_dir) / f"cost_aligned_comparison_{timestamp}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.display_surf = None
        self.font = None
        if not args.no_display:
            pygame.init()
            pygame.font.init()
            self.display_surf = pygame.display.set_mode((args.width, args.height))
            pygame.display.set_caption("Cost-Aligned Optimizer Comparison")
            self.font = pygame.font.SysFont("Arial", 22)

    @staticmethod
    def parse_bbox(value: str) -> Optional[Tuple[float, float, float, float]]:
        if not value:
            return None
        parts = [float(part.strip()) for part in value.split(",") if part.strip()]
        if len(parts) != 4:
            raise ValueError("--reference-bbox must contain x1,y1,x2,y2")
        x1, y1, x2, y2 = parts
        if x2 <= x1 or y2 <= y1:
            raise ValueError("--reference-bbox must satisfy x2>x1 and y2>y1")
        return (x1, y1, x2, y2)

    @staticmethod
    def bbox_area(box: Optional[Tuple[float, float, float, float]]) -> float:
        if box is None:
            return 0.0
        x1, y1, x2, y2 = box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    @classmethod
    def bbox_iou(
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
        intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = cls.bbox_area(a) + cls.bbox_area(b) - intersection
        return intersection / union if union > 0.0 else 0.0

    @staticmethod
    def center_consistency(
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
        diagonal = (width**2 + height**2) ** 0.5
        distance = ((cx - rcx) ** 2 + (cy - rcy) ** 2) ** 0.5
        return float(np.clip(1.0 - distance / max(diagonal, 1e-6), 0.0, 1.0))

    def reference_weather(self) -> Dict[str, float]:
        return {
            "sun_azimuth_angle": 0.0,
            "sun_altitude_angle": 45.0,
            "cloudiness": 0.0,
            "fog_density": 0.0,
            "precipitation": 0.0,
            "wetness": 0.0,
            "rayleigh_scattering_scale": 0.0331,
            "mie_scattering_scale": 0.03,
        }

    def initialize_reference_bbox(self) -> None:
        if self.args.objective_mode != "composite" or self.reference_bbox is not None:
            return
        print("\nInitializing reference bbox from clear scene...")
        frame = self.env.capture_frame(self.reference_weather())
        if frame is None:
            print("Warning: reference frame capture failed; falling back to confidence score.")
            return
        detections = self.yolo.predict(frame.bgr)
        if not detections:
            print("Warning: no reference vehicle detected; falling back to confidence score.")
            return
        self.reference_bbox = detections[0].xyxy
        self.reference_area = self.bbox_area(self.reference_bbox)
        print(
            "Reference bbox: "
            f"({self.reference_bbox[0]:.1f}, {self.reference_bbox[1]:.1f}, "
            f"{self.reference_bbox[2]:.1f}, {self.reference_bbox[3]:.1f}), "
            f"conf={detections[0].confidence:.3f}"
        )

    def suggest_params(self, trial: optuna.Trial) -> Dict[str, float]:
        return {name: trial.suggest_float(name, low, high) for name, (low, high) in PARAM_BOUNDS.items()}

    @staticmethod
    def vector_to_params(vector: np.ndarray) -> Dict[str, float]:
        return {name: float(value) for name, value in zip(PARAM_NAMES, vector)}

    @staticmethod
    def random_vector(rng: np.random.Generator) -> np.ndarray:
        lows = np.array([PARAM_BOUNDS[name][0] for name in PARAM_NAMES], dtype=float)
        highs = np.array([PARAM_BOUNDS[name][1] for name in PARAM_NAMES], dtype=float)
        return rng.uniform(lows, highs)

    @staticmethod
    def clip_vector(vector: np.ndarray) -> np.ndarray:
        lows = np.array([PARAM_BOUNDS[name][0] for name in PARAM_NAMES], dtype=float)
        highs = np.array([PARAM_BOUNDS[name][1] for name in PARAM_NAMES], dtype=float)
        return np.clip(vector, lows, highs)

    @staticmethod
    def bounds_span() -> np.ndarray:
        lows = np.array([PARAM_BOUNDS[name][0] for name in PARAM_NAMES], dtype=float)
        highs = np.array([PARAM_BOUNDS[name][1] for name in PARAM_NAMES], dtype=float)
        return highs - lows

    def score_detection(self, detection: Detection, width: int, height: int) -> Tuple[float, float, float]:
        iou = self.bbox_iou(detection.xyxy, self.reference_bbox)
        area = self.bbox_area(detection.xyxy)
        if self.reference_bbox is None or self.reference_area <= 0.0:
            area_consistency = 1.0
        else:
            ratio = area / max(self.reference_area, 1e-6)
            area_consistency = float(np.clip(min(ratio, 1.0 / max(ratio, 1e-6)), 0.0, 1.0))

        bbox_quality = float(
            (
                area_consistency
                * self.center_consistency(detection.xyxy, self.reference_bbox, width, height)
            )
            ** 0.5
        )

        if self.args.objective_mode == "confidence" or self.reference_bbox is None:
            score = detection.confidence
        else:
            score = (
                detection.confidence ** self.args.confidence_weight
                * max(iou, 1e-6) ** self.args.iou_weight
                * max(bbox_quality, 1e-6) ** self.args.bbox_weight
            )
        return float(score), float(iou), float(bbox_quality)

    def evaluate(self, params: Dict[str, float]) -> Tuple[float, float, float, float, Optional[FrameData]]:
        frame = self.env.capture_frame(params)
        if frame is None:
            return 0.0, 0.0, 0.0, 0.0, None
        detections = self.yolo.predict(frame.bgr)
        if not detections:
            return 0.0, 0.0, 0.0, 0.0, frame

        height, width = frame.bgr.shape[:2]
        best_score = -1.0
        best_confidence = 0.0
        best_iou = 0.0
        best_bbox_quality = 0.0
        for detection in detections:
            score, iou, bbox_quality = self.score_detection(detection, width, height)
            if score > best_score:
                best_score = score
                best_confidence = detection.confidence
                best_iou = iou
                best_bbox_quality = bbox_quality
        return best_score, best_confidence, best_iou, best_bbox_quality, frame

    def update_display(self, method: str, iteration: int, score: float, plotted_best: float, frame: Optional[FrameData]) -> None:
        if frame is None or self.display_surf is None or self.font is None:
            return
        pygame.event.pump()
        surface = pygame.surfarray.make_surface(frame.rgb.swapaxes(0, 1))
        self.display_surf.blit(surface, (0, 0))
        text = f"[{method}] {iteration}/{self.args.trials} | score={score:.3f} | plotted={plotted_best:.3f}"
        text_surface = self.font.render(text, True, (0, 255, 0))
        self.display_surf.blit(text_surface, (10, 10))
        pygame.display.flip()

    def run_manual_sampling(self) -> None:
        method = "Manual Sampling"
        role = METHOD_ROLES[method]
        history = MethodHistory(method, role)
        self.histories[method] = history
        selected = list(WEATHER_PRESETS.items())
        if self.args.manual_limit > 0:
            selected = selected[: self.args.manual_limit]

        print(f"\n---> Running {method} ({role})")
        for index, (preset_name, params) in enumerate(selected[: self.args.trials], start=1):
            score, confidence, iou, bbox_quality, frame = self.evaluate(params)
            history.add_record(index, score, confidence, iou, bbox_quality, dict(params), preset_name)
            self.update_display(method, index, score, history.plotted_best_scores[-1], frame)
            print(
                f"  {preset_name}: score={score:.4f}, cost={history.records[-1].cost:.4f}, "
                f"plotted={history.plotted_best_scores[-1]:.4f}"
            )

    def run_sampler_method(self, method: str, sampler: optuna.samplers.BaseSampler) -> None:
        role = METHOD_ROLES[method]
        history = MethodHistory(method, role)
        self.histories[method] = history
        study = optuna.create_study(direction="minimize", sampler=sampler)

        print(f"\n---> Running {method} ({role}, minimized cost)")

        def objective(trial: optuna.Trial) -> float:
            params = self.suggest_params(trial)
            score, confidence, iou, bbox_quality, frame = self.evaluate(params)
            history.add_record(trial.number + 1, score, confidence, iou, bbox_quality, params)
            self.update_display(method, trial.number + 1, score, history.plotted_best_scores[-1], frame)
            record = history.records[-1]
            print(
                f"  trial={trial.number + 1}/{self.args.trials} "
                f"score={score:.4f} cost={record.cost:.4f} plotted={record.plotted_best_score:.4f} "
                f"conf={confidence:.4f} iou={iou:.3f} bbox={bbox_quality:.3f}"
            )
            return record.cost

        study.optimize(objective, n_trials=self.args.trials)
        print(f"Finished {method}. Best minimized cost: {study.best_value:.4f}")

    def run_pso(self) -> None:
        method = "PSO"
        role = METHOD_ROLES[method]
        history = MethodHistory(method, role)
        self.histories[method] = history
        rng = np.random.default_rng(self.args.seed + 303)
        n_particles = max(1, min(self.args.pso_particles, self.args.trials))
        dimension = len(PARAM_NAMES)
        span = self.bounds_span()
        max_velocity = span * self.args.pso_velocity_fraction

        positions = np.array([self.random_vector(rng) for _ in range(n_particles)])
        velocities = rng.uniform(-max_velocity, max_velocity, size=(n_particles, dimension))
        personal_best_positions = positions.copy()
        personal_best_costs = np.full(n_particles, np.inf, dtype=float)
        global_best_position: Optional[np.ndarray] = None
        global_best_cost = np.inf

        print(f"\n---> Running {method} ({role}, minimized cost)")

        evaluations = 0
        for particle_index in range(n_particles):
            evaluations += 1
            params = self.vector_to_params(positions[particle_index])
            score, confidence, iou, bbox_quality, frame = self.evaluate(params)
            history.add_record(evaluations, score, confidence, iou, bbox_quality, params)
            self.update_display(method, evaluations, score, history.plotted_best_scores[-1], frame)
            record = history.records[-1]
            personal_best_costs[particle_index] = record.cost
            personal_best_positions[particle_index] = positions[particle_index].copy()
            if record.cost < global_best_cost:
                global_best_cost = record.cost
                global_best_position = positions[particle_index].copy()
            print(
                f"  eval={evaluations}/{self.args.trials} particle={particle_index + 1}/{n_particles} "
                f"score={score:.4f} cost={record.cost:.4f} plotted={record.plotted_best_score:.4f} "
                f"conf={confidence:.4f} iou={iou:.3f} bbox={bbox_quality:.3f}"
            )
            if evaluations >= self.args.trials:
                print(f"Finished {method}. Best minimized cost: {global_best_cost:.4f}")
                return

        while evaluations < self.args.trials and global_best_position is not None:
            for particle_index in range(n_particles):
                r1 = rng.random(dimension)
                r2 = rng.random(dimension)
                velocities[particle_index] = (
                    self.args.pso_inertia * velocities[particle_index]
                    + self.args.pso_cognitive * r1 * (personal_best_positions[particle_index] - positions[particle_index])
                    + self.args.pso_social * r2 * (global_best_position - positions[particle_index])
                )
                velocities[particle_index] = np.clip(velocities[particle_index], -max_velocity, max_velocity)
                positions[particle_index] = self.clip_vector(positions[particle_index] + velocities[particle_index])

                evaluations += 1
                params = self.vector_to_params(positions[particle_index])
                score, confidence, iou, bbox_quality, frame = self.evaluate(params)
                history.add_record(evaluations, score, confidence, iou, bbox_quality, params)
                self.update_display(method, evaluations, score, history.plotted_best_scores[-1], frame)
                record = history.records[-1]
                if record.cost < personal_best_costs[particle_index]:
                    personal_best_costs[particle_index] = record.cost
                    personal_best_positions[particle_index] = positions[particle_index].copy()
                if record.cost < global_best_cost:
                    global_best_cost = record.cost
                    global_best_position = positions[particle_index].copy()
                print(
                    f"  eval={evaluations}/{self.args.trials} particle={particle_index + 1}/{n_particles} "
                    f"score={score:.4f} cost={record.cost:.4f} plotted={record.plotted_best_score:.4f} "
                    f"conf={confidence:.4f} iou={iou:.3f} bbox={bbox_quality:.3f}"
                )
                if evaluations >= self.args.trials:
                    break

        print(f"Finished {method}. Best minimized cost: {global_best_cost:.4f}")

    def run_sa(self) -> None:
        method = "SA"
        role = METHOD_ROLES[method]
        history = MethodHistory(method, role)
        self.histories[method] = history
        rng = np.random.default_rng(self.args.seed + 404)
        span = self.bounds_span()
        initial_temperature = max(self.args.sa_initial_temperature, 1e-9)
        final_temperature = max(self.args.sa_final_temperature, 1e-9)

        print(f"\n---> Running {method} ({role}, minimized cost)")

        current_position = self.random_vector(rng)
        current_params = self.vector_to_params(current_position)
        score, confidence, iou, bbox_quality, frame = self.evaluate(current_params)
        history.add_record(1, score, confidence, iou, bbox_quality, current_params)
        self.update_display(method, 1, score, history.plotted_best_scores[-1], frame)
        current_cost = history.records[-1].cost
        print(
            f"  eval=1/{self.args.trials} score={score:.4f} cost={current_cost:.4f} "
            f"plotted={history.records[-1].plotted_best_score:.4f} conf={confidence:.4f} "
            f"iou={iou:.3f} bbox={bbox_quality:.3f} accepted=True"
        )

        for evaluation in range(2, self.args.trials + 1):
            progress = (evaluation - 2) / max(self.args.trials - 2, 1)
            temperature = float(
                np.exp(
                    np.log(initial_temperature)
                    + (np.log(final_temperature) - np.log(initial_temperature)) * progress
                )
            )
            step_scale = self.args.sa_step_fraction * max(temperature / initial_temperature, 0.05)
            proposed_position = self.clip_vector(current_position + rng.normal(0.0, span * step_scale))
            proposed_params = self.vector_to_params(proposed_position)
            score, confidence, iou, bbox_quality, frame = self.evaluate(proposed_params)
            proposed_cost = MethodHistory.score_to_cost(score, role)
            delta = proposed_cost - current_cost
            accepted = delta <= 0.0 or rng.random() < float(np.exp(-delta / max(temperature, 1e-9)))
            if accepted:
                current_position = proposed_position
                current_cost = proposed_cost

            history.add_record(evaluation, score, confidence, iou, bbox_quality, proposed_params)
            self.update_display(method, evaluation, score, history.plotted_best_scores[-1], frame)
            record = history.records[-1]
            print(
                f"  eval={evaluation}/{self.args.trials} temp={temperature:.5f} "
                f"score={score:.4f} cost={record.cost:.4f} plotted={record.plotted_best_score:.4f} "
                f"conf={confidence:.4f} iou={iou:.3f} bbox={bbox_quality:.3f} accepted={accepted}"
            )

        print(f"Finished {method}. Best minimized cost: {history.best_costs[-1]:.4f}")

    def padded_curve(self, history: MethodHistory, attr: str) -> List[float]:
        values = [float(getattr(record, attr)) for record in history.records[: self.args.trials]]
        if values and len(values) < self.args.trials:
            values.extend([values[-1]] * (self.args.trials - len(values)))
        return values

    def plot_curves(self) -> None:
        plt.rcParams.update({"font.family": "serif", "font.size": 12})
        styles = {
            "Random Search": {"color": "#777777", "linestyle": ":", "linewidth": 2.0},
            "Manual Sampling": {"color": "#2ca02c", "linestyle": "-.", "linewidth": 2.0},
            "Genetic Algorithm": {"color": "#9467bd", "linestyle": "--", "linewidth": 2.0},
            "PSO": {"color": "#ff7f0e", "linestyle": (0, (3, 1, 1, 1)), "linewidth": 2.0},
            "SA": {"color": "#17becf", "linestyle": (0, (5, 2)), "linewidth": 2.0},
            "SA-TPE Favorable": {"color": "#d62728", "linestyle": "-", "linewidth": 2.5},
        }
        ylabel = "Composite Perception Score" if self.args.objective_mode == "composite" else "YOLO Confidence"

        def draw(stem: str, attr: str, invert: bool = False) -> None:
            fig, ax = plt.subplots(figsize=(8.4, 5.1))
            iterations = np.arange(1, self.args.trials + 1)
            all_values: List[float] = []
            for method in METHODS:
                history = self.histories.get(method)
                if history is None:
                    continue
                curve = self.padded_curve(history, attr)
                if not curve:
                    continue
                values = [1.0 - value for value in curve] if invert else curve
                all_values.extend(values)
                ax.plot(iterations, values, label=method, **styles[method])

            ax.set_xlabel("Number of Iterations (Sample Efficiency)")
            ax.set_ylabel(f"1 - {ylabel}" if invert else ylabel)
            ax.set_title("Optimization Convergence Comparison")
            ax.set_xlim(1, self.args.trials)
            if self.args.ymin is not None or self.args.ymax is not None:
                ymin = self.args.ymin if self.args.ymin is not None else 0.0
                ymax = self.args.ymax if self.args.ymax is not None else 1.0
            elif all_values:
                value_min = min(all_values)
                value_max = max(all_values)
                padding = max(0.005, (value_max - value_min) * self.args.y_padding)
                ymin = max(0.0, value_min - padding)
                ymax = min(1.0, value_max + padding)
                if ymax - ymin < self.args.min_y_span:
                    center = (ymin + ymax) / 2.0
                    ymin = max(0.0, center - self.args.min_y_span / 2.0)
                    ymax = min(1.0, center + self.args.min_y_span / 2.0)
            else:
                ymin, ymax = 0.0, 1.0
            ax.set_ylim(ymin, ymax)
            ax.grid(True, linestyle="--", alpha=0.45)
            ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.18),
                ncol=3,
                fontsize=10,
                framealpha=0.95,
                handlelength=2.6,
                columnspacing=1.15,
            )
            fig.subplots_adjust(left=0.11, right=0.985, top=0.88, bottom=0.31)
            fig.savefig(self.output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
            fig.savefig(self.output_dir / f"{stem}.pdf", dpi=300, bbox_inches="tight")
            plt.close(fig)

        draw("score_convergence", "plotted_best_score")
        draw("score_convergence_inverse", "plotted_best_score", invert=True)
        draw("current_score", "score")

    def save_csvs(self) -> None:
        with open(self.output_dir / "comparison_results.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Iteration", *METHODS])
            for index in range(self.args.trials):
                row = [index + 1]
                for method in METHODS:
                    history = self.histories.get(method)
                    curve = self.padded_curve(history, "plotted_best_score") if history else []
                    row.append(curve[index] if index < len(curve) else "")
                writer.writerow(row)

        with open(self.output_dir / "per_trial_details.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Method",
                    "Role",
                    "Iteration",
                    "Score",
                    "Cost",
                    "PlottedBestScore",
                    "Confidence",
                    "IoU",
                    "BBoxQuality",
                    "PresetName",
                    *PARAM_NAMES,
                ]
            )
            for method in METHODS:
                history = self.histories.get(method)
                if history is None:
                    continue
                for record in history.records:
                    writer.writerow(
                        [
                            record.method,
                            record.role,
                            record.iteration,
                            record.score,
                            record.cost,
                            record.plotted_best_score,
                            record.confidence,
                            record.iou,
                            record.bbox_quality,
                            record.preset_name,
                            *[record.params.get(name, "") for name in PARAM_NAMES],
                        ]
                    )

        config = {
            "score_definition": (
                "confidence"
                if self.args.objective_mode == "confidence"
                else "confidence^confidence_weight * IoU^iou_weight * bbox_quality^bbox_weight"
            ),
            "favorable_cost": "1 - score",
            "boundary_cost": "score",
            "plotted_favorable_curve": "cumulative max score",
            "plotted_boundary_curve": "cumulative min score",
            "objective_mode": self.args.objective_mode,
            "confidence_weight": self.args.confidence_weight,
            "iou_weight": self.args.iou_weight,
            "bbox_weight": self.args.bbox_weight,
            "target_offset_fraction": self.args.target_offset_fraction,
            "pso_particles": self.args.pso_particles,
            "pso_inertia": self.args.pso_inertia,
            "pso_cognitive": self.args.pso_cognitive,
            "pso_social": self.args.pso_social,
            "pso_velocity_fraction": self.args.pso_velocity_fraction,
            "sa_initial_temperature": self.args.sa_initial_temperature,
            "sa_final_temperature": self.args.sa_final_temperature,
            "sa_step_fraction": self.args.sa_step_fraction,
        }
        with open(self.output_dir / "cost_definition.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    def run(self) -> None:
        print("\n" + "=" * 70)
        print("Cost-aligned optimizer comparison")
        print("Score S: confidence or composite perception score")
        print("Favorable cost: 1 - S; Boundary cost: S; all optimizers minimize cost")
        print("=" * 70)
        with self.env:
            self.initialize_reference_bbox()
            self.run_sampler_method("Random Search", RandomSampler(seed=self.args.seed))
            self.run_manual_sampling()
            self.run_sampler_method("Genetic Algorithm", NSGAIISampler(seed=self.args.seed, population_size=self.args.ga_population))
            self.run_pso()
            self.run_sa()
            self.run_sampler_method(
                "SA-TPE Favorable",
                TPESampler(seed=self.args.seed + 101, n_startup_trials=self.args.tpe_startup_trials),
            )
        if self.display_surf is not None:
            pygame.quit()
        self.plot_curves()
        self.save_csvs()
        print(f"\nOutputs saved to: {self.output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cost-aligned optimizer comparison for CARLA + YOLO weather search.")
    parser.add_argument("--trials", type=int, default=150)
    parser.add_argument("--remote-host", default="127.0.0.1")
    parser.add_argument("--remote-port", type=int, default=5555)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--weights", default="yolo12x.pt")
    parser.add_argument("--device", default=None)
    parser.add_argument("--output-dir", default="./paper_results")
    parser.add_argument("--no-display", action="store_true")

    parser.add_argument("--objective-mode", choices=["confidence", "composite"], default="composite")
    parser.add_argument("--reference-bbox", default="", help="Optional reference bbox x1,y1,x2,y2.")
    parser.add_argument("--confidence-weight", type=float, default=1.0)
    parser.add_argument("--iou-weight", type=float, default=0.8)
    parser.add_argument("--bbox-weight", type=float, default=0.4)
    parser.add_argument("--target-offset-fraction", type=float, default=0.0)

    parser.add_argument("--manual-limit", type=int, default=0)
    parser.add_argument("--ga-population", type=int, default=10)
    parser.add_argument("--tpe-startup-trials", type=int, default=10)
    parser.add_argument("--pso-particles", type=int, default=10)
    parser.add_argument("--pso-inertia", type=float, default=0.72)
    parser.add_argument("--pso-cognitive", type=float, default=1.49)
    parser.add_argument("--pso-social", type=float, default=1.49)
    parser.add_argument("--pso-velocity-fraction", type=float, default=0.2)
    parser.add_argument("--sa-initial-temperature", type=float, default=0.2)
    parser.add_argument("--sa-final-temperature", type=float, default=0.005)
    parser.add_argument("--sa-step-fraction", type=float, default=0.15)
    parser.add_argument("--ymin", type=float, default=None, help="Optional fixed plot y-axis minimum.")
    parser.add_argument("--ymax", type=float, default=None, help="Optional fixed plot y-axis maximum.")
    parser.add_argument("--y-padding", type=float, default=0.25, help="Relative padding around automatic y-axis limits.")
    parser.add_argument("--min-y-span", type=float, default=0.06, help="Minimum automatic y-axis span for visually separating close curves.")
    return parser.parse_args()


if __name__ == "__main__":
    CostAlignedComparison(parse_args()).run()
