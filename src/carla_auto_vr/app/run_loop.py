
from __future__ import annotations

import time
import traceback

import pygame

from ..config.constants import FPS
from ..config.logging_config import get_logger
from ..core.sync_mode import CarlaSyncMode
from ..ui import DisplayContext, InputCallbacks, InputHandler, render_hud, speed_kmh
from .simulation import Simulation

_logger = get_logger()


def run_loop(sim: Simulation) -> None:
    assert sim.world is not None and sim.vehicle is not None

    display_ctx = DisplayContext(caption="CARLA Sync Demo (Refactored)")
    callbacks = _build_callbacks(sim)
    input_handler = InputHandler(callbacks)

    assert sim.carla_client is not None
    sim.carla_client.ensure_sync_and_traffic_manager(FPS)

    frame_counter = 0
    last_time = time.time()

    with CarlaSyncMode(sim.world, *sim.camera_rig.sensors, fps=FPS) as sync_mode:
        while True:
            if input_handler.poll():
                _logger.info("用户退出")
                break

            # 键盘控制只在没有其它输入时生效
            if sim.keyboard.enabled:
                sim.keyboard.apply(sim.vehicle)

            display_ctx.tick()

            try:
                data = sync_mode.tick(timeout=2.0)
                snapshot = data[0]
                camera_images = data[1:]

                frame_counter += 1
                if frame_counter >= 100:
                    now = time.time()
                    elapsed = now - last_time
                    fps = frame_counter / elapsed if elapsed > 0 else 0
                    _logger.info(f"真实帧率: {fps:.1f} FPS")
                    frame_counter = 0
                    last_time = now

                sim.camera_rig.process(display_ctx.display, camera_images)

                if not sim.keyboard.enabled:
                    if sim.json_player is not None:
                        if not sim.apply_next_json_frame():
                            _logger.info("JSON 文件数据已消费完毕，保持当前状态")
                    elif sim.ros_bridge is not None:
                        sim.apply_latest_ros_data()

                if sim.accident_manager is not None:
                    try:
                        elapsed = snapshot.timestamp.elapsed_seconds
                    except Exception:  # noqa: BLE001
                        elapsed = None
                    sim.accident_manager.update(elapsed)

                _draw_hud(sim, display_ctx)
                display_ctx.flip()
            except Exception as e:  # noqa: BLE001
                _logger.error(f"主循环执行出错: {e}")
                _logger.error(traceback.format_exc())
                break


def _build_callbacks(sim: Simulation) -> InputCallbacks:
    cb = InputCallbacks()

    def on_weather():
        if sim.weather_controller:
            name = sim.weather_controller.next()
            _logger.info(f"天气已更改为: {name}")
            return name
        return None

    def on_toggle_keyboard():
        enabled = sim.keyboard.toggle()
        _logger.info(f"键盘控制模式 {'已启用' if enabled else '已禁用'}")
        if enabled:
            _logger.info("使用WASD控制车辆，空格键切换倒车模式")
        return enabled

    def on_toggle_layer(layer_name: str):
        if sim.layered_renderer:
            sim.layered_renderer.toggle_layer(layer_name)

    def on_layer_status():
        if sim.layered_renderer:
            status = sim.layered_renderer.get_layer_status()
            _logger.info("分层渲染状态:")
            for layer, enabled in status.items():
                _logger.info(f"  {layer}: {'开启' if enabled else '关闭'}")

    def on_hide_all():
        if sim.layered_renderer:
            for name in ("BUILDINGS", "VEGETATION", "FENCES", "POLES", "WALLS"):
                sim.layered_renderer.set_layer(name, False)
            _logger.info("已隐藏所有环境对象")

    def on_show_all():
        if sim.layered_renderer:
            for name in ("BUILDINGS", "VEGETATION", "FENCES", "POLES", "WALLS"):
                sim.layered_renderer.set_layer(name, True)
            _logger.info("已显示所有环境对象")

    def on_camera_info():
        _logger.info("摄像头模式切换暂不支持实时切换，请使用命令行参数")
        _logger.info(f"当前模式: {sim.camera_rig.mode}")

    def on_recalibrate_yaw():
        sim.yaw_calibrator.reset()
        _logger.info("ROS yaw偏移已重置，将在下次接收数据时重新校准")
        _logger.info("请确保车辆朝向正确后再接收ROS数据")

    cb.on_weather_next = on_weather
    cb.on_toggle_keyboard = on_toggle_keyboard
    cb.on_toggle_layer = on_toggle_layer
    cb.on_layer_status = on_layer_status
    cb.on_hide_all_env = on_hide_all
    cb.on_show_all_env = on_show_all
    cb.on_camera_info = on_camera_info
    cb.on_recalibrate_yaw = on_recalibrate_yaw
    return cb


def _draw_hud(sim: Simulation, display_ctx: DisplayContext) -> None:
    vehicle = sim.vehicle
    if vehicle is None:
        return
    try:
        velocity = vehicle.get_velocity()
        transform = vehicle.get_transform()
    except Exception:  # noqa: BLE001
        return

    weather_name = (
        sim.weather_controller.current_name if sim.weather_controller else "Unknown"
    )
    render_hud(
        display_ctx.display,
        display_ctx.font,
        speed_kmh=speed_kmh(velocity),
        yaw=transform.rotation.yaw,
        weather_name=weather_name,
        camera_mode=sim.camera_rig.mode,
        fov=sim.camera_rig.current_fov,
        keyboard_control=sim.keyboard.enabled,
        throttle=sim.keyboard.control.throttle,
        brake=sim.keyboard.control.brake,
        steer=sim.keyboard.control.steer,
        reverse=sim.keyboard.control.reverse,
        ros_enabled=sim.ros_bridge is not None,
        ros_data_fresh=(
            sim.ros_bridge.is_data_fresh() if sim.ros_bridge else False
        ),
        accident_active=(
            sim.accident_manager.is_accident_active if sim.accident_manager else False
        ),
    )
