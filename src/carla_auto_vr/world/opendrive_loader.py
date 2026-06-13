"""OpenDRIVE (.xodr) 地图加载。"""

from __future__ import annotations

import os
import sys
import time
import traceback

import carla

from ..config.logging_config import get_logger
from ..config.scenarios_config import OPENDRIVE_GEN_PARAMS, OPENDRIVE_SEARCH_PATHS

_logger = get_logger()


def resolve_xodr_path(map_file: str, script_dir: str | None = None) -> str:
    """返回有效的 .xodr 绝对路径；找不到则抛出 FileNotFoundError。"""
    if os.path.isabs(map_file):
        if not os.path.exists(map_file):
            _logger.error(f"OpenDRIVE文件不存在: {map_file}")
            raise FileNotFoundError(f"OpenDRIVE文件不存在: {map_file}")
        return map_file

    if script_dir is None:
        script_dir = (
            os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
        )

    candidates = []
    for base in OPENDRIVE_SEARCH_PATHS:
        expanded = os.path.expanduser(base)
        if not os.path.isabs(expanded):
            expanded = os.path.normpath(os.path.join(script_dir, expanded))
        candidates.append(expanded)

    for base in candidates:
        test_path = os.path.join(base, map_file)
        _logger.debug(f"尝试路径: {test_path}")
        if os.path.exists(test_path):
            _logger.info(f"找到OpenDRIVE文件: {test_path}")
            return test_path

    _logger.error(f"找不到OpenDRIVE文件: {map_file}")
    _logger.error(f"已尝试的路径: {candidates}")
    raise FileNotFoundError(f"找不到OpenDRIVE文件: {map_file}")


def load_opendrive_world(
    client: carla.Client, map_file: str, script_dir: str | None = None
) -> carla.World:
    """根据 .xodr 文件生成一个 OpenDRIVE world。"""
    try:
        _logger.info(f"正在加载OpenDRIVE地图: {map_file}")
        xodr_path = resolve_xodr_path(map_file, script_dir=script_dir)

        _logger.info(f"正在读取OpenDRIVE文件: {xodr_path}")
        with open(xodr_path, "r", encoding="utf-8") as f:
            opendrive_content = f.read()
        _logger.info(f"OpenDRIVE文件大小: {len(opendrive_content)} 字节")

        _logger.info("正在生成OpenDRIVE地图世界...")
        params = carla.OpendriveGenerationParameters(**OPENDRIVE_GEN_PARAMS)
        world = client.generate_opendrive_world(
            opendrive_content,
            params,
            reset_settings=False,
        )
        _logger.info("OpenDRIVE地图已成功加载")
        _logger.info(f"当前地图名称: {world.get_map().name}")

        time.sleep(2.0)
        world.tick()
        _logger.info("OpenDRIVE地图加载完成")
        return world
    except FileNotFoundError:
        raise
    except Exception as e:  # noqa: BLE001
        _logger.error(f"加载OpenDRIVE地图失败: {e}")
        _logger.error(traceback.format_exc())
        raise


def is_opendrive_target(map_value: str) -> bool:
    """判定 CLI ``--map`` 值是否为 .xodr 文件。"""
    return map_value.endswith(".xodr")
