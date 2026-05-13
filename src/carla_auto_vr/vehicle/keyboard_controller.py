"""键盘 WASD + 空格 的主车控制。"""

from __future__ import annotations

import carla
import pygame

from ..config.constants import (
    CONTROL_BRAKE_INCREMENT,
    CONTROL_STEERING_INCREMENT,
    CONTROL_STEERING_MAX,
    CONTROL_THROTTLE_INCREMENT,
)


class KeyboardController:
    """把键盘状态翻译为 ``carla.VehicleControl``。"""

    def __init__(self) -> None:
        self.enabled = False
        self.control = carla.VehicleControl()

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def apply(self, vehicle: carla.Actor) -> None:
        """若启用键控则读取按键状态并应用到车辆。"""
        if not self.enabled or vehicle is None:
            return
        keys = pygame.key.get_pressed()

        # 自然回落油门
        self.control.throttle = max(0.0, self.control.throttle - CONTROL_THROTTLE_INCREMENT / 2)
        self.control.brake = 0.0

        if keys[pygame.K_w]:
            self.control.throttle = min(1.0, self.control.throttle + CONTROL_THROTTLE_INCREMENT)
            self.control.brake = 0.0
        if keys[pygame.K_s]:
            self.control.throttle = 0.0
            self.control.brake = min(1.0, self.control.brake + CONTROL_BRAKE_INCREMENT)

        if keys[pygame.K_a]:
            self.control.steer = max(
                -CONTROL_STEERING_MAX, self.control.steer - CONTROL_STEERING_INCREMENT
            )
        elif keys[pygame.K_d]:
            self.control.steer = min(
                CONTROL_STEERING_MAX, self.control.steer + CONTROL_STEERING_INCREMENT
            )
        else:
            self.control.steer = 0.0 if abs(self.control.steer) < 0.1 else self.control.steer * 0.9

        self.control.reverse = keys[pygame.K_SPACE]
        vehicle.apply_control(self.control)
