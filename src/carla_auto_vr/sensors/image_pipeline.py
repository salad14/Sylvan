"""摄像头原始图像到 pygame.Surface 的公共处理。"""

from __future__ import annotations

import numpy as np
import pygame


def carla_image_to_surface(image) -> pygame.Surface:
    """BGRA raw_data → pygame Surface (RGB)。"""
    array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
    array = np.reshape(array, (image.height, image.width, 4))
    array = array[:, :, :3]
    array = array[:, :, ::-1]  # BGR -> RGB
    return pygame.surfarray.make_surface(array.swapaxes(0, 1))
