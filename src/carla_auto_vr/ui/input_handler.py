"""Pygame 事件处理"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pygame

from ..config.logging_config import get_logger
from . import keybindings as kb

_logger = get_logger()


@dataclass
class InputCallbacks:
    """主循环关心的回调集合。全部可选。"""

    on_quit: Optional[Callable[[], None]] = None
    on_weather_next: Optional[Callable[[], Optional[str]]] = None
    on_toggle_keyboard: Optional[Callable[[], bool]] = None
    on_toggle_layer: Optional[Callable[[str], None]] = None
    on_layer_status: Optional[Callable[[], None]] = None
    on_hide_all_env: Optional[Callable[[], None]] = None
    on_show_all_env: Optional[Callable[[], None]] = None
    on_camera_info: Optional[Callable[[], None]] = None
    on_recalibrate_yaw: Optional[Callable[[], None]] = None
    extras: dict[int, Callable[[], None]] = field(default_factory=dict)


class InputHandler:
    """封装 ``pygame.event.get()`` 的分发。"""

    def __init__(self, callbacks: InputCallbacks):
        self.cb = callbacks
        self.quit_requested = False

    def poll(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit_requested = True
                if self.cb.on_quit:
                    self.cb.on_quit()
                continue
            if event.type != pygame.KEYUP:
                continue
            key = event.key
            if key in kb.QUIT_KEYS:
                self.quit_requested = True
                if self.cb.on_quit:
                    self.cb.on_quit()
            elif key == kb.WEATHER_KEY and self.cb.on_weather_next:
                self.cb.on_weather_next()
            elif key == kb.KEYBOARD_TOGGLE_KEY and self.cb.on_toggle_keyboard:
                self.cb.on_toggle_keyboard()
            elif key in kb.LAYER_TOGGLE_KEYS and self.cb.on_toggle_layer:
                self.cb.on_toggle_layer(kb.LAYER_TOGGLE_KEYS[key])
            elif key == kb.LAYER_STATUS_KEY and self.cb.on_layer_status:
                self.cb.on_layer_status()
            elif key == kb.HIDE_ALL_ENV_KEY and self.cb.on_hide_all_env:
                self.cb.on_hide_all_env()
            elif key == kb.SHOW_ALL_ENV_KEY and self.cb.on_show_all_env:
                self.cb.on_show_all_env()
            elif key == kb.CAMERA_MODE_KEY and self.cb.on_camera_info:
                self.cb.on_camera_info()
            elif key == kb.RECALIBRATE_YAW_KEY and self.cb.on_recalibrate_yaw:
                self.cb.on_recalibrate_yaw()
            elif key in self.cb.extras:
                self.cb.extras[key]()
        return self.quit_requested
