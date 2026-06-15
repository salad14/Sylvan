#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA 0.9.15 桥接服务（运行在 Python 3.7 环境）

作用：
1. 在本机启动 CARLA 客户端，生成主车与目标车，挂载 RGB 相机。
2. 监听 TCP 端口，接收 JSON 指令：
   {"cmd": "apply_and_capture", "weather": {...}, "width": 1280, "height": 720}
3. 按照请求设置天气，前进几帧以稳定，然后返回单张图像（BGR 原始字节 base64）。

这样可以让上层优化/YOLO（Python 3.10+ 环境）通过网络调用，无需在高版本里安装 carla。

使用示例（Python 3.7 环境）：
    python yolo/carla_bridge_server.py --port 5555 --width 1280 --height 720

协议：
 - 传入：一行 JSON（UTF-8），必须包含 cmd 字段。
 - 仅支持 cmd=apply_and_capture:
     {"cmd": "apply_and_capture", "weather": {...}, "width": 1280, "height": 720}
 - 返回：一行 JSON
     {"ok": true, "frame": 123, "width": 1280, "height": 720, "bgr_b64": "..."}
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import socket
import sys
import time
from typing import Dict, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# 寻找 CARLA Python API（适配 0.9.15 + Python 3.7）
# ---------------------------------------------------------------------------

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.join(ROOT, "PythonAPI"))

CARLA_EGG_PATTERN = os.path.join(
    ROOT,
    "PythonAPI",
    "carla",
    "dist",
    # 直接将版本固定为 3.7，不再动态获取
    "carla-*3.7-%s.egg"
    % (
        "win-amd64" if os.name == "nt" else "linux-x86_64",
    ),
)

try:
    sys.path.append(glob.glob(CARLA_EGG_PATTERN)[0])
except IndexError as exc:
    raise RuntimeError("未找到 CARLA egg，检查路径与 Python 版本是否匹配: %s" % CARLA_EGG_PATTERN) from exc

import carla  # noqa: E402


class CarlaBridgeEnv:
    """封装 CARLA，同步模式，提供天气设置与图像抓取。"""

    def __init__(
        self,
        host: str,
        port: int,
        width: int,
        height: int,
        fov: float,
        fixed_delta: float,
        camera_offset: Tuple[float, float, float],
        camera_pitch: float,
        target_offset_scale: float,
    ) -> None:
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.fov = fov
        self.fixed_delta = fixed_delta
        self.camera_offset = camera_offset
        self.camera_pitch = camera_pitch
        self.target_offset_scale = target_offset_scale

        self.client: Optional[carla.Client] = None
        self.world: Optional[carla.World] = None
        self.original_settings: Optional[carla.WorldSettings] = None
        self.ego: Optional[carla.Actor] = None
        self.target: Optional[carla.Actor] = None
        self.target_base_transform: Optional[carla.Transform] = None
        self.camera: Optional[carla.Sensor] = None
        self.actors = []
        self.sensors = []
        self.image_queue = []

    def connect(self) -> None:
        print("\n" + "="*60)
        print("CARLA 桥接服务启动 - OpenDrive 自定义地图模式")
        print("="*60)
        
        print(f"\n[1/5] 连接 CARLA 服务器 {self.host}:{self.port}...")
        self.client = carla.Client(self.host, self.port)
        self.client.set_timeout(10.0)
        
        # 加载自定义 OpenDrive 地图
        print(f"\n[2/5] 加载 OpenDrive 地图...")
        xodr_path = "/home/vr/桌面/Carla0.9.15/PythonAPI/util/opendrive/Motorway.xodr"
        print(f"   地图文件: {xodr_path}")
        
        try:
            with open(xodr_path, 'r', encoding='utf-8') as f:
                opendrive_content = f.read()
            
            # 加载 OpenDrive 地图
            vertex_distance = 2.0  # 道路网格顶点间距
            max_road_length = 50.0  # 最大道路长度
            wall_height = 1.0  # 墙体高度
            extra_width = 0.6  # 额外宽度
            
            self.world = self.client.generate_opendrive_world(
                opendrive_content,
                carla.OpendriveGenerationParameters(
                    vertex_distance=vertex_distance,
                    max_road_length=max_road_length,
                    wall_height=wall_height,
                    additional_width=extra_width,
                    smooth_junctions=True,
                    enable_mesh_visibility=True
                )
            )
            print(f"✓ OpenDrive 地图已加载")
            
            # 等待地图稳定
            import time
            time.sleep(3)
            
        except Exception as e:
            raise RuntimeError(f"加载 OpenDrive 地图失败: {e}")
        
        self.original_settings = self.world.get_settings()

        print(f"\n[3/5] 配置同步模式...")
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = self.fixed_delta
        settings.max_substeps = 1
        settings.max_substep_delta_time = self.fixed_delta
        self.world.apply_settings(settings)
        self.world.tick()
        print(f"✓ 同步模式已启用（步长: {self.fixed_delta}s）")

        print(f"\n[4/5] 生成车辆...")
        self._spawn_vehicles()
        
        print(f"\n[5/5] 配置相机...")
        self._setup_camera()
        
        print("\n" + "="*60)
        print("✓ 桥接服务初始化完成，等待连接...")
        print("="*60 + "\n")

    def close(self) -> None:
        if self.world and self.original_settings:
            self.world.apply_settings(self.original_settings)
        for sensor in self.sensors:
            try:
                sensor.stop()
                sensor.destroy()
            except Exception:
                pass
        for actor in self.actors:
            try:
                actor.destroy()
            except Exception:
                pass

    def _spawn_vehicles(self) -> None:
        blueprint_library = self.world.get_blueprint_library()
        ego_bp = blueprint_library.find("vehicle.tesla.model3")
        ego_bp.set_attribute("role_name", "ego")
        target_bp = blueprint_library.find("vehicle.tesla.model3")
        target_bp.set_attribute("role_name", "target")

        print(f"   使用固定坐标生成车辆（OpenDrive 地图）...")
        
        # 固定主车位置
        ego_location = carla.Location(x=-60.0, y=-50.0, z=0.1)
        ego_rotation = carla.Rotation(yaw=0.0)
        ego_transform = carla.Transform(ego_location, ego_rotation)
        
        print(f"   主车坐标: X={ego_location.x}, Y={ego_location.y}, Z={ego_location.z}, Yaw={ego_rotation.yaw}")
        print(f"   生成主车...")
        ego_actor = self.world.try_spawn_actor(ego_bp, ego_transform)
        
        if ego_actor is None:
            # 如果固定位置被占用，尝试稍微调整Z坐标
            print(f"   ⚠ 固定位置被占用，尝试调整高度...")
            for z_offset in [0.5, 1.0, 2.0, 3.0]:
                test_transform = carla.Transform(
                    carla.Location(x=-60.0, y=-50.0, z=0.1 + z_offset),
                    ego_rotation
                )
                ego_actor = self.world.try_spawn_actor(ego_bp, test_transform)
                if ego_actor:
                    print(f"   ✓ 主车已生成（高度偏移 +{z_offset}m）")
                    break
        else:
            print(f"   ✓ 主车已生成")
        
        if ego_actor is None:
            raise RuntimeError("生成主车失败：所有尝试的位置都被占用")
        
        # 固定目标车位置
        target_location = carla.Location(x=-50.0, y=-50.0, z=0.1)
        target_rotation = carla.Rotation(yaw=0.0)
        target_transform = carla.Transform(target_location, target_rotation)
        
        print(f"   目标车坐标: X={target_location.x}, Y={target_location.y}, Z={target_location.z}, Yaw={target_rotation.yaw}")
        print(f"   生成目标车...")
        target_actor = self.world.try_spawn_actor(target_bp, target_transform)
        
        if target_actor is None:
            # 如果固定位置被占用，尝试稍微调整Z坐标
            print(f"   ⚠ 固定位置被占用，尝试调整高度...")
            for z_offset in [0.5, 1.0, 2.0, 3.0]:
                test_transform = carla.Transform(
                    carla.Location(x=-50.0, y=-50.0, z=0.1 + z_offset),
                    target_rotation
                )
                target_actor = self.world.try_spawn_actor(target_bp, test_transform)
                if target_actor:
                    print(f"   ✓ 目标车已生成（高度偏移 +{z_offset}m）")
                    break
        else:
            print(f"   ✓ 目标车已生成")
        
        if target_actor is None:
            ego_actor.destroy()
            raise RuntimeError("生成目标车失败：所有尝试的位置都被占用")
        
        print(f"   等待车辆稳定...")
        
        ego_actor.set_autopilot(False)
        target_actor.set_autopilot(False)
        
        self.ego = ego_actor
        self.target = target_actor
        self.actors.extend([ego_actor, target_actor])
        
        # 等待车辆稳定（如果从空中生成会自然掉落）
        for i in range(20):  # 等待约1秒（20 * 0.05s）
            self.world.tick()
            if i % 5 == 0 and i > 0:
                print(f"   等待中... {i*self.fixed_delta:.1f}s")
        
        # 获取最终位置
        ego_tf = self.ego.get_transform()
        target_tf = self.target.get_transform()
        self.target_base_transform = target_tf
        target_loc = target_tf.location
        
        # 计算实际距离和方向
        actual_distance = ego_tf.location.distance(target_loc)
        direction_vec = target_loc - ego_tf.location
        
        # 计算目标车相对主车的方位
        forward = ego_tf.get_forward_vector()
        forward_normalized = forward / (forward.length() + 1e-6)
        direction_normalized = direction_vec / (actual_distance + 1e-6)
        
        # 点积：判断前后
        dot_forward = (forward_normalized.x * direction_normalized.x + 
                      forward_normalized.y * direction_normalized.y)
        
        # 叉积Z分量：判断左右
        cross_z = forward_normalized.x * direction_normalized.y - forward_normalized.y * direction_normalized.x
        
        # 判断方位
        if dot_forward > 0.866:  # cos(30°)
            position_desc = "正前方"
        elif dot_forward > 0.5:  # cos(60°)
            position_desc = "前方偏" + ("左" if cross_z > 0 else "右")
        elif dot_forward > 0:
            position_desc = "侧前方-" + ("左" if cross_z > 0 else "右")
        elif dot_forward > -0.5:
            position_desc = "侧后方-" + ("左" if cross_z > 0 else "右")
        else:
            position_desc = "后方"
        
        # 检查是否在相机视野内
        in_camera_view = dot_forward > 0.3 and abs(cross_z) < 0.7
        
        print(f"\n   === 车辆坐标信息（最终位置） ===")
        print(f"   主车位置: X={ego_tf.location.x:.2f}, Y={ego_tf.location.y:.2f}, Z={ego_tf.location.z:.2f}")
        print(f"   主车朝向: Yaw={ego_tf.rotation.yaw:.2f}°")
        print(f"   目标车位置: X={target_loc.x:.2f}, Y={target_loc.y:.2f}, Z={target_loc.z:.2f}")
        print(f"   车辆间距: {actual_distance:.2f} 米")
        print(f"   相对位置: ΔX={direction_vec.x:.2f}, ΔY={direction_vec.y:.2f}, ΔZ={direction_vec.z:.2f}")
        print(f"   方位判断: {position_desc} (前向相似度: {dot_forward:.2f})")
        print(f"   相机视野: {'✓ 应该在画面中' if in_camera_view else '✗ 可能不在画面中'}")
        print(f"   ===================================")
        
        # 设置观察者视角（从上方俯视）
        final_ego_tf = self.ego.get_transform()
        spectator = self.world.get_spectator()
        spectator_loc = final_ego_tf.location + carla.Location(z=25.0)
        spectator.set_transform(
            carla.Transform(
                spectator_loc,
                carla.Rotation(pitch=-60.0, yaw=final_ego_tf.rotation.yaw),
            )
        )
        print(f"   ✓ 观察者视角已设置（俯视角度）")

    def _setup_camera(self) -> None:
        blueprint_library = self.world.get_blueprint_library()
        cam_bp = blueprint_library.find("sensor.camera.rgb")
        
        # 基本设置
        cam_bp.set_attribute("image_size_x", str(self.width))
        cam_bp.set_attribute("image_size_y", str(self.height))
        cam_bp.set_attribute("fov", str(self.fov))
        cam_bp.set_attribute("sensor_tick", str(self.fixed_delta))
        
        # 图像质量设置（禁用运动模糊等后处理效果）
        cam_bp.set_attribute("motion_blur_intensity", "0.0")
        cam_bp.set_attribute("motion_blur_max_distortion", "0.0")
        cam_bp.set_attribute("motion_blur_min_object_screen_size", "0.0")
        
        print(f"   相机配置:")
        print(f"   - 分辨率: {self.width}x{self.height}")
        print(f"   - 视场角: {self.fov}°")
        print(f"   - 运动模糊: 已禁用")

        # 相机位置（相对于主车）
        cam_loc = carla.Location(
            x=self.camera_offset[0],
            y=self.camera_offset[1],
            z=self.camera_offset[2],
        )
        cam_rot = carla.Rotation(pitch=self.camera_pitch)
        cam_tf = carla.Transform(cam_loc, cam_rot)
        
        # 计算相机在世界坐标系中的位置
        ego_tf = self.ego.get_transform()
        camera_world_loc = ego_tf.transform(cam_loc)
        
        print(f"   相机位置:")
        print(f"   - 相对主车: 前{self.camera_offset[0]:.1f}m, 左{self.camera_offset[1]:.1f}m, 高{self.camera_offset[2]:.1f}m")
        print(f"   - 世界坐标: X={camera_world_loc.x:.2f}, Y={camera_world_loc.y:.2f}, Z={camera_world_loc.z:.2f}")
        print(f"   - 俯仰角: {self.camera_pitch:.1f}° {'(向下)' if self.camera_pitch < 0 else '(向上)' if self.camera_pitch > 0 else '(水平)'}")
        
        camera = self.world.spawn_actor(cam_bp, cam_tf, attach_to=self.ego)
        camera.listen(self._on_image)

        self.camera = camera
        self.sensors.append(camera)
        
        # 等待相机准备好
        for _ in range(3):
            self.world.tick()
        
        print(f"   ✓ 相机已就绪")

    def _on_image(self, image: carla.Image) -> None:
        self.image_queue.append(image)

    def apply_weather(self, params: Dict[str, float]) -> None:
        weather = carla.WeatherParameters(
            cloudiness=params.get("cloudiness", 0.0),
            precipitation=params.get("precipitation", 0.0),
            fog_density=params.get("fog_density", 0.0),
            wetness=params.get("wetness", 0.0),
            sun_altitude_angle=params.get("sun_altitude_angle", 0.0),
            sun_azimuth_angle=params.get("sun_azimuth_angle", 0.0),
            rayleigh_scattering_scale=params.get("rayleigh_scattering_scale", 0.0),
            mie_scattering_scale=params.get("mie_scattering_scale", 0.0),
        )
        self.world.set_weather(weather)
        for _ in range(2):
            self.world.tick()
            self._drain_queue()

    def set_target_offset(self, offset_fraction: float) -> None:
        if self.target is None or self.target_base_transform is None:
            return
        offset_fraction = float(np.clip(offset_fraction, -1.0, 1.0))

        base = self.target_base_transform
        lateral_offset = self.target_offset_scale * offset_fraction
        shifted = carla.Transform(
            carla.Location(
                x=base.location.x,
                y=base.location.y + lateral_offset,
                z=base.location.z,
            ),
            base.rotation,
        )
        self.target.set_transform(shifted)
        self.target.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
        self.target.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, 0.0))
        for _ in range(2):
            self.world.tick()
            self._drain_queue()

    def _drain_queue(self) -> None:
        if not self.image_queue:
            return
        self.image_queue.clear()

    def capture_frame(self, timeout: float = 2.0) -> Optional[Dict[str, object]]:
        self.world.tick()
        frame_id = self.world.get_snapshot().frame
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.image_queue:
                time.sleep(0.01)
                continue
            image = self.image_queue.pop(0)
            if image.frame != frame_id:
                continue
            array = np.frombuffer(image.raw_data, dtype=np.uint8)
            array = array.reshape((image.height, image.width, 4))
            bgr = array[:, :, :3].copy()
            return {
                "frame": frame_id,
                "width": image.width,
                "height": image.height,
                "bgr": bgr,
            }
        return None


def handle_client(conn: socket.socket, env: CarlaBridgeEnv) -> None:
    """处理单个客户端连接（行分隔 JSON 协议）。"""
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                except Exception as exc:
                    resp = {"ok": False, "error": "JSON 解析失败: %s" % exc}
                    conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                    continue

                cmd = req.get("cmd")
                if cmd != "apply_and_capture":
                    resp = {"ok": False, "error": "未知 cmd: %s" % cmd}
                    conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                    continue

                print(f"\n[请求] 设置天气并捕获图像")
                weather = req.get("weather", {})
                target_offset_fraction = float(req.get("target_offset_fraction", 0.0))
                width = req.get("width", env.width)
                height = req.get("height", env.height)
                
                # 若请求分辨率不同，重新配置相机
                if (width, height) != (env.width, env.height):
                    print(f"  分辨率变更: {env.width}x{env.height} -> {width}x{height}")
                    env.width, env.height = width, height
                    env.close()
                    env.connect()
                
                # 打印天气参数（简略）
                print(
                    f"  天气: Sun{weather.get('sun_altitude_angle', 0):.0f}° "
                    f"Cloud{weather.get('cloudiness', 0):.0f}% Fog{weather.get('fog_density', 0):.0f}% "
                    f"TargetLeftOffset{target_offset_fraction:.2f}"
                )
                
                env.set_target_offset(target_offset_fraction)
                env.apply_weather(weather)
                frame = env.capture_frame()
                
                if frame is None:
                    print(f"  ✗ 捕获失败：超时")
                    resp = {"ok": False, "error": "抓取帧超时"}
                else:
                    bgr_bytes = frame["bgr"].tobytes()
                    b64 = base64.b64encode(bgr_bytes).decode("ascii")
                    print(f"  ✓ 捕获成功：帧#{frame['frame']} ({frame['width']}x{frame['height']}, {len(b64)} bytes)")
                    resp = {
                        "ok": True,
                        "frame": frame["frame"],
                        "width": frame["width"],
                        "height": frame["height"],
                        "bgr_b64": b64,
                    }
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))


def serve(args: argparse.Namespace) -> None:
    env = CarlaBridgeEnv(
        host=args.host,
        port=args.carla_port,
        width=args.width,
        height=args.height,
        fov=args.fov,
        fixed_delta=args.fixed_delta,
        camera_offset=(args.camera_x, 0.0, args.camera_z),
        camera_pitch=args.camera_pitch,
        target_offset_scale=args.target_offset_scale,
    )
    env.connect()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.bind, args.port))
    srv.listen(1)
    print("桥接服务已启动，监听 %s:%d" % (args.bind, args.port))
    try:
        while True:
            conn, addr = srv.accept()
            print("客户端连接:", addr)
            handle_client(conn, env)
    except KeyboardInterrupt:
        print("服务被中断，退出。")
    finally:
        env.close()
        srv.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CARLA 图像桥接服务 (Python 3.7) - OpenDrive 自定义地图模式",
        epilog="使用 Motorway.xodr 地图，车辆固定在指定坐标"
    )
    parser.add_argument("--bind", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=5555, help="监听端口")
    parser.add_argument("--carla-port", type=int, default=2000, help="CARLA 服务器端口")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA 服务器地址")
    parser.add_argument("--width", type=int, default=1280, help="相机宽度")
    parser.add_argument("--height", type=int, default=720, help="相机高度")
    parser.add_argument("--fov", type=float, default=90.0, help="相机视场角")
    parser.add_argument("--fixed-delta", type=float, default=0.05, help="同步模式步长秒")
    parser.add_argument("--camera-x", type=float, default=1.5, help="相机前向偏移米")
    parser.add_argument("--camera-z", type=float, default=2.0, help="相机高度偏移米")
    parser.add_argument("--camera-pitch", type=float, default=-8.0, help="相机俯仰角（负值向下）")
    parser.add_argument("--target-offset-scale", type=float, default=2.0, help="target_offset_fraction=1.0 时对应的目标车横向偏移米数")
    return parser.parse_args()


if __name__ == "__main__":
    serve(parse_args())

