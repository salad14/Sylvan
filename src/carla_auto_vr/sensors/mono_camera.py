"""单目摄像头（全宽）。参数 1:1 对齐原 _setup_mono_camera。"""

from __future__ import annotations

from typing import Sequence

import carla
import pygame

from ..config.constants import WINDOW_HEIGHT, WINDOW_WIDTH
from ..config.logging_config import get_logger
from .base import SensorRig
from .image_pipeline import carla_image_to_surface

_logger = get_logger()


class MonoCameraRig(SensorRig):
    mode = "mono"

    # 原代码中 FOV 属性初始化为 100.0，_setup_mono_camera 里实际设置 110.0
    FOV = 110.0

    def __init__(self) -> None:
        super().__init__()
        self.main_camera: carla.Actor | None = None

    def attach(self, world: carla.World, vehicle: carla.Actor) -> None:
        _logger.info("正在设置单目摄像头...")
        bp_lib = world.get_blueprint_library()
        bp = bp_lib.find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(WINDOW_WIDTH))
        bp.set_attribute("image_size_y", str(WINDOW_HEIGHT))
        bp.set_attribute("fov", str(self.FOV))
        bp.set_attribute("enable_postprocess_effects", "True")
        bp.set_attribute("lens_circle_falloff", "5.0")
        bp.set_attribute("lens_circle_multiplier", "0.7")
        bp.set_attribute("chromatic_aberration_intensity", "0.3")
        bp.set_attribute("chromatic_aberration_offset", "0")
        bp.set_attribute("fstop", "2.8")
        bp.set_attribute("focal_distance", "500.0")
        bp.set_attribute("blur_amount", "1.0")

        transform = carla.Transform(
            carla.Location(x=0.8, y=0.0, z=1.7),
            carla.Rotation(pitch=-10),
        )
        self.main_camera = world.spawn_actor(
            bp, transform, attach_to=vehicle, attachment_type=carla.AttachmentType.Rigid
        )
        self.sensors = [self.main_camera]
        self._fovs = {"main_rgb": self.FOV}
        _logger.info(f"已创建单目摄像头 (FOV: {self.FOV})")

    def process(self, display: pygame.Surface, images: Sequence) -> None:
        if not images:
            return
        main_image = images[0]
        if main_image is None:
            return
        surface = carla_image_to_surface(main_image)
        display.blit(surface, (0, 0))

    @property
    def current_fov(self) -> float:
        return self.FOV
