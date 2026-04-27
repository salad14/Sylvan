"""交通域：静态/动态车辆与交通锥。"""

from .cones import spawn_traffic_cones
from .dynamic import setup_dynamic_traffic
from .static_vehicles import setup_static_vehicles

__all__ = ["setup_dynamic_traffic", "setup_static_vehicles", "spawn_traffic_cones"]
