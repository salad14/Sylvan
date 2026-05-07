"""把 JSON 风格的 ROS 数据应用到 CARLA 车辆。对齐原 _process_json_data。"""

from __future__ import annotations

from typing import Optional

import carla

from ..config.logging_config import get_logger
from .yaw_calibrator import YawCalibrator

_logger = get_logger()


class VehicleStateApplier:
    """把形如 ``{'timestamp', 'rotation', 'velocity'}`` 的字典应用到主车。"""

    def __init__(self, vehicle: carla.Actor, yaw_calibrator: YawCalibrator):
        self.vehicle = vehicle
        self.yaw_calibrator = yaw_calibrator
        self._process_count = 0

    def apply(self, json_data: dict) -> Optional[float]:
        """返回消息中的 timestamp（若存在）。"""
        try:
            if not json_data:
                _logger.warning("收到空的JSON数据")
                return None

            timestamp = json_data.get("timestamp")
            rotation = json_data.get("rotation", {}) or {}
            velocity = json_data.get("velocity", {}) or {}

            yaw_rad = float(rotation.get("yaw", 0.0))

            current_transform = self.vehicle.get_transform()
            current_carla_yaw = current_transform.rotation.yaw
            final_yaw = self.yaw_calibrator.ros_to_carla_yaw(yaw_rad, current_carla_yaw)

            vel_x = float(velocity.get("x", 0.0))
            vel_y = float(velocity.get("y", 0.0))
            vel_z = float(velocity.get("z", 0.0))
            # ROS: x=前进, y=左；CARLA: forward, right
            local_vel_x = vel_x
            local_vel_y = -vel_y

            new_rotation = carla.Rotation(
                pitch=current_transform.rotation.pitch,
                yaw=final_yaw,
                roll=current_transform.rotation.roll,
            )
            new_transform = carla.Transform(
                location=current_transform.location,
                rotation=new_rotation,
            )
            self.vehicle.set_transform(new_transform)

            new_tf = self.vehicle.get_transform()
            self.vehicle.set_target_velocity(
                new_tf.get_forward_vector() * local_vel_x
                + new_tf.get_right_vector() * local_vel_y
                + carla.Vector3D(0, 0, vel_z)
            )

            self._process_count += 1
            if self._process_count % 10 == 0:
                import math

                _logger.debug(
                    "ROS yaw: %.1f° -> 校准后CARLA yaw: %.1f° (偏移: %.1f°)"
                    % (
                        math.degrees(yaw_rad),
                        final_yaw,
                        self.yaw_calibrator.offset,
                    )
                )
                _logger.debug(f"速度: 前进={local_vel_x:.2f}, 侧向={local_vel_y:.2f}")
            return timestamp
        except Exception as e:  # noqa: BLE001
            _logger.warning(f"处理JSON数据出错: {e}")
            return None
