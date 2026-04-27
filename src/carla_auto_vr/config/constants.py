"""全局常量：与 sync_vehicle.py 中顶层常量完全对齐。"""

from __future__ import annotations

TESLA_MODEL = "model3"

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 600
FPS = 60

CONTROL_THROTTLE_INCREMENT = 0.1
CONTROL_BRAKE_INCREMENT = 0.2
CONTROL_STEERING_INCREMENT = 0.1
CONTROL_STEERING_MAX = 0.7

RENDER_LAYERS: dict[str, bool] = {
    "ROADS": True,
    "VEHICLES": True,
    "PEDESTRIANS": True,
    "BUILDINGS": False,
    "VEGETATION": False,
    "FENCES": False,
    "POLES": False,
    "WALLS": False,
    "TERRAIN": True,
    "SKY": True,
    "TRAFFIC_SIGNS": True,
}

SEMANTIC_TAGS: dict[str, int] = {
    "UNLABELED": 0,
    "BUILDING": 1,
    "FENCE": 2,
    "OTHER": 3,
    "PEDESTRIAN": 4,
    "POLE": 5,
    "ROADLINE": 6,
    "ROAD": 7,
    "SIDEWALK": 8,
    "VEGETATION": 9,
    "VEHICLES": 10,
    "WALL": 11,
    "TRAFFIC_SIGN": 12,
    "SKY": 13,
    "GROUND": 14,
    "BRIDGE": 15,
    "RAILTRACK": 16,
    "GUARDRAIL": 17,
    "TRAFFIC_LIGHT": 18,
    "STATIC": 19,
    "DYNAMIC": 20,
    "WATER": 21,
    "TERRAIN": 22,
}

ENV_OBJECT_TYPES: tuple[str, ...] = (
    "BUILDINGS",
    "VEGETATION",
    "FENCES",
    "POLES",
    "WALLS",
)

TRAFFIC_MANAGER_PORT = 8000
