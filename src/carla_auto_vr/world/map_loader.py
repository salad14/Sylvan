"""内置 Town* 地图切换。"""

from __future__ import annotations

import carla

from ..config.logging_config import get_logger

_logger = get_logger()


def switch_builtin_map(client: carla.Client, current_world: carla.World, target_map: str) -> carla.World:
    """切换到指定内置地图；找不到时保留当前 world。"""
    current_name = current_world.get_map().name
    if current_name == target_map or target_map in current_name:
        _logger.info(f"已经在目标地图: {current_name}")
        return current_world

    _logger.info(f"正在切换到地图: {target_map}")
    try:
        available = client.get_available_maps()
        _logger.info(f"可用地图: {[m.split('/')[-1] for m in available]}")
        target_path = next((m for m in available if target_map in m), None)
        if target_path:
            _logger.info(f"找到目标地图: {target_path}")
            world = client.load_world(target_path)
            _logger.info(f"已成功切换到地图: {world.get_map().name}")
            return world
        _logger.warning(f"未找到地图 {target_map}，使用当前地图: {current_name}")
        return current_world
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"切换地图失败: {e}，使用当前地图: {current_name}")
        return current_world
