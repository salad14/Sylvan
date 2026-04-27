"""CARLA 核心基础设施。"""

from .actor_registry import ActorRegistry
from .client import CarlaClient
from .sync_mode import CarlaSyncMode

__all__ = ["ActorRegistry", "CarlaClient", "CarlaSyncMode"]
