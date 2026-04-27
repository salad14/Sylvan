"""运行期可配置项。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimulationSettings:
    """封装 CLI 参数，避免在整个工程里传递 argparse.Namespace。"""

    host: str = "127.0.0.1"
    port: int = 2000
    json: str = ""
    ros: bool = True
    debug: bool = False
    map: str = "Town04"

    no_buildings: bool = False
    no_vegetation: bool = False
    no_fences: bool = False
    clean_environment: bool = False
    layered_rendering: bool = True

    mono_camera: bool = False
    stereo_camera: bool = False

    # True: 默认根据地图自动决定（黑名单外才启用）
    # False: 强制关闭事故模拟（也会跳过 AccidentSimulation 内部的行人生成）
    # None: 命令行未显式指定，走自动策略
    accidents: bool | None = None

    @property
    def camera_mode(self) -> str:
        """'stereo' 或 'mono'；沿用原 sync_vehicle.py 的默认优先级。"""
        return "mono" if self.mono_camera else "stereo"

    @classmethod
    def from_namespace(cls, ns) -> "SimulationSettings":
        """从 argparse.Namespace 构造。缺省字段保持默认。"""
        return cls(
            host=getattr(ns, "host", "127.0.0.1"),
            port=getattr(ns, "port", 2000),
            json=getattr(ns, "json", "") or "",
            ros=getattr(ns, "ros", True),
            debug=getattr(ns, "debug", False),
            map=getattr(ns, "map", "Town04"),
            no_buildings=getattr(ns, "no_buildings", False),
            no_vegetation=getattr(ns, "no_vegetation", False),
            no_fences=getattr(ns, "no_fences", False),
            clean_environment=getattr(ns, "clean_environment", False),
            layered_rendering=getattr(ns, "layered_rendering", True),
            mono_camera=getattr(ns, "mono_camera", False),
            stereo_camera=getattr(ns, "stereo_camera", False),
            accidents=getattr(ns, "accidents", None),
        )
