#!/usr/bin/env python3

from __future__ import annotations

import os
import sys


def _ensure_src_on_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, os.pardir))
    src = os.path.join(root, "src")
    if os.path.isdir(src) and src not in sys.path:
        sys.path.insert(0, src)
    if root not in sys.path:
        sys.path.insert(0, root)  # 便于 accidents.manager 加载旧的 AccidentSimulation


if __name__ == "__main__":
    _ensure_src_on_path()
    from carla_auto_vr.app.cli import main

    sys.exit(main())
