from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lifetime import ResourceLifetimePlan
from .runtime import RuntimeOperation


SCHEDULER_MODE = "frame-scheduler-simulation-v0.12"


@dataclass(frozen=True)
class ScheduledStep:
    sequence: int
    kind: str
    phase: str
    frame: int | None
    queue: str
    operation_id: str | None
    resource_id: str | None
    cost_ms: float
    size_mb: float
    source_action: str | None
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "phase": self.phase,
            "frame": self.frame,
            "queue": self.queue,
            "operation_id": self.operation_id,
            "resource_id": self.resource_id,
            "cost_ms": round(self.cost_ms, 4),
            "size_mb": round(self.size_mb, 4),
            "source_action": self.source_action,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class FrameSchedule:
    frame: int
    target_frame_ms: float
    critical_path_before_ms: float
    critical_path_after_ms: float
    moved_transfer_ms: float
    moved_transfer_mb: float
    budget_status_before: str
    budget_status_after: str
    step_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "critical_path_before_ms": round(self.critical_path_before_ms, 4),
            "critical_path_after_ms": round(self.critical_path_after_ms, 4),
            "moved_transfer_ms": round(self.moved_transfer_ms, 4),
            "moved_transfer_mb": round(self.moved_transfer_mb, 4),
            "budget_status_before": self.budget_status_before,
            "budget_status_after": self.budget_status_after,
            "step_count": self.step_count,
        }


@dataclass(frozen=True)
class SchedulerPlan:
    mode: str
    scheduled_step_count: int
    estimated_critical_path_before_ms: float
    estimated_critical_path_after_ms: float
    estimated_latency_reduction_ms: float
    estimated_moved_transfer_mb: float
    frames: list[FrameSchedule]
    steps: list[ScheduledStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scheduled_step_count": self.scheduled_step_count,
            "estimated_critical_path_before_ms": round(
                self.estimated_critical_path_before_ms, 4
            ),
            "estimated_critical_path_after_ms": round(
                self.estimated_critical_path_after_ms, 4
            ),
            "estimated_latency_reduction_ms": round(
                self.estimated_latency_reduction_ms, 4
            ),
            "estimated_moved_transfer_mb": round(self.estimated_moved_transfer_mb, 4),
            "frames": [frame.to_dict() for frame in self.frames],
            "steps": [step.to_dict() for step in self.steps],
        }


def simulate_scheduler(
    operations: list[RuntimeOperation],
    frame_targets_ms: dict[int, float],
    frame_costs_ms: dict[int, float],
    lifetime_plan: ResourceLifetimePlan,
) -> SchedulerPlan:
    prefetch_actions = {
        action.source_operation_id: action
        for action in lifetime_plan.actions
        if action.action == "prefetch-before-frame" and action.source_operation_id
    }
    release_actions_by_frame: dict[int, list[Any]] = {}
    for action in lifetime_plan.actions:
        if action.action == "release-after-frame" and action.target_frame is not None:
            release_actions_by_frame.setdefault(action.target_frame, []).append(action)

    operations_by_frame: dict[int, list[RuntimeOperation]] = {}
    for operation in operations:
        if operation.frame is not None:
            operations_by_frame.setdefault(operation.frame, []).append(operation)

    frame_ids = sorted(set(frame_targets_ms) | set(frame_costs_ms) | set(operations_by_frame))
    frames: list[FrameSchedule] = []
    steps: list[ScheduledStep] = []
    sequence = 1

    for frame in frame_ids:
        frame_operations = operations_by_frame.get(frame, [])
        target_ms = frame_targets_ms.get(frame, 16.67)
        before_ms = frame_costs_ms.get(
            frame, sum(operation.cost_ms for operation in frame_operations)
        )
        moved_operations = [
            operation for operation in frame_operations if operation.id in prefetch_actions
        ]
        moved_transfer_ms = sum(operation.cost_ms for operation in moved_operations)
        moved_transfer_mb = sum(operation.size_mb for operation in moved_operations)
        after_ms = max(0.0, before_ms - moved_transfer_ms)

        for operation in sorted(moved_operations, key=lambda item: item.id):
            action = prefetch_actions[operation.id]
            steps.append(
                ScheduledStep(
                    sequence=sequence,
                    kind="operation",
                    phase="prefetch",
                    frame=frame,
                    queue=operation.queue,
                    operation_id=operation.id,
                    resource_id=operation.target,
                    cost_ms=operation.cost_ms,
                    size_mb=operation.size_mb,
                    source_action=action.action,
                    rationale=action.rationale,
                )
            )
            sequence += 1

        critical_operations = [
            operation for operation in frame_operations if operation.id not in prefetch_actions
        ]
        for operation in sorted(critical_operations, key=operation_sort_key):
            steps.append(
                ScheduledStep(
                    sequence=sequence,
                    kind="operation",
                    phase=operation_phase(operation),
                    frame=frame,
                    queue=operation.queue,
                    operation_id=operation.id,
                    resource_id=operation.target,
                    cost_ms=operation.cost_ms,
                    size_mb=operation.size_mb,
                    source_action=None,
                    rationale="Keep operation on the frame-critical schedule.",
                )
            )
            sequence += 1

        for action in sorted(
            release_actions_by_frame.get(frame, []),
            key=lambda item: (-item.priority, item.resource_id),
        ):
            steps.append(
                ScheduledStep(
                    sequence=sequence,
                    kind="lifetime-action",
                    phase="cleanup",
                    frame=frame,
                    queue="memory",
                    operation_id=action.source_operation_id,
                    resource_id=action.resource_id,
                    cost_ms=0.0,
                    size_mb=action.size_mb,
                    source_action=action.action,
                    rationale=action.rationale,
                )
            )
            sequence += 1

        frame_step_count = sum(1 for step in steps if step.frame == frame)
        frames.append(
            FrameSchedule(
                frame=frame,
                target_frame_ms=target_ms,
                critical_path_before_ms=before_ms,
                critical_path_after_ms=after_ms,
                moved_transfer_ms=moved_transfer_ms,
                moved_transfer_mb=moved_transfer_mb,
                budget_status_before=budget_status(before_ms, target_ms),
                budget_status_after=budget_status(after_ms, target_ms),
                step_count=frame_step_count,
            )
        )

    before_total = sum(frame.critical_path_before_ms for frame in frames)
    after_total = sum(frame.critical_path_after_ms for frame in frames)
    moved_mb = sum(frame.moved_transfer_mb for frame in frames)
    return SchedulerPlan(
        mode=SCHEDULER_MODE,
        scheduled_step_count=len(steps),
        estimated_critical_path_before_ms=before_total,
        estimated_critical_path_after_ms=after_total,
        estimated_latency_reduction_ms=max(0.0, before_total - after_total),
        estimated_moved_transfer_mb=moved_mb,
        frames=frames,
        steps=steps,
    )


def operation_sort_key(operation: RuntimeOperation) -> tuple[int, str]:
    order = {
        "sync": 0,
        "copy": 1,
        "upload": 1,
        "compute": 2,
        "draw": 3,
        "present": 4,
    }
    return (order.get(operation.type, 5), operation.id)


def operation_phase(operation: RuntimeOperation) -> str:
    if operation.type in {"copy", "upload"}:
        return "prepare"
    if operation.type in {"draw", "compute", "present"}:
        return "critical"
    if operation.type == "sync":
        return "sync"
    return "work"


def budget_status(cost_ms: float, target_ms: float) -> str:
    return "within-budget" if cost_ms <= target_ms else "over-budget"
