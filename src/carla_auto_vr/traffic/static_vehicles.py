"""OpenDRIVE 模式下的静态车辆布置。"""

from __future__ import annotations

import random
import traceback

import carla

from ..config.logging_config import get_logger
from ..config.scenarios_config import (
    SPECIAL_STATIC_SPAWNS,
    STATIC_VEHICLE_BP_BLACKLIST_PREFIXES,
    STATIC_VEHICLE_POSITIONS,
)
from ..core.actor_registry import ActorRegistry

_logger = get_logger()


def setup_static_vehicles(world: carla.World, registry: ActorRegistry) -> int:
    """在 OpenDRIVE 模式预设坐标上放置静态车辆，返回生成数量。"""
    try:
        _logger.info("正在设置静态车辆（OpenDRIVE地图模式）...")
        bp_lib = world.get_blueprint_library()
        vehicle_bps = [
            bp
            for bp in bp_lib.filter("vehicle.*")
            if not bp.id.startswith(STATIC_VEHICLE_BP_BLACKLIST_PREFIXES)
        ]
        if not vehicle_bps:
            _logger.warning("没有找到可用的车辆蓝图")
            return 0

        created = 0
        for i, (x, y, z, yaw) in enumerate(STATIC_VEHICLE_POSITIONS):
            bp = None
            color_choices: list[str] | None = None
            key = (x, y, z, yaw)
            if key in SPECIAL_STATIC_SPAWNS:
                cfg = SPECIAL_STATIC_SPAWNS[key]
                try:
                    bp = bp_lib.find(cfg["bp_id"])
                    color_choices = cfg.get("preferred_colors")
                except Exception as e:  # noqa: BLE001
                    _logger.warning(
                        f"定制蓝图 {cfg['bp_id']} 获取失败，改用随机: {e}"
                    )
                    bp = None
            if bp is None:
                bp = random.choice(vehicle_bps)
                color_choices = None

            if bp.has_attribute("color"):
                colors = bp.get_attribute("color").recommended_values
                chosen = None
                if color_choices:
                    if colors:
                        for c in color_choices:
                            if c in colors:
                                chosen = c
                                break
                    if not chosen:
                        chosen = color_choices[0]
                if not chosen and colors:
                    chosen = random.choice(colors)
                if chosen:
                    bp.set_attribute("color", chosen)

            transform = carla.Transform(
                carla.Location(x=x, y=y, z=z),
                carla.Rotation(pitch=0.0, yaw=yaw, roll=0.0),
            )
            try:
                vehicle = world.spawn_actor(bp, transform)
                if vehicle:
                    vehicle.set_simulate_physics(False)
                    registry.add(vehicle, tag="static_vehicle")
                    created += 1
                    _logger.info(
                        f"已创建静态车辆 {i+1}: {bp.id} at ({x}, {y}, {z})"
                    )
            except Exception as e:  # noqa: BLE001
                _logger.warning(f"创建静态车辆 {i+1} 失败: {e}")
                continue

        world.tick()
        _logger.info(f"静态车辆设置完成，共创建 {created} 辆静态车辆")
        return created
    except Exception as e:  # noqa: BLE001
        _logger.error(f"设置静态车辆失败: {e}")
        _logger.error(traceback.format_exc())
        return 0
