"""ROS yaw 偏移校准。完整保留原 _process_json_data 中的校准逻辑。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..config.logging_config import get_logger

_logger = get_logger()


def _wrap_deg(angle: float) -> float:
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


@dataclass
class YawCalibrator:
    """首次收到数据时将 ROS yaw 与当前 CARLA yaw 对齐。"""

    calibrated: bool = False
    offset: float = 0.0
    initial_ros_yaw: Optional[float] = None
    initial_carla_yaw: Optional[float] = None

    def reset(self) -> None:
        self.calibrated = False
        self.offset = 0.0
        self.initial_ros_yaw = None
        self.initial_carla_yaw = None
        _logger.info("ROS yaw校准已重置，下次接收数据时将重新校准")

    def ros_to_carla_yaw(self, ros_yaw_rad: float, current_carla_yaw: float) -> float:
        """ROS yaw（弧度）→ CARLA yaw（度）。"""
        yaw_degrees = math.degrees(ros_yaw_rad)
        ros_yaw_converted = -yaw_degrees  # 方向反转：ROS -> CARLA

        if not self.calibrated:
            self.initial_ros_yaw = ros_yaw_converted
            self.initial_carla_yaw = current_carla_yaw
            self.offset = current_carla_yaw - ros_yaw_converted
            self.calibrated = True
            _logger.info("=" * 50)
            _logger.info("ROS YAW偏移校准完成!")
            _logger.info(f"  初始ROS yaw (转换后): {ros_yaw_converted:.1f}度")
            _logger.info(f"  当前CARLA车辆yaw: {current_carla_yaw:.1f}度")
            _logger.info(f"  计算的偏移量: {self.offset:.1f}度")
            _logger.info("  此后ROS角度变化将相对于当前车辆朝向")
            _logger.info("  按 Y 键可重新校准")
            _logger.info("=" * 50)

        return _wrap_deg(ros_yaw_converted + self.offset)
