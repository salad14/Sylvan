"""数据源协议。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class VehicleDataSource(ABC):
    """为主车提供状态更新的抽象源。"""

    name: str = "base"

    @abstractmethod
    def is_ready(self) -> bool:
        """是否已经有可应用的数据。"""

    @abstractmethod
    def poll(self) -> Optional[dict]:
        """取得下一条 JSON 状态（可能返回 None 表示当前没有新数据）。"""

    def shutdown(self) -> None:
        """可选：释放资源。"""
