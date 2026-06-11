"""交通锥布置（原 _spawn_traffic_cones）。"""

from __future__ import annotations

import traceback
from typing import Optional, Sequence, Tuple

import carla

from ..config.logging_config import get_logger
from ..config.scenarios_config import (
    CONSTRUCTION_CONE_BP_ID,
    DEFAULT_CONSTRUCTION_CONE_LOCATIONS,
    DEFAULT_TRAFFIC_CONE_LOCATIONS,
    TRAFFIC_CONE_BP_ID,
)
from ..core.actor_registry import ActorRegistry

_logger = get_logger()

ConeLocation = Tuple[float, float, float, float]


def spawn_traffic_cones(
    world: carla.World,
    registry: ActorRegistry,
    construction_locations: Optional[Sequence[ConeLocation]] = None,
    trafficcone_locations: Optional[Sequence[ConeLocation]] = None,
) -> None:
    """根据给定坐标（或默认列表）布置两种交通锥。"""
    try:
        bp_lib = world.get_blueprint_library()
        if construction_locations is None and trafficcone_locations is None:
            construction_locations = DEFAULT_CONSTRUCTION_CONE_LOCATIONS
            trafficcone_locations = DEFAULT_TRAFFIC_CONE_LOCATIONS

        plan: list[tuple[str, Sequence[ConeLocation]]] = [
            (CONSTRUCTION_CONE_BP_ID, construction_locations or []),
            (TRAFFIC_CONE_BP_ID, trafficcone_locations or []),
        ]

        for cone_id, locations in plan:
            if not locations:
                continue
            try:
                bp = bp_lib.find(cone_id)
            except Exception:  # noqa: BLE001
                _logger.warning(f"未找到交通锥蓝图: {cone_id}")
                continue

            for x, y, z, yaw in locations:
                transform = carla.Transform(
                    carla.Location(x=x, y=y, z=z),
                    carla.Rotation(pitch=0.0, yaw=yaw, roll=0.0),
                )
                try:
                    cone = world.spawn_actor(bp, transform)
                    if cone:
                        try:
                            cone.set_simulate_physics(False)
                        except Exception:  # noqa: BLE001
                            pass
                        registry.add(cone, tag="cone")
                        _logger.info(f"已在({x}, {y}, {z}) 放置交通锥: {bp.id}")
                except Exception as e:  # noqa: BLE001
                    _logger.warning(f"放置交通锥 {bp.id} 失败: {e}")
                    _logger.warning(traceback.format_exc())
                    continue
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"放置交通锥失败: {e}")
        _logger.warning(traceback.format_exc())
