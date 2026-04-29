"""命令行入口。完全兼容原 ``sync_vehicle.py`` 的参数。"""

from __future__ import annotations

import argparse
import sys
import traceback

from ..config.logging_config import setup_logger
from ..config.settings import SimulationSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CARLA 车辆同步模拟（重构版）")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA服务器主机")
    parser.add_argument("--port", default=2000, type=int, help="CARLA服务器端口")
    parser.add_argument(
        "--json", default="", help="JSON 数据文件路径；提供后将忽略 ROS"
    )
    parser.add_argument(
        "--ros",
        dest="ros",
        action='store_true',
        default=True,
        help="启用/禁用 ROS 数据源（默认启用）",
    )
    parser.add_argument(
        "--debug", action="store_true", help="开启 DEBUG 日志"
    )
    parser.add_argument(
        "--map",
        default="Town04",
        help="目标地图名或 .xodr 文件 (OpenDRIVE)",
    )
    parser.add_argument(
        "--no-buildings", action="store_true", help="移除建筑物"
    )
    parser.add_argument(
        "--no-vegetation", action="store_true", help="移除植被"
    )
    parser.add_argument("--no-fences", action="store_true", help="移除围栏")
    parser.add_argument(
        "--clean-environment",
        action="store_true",
        help="移除建筑/植被/围栏/杆/墙，创造干净场景",
    )
    parser.add_argument(
        "--layered-rendering",
        dest="layered_rendering",
        action='store_true',
        default=True,
        help="启用/禁用分层渲染（默认启用）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--mono-camera", action="store_true", help="使用单目摄像头"
    )
    group.add_argument(
        "--stereo-camera", action="store_true", help="使用双目摄像头（默认）"
    )
    parser.add_argument(
        "--accidents",
        dest="accidents",
        action='store_true',
        default=None,
        help=(
            "开启/关闭事故模拟。未指定时按地图自动决定："
            "Town04/Town06/.xodr 等无行人 navmesh 的地图默认关闭，其余默认开启。"
            "使用 --accidents 可强制开启（风险自负）；--no-accidents 强制关闭。"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import logging

    ns = build_parser().parse_args(argv)
    level = logging.DEBUG if ns.debug else logging.INFO
    logger = setup_logger(level=level)
    logger.info("=== CARLA 自动驾驶仿真（重构版）启动 ===")

    settings = SimulationSettings.from_namespace(ns)
    try:
        # 延迟导入：日志先行
        from .simulation import Simulation
        from .run_loop import run_loop

        sim = Simulation(settings)
        sim.connect()
        sim.setup_world_and_vehicle()
        sim.setup_sensors()
        sim.setup_traffic()
        sim.setup_data_sources()
        sim.setup_accidents()
        run_loop(sim)
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:  # noqa: BLE001
        logger.error(f"运行时错误: {e}")
        logger.error(traceback.format_exc())
        return 1
    finally:
        try:
            sim.cleanup()  # type: ignore[possibly-undefined]
        except Exception as e:  # noqa: BLE001
            logger.warning(f"cleanup 失败: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
