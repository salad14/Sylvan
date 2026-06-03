"""特斯拉风格双目摄像头。参数 1:1 对齐原 _setup_stereo_camera。"""

from __future__ import annotations

from typing import Sequence

import carla
import pygame

from ..config.constants import WINDOW_HEIGHT, WINDOW_WIDTH
from ..config.logging_config import get_logger
from .base import SensorRig
from .image_pipeline import carla_image_to_surface

_logger = get_logger()


class StereoCameraRig(SensorRig):
    mode = "stereo"

    # 参数与原文件完全一致
    L_FOV = 100.0
    R_FOV = 100.0

    def __init__(self) -> None:
        super().__init__()
        self.left_camera: carla.Actor | None = None
        self.right_camera: carla.Actor | None = None

    def attach(self, world: carla.World, vehicle: carla.Actor) -> None:
        _logger.info("正在设置特斯拉风格的双目摄像头...")
        bp_lib = world.get_blueprint_library()

        left_bp = bp_lib.find("sensor.camera.rgb")
        left_bp.set_attribute("image_size_x", str(WINDOW_WIDTH // 2))
        left_bp.set_attribute("image_size_y", str(WINDOW_HEIGHT))
        left_bp.set_attribute("fov", str(self.L_FOV))
        left_bp.set_attribute("enable_postprocess_effects", "True")
        left_bp.set_attribute("lens_circle_falloff", "5.0")
        left_bp.set_attribute("lens_circle_multiplier", "0.7")
        left_bp.set_attribute("chromatic_aberration_intensity", "0.5")
        left_bp.set_attribute("chromatic_aberration_offset", "0")
        left_bp.set_attribute("fstop", "1.0")
        left_bp.set_attribute("focal_distance", "100.0")
        left_bp.set_attribute("blur_amount", "10.0")

        right_bp = bp_lib.find("sensor.camera.rgb")
        right_bp.set_attribute("image_size_x", str(WINDOW_WIDTH // 2))
        right_bp.set_attribute("image_size_y", str(WINDOW_HEIGHT))
        right_bp.set_attribute("fov", str(self.R_FOV))
        right_bp.set_attribute("enable_postprocess_effects", "True")
        right_bp.set_attribute("lens_circle_falloff", "5.0")
        right_bp.set_attribute("lens_circle_multiplier", "0.7")
        right_bp.set_attribute("chromatic_aberration_intensity", "0.5")
        right_bp.set_attribute("chromatic_aberration_offset", "0")
        right_bp.set_attribute("fstop", "4.0")
        right_bp.set_attribute("focal_distance", "1000.0")
        right_bp.set_attribute("blur_amount", "0.1")

        left_tf = carla.Transform(
            carla.Location(x=0.8, y=-0.15, z=1.7),
            carla.Rotation(pitch=-10),
        )
        right_tf = carla.Transform(
            carla.Location(x=0.8, y=0.15, z=1.7),
            carla.Rotation(pitch=-10),
        )

        self.left_camera = world.spawn_actor(
            left_bp, left_tf, attach_to=vehicle, attachment_type=carla.AttachmentType.Rigid
        )
        self.right_camera = world.spawn_actor(
            right_bp, right_tf, attach_to=vehicle, attachment_type=carla.AttachmentType.Rigid
        )
        self.sensors = [self.left_camera, self.right_camera]
        self._fovs = {"left_rgb": self.L_FOV, "right_rgb": self.R_FOV}
        _logger.info("已创建双目摄像头")

    def process(self, display: pygame.Surface, images: Sequence) -> None:
        if not images or len(images) < 2:
            return
        left_image, right_image = images[0], images[1]
        if left_image is None or right_image is None:
            return
        left_surface = carla_image_to_surface(left_image)
        right_surface = carla_image_to_surface(right_image)

        display.blit(left_surface, (0, 0))
        display.blit(right_surface, (WINDOW_WIDTH // 2, 0))
        pygame.draw.line(
            display,
            (255, 255, 255),
            (WINDOW_WIDTH // 2, 0),
            (WINDOW_WIDTH // 2, WINDOW_HEIGHT),
            2,
        )

    @property
    def current_fov(self) -> float:
        return self.L_FOV
