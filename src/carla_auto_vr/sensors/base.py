"""传感器抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

import carla
import pygame


class SensorRig(ABC):
    """一组传感器 + 渲染逻辑的抽象。"""

    mode: str = "base"

    def __init__(self) -> None:
        self.sensors: list[carla.Actor] = []
        self._fovs: dict[str, float] = {}

    @abstractmethod
    def attach(self, world: carla.World, vehicle: carla.Actor) -> None:
        """创建传感器并绑定到车辆。"""

    @abstractmethod
    def process(self, display: pygame.Surface, images: Sequence) -> None:
        """把 :func:`CarlaSyncMode.tick` 返回的图像绘制到 ``display``。"""

    @property
    def current_fov(self) -> float:
        if not self._fovs:
            return 90.0
        return next(iter(self._fovs.values()))

    def destroy(self) -> None:
        for s in self.sensors:
            try:
                if getattr(s, "is_alive", False):
                    s.destroy()
            except Exception:  # noqa: BLE001
                pass
        self.sensors.clear()
