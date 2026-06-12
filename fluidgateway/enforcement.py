from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scheduler import SchedulerPlan, ScheduledStep


ENFORCEMENT_MODE = "adapter-enforcement-contract-v0.13"


@dataclass(frozen=True)
class EnforcementCommand:
    sequence: int
    action: str
    frame: int | None
    queue: str
    operation_id: str | None
    resource_id: str | None
    reason: str
    source_phase: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "action": self.action,
            "frame": self.frame,
            "queue": self.queue,
            "operation_id": self.operation_id,
            "resource_id": self.resource_id,
            "reason": self.reason,
            "source_phase": self.source_phase,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class EnforcementPlan:
    mode: str
    command_count: int
    commands_by_action: dict[str, int]
    commands: list[EnforcementCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "command_count": self.command_count,
            "commands_by_action": dict(sorted(self.commands_by_action.items())),
            "commands": [command.to_dict() for command in self.commands],
        }


def build_enforcement_plan(schedule_plan: SchedulerPlan) -> EnforcementPlan:
    commands = [
        command
        for command in (
            command_from_step(step) for step in schedule_plan.steps
        )
        if command is not None
    ]
    counts: dict[str, int] = {}
    for command in commands:
        counts[command.action] = counts.get(command.action, 0) + 1
    return EnforcementPlan(
        mode=ENFORCEMENT_MODE,
        command_count=len(commands),
        commands_by_action=counts,
        commands=commands,
    )


def command_from_step(step: ScheduledStep) -> EnforcementCommand | None:
    if step.phase == "prefetch":
        return EnforcementCommand(
            sequence=step.sequence,
            action="prefetch_now",
            frame=step.frame,
            queue=step.queue,
            operation_id=step.operation_id,
            resource_id=step.resource_id,
            reason="Move this transfer before frame-critical work.",
            source_phase=step.phase,
            expected_effect="Reduce copy/upload work on the active frame path.",
        )
    if step.phase in {"critical", "prepare", "sync", "work"}:
        return EnforcementCommand(
            sequence=step.sequence,
            action="execute_now",
            frame=step.frame,
            queue=step.queue,
            operation_id=step.operation_id,
            resource_id=step.resource_id,
            reason="Operation remains on the current executable frame path.",
            source_phase=step.phase,
            expected_effect="Preserve required frame work while earlier phases reduce pressure.",
        )
    if step.phase == "cleanup":
        return EnforcementCommand(
            sequence=step.sequence,
            action="release_after_frame",
            frame=step.frame,
            queue=step.queue,
            operation_id=step.operation_id,
            resource_id=step.resource_id,
            reason="Release transient memory once frame work has consumed it.",
            source_phase=step.phase,
            expected_effect="Lower memory residency pressure for later frames.",
        )
    return None
