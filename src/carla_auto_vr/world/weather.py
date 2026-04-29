"""天气预设循环器。"""

from __future__ import annotations

import re
from typing import List, Tuple

import carla

from ..config.logging_config import get_logger

_logger = get_logger()


class WeatherController:
    """循环切换 ``carla.WeatherParameters`` 中的预设。"""

    def __init__(self, world: carla.World):
        self.world = world
        self.presets: List[Tuple[carla.WeatherParameters, str]] = self._find_presets()
        self.index = 0

    @staticmethod
    def _find_presets() -> List[Tuple[carla.WeatherParameters, str]]:
        try:
            names = [x for x in dir(carla.WeatherParameters) if re.match("[A-Z].+", x)]
            return [(getattr(carla.WeatherParameters, n), n) for n in names]
        except Exception as e:  # noqa: BLE001
            _logger.error(f"获取天气预设失败: {e}")
            return [(carla.WeatherParameters.ClearNoon, "ClearNoon")]

    def next(self, reverse: bool = False) -> str:
        try:
            self.index += -1 if reverse else 1
            self.index %= len(self.presets)
            preset, name = self.presets[self.index]
            self.world.set_weather(preset)
            return name
        except Exception as e:  # noqa: BLE001
            _logger.error(f"更改天气失败: {e}")
            return "未知天气"

    @property
    def current_name(self) -> str:
        if not self.presets:
            return "Unknown"
        return self.presets[self.index][1]
