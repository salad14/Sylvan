from __future__ import annotations

import time
import traceback

import carla
import pygame

from ..accidents import AccidentManager
from ..bootstrap.carla_loader import import_carla
from ..bootstrap.ros_environment import setup_ros_environment
from ..config.constants import FPS
from ..config.logging_config import get_logger
from ..config.scenarios_config import map_has_pedestrian_navmesh
from ..config.settings import SimulationSettings
from ..core.actor_registry import ActorRegistry
from ..core.client import CarlaClient
from ..data_sources import JsonFilePlayer, VehicleStateApplier, YawCalibrator
from ..sensors import build_camera_rig
from ..traffic import setup_dynamic_traffic, setup_static_vehicles, spawn_traffic_cones
from ..vehicle import KeyboardController, spawn_ego_vehicle
from ..world import (
    LayeredRenderer,
    WeatherController,
    is_opendrive_target,
    load_opendrive_world,
    switch_builtin_map,
)

_logger = get_logger()


class Simulation:
    """顶层装配。由 run_loop 驱动。"""

    def __init__(self, settings: SimulationSettings):
        self.settings = settings

        self.registry = ActorRegistry()
        self.carla_client: CarlaClient | None = None
        self.world: carla.World | None = None
        self.vehicle: carla.Actor | None = None

        self.camera_rig = build_camera_rig(settings.camera_mode)
        self.keyboard = KeyboardController()
        self.weather_controller: WeatherController | None = None
        self.layered_renderer: LayeredRenderer | None = None
        self.yaw_calibrator = YawCalibrator()
        self.state_applier: VehicleStateApplier | None = None
        self.ros_bridge = None
        self.json_player: JsonFilePlayer | None = None
        self.accident_manager: AccidentManager | None = None

        self._is_opendrive = is_opendrive_target(settings.map)

    # ----------------------- 初始化 -----------------------
    def connect(self) -> None:
        # 确保 CARLA egg 在 sys.path（在 import_carla 中处理）
        import_carla()
        self.carla_client = CarlaClient(self.settings.host, self.settings.port)
        self.carla_client.connect()
        client = self.carla_client.client
        world = self.carla_client.world
        assert client is not None and world is not None

        # 地图切换
        if self._is_opendrive:
            _logger.info(f"检测到OpenDRIVE地图文件: {self.settings.map}")
            world = load_opendrive_world(client, self.settings.map)
        else:
            world = switch_builtin_map(client, world, self.settings.map)

        self.carla_client.world = world
        self.world = world
        self.carla_client.apply_sync_settings(FPS)

    def setup_world_and_vehicle(self) -> None:
        assert self.world is not None
        self.vehicle = spawn_ego_vehicle(
            self.world,
            is_opendrive_map=self._is_opendrive,
            map_argument=self.settings.map,
        )
        self.registry.add(self.vehicle, tag="ego")

        self.weather_controller = WeatherController(self.world)

        if self.settings.layered_rendering:
            assert self.carla_client is not None and self.carla_client.client is not None
            self.layered_renderer = LayeredRenderer(self.world, self.carla_client.client)
            # 初始按 CLI 开关调整
            if self.settings.clean_environment:
                self.layered_renderer.remove_clean_environment()
            else:
                if self.settings.no_buildings:
                    self.layered_renderer.remove_environment_objects(["BUILDINGS"])
                if self.settings.no_vegetation:
                    self.layered_renderer.remove_environment_objects(["VEGETATION"])
                if self.settings.no_fences:
                    self.layered_renderer.remove_environment_objects(["FENCES"])

    def setup_sensors(self) -> None:
        assert self.world is not None and self.vehicle is not None
        self.camera_rig.attach(self.world, self.vehicle)
        for s in self.camera_rig.sensors:
            self.registry.add(s, tag="camera")

    def setup_traffic(self) -> None:
        assert self.world is not None and self.carla_client is not None
        client = self.carla_client.client
        assert client is not None

        if self._is_opendrive:
            # OpenDRIVE: 静态车辆 + 交通锥，不生成动态 AI
            setup_static_vehicles(self.world, self.registry)
            spawn_traffic_cones(self.world, self.registry)
        else:
            setup_dynamic_traffic(client, self.world, self.registry)

    def setup_data_sources(self) -> None:
        assert self.vehicle is not None
        self.state_applier = VehicleStateApplier(self.vehicle, self.yaw_calibrator)

        if self.settings.json:
            player = JsonFilePlayer(self.settings.json)
            if player.load():
                self.json_player = player

        if self.settings.ros and not self.settings.json:
            try:
                setup_ros_environment()
                import rclpy

                if not rclpy.ok():
                    rclpy.init()

                from ..data_sources import get_ros_bridge_class

                ROSBridge = get_ros_bridge_class()
                self.ros_bridge = ROSBridge(self.settings.host, self.settings.port)
                time.sleep(1.0)
                _logger.info("ROS桥接已设置")
            except Exception as e:  # noqa: BLE001
                _logger.error(f"设置ROS桥接失败: {e}")
                _logger.error(traceback.format_exc())
                self.ros_bridge = None

    def setup_accidents(self) -> None:
        assert self.world is not None and self.vehicle is not None
        enabled = self._should_enable_accidents()
        if not enabled:
            return
        try:
            self.accident_manager = AccidentManager(self.world, self.vehicle)
            if not self.accident_manager.is_available():
                _logger.warning("事故模拟管理器未能初始化，已禁用")
                self.accident_manager = None
        except Exception as e:  # noqa: BLE001
            _logger.error(f"初始化事故模拟时出错，已禁用: {e}")
            self.accident_manager = None

    def _should_enable_accidents(self) -> bool:
        """综合 CLI 开关 + 地图黑名单 + 运行时 navmesh 探测。"""
        assert self.world is not None
        flag = self.settings.accidents

        # 显式关闭：最高优先级
        if flag is False:
            _logger.info("事故模拟：已通过 --no-accidents 禁用")
            return False

        map_name = self.world.get_map().name
        auto_safe = map_has_pedestrian_navmesh(map_name) and not self._is_opendrive

        if flag is True:
            # 用户强制开启。若黑名单则警告
            if not auto_safe:
                _logger.warning(
                    f"事故模拟：用户通过 --accidents 强制开启，但地图 {map_name} "
                    f"通常缺少行人导航网格，可能导致段错误。继续执行..."
                )
            return True

        # 未指定：按黑名单 + navmesh 探测自动决定
        if not auto_safe:
            _logger.info(
                f"事故模拟：地图 {map_name} 在黑名单内或为 OpenDRIVE，自动禁用。"
                f"可加 --accidents 强制开启。"
            )
            return False

        # 运行时探测：尝试两次 get_random_location_from_navigation
        try:
            probe_ok = False
            for _ in range(3):
                loc = self.world.get_random_location_from_navigation()
                if loc is not None:
                    probe_ok = True
                    break
            if not probe_ok:
                _logger.info(
                    f"事故模拟：地图 {map_name} 实时探测无行人导航网格，自动禁用。"
                    f"可加 --accidents 强制开启。"
                )
                return False
        except Exception as e:  # noqa: BLE001
            _logger.warning(
                f"事故模拟：探测行人导航网格时出错 ({e})，保守禁用。可加 --accidents 强制开启。"
            )
            return False

        _logger.info(f"事故模拟：地图 {map_name} 通过导航网格探测，已启用")
        return True

    # ----------------------- 数据应用 -----------------------
    def apply_latest_ros_data(self) -> None:
        if self.ros_bridge is None or self.state_applier is None:
            return
        data = self.ros_bridge.get_latest_data()
        if data:
            self.state_applier.apply(data)

    def apply_next_json_frame(self) -> bool:
        if self.json_player is None or self.state_applier is None:
            return False
        frame = self.json_player.poll()
        if frame is None:
            return False
        self.state_applier.apply(frame)
        return True

    # ----------------------- 资源清理 -----------------------
    def cleanup(self) -> None:
        _logger.info("开始清理资源...")
        if self.ros_bridge is not None:
            try:
                self.ros_bridge.shutdown()
            except Exception as e:  # noqa: BLE001
                _logger.warning(f"关闭ROS桥接失败: {e}")
        if self.accident_manager is not None:
            self.accident_manager.cleanup()
        if self.layered_renderer is not None:
            self.layered_renderer.cleanup()
        try:
            self.camera_rig.destroy()
        except Exception:  # noqa: BLE001
            pass
        destroyed = self.registry.destroy_all()
        _logger.info(f"已销毁 {destroyed} 个 CARLA actor")
        try:
            pygame.quit()
        except Exception:  # noqa: BLE001
            pass
        try:
            import rclpy  # 仅在加载过时 shutdown

            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass
        _logger.info("清理完成")
