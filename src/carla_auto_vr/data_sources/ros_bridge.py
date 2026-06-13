"""ROS2 桥接节点。

同时适配 :class:`VehicleDataSource` 协议。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSDurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32MultiArray

try:
    from testcarla_interfaces.msg import Gongjicarla  # type: ignore

    USE_CUSTOM_MSG = True
    print("成功导入自定义消息类型 Gongjicarla")
except ImportError as e:  # pragma: no cover
    USE_CUSTOM_MSG = False
    print(f"无法导入自定义消息类型 Gongjicarla: {e}")
    print("将使用标准 Float32MultiArray 作为备选")

from .base import VehicleDataSource


class ROSBridge(Node, VehicleDataSource):
    """ROSBridge 数据源实现。"""

    name = "ros"

    def __init__(self, host: str = "localhost", port: int = 2000):
        Node.__init__(self, "carlatest")
        self.get_logger().info("ROS2桥接节点已启动")

        self.latest_data: Optional[dict] = None
        self.data_lock = threading.Lock()

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self.get_logger().info("正在检查可用的话题...")
        self.topic_timer = self.create_timer(2.0, self.check_available_topics)
        self.available_topics: set = set()

        msg_type = Gongjicarla if USE_CUSTOM_MSG else Float32MultiArray
        msg_type_name = "Gongjicarla" if USE_CUSTOM_MSG else "Float32MultiArray"
        self.get_logger().info(f"使用消息类型: {msg_type_name}")

        self.get_logger().info(
            "订阅主要话题: /carlatest 和 carlatest (带斜杠和不带斜杠的版本)"
        )
        self.vehicle_data_sub1 = self.create_subscription(
            msg_type, "/carlatest", self.vehicle_data_callback, qos_profile
        )
        self.vehicle_data_sub2 = self.create_subscription(
            msg_type, "carlatest", self.vehicle_data_callback, qos_profile
        )

        alt_topics = ["/vehicle/data", "/carla/vehicle_data", "/vehicle_data", "/data"]
        self.alt_subs = []
        for topic in alt_topics:
            self.get_logger().info(f"尝试订阅备选话题: {topic}")
            sub = self.create_subscription(
                msg_type, topic, self.vehicle_data_callback, qos_profile
            )
            self.alt_subs.append(sub)

        self.get_logger().info("已订阅以下话题:")
        self.get_logger().info(" - /carlatest (主话题，带斜杠)")
        self.get_logger().info(" - carlatest (主话题，不带斜杠)")
        for topic in alt_topics:
            self.get_logger().info(f" - {topic} (备选话题)")

        self.timestamp = None
        self.pitch = None
        self.roll = None
        self.yaw = None
        self.vel_x = None
        self.vel_y = None
        self.vel_z = None

        self.last_update_time = self.get_clock().now().nanoseconds / 1e9
        self.signal_count = 0
        self.signal_check_timer = self.create_timer(2.0, self.check_signal_status)

        self.ros_spin_thread: Optional[threading.Thread] = None
        self.running = True
        self.get_logger().info("ROS2桥接已启动并等待数据...")
        self.start_ros_spin_thread()

    # ---------- VehicleDataSource 接口 ----------
    def is_ready(self) -> bool:
        return self.latest_data is not None

    def poll(self) -> Optional[dict]:
        return self.get_latest_data()

    # ---------- ROSBridge 辅助方法 ----------
    def start_ros_spin_thread(self) -> None:
        self.get_logger().info("启动ROS消息处理线程...")
        self.ros_spin_thread = threading.Thread(target=self._ros_spin)
        self.ros_spin_thread.daemon = True
        self.ros_spin_thread.start()
        self.get_logger().info("ROS消息处理线程已启动")

    def _ros_spin(self) -> None:
        try:
            self.get_logger().info("ROS消息处理循环已开始")
            rate_limiter = 0
            while self.running and rclpy.ok():
                rclpy.spin_once(self, timeout_sec=0.1)
                rate_limiter += 1
                if rate_limiter >= 50:
                    self.get_logger().debug("ROS消息处理循环正在运行")
                    rate_limiter = 0
                time.sleep(0.01)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"ROS消息处理循环异常: {e}")
        finally:
            self.get_logger().info("ROS消息处理循环已结束")

    def check_available_topics(self) -> None:
        topic_names_and_types = self.get_topic_names_and_types()
        current_topics = {name for name, _ in topic_names_and_types}
        new_topics = current_topics - self.available_topics
        if new_topics:
            self.get_logger().info(f"发现新话题: {', '.join(new_topics)}")
            for topic in new_topics:
                if (
                    "vehicle" in topic.lower()
                    or "data" in topic.lower()
                    or "carla" in topic.lower()
                ):
                    self.get_logger().info(f"自动订阅新发现的相关话题: {topic}")
                    try:
                        msg_type = Gongjicarla if USE_CUSTOM_MSG else Float32MultiArray
                        sub = self.create_subscription(
                            msg_type, topic, self.vehicle_data_callback, 10
                        )
                        self.alt_subs.append(sub)
                    except Exception as e:  # noqa: BLE001
                        self.get_logger().error(f"无法订阅话题 {topic}: {e}")
        self.available_topics = current_topics

    def vehicle_data_callback(self, msg) -> None:  # noqa: ANN001
        with self.data_lock:
            self.signal_count += 1
            self.get_logger().info(f"接收到第 {self.signal_count} 个车辆数据信号")

            if USE_CUSTOM_MSG:
                try:
                    self.timestamp = int(msg.timestamp)
                    self.pitch = msg.pitch
                    self.roll = msg.roll
                    self.yaw = msg.yaw
                    self.vel_x = msg.vel_x
                    self.vel_y = msg.vel_y
                    self.vel_z = msg.vel_z
                    self.get_logger().info(
                        f"解析自定义消息成功：timestamp={self.timestamp}"
                    )
                    self.get_logger().info(
                        f"消息内容: pitch={self.pitch:.4f}, roll={self.roll:.4f}, yaw={self.yaw:.4f}"
                    )
                    self.get_logger().info(
                        f"速度: x={self.vel_x:.4f}, y={self.vel_y:.4f}, z={self.vel_z:.4f}"
                    )
                except AttributeError as e:
                    self.get_logger().error(f"解析自定义消息失败，字段不存在: {e}")
                    self.get_logger().info(f"消息字段: {dir(msg)}")
                    return
                except Exception as e:  # noqa: BLE001
                    self.get_logger().error(f"解析自定义消息时发生错误: {e}")
                    return
            else:
                if len(msg.data) >= 7:
                    self.timestamp = int(msg.data[0])
                    self.pitch = msg.data[1]
                    self.roll = msg.data[2]
                    self.yaw = msg.data[3]
                    self.vel_x = msg.data[4]
                    self.vel_y = msg.data[5]
                    self.vel_z = msg.data[6]
                else:
                    self.get_logger().warn(
                        f"接收到的数据格式不正确: {msg.data}, 长度: {len(msg.data)}"
                    )
                    self.get_logger().info(f"原始数据: {msg.data}")
                    return

            self.get_logger().debug(
                f"数据详情: 时间戳={self.timestamp}, 俯仰={self.pitch:.2f}, 横滚={self.roll:.2f}, 偏航={self.yaw:.2f}"
            )
            self.get_logger().debug(
                f"速度: x={self.vel_x:.2f}, y={self.vel_y:.2f}, z={self.vel_z:.2f}"
            )
            self.update_latest_data()
            self.last_update_time = self.get_clock().now().nanoseconds / 1e9

    def check_signal_status(self) -> None:
        current_time = self.get_clock().now().nanoseconds / 1e9
        time_diff = current_time - self.last_update_time
        if time_diff > 5.0:
            self.get_logger().warn(
                f"警告: {time_diff:.1f}秒内未接收到任何车辆数据信号"
            )
            self.get_logger().info("当前可用的话题:")
            for topic, types in self.get_topic_names_and_types():
                self.get_logger().info(f" - {topic}: {types}")
        elif time_diff > 2.0:
            self.get_logger().info(
                f"提示: {time_diff:.1f}秒内未接收到新的车辆数据信号"
            )

    def update_latest_data(self) -> None:
        if self.pitch is None or self.vel_x is None:
            return
        data = {
            "timestamp": self.timestamp,
            "rotation": {"roll": self.roll, "pitch": self.pitch, "yaw": self.yaw},
            "velocity": {"x": self.vel_x, "y": self.vel_y, "z": self.vel_z},
        }
        self.latest_data = data
        self.publish_processed_data()

    def publish_processed_data(self) -> None:
        if self.latest_data:
            self.get_logger().debug("数据已处理完成 (发布功能已禁用)")
            self.get_logger().debug(f"处理后的数据: {self.latest_data}")

    def get_latest_data(self) -> Optional[dict]:
        with self.data_lock:
            return self.latest_data

    def is_data_fresh(self, max_age: float = 1.0) -> bool:
        current_time = self.get_clock().now().nanoseconds / 1e9
        return (current_time - self.last_update_time) < max_age

    def shutdown(self) -> None:
        self.get_logger().info("正在关闭ROS桥接节点...")
        self.running = False
        if self.ros_spin_thread and self.ros_spin_thread.is_alive():
            self.ros_spin_thread.join(timeout=2.0)
        self.get_logger().info("ROS桥接节点已关闭")


def main(args=None):  # noqa: ANN001
    """console_scripts 入口。"""
    try:
        rclpy.init(args=args)
        bridge = ROSBridge()
        bridge.get_logger().info("节点初始化完成，开始监听话题...")
        bridge.get_logger().info(
            f"当前可用话题: {[topic for topic, _ in bridge.get_topic_names_and_types()]}"
        )
        try:
            while rclpy.ok():
                time.sleep(0.5)
        except KeyboardInterrupt:
            bridge.get_logger().info("用户中断，准备关闭节点")
        finally:
            bridge.shutdown()
    except Exception as e:  # noqa: BLE001
        print(f"发生错误: {e}")
    finally:
        if "bridge" in locals():
            bridge.destroy_node()  # type: ignore[possibly-undefined]
        rclpy.shutdown()


if __name__ == "__main__":
    main()
