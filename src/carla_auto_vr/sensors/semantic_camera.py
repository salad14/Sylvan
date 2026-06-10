"""辅助语义分割相机。实际逻辑已内聚到 world.layered_renderer.LayeredRenderer。

这里只保留一个薄入口，让外部能按需独立创建。
"""

from __future__ import annotations

import carla

from ..config.constants import WINDOW_HEIGHT, WINDOW_WIDTH
from ..config.logging_config import get_logger

_logger = get_logger()


def spawn_semantic_camera(
    world: carla.World,
    vehicle: carla.Actor,
    *,
    downscale: int = 4,
    fov: float = 90.0,
) -> carla.Actor | None:
    try:
        _logger.info("设置语义分割相机...")
        bp_lib = world.get_blueprint_library()
        bp = bp_lib.find("sensor.camera.semantic_segmentation")
        bp.set_attribute("image_size_x", str(max(1, WINDOW_WIDTH // downscale)))
        bp.set_attribute("image_size_y", str(max(1, WINDOW_HEIGHT // downscale)))
        bp.set_attribute("fov", str(fov))

        transform = carla.Transform(
            carla.Location(x=1.5, y=0.0, z=2.0),
            carla.Rotation(pitch=0),
        )
        cam = world.spawn_actor(
            bp, transform, attach_to=vehicle, attachment_type=carla.AttachmentType.Rigid
        )
        _logger.info("语义分割相机已创建")
        return cam
    except Exception as e:  # noqa: BLE001
        _logger.error(f"创建语义分割相机失败: {e}")
        return None
