"""Pygame 显示初始化。"""

from __future__ import annotations

import pygame

from ..config.constants import FPS, WINDOW_HEIGHT, WINDOW_WIDTH
from ..config.logging_config import get_logger

_logger = get_logger()


class DisplayContext:
    """持有 pygame ``display`` + ``clock`` + ``font``。"""

    def __init__(self, caption: str = "CARLA Sync Demo"):
        pygame.init()
        self.display = pygame.display.set_mode(
            (WINDOW_WIDTH, WINDOW_HEIGHT), pygame.HWSURFACE | pygame.DOUBLEBUF
        )
        pygame.display.set_caption(caption)
        self.clock = pygame.time.Clock()
        try:
            self.font = pygame.font.Font(pygame.font.get_default_font(), 20)
        except Exception:  # noqa: BLE001
            self.font = pygame.font.SysFont(None, 20)
        _logger.info(f"Pygame 显示窗口已创建: {WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    @property
    def fps(self) -> int:
        return FPS

    def tick(self) -> None:
        self.clock.tick()

    def flip(self) -> None:
        pygame.display.flip()

    def quit(self) -> None:
        try:
            pygame.quit()
        except Exception:  # noqa: BLE001
            pass
