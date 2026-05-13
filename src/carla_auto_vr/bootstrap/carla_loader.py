
from __future__ import annotations

import glob
import os
import sys
from types import ModuleType
from typing import Iterable

from ..config.logging_config import get_logger

_DEFAULT_CANDIDATES: tuple[str, ...] = (
    "../PythonAPI/carla/dist/carla-0.9.15-py3.10-linux-x86_64.egg",
    "../../PythonAPI/carla/dist/carla-0.9.15-py3.10-linux-x86_64.egg",
    "/opt/carla-simulator/PythonAPI/carla/dist/carla-0.9.15-py3.10-linux-x86_64.egg",
    "/opt/carla-simulator/PythonAPI/carla/dist/carla-*-py3.10-linux-x86_64.egg",
    "~/carla/PythonAPI/carla/dist/carla-0.9.15-py3.10-linux-x86_64.egg",
    "./PythonAPI/carla/dist/carla-0.9.15-py3.10-linux-x86_64.egg",
)


def _expand(path: str, base_dir: str | None = None) -> str:
    """展开 ~ 并把相对路径解析为相对于 base_dir（默认当前脚本所在目录）。"""
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    base = base_dir or (
        os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
    )
    return os.path.normpath(os.path.join(base, expanded))


def _first_existing(patterns: Iterable[str], base_dir: str | None) -> str | None:
    for p in patterns:
        full = _expand(p, base_dir)
        if "*" in full:
            hits = glob.glob(full)
            if hits and os.path.exists(hits[0]):
                return hits[0]
        elif os.path.exists(full):
            return full
    return None


def ensure_carla_on_path(base_dir: str | None = None) -> bool:
    """把 CARLA egg 加入 sys.path。返回是否找到。"""
    logger = get_logger()

    primary = "../PythonAPI/carla/dist/carla-0.9.15-py3.10-linux-x86_64.egg"
    primary_abs = _expand(primary, base_dir)
    if os.path.exists(primary_abs):
        if primary_abs not in sys.path:
            sys.path.append(primary_abs)
        logger.info(f"已添加CARLA Python API路径: {primary_abs}")
        return True

    logger.error(f"找不到CARLA Python API文件: {primary_abs}")
    hit = _first_existing(_DEFAULT_CANDIDATES, base_dir)
    if hit:
        if hit not in sys.path:
            sys.path.append(hit)
        logger.info(f"已添加CARLA Python API路径: {hit}")
        return True

    logger.warning("找不到CARLA Python API文件，将尝试直接导入")
    return False


def import_carla(base_dir: str | None = None) -> ModuleType:
    """保证 carla 可导入并返回模块。import 失败时抛出。"""
    ensure_carla_on_path(base_dir)
    logger = get_logger()
    try:
        import carla  # noqa: F401

        logger.info("已成功导入CARLA模块，版本：%s", getattr(carla, "__version__", "未知"))
        return carla
    except ImportError as e:
        logger.error(f"无法导入CARLA模块: {e}")
        logger.error("请确保CARLA已正确安装并使用兼容的Python版本")
        raise
