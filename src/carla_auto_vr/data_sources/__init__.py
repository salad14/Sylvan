"""数据源域：ROS / JSON / 状态应用。"""

from .base import VehicleDataSource
from .json_player import JsonFilePlayer
from .state_applier import VehicleStateApplier
from .yaw_calibrator import YawCalibrator


def get_ros_bridge_class():
    """懒加载 ROSBridge（仅在安装了 rclpy 时可用）。"""
    from .ros_bridge import ROSBridge

    return ROSBridge


__all__ = [
    "JsonFilePlayer",
    "VehicleDataSource",
    "VehicleStateApplier",
    "YawCalibrator",
    "get_ros_bridge_class",
]
