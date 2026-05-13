"""统一的 CARLA actor 生命周期管理。"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from ..config.logging_config import get_logger

_logger = get_logger()


class ActorRegistry:
    """按可选标签登记 actor，并统一销毁。

    替代原 sync_vehicle.py 中散乱的 ``self.actor_list`` / ``self.camera`` /
    ``self.left_camera`` / ``self.vehicle`` 等资源。
    """

    def __init__(self) -> None:
        self._actors: list = []
        self._by_tag: dict[str, list] = defaultdict(list)

    def add(self, actor, tag: Optional[str] = None):
        if actor is None:
            return actor
        self._actors.append(actor)
        if tag:
            self._by_tag[tag].append(actor)
        return actor

    def extend(self, actors: Iterable, tag: Optional[str] = None) -> None:
        for a in actors:
            self.add(a, tag=tag)

    def get(self, tag: str) -> list:
        return list(self._by_tag.get(tag, ()))

    def remove(self, actor) -> None:
        try:
            self._actors.remove(actor)
        except ValueError:
            pass
        for bucket in self._by_tag.values():
            if actor in bucket:
                bucket.remove(actor)

    def destroy_tag(self, tag: str) -> int:
        """销毁某个 tag 下所有 actor，返回实际销毁数量。"""
        destroyed = 0
        for actor in list(self._by_tag.get(tag, ())):
            if actor is None:
                continue
            try:
                if getattr(actor, "is_alive", False):
                    actor.destroy()
                    destroyed += 1
            except Exception as e:  # noqa: BLE001
                _logger.warning(f"销毁 actor 失败 ({tag}): {e}")
            finally:
                self.remove(actor)
        return destroyed

    def destroy_all(self) -> int:
        destroyed = 0
        for actor in list(self._actors):
            if actor is None:
                continue
            try:
                if getattr(actor, "is_alive", False):
                    actor.destroy()
                    destroyed += 1
            except Exception as e:  # noqa: BLE001
                _logger.warning(f"销毁 actor 失败: {e}")
        self._actors.clear()
        self._by_tag.clear()
        return destroyed

    def __len__(self) -> int:
        return len(self._actors)
