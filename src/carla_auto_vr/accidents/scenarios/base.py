"""事故场景基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import carla


@dataclass
class ScenarioContext:
    """场景共享上下文。"""

    world: carla.World
    player_vehicle: carla.Actor
    start_time: float
    timeout: float


class BaseScenario(ABC):
    """事故场景协议。"""

    name: str = "base"

    def __init__(self, ctx: ScenarioContext):
        self.ctx = ctx
        self.active = False

    @abstractmethod
    def init(self) -> bool:
        """初始化并激活场景。返回是否成功。"""

    @abstractmethod
    def update(self, current_time: float) -> bool:
        """每帧更新场景。返回 True 表示仍在运行。"""

    def end(self) -> None:
        self.active = False

    @property
    def incident_result(self) -> Optional[str]:
        return None
