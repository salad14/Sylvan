#!/usr/bin/env python3
"""独立启动 ROS 桥接节点"""

from __future__ import annotations

import os
import sys


def _ensure_src_on_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, os.pardir))
    src = os.path.join(root, "src")
    if os.path.isdir(src) and src not in sys.path:
        sys.path.insert(0, src)


if __name__ == "__main__":
    _ensure_src_on_path()
    from carla_auto_vr.bootstrap.ros_environment import setup_ros_environment
    from carla_auto_vr.data_sources.ros_bridge import main

    setup_ros_environment()
    main()
