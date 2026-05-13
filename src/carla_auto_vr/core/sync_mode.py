
from __future__ import annotations

import queue
import time

import carla

from ..config.constants import FPS
from ..config.logging_config import get_logger

_logger = get_logger()


class CarlaSyncMode:
    """同步世界 tick 与传感器队列。"""

    def __init__(self, world, *sensors, fps: int = FPS):
        self.world = world
        self.sensors = sensors
        self.frame = None
        self.delta_seconds = 1.0 / fps
        self._queues: list[queue.Queue] = []
        self._settings = None
        self.tick_count = 0

    def __enter__(self):
        self._settings = self.world.get_settings()
        self.frame = self.world.apply_settings(
            carla.WorldSettings(
                no_rendering_mode=False,
                synchronous_mode=True,
                fixed_delta_seconds=self.delta_seconds,
            )
        )

        def make_queue(register_event):
            q: queue.Queue = queue.Queue()
            register_event(q.put)
            self._queues.append(q)

        make_queue(self.world.on_tick)
        for sensor in self.sensors:
            make_queue(sensor.listen)
        return self

    def tick(self, timeout: float = 2.0):
        self.tick_count += 1
        if self.tick_count % 10 == 0:
            _logger.debug(f"执行第 {self.tick_count} 次tick更新")

        self.frame = self.world.tick()
        data = []
        for q in self._queues:
            try:
                data.append(self._retrieve_data(q, timeout))
            except RuntimeError as e:
                _logger.error(f"获取数据失败: {e}")
                raise
        if any(x.frame != self.frame for x in data):
            _logger.warning(
                f"数据帧不一致: world={self.frame}, data={[x.frame for x in data]}"
            )
        return data

    def __exit__(self, *args, **kwargs):
        if self._settings is not None:
            self.world.apply_settings(self._settings)

    def _retrieve_data(self, sensor_queue: queue.Queue, timeout: float):
        start_time = time.time()
        while True:
            if sensor_queue.empty():
                time.sleep(0.001)
            if time.time() - start_time > timeout:
                raise RuntimeError("获取数据超时")
            try:
                data = sensor_queue.get(block=False)
                if data.frame == self.frame:
                    return data
            except queue.Empty:
                continue
