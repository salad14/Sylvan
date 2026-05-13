"""CARLA 客户端封装。"""

from __future__ import annotations

import traceback
from typing import Optional

import carla

from ..config.constants import FPS, TRAFFIC_MANAGER_PORT
from ..config.logging_config import get_logger

_logger = get_logger()


class CarlaClient:
    """封装 CARLA ``Client`` + ``World`` 的连接与同步模式应用。"""

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.client: Optional[carla.Client] = None
        self.world: Optional[carla.World] = None

    def connect(self) -> None:
        """连接服务器并获取 world。"""
        _logger.info(f"正在连接到CARLA服务器: {self.host}:{self.port}...")
        try:
            self.client = carla.Client(self.host, self.port)
            self.client.set_timeout(self.timeout)
        except Exception as e:  # noqa: BLE001
            _logger.error(f"创建CARLA客户端失败: {e}")
            raise

        try:
            version = self.client.get_server_version()
            _logger.info(f"已连接到CARLA服务器 (版本: {version})")
        except Exception as e:  # noqa: BLE001
            _logger.error(f"无法获取CARLA服务器版本，服务器可能未运行: {e}")
            raise

        try:
            self.world = self.client.get_world()
            _logger.info(f"当前CARLA世界实例: {self.world.get_map().name}")
        except Exception as e:  # noqa: BLE001
            _logger.error(f"获取CARLA世界实例失败: {e}")
            raise

        _logger.info(f"已成功连接到CARLA服务器: {self.host}:{self.port}")

    def apply_sync_settings(self, fps: int = FPS) -> None:
        """开启同步模式 + 物理子步进（与原实现一致）。"""
        assert self.world is not None
        try:
            settings = self.world.get_settings()
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 1.0 / fps
            settings.no_rendering_mode = False
            settings.substepping = True
            settings.max_substep_delta_time = 0.01
            settings.max_substeps = 10
            self.world.apply_settings(settings)
            _logger.info("已将CARLA世界设置为同步模式，并优化了物理模拟设置")
        except Exception as e:  # noqa: BLE001
            _logger.error(f"设置同步模式失败: {e}")
            raise

    def ensure_sync_and_traffic_manager(self, fps: int = FPS) -> carla.TrafficManager:
        """运行期重新确认同步与交通管理器状态（对应原 run/run_with_json_file）。"""
        assert self.client is not None and self.world is not None
        settings = self.world.get_settings()
        if not settings.synchronous_mode:
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 1.0 / fps
            settings.no_rendering_mode = False
            self.world.apply_settings(settings)
            _logger.info("重新确认世界同步模式已开启")
        tm = self.client.get_trafficmanager(TRAFFIC_MANAGER_PORT)
        tm.set_synchronous_mode(True)
        _logger.info("重新确认交通管理器同步模式已开启")
        return tm

    @staticmethod
    def precheck(host: str, port: int, timeout: float = 5.0) -> bool:
        """快速预检。"""
        try:
            _logger.info(f"预检查: 尝试连接CARLA服务器 {host}:{port}")
            c = carla.Client(host, port)
            c.set_timeout(timeout)
            version = c.get_server_version()
            _logger.info(f"预检查通过: CARLA服务器正在运行 (版本: {version})")
            return True
        except Exception as e:  # noqa: BLE001
            _logger.error(f"预检查失败: 无法连接到CARLA服务器: {e}")
            _logger.error(traceback.format_exc())
            return False
