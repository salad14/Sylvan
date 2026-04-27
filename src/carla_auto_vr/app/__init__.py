"""应用域：CLI + 装配 + 主循环。"""

from .cli import build_parser, main
from .run_loop import run_loop
from .simulation import Simulation

__all__ = ["Simulation", "build_parser", "main", "run_loop"]
