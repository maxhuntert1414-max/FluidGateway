from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STATE_SNAPSHOT_MODE = "live-state-snapshot-v0.15"


@dataclass(frozen=True)
class LiveStateSnapshot:
    mode: str
    session_id: str
    current_frame: int | None
    open_frame: bool
    frames_observed: int
    events_processed: int
    operation_events: int
    resource_events: int
    active_resource_count: int
    memory_totals_mb: dict[str, float]
    memory_budgets_mb: dict[str, float]
    queue_costs_ms: dict[str, float]
    decisions_count: int
    policy_action_count: int
    live_command_count: int
    estimated_total_cost_ms_current_frame: float
    transfer_mb_current_frame: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "session_id": self.session_id,
            "current_frame": self.current_frame,
            "open_frame": self.open_frame,
            "frames_observed": self.frames_observed,
            "events_processed": self.events_processed,
            "operation_events": self.operation_events,
            "resource_events": self.resource_events,
            "active_resource_count": self.active_resource_count,
            "memory_totals_mb": rounded_map(self.memory_totals_mb),
            "memory_budgets_mb": rounded_map(self.memory_budgets_mb),
            "queue_costs_ms": rounded_map(self.queue_costs_ms),
            "decisions_count": self.decisions_count,
            "policy_action_count": self.policy_action_count,
            "live_command_count": self.live_command_count,
            "estimated_total_cost_ms_current_frame": round(
                self.estimated_total_cost_ms_current_frame, 4
            ),
            "transfer_mb_current_frame": round(self.transfer_mb_current_frame, 4),
        }


def build_live_state_snapshot(
    *,
    session_id: str,
    current_frame: int | None,
    frames: dict[int, Any],
    active_resource_count: int,
    memory_totals_mb: dict[str, float],
    memory_budgets_mb: dict[str, float],
    decisions_count: int,
    events_processed: int,
    operation_events: int,
    resource_events: int,
    policy_action_count: int,
    live_command_count: int,
) -> LiveStateSnapshot:
    queue_costs: dict[str, float] = {}
    for frame in frames.values():
        for queue, cost in (frame.queue_costs or {}).items():
            queue_costs[queue] = queue_costs.get(queue, 0.0) + cost

    current_stats = frames.get(current_frame) if current_frame is not None else None
    return LiveStateSnapshot(
        mode=STATE_SNAPSHOT_MODE,
        session_id=session_id,
        current_frame=current_frame,
        open_frame=current_frame is not None,
        frames_observed=len(frames),
        events_processed=events_processed,
        operation_events=operation_events,
        resource_events=resource_events,
        active_resource_count=active_resource_count,
        memory_totals_mb=dict(memory_totals_mb),
        memory_budgets_mb=dict(memory_budgets_mb),
        queue_costs_ms=queue_costs,
        decisions_count=decisions_count,
        policy_action_count=policy_action_count,
        live_command_count=live_command_count,
        estimated_total_cost_ms_current_frame=(
            current_stats.estimated_total_cost_ms if current_stats else 0.0
        ),
        transfer_mb_current_frame=current_stats.transfer_mb if current_stats else 0.0,
    )


def rounded_map(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 4) for key, value in sorted(values.items())}
