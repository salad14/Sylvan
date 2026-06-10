"""HUD/文字渲染。对齐原 sync_vehicle.py 主循环中的 HUD 绘制块。"""

from __future__ import annotations

import math

import pygame

from ..config.constants import WINDOW_WIDTH


def render_hud(
    display: pygame.Surface,
    font: pygame.font.Font,
    *,
    speed_kmh: float,
    yaw: float,
    weather_name: str,
    camera_mode: str,
    fov: float,
    keyboard_control: bool,
    throttle: float = 0.0,
    brake: float = 0.0,
    steer: float = 0.0,
    reverse: bool = False,
    ros_enabled: bool = False,
    ros_data_fresh: bool = False,
    accident_active: bool = False,
) -> None:
    """把状态文本绘制到 display。保持原布局与字体。"""
    lines = [
        f"Speed: {speed_kmh:.1f} km/h",
        f"Yaw: {yaw:.1f} deg",
        f"Weather: {weather_name}",
        f"Camera: {camera_mode} (FOV {fov:.0f})",
        f"Keyboard Control: {'ON' if keyboard_control else 'OFF'}",
    ]
    if keyboard_control:
        lines.append(
            f"  throttle={throttle:.2f} brake={brake:.2f} steer={steer:+.2f}"
            + ("  [R]" if reverse else "")
        )
    if ros_enabled:
        lines.append(f"ROS: {'FRESH' if ros_data_fresh else 'stale/none'}")
    if accident_active:
        lines.append("Accident scenario: ACTIVE")

    y = 10
    for line in lines:
        try:
            surf = font.render(line, True, (255, 255, 255))
            shadow = font.render(line, True, (0, 0, 0))
            display.blit(shadow, (12, y + 1))
            display.blit(surf, (10, y))
            y += 22
        except Exception:  # noqa: BLE001
            continue


def speed_kmh(velocity) -> float:
    return 3.6 * math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
