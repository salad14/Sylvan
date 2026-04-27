"""传感器域。"""

from .base import SensorRig
from .image_pipeline import carla_image_to_surface
from .mono_camera import MonoCameraRig
from .semantic_camera import spawn_semantic_camera
from .stereo_camera import StereoCameraRig


def build_camera_rig(mode: str) -> SensorRig:
    """根据模式字符串返回对应相机组。"""
    if mode == "mono":
        return MonoCameraRig()
    return StereoCameraRig()


__all__ = [
    "MonoCameraRig",
    "SensorRig",
    "StereoCameraRig",
    "build_camera_rig",
    "carla_image_to_surface",
    "spawn_semantic_camera",
]
