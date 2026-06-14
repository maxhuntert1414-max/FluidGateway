from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dispatch import DispatchCommand, RuntimeDispatchPlan


DISPATCH_EXECUTION_MODE = "runtime-dispatch-execution-v0.31"


@dataclass(frozen=True)
class DispatchExecutionStep:
    sequence: int
    phase: str
    command: str
    outcome: str
    operation_id: str | None
    memory: str | None
    frame: int | None
    current_frame_cost_ms: float
    pre_frame_cost_ms: float
    avoided_cost_ms: float
    deferred_cost_ms: float
    memory_relief_mb: float
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "phase": self.phase,
            "command": self.command,
            "outcome": self.outcome,
            "operation_id": self.operation_id,
            "memory": self.memory,
            "frame": self.frame,
            "current_frame_cost_ms": round(self.current_frame_cost_ms, 4),
            "pre_frame_cost_ms": round(self.pre_frame_cost_ms, 4),
            "avoided_cost_ms": round(self.avoided_cost_ms, 4),
            "deferred_cost_ms": round(self.deferred_cost_ms, 4),
            "memory_relief_mb": round(self.memory_relief_mb, 4),
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class DispatchExecutionReport:
    mode: str
    profile: str
    next_frame_policy: str
    step_count: int
    applied_count: int
    scheduled_count: int
    deferred_count: int
    removed_count: int
    memory_action_count: int
    current_frame_cost_ms: float
    pre_frame_cost_ms: float
    avoided_cost_ms: float
    deferred_cost_ms: float
    memory_relief_mb: float
    steps: list[DispatchExecutionStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "step_count": self.step_count,
            "applied_count": self.applied_count,
            "scheduled_count": self.scheduled_count,
            "deferred_count": self.deferred_count,
            "removed_count": self.removed_count,
            "memory_action_count": self.memory_action_count,
            "current_frame_cost_ms": round(self.current_frame_cost_ms, 4),
            "pre_frame_cost_ms": round(self.pre_frame_cost_ms, 4),
            "avoided_cost_ms": round(self.avoided_cost_ms, 4),
            "deferred_cost_ms": round(self.deferred_cost_ms, 4),
            "memory_relief_mb": round(self.memory_relief_mb, 4),
            "steps": [step.to_dict() for step in self.steps],
        }


def execute_dispatch_plan(dispatch_plan: RuntimeDispatchPlan) -> DispatchExecutionReport:
    steps = [
        execution_step(command) for command in dispatch_plan.commands
    ]
    return DispatchExecutionReport(
        mode=DISPATCH_EXECUTION_MODE,
        profile=dispatch_plan.profile,
        next_frame_policy=dispatch_plan.next_frame_policy,
        step_count=len(steps),
        applied_count=count_outcome(steps, "applied"),
        scheduled_count=count_outcome(steps, "scheduled"),
        deferred_count=count_outcome(steps, "deferred"),
        removed_count=count_command(steps, "drop_operation"),
        memory_action_count=sum(1 for step in steps if step.memory is not None),
        current_frame_cost_ms=sum_value(steps, "current_frame_cost_ms"),
        pre_frame_cost_ms=sum_value(steps, "pre_frame_cost_ms"),
        avoided_cost_ms=sum_value(steps, "avoided_cost_ms"),
        deferred_cost_ms=sum_value(steps, "deferred_cost_ms"),
        memory_relief_mb=sum_value(steps, "memory_relief_mb"),
        steps=steps,
    )


def execution_step(command: DispatchCommand) -> DispatchExecutionStep:
    if command.command == "drop_operation":
        return step(
            command,
            outcome="applied",
            avoided_cost_ms=command.cost_ms,
        )
    if command.command == "prestage_operation":
        return step(
            command,
            outcome="scheduled",
            pre_frame_cost_ms=command.cost_ms,
        )
    if command.command == "execute_operation":
        return step(
            command,
            outcome="applied",
            current_frame_cost_ms=command.cost_ms,
        )
    if command.command == "defer_or_split_operation":
        return step(
            command,
            outcome="deferred",
            deferred_cost_ms=command.cost_ms,
        )
    if command.command in {"evict_or_defer_residency", "reserve_memory_headroom"}:
        return step(
            command,
            outcome="scheduled",
            memory_relief_mb=command.value_mb,
        )
    return step(command, outcome="ignored")


def step(
    command: DispatchCommand,
    *,
    outcome: str,
    current_frame_cost_ms: float = 0.0,
    pre_frame_cost_ms: float = 0.0,
    avoided_cost_ms: float = 0.0,
    deferred_cost_ms: float = 0.0,
    memory_relief_mb: float = 0.0,
) -> DispatchExecutionStep:
    return DispatchExecutionStep(
        sequence=command.sequence,
        phase=command.phase,
        command=command.command,
        outcome=outcome,
        operation_id=command.operation_id,
        memory=command.memory,
        frame=command.frame,
        current_frame_cost_ms=current_frame_cost_ms,
        pre_frame_cost_ms=pre_frame_cost_ms,
        avoided_cost_ms=avoided_cost_ms,
        deferred_cost_ms=deferred_cost_ms,
        memory_relief_mb=memory_relief_mb,
        reason=command.reason,
        expected_effect=command.expected_effect,
    )


def count_outcome(steps: list[DispatchExecutionStep], outcome: str) -> int:
    return sum(1 for step in steps if step.outcome == outcome)


def count_command(steps: list[DispatchExecutionStep], command: str) -> int:
    return sum(1 for step in steps if step.command == command)


def sum_value(steps: list[DispatchExecutionStep], field: str) -> float:
    return sum(float(getattr(step, field)) for step in steps)
