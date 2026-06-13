"""事故模拟管理器。

当前设计为适配层：对外暴露干净的 ``AccidentManager`` 接口，内部将复杂的状态机
逻辑委托给仓库根目录下已经经过验证的 :class:`accident_simulation.AccidentSimulation`
实现。这样做的目的是：

* 按功能域划分（事故域独立）；
* 保持事故触发/恢复/统计的行为稳定；
* 后续可以按场景继续完善 ``scenarios/`` 子目录。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

import carla

from ..config.logging_config import get_logger
from .stats import IncidentStats

_logger = get_logger()


def _ensure_legacy_on_path() -> None:
    """把仓库根目录加入 ``sys.path``，以便导入 ``accident_simulation``。"""
    here = os.path.dirname(os.path.abspath(__file__))
    # 当前文件位于 src/carla_auto_vr/accidents/manager.py，向上四层到仓库根
    candidate_roots = [
        os.path.abspath(os.path.join(here, "..", "..", "..")),
        os.getcwd(),
    ]
    for root in candidate_roots:
        if root and root not in sys.path and os.path.isdir(root):
            sys.path.insert(0, root)


class AccidentManager:
    """事故模拟高阶管理器。"""

    def __init__(self, world: carla.World, player_vehicle: carla.Actor):
        self.world = world
        self.player_vehicle = player_vehicle
        self.stats = IncidentStats()
        self._legacy = None
        self._init_legacy()

    # ----- 内部 -----
    def _init_legacy(self) -> None:
        _ensure_legacy_on_path()
        try:
            from accident_simulation import AccidentSimulation  # type: ignore
        except Exception as e:  # noqa: BLE001
            _logger.error(f"加载旧事故模拟实现失败: {e}")
            self._legacy = None
            return
        try:
            self._legacy = AccidentSimulation(self.world, self.player_vehicle)
            # 共享统计对象，避免两份
            try:
                self._legacy.incident_results = self.stats.counters
            except Exception:  # noqa: BLE001
                pass
            _logger.info("AccidentManager 初始化成功")
        except Exception as e:  # noqa: BLE001
            _logger.error(f"构造 AccidentSimulation 失败: {e}")
            self._legacy = None

    # ----- 对外 -----
    def is_available(self) -> bool:
        return self._legacy is not None

    def update(self, current_time: float | None = None) -> bool:
        """在主循环中按原频率调用。

        兼容 ``AccidentSimulation.update(current_time)`` 的签名；
        默认使用 ``time.time()``，也允许调用方传入同步时钟以保持确定性。
        """
        if self._legacy is None:
            return False
        if current_time is None:
            current_time = time.time()
        try:
            result = self._legacy.update(current_time)
            # update 很多分支返回 None；统一为 bool
            return bool(result) if result is not None else True
        except Exception as e:  # noqa: BLE001
            _logger.warning(f"事故模拟 update 出错: {e}")
            return False

    @property
    def is_accident_active(self) -> bool:
        if self._legacy is None:
            return False
        return bool(getattr(self._legacy, "accident_is_active", False))

    def cleanup(self) -> None:
        if self._legacy is None:
            return
        try:
            self._legacy.cleanup()
        except Exception as e:  # noqa: BLE001
            _logger.warning(f"事故模拟 cleanup 出错: {e}")

    def summary(self) -> dict[str, int]:
        return self.stats.snapshot()

    # 暴露底层实例，便于高级使用场景
    @property
    def legacy(self):  # noqa: ANN201
        return self._legacy
