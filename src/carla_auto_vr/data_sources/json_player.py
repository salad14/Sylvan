"""从 JSON 文件回放数据。"""

from __future__ import annotations

import json
from typing import Iterator, Optional

from ..config.logging_config import get_logger
from .base import VehicleDataSource

_logger = get_logger()


class JsonFilePlayer(VehicleDataSource):
    """每次 :meth:`poll` 返回下一帧；读尽后返回 ``None``。"""

    name = "json"

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._data: list[dict] = []
        self._iter: Optional[Iterator[dict]] = None
        self._loaded = False

    def load(self) -> bool:
        try:
            _logger.info(f"正在读取JSON文件: {self.file_path}")
            with open(self.file_path, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                _logger.error("JSON 根不是数组，无法回放")
                return False
            self._data = data
            self._iter = iter(self._data)
            self._loaded = True
            _logger.info(f"成功读取JSON数据，包含 {len(self._data)} 个数据点")
            return True
        except FileNotFoundError:
            _logger.error(f"错误: 找不到文件 {self.file_path}")
            return False
        except json.JSONDecodeError:
            _logger.error(f"错误: 文件 {self.file_path} 不是有效的JSON格式")
            return False
        except Exception as e:  # noqa: BLE001
            _logger.error(f"读取JSON文件失败: {e}")
            return False

    def is_ready(self) -> bool:
        return self._loaded

    def poll(self) -> Optional[dict]:
        if not self._loaded or self._iter is None:
            return None
        return next(self._iter, None)

    @property
    def size(self) -> int:
        return len(self._data)
