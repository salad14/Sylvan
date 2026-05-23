"""键位映射。单一事实来源，供 ``input_handler`` 与文档引用。"""

from __future__ import annotations

import pygame

QUIT_KEYS = (pygame.K_ESCAPE,)
WEATHER_KEY = pygame.K_r
KEYBOARD_TOGGLE_KEY = pygame.K_k

LAYER_TOGGLE_KEYS: dict[int, str] = {
    pygame.K_b: "BUILDINGS",
    pygame.K_v: "VEGETATION",
    pygame.K_f: "FENCES",
    pygame.K_p: "POLES",
    pygame.K_m: "WALLS",
}

LAYER_STATUS_KEY = pygame.K_l
HIDE_ALL_ENV_KEY = pygame.K_h
SHOW_ALL_ENV_KEY = pygame.K_j

CAMERA_MODE_KEY = pygame.K_c
RECALIBRATE_YAW_KEY = pygame.K_y
