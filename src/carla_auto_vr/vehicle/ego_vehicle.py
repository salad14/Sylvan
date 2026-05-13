"""主车（EGO）生成。"""

from __future__ import annotations

import random

import carla

from ..config.constants import TESLA_MODEL
from ..config.logging_config import get_logger
from ..config.scenarios_config import MOTORWAY_PREFERRED_SPAWN

_logger = get_logger()


def _build_motorway_preferred_transform() -> carla.Transform:
    loc = MOTORWAY_PREFERRED_SPAWN["location"]
    rot = MOTORWAY_PREFERRED_SPAWN["rotation"]
    return carla.Transform(
        carla.Location(x=loc["x"], y=loc["y"], z=loc["z"]),
        carla.Rotation(pitch=rot["pitch"], yaw=rot["yaw"], roll=rot["roll"]),
    )


def spawn_ego_vehicle(
    world: carla.World,
    *,
    is_opendrive_map: bool = False,
    map_argument: str = "",
) -> carla.Actor:
    """按原 ``_setup_vehicle`` 行为生成特斯拉主车。

    - 优先使用 ``vehicle.tesla.model3``；退化为其他 Tesla；最终退化为随机车辆。
    - 在 Motorway.xodr 模式下优先使用首选生成点，剩余点打乱。
    - 最多尝试 20 个生成点；全部失败时抬高 3m 再试一次。
    """
    _logger.info("正在创建车辆...")
    blueprint_library = world.get_blueprint_library()

    tesla_bps = blueprint_library.filter(f"vehicle.tesla.{TESLA_MODEL}")
    if not tesla_bps:
        _logger.warning(f"找不到 vehicle.tesla.{TESLA_MODEL} 蓝图，尝试使用任意Tesla车型")
        tesla_bps = blueprint_library.filter("vehicle.tesla.*")

    if not tesla_bps:
        _logger.warning("找不到任何Tesla车型，使用默认车辆")
        bp = random.choice(blueprint_library.filter("vehicle.*"))
    else:
        bp = tesla_bps[0]
    bp.set_attribute("role_name", "hero")

    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        _logger.error("错误: 地图没有有效的出生点")
        raise RuntimeError("地图没有有效的出生点")

    try:
        if is_opendrive_map and str(map_argument).endswith("Motorway.xodr"):
            preferred = _build_motorway_preferred_transform()
            spawn_points = [preferred] + list(spawn_points)
            if len(spawn_points) > 1:
                tail = spawn_points[1:]
                random.shuffle(tail)
                spawn_points = [spawn_points[0]] + tail
            _logger.info("Motorway.xodr 模式：优先使用自定义出生点 (-150, -60, 0.5)")
        else:
            random.shuffle(spawn_points)
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"设置Motorway自定义出生点失败，将使用默认生成点: {e}")
        random.shuffle(spawn_points)

    vehicle = None
    max_attempts = min(20, len(spawn_points))
    for i in range(max_attempts):
        spawn_point = spawn_points[i]
        _logger.info(
            f"尝试生成点 {i+1}/{max_attempts}: "
            f"x={spawn_point.location.x:.1f}, "
            f"y={spawn_point.location.y:.1f}, "
            f"z={spawn_point.location.z:.1f}"
        )
        try:
            vehicle = world.spawn_actor(bp, spawn_point)
            _logger.info(f"成功在生成点 {i+1} 创建车辆: {bp.id}")
            break
        except RuntimeError as e:
            if "collision" in str(e):
                _logger.warning(f"生成点 {i+1} 发生碰撞，尝试下一个点")
            else:
                _logger.warning(f"在生成点 {i+1} 创建车辆时遇到错误: {e}")

    if vehicle is None:
        _logger.error("尝试了多个生成点，但都失败了。尝试强制生成车辆...")
        spawn_point = random.choice(spawn_points)
        spawn_point.location.z += 3.0
        try:
            vehicle = world.spawn_actor(bp, spawn_point)
            _logger.info("成功在空中生成车辆，等待其落地")
            world.tick()
        except Exception as e:  # noqa: BLE001
            _logger.error(f"强制生成车辆也失败了: {e}")
            raise RuntimeError("无法生成车辆，请尝试重启模拟或更换地图")

    _logger.info(f"已成功创建车辆: {bp.id}")
    return vehicle
