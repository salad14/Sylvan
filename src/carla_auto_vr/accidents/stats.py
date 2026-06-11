"""事故事件统计。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IncidentStats:
    """事件发生次数累计。字段名与原 accident_simulation.incident_results 对齐。"""

    counters: dict[str, int] = field(
        default_factory=lambda: {
            "successful_crossing": 0,
            "potential_collision": 0,
            "timeout": 0,
            "vehicle_braking": 0,
            "vehicle_lane_change": 0,
        }
    )

    def bump(self, key: str) -> int:
        if key not in self.counters:
            self.counters[key] = 0
        self.counters[key] += 1
        return self.counters[key]

    def snapshot(self) -> dict[str, int]:
        return dict(self.counters)
