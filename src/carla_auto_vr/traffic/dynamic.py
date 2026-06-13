"""动态 AI 车辆与行人。"""

from __future__ import annotations

import random
import time
import traceback

import carla

from ..config.constants import TRAFFIC_MANAGER_PORT
from ..config.logging_config import get_logger
from ..config.scenarios_config import (
    DYNAMIC_VEHICLE_BP_BLACKLIST_PREFIXES,
    DYNAMIC_VEHICLE_MAX_COUNT,
    DYNAMIC_WALKER_MAX_COUNT,
    TM_GLOBAL_DISTANCE_TO_LEAD,
    TM_IGNORE_LIGHTS_PCT_WHEN_BAD,
    TM_IGNORE_LIGHTS_RATIO,
    TM_LANE_CHANGE_LEFT_PCT,
    TM_LANE_CHANGE_RIGHT_PCT,
    TM_SPEED_DIFF_RANGE,
)
from ..core.actor_registry import ActorRegistry

_logger = get_logger()


def setup_dynamic_traffic(
    client: carla.Client,
    world: carla.World,
    registry: ActorRegistry,
) -> carla.TrafficManager | None:
    """生成 AI 车辆与行人，并配置交通管理器。返回 traffic manager（失败时 None）。"""
    try:
        _logger.info("正在设置交通流量...")
        tm = client.get_trafficmanager(TRAFFIC_MANAGER_PORT)
        tm.set_synchronous_mode(True)
        tm.set_global_distance_to_leading_vehicle(TM_GLOBAL_DISTANCE_TO_LEAD)
        tm.set_hybrid_physics_mode(False)
        tm.set_random_device_seed(int(time.time()))

        bp_lib = world.get_blueprint_library()
        vehicle_bps = [
            bp
            for bp in bp_lib.filter("vehicle.*")
            if not bp.id.startswith(DYNAMIC_VEHICLE_BP_BLACKLIST_PREFIXES)
        ]
        spawn_points = world.get_map().get_spawn_points()

        num_vehicles = min(DYNAMIC_VEHICLE_MAX_COUNT, len(spawn_points))
        _logger.info(f"尝试生成 {num_vehicles} 辆AI车辆...")
        random.shuffle(spawn_points)

        ai_vehicles: list[carla.Actor] = []
        vehicles_created = 0
        for i in range(num_vehicles):
            bp = random.choice(vehicle_bps)
            if bp.has_attribute("role_name"):
                bp.set_attribute("role_name", "autopilot")
            if bp.has_attribute("physics"):
                bp.set_attribute("physics", "true")
            try:
                vehicle = world.spawn_actor(bp, spawn_points[i])
                registry.add(vehicle, tag="ai_vehicle")
                ai_vehicles.append(vehicle)
                vehicles_created += 1
            except Exception as e:  # noqa: BLE001
                _logger.debug(f"生成车辆失败: {e}")

        _logger.info(f"已创建 {vehicles_created} 辆AI控制的车辆")

        for vehicle in ai_vehicles:
            vehicle.set_target_velocity(carla.Vector3D(x=0.1, y=0.1, z=0))
        world.tick()
        _logger.info("强制世界更新完成，确保所有车辆物理系统初始化")

        for vehicle in ai_vehicles:
            try:
                vehicle.set_autopilot(True, tm.get_port())
                tm.vehicle_percentage_speed_difference(
                    vehicle, random.uniform(*TM_SPEED_DIFF_RANGE)
                )
                tm.auto_lane_change(vehicle, True)
                tm.random_left_lanechange_percentage(vehicle, TM_LANE_CHANGE_LEFT_PCT)
                tm.random_right_lanechange_percentage(vehicle, TM_LANE_CHANGE_RIGHT_PCT)
                if random.random() > TM_IGNORE_LIGHTS_RATIO:
                    tm.ignore_lights_percentage(vehicle, TM_IGNORE_LIGHTS_PCT_WHEN_BAD)
                else:
                    tm.ignore_lights_percentage(vehicle, 0)
                tm.force_lane_change(vehicle, True)
            except Exception as e:  # noqa: BLE001
                _logger.debug(f"设置车辆AI失败: {e}")

        world.tick()
        _logger.info("交通管理器设置完成并已强制更新")

        current_map_name = world.get_map().name
        if "Town04" in current_map_name:
            _logger.info("检测到高速公路地图，跳过行人生成以避免段错误")
        else:
            _setup_walkers(world, registry)

        _logger.info(f"总共创建了 {len(registry)} 个AI控制的角色（含既有 actor）")
        tm.set_synchronous_mode(True)
        world.tick()
        _logger.info("交通流配置完成")
        return tm
    except Exception as e:  # noqa: BLE001
        _logger.error(f"设置交通失败: {e}")
        _logger.error(traceback.format_exc())
        _logger.error("继续执行，但可能没有交通流量")
        return None


def _setup_walkers(world: carla.World, registry: ActorRegistry) -> int:
    try:
        bp_lib = world.get_blueprint_library()
        walker_bps = bp_lib.filter("walker.pedestrian.*")
        walker_controller_bp = bp_lib.find("controller.ai.walker")

        spawn_points: list[carla.Transform] = []
        for _ in range(DYNAMIC_WALKER_MAX_COUNT):
            try:
                sp = carla.Transform()
                sp.location = world.get_random_location_from_navigation()
                if sp.location is not None:
                    spawn_points.append(sp)
            except Exception as e:  # noqa: BLE001
                _logger.debug(f"获取行人生成点失败: {e}")
                continue

        controllers: list[carla.Actor] = []
        walkers_created = 0
        for i in range(min(DYNAMIC_WALKER_MAX_COUNT, len(spawn_points))):
            bp = random.choice(walker_bps)
            if bp.has_attribute("is_invincible"):
                bp.set_attribute("is_invincible", "false")
            try:
                walker = world.spawn_actor(bp, spawn_points[i])
                controller = world.spawn_actor(
                    walker_controller_bp, carla.Transform(), walker
                )
                registry.add(walker, tag="walker")
                registry.add(controller, tag="walker_controller")
                controllers.append(controller)
                walkers_created += 1
            except Exception as e:  # noqa: BLE001
                _logger.debug(f"生成行人失败: {e}")

        _logger.info(f"已创建 {walkers_created} 个AI控制的行人")

        for controller in controllers:
            try:
                controller.start()
                nav = world.get_random_location_from_navigation()
                if nav:
                    controller.go_to_location(nav)
                controller.set_max_speed(float(random.randrange(30, 60) / 10.0))
            except Exception as e:  # noqa: BLE001
                _logger.debug(f"设置行人控制器失败: {e}")
        return walkers_created
    except Exception as e:  # noqa: BLE001
        _logger.warning(f"行人生成完全失败: {e}")
        return 0
