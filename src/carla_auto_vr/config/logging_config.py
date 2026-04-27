"""统一日志配置。与原 sync_vehicle.py 顶层一致：同时写文件与终端。"""

from __future__ import annotations

import logging
import os
import sys

_LOGGER_NAME = "carla_sync"
_DEFAULT_LOG_FILENAME = "carla_sync.log"


def setup_logger(
    log_dir: str | None = None,
    level: int = logging.INFO,
    log_filename: str = _DEFAULT_LOG_FILENAME,
) -> logging.Logger:
    """配置并返回项目主 logger。幂等：重复调用不会重复添加 handler。"""
    if log_dir is None:
        # 与原脚本一致：放在调用文件所在目录
        log_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()

    log_file = os.path.join(log_dir, log_filename)
    logger = logging.getLogger(_LOGGER_NAME)

    # 幂等：若已经配置过则跳过
    if getattr(logger, "_carla_sync_configured", False):
        logger.setLevel(level)
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # 文件系统不可写也不致命
        pass

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger._carla_sync_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger() -> logging.Logger:
    """获取已配置的 logger；若未配置则使用默认设置初始化。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if not getattr(logger, "_carla_sync_configured", False):
        return setup_logger()
    return logger
