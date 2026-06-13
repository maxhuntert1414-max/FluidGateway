from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .feedback import FeedbackAction, FeedbackPlan


ACTUATION_MODE = "runtime-actuation-plan-v0.21"


@dataclass(frozen=True)
class ActuationCommand:
    sequence: int
    command: str
    frame: int
    target: str
    value: float
    unit: str
    source_action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "command": self.command,
            "frame": self.frame,
            "target": self.target,
            "value": round(self.value, 4),
            "unit": self.unit,
            "source_action": self.source_action,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ActuationPlan:
    mode: str
    command_count: int
    total_copy_budget_ms: float
    total_prefetch_window_ms: float
    commands: list[ActuationCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "command_count": self.command_count,
            "total_copy_budget_ms": round(self.total_copy_budget_ms, 4),
            "total_prefetch_window_ms": round(self.total_prefetch_window_ms, 4),
            "commands": [command.to_dict() for command in self.commands],
        }


def build_actuation_plan(feedback_plan: FeedbackPlan) -> ActuationPlan:
    commands: list[ActuationCommand] = []
    for action in feedback_plan.actions:
        command = command_from_action(len(commands) + 1, action)
        if command is not None:
            commands.append(command)
    return ActuationPlan(
        mode=ACTUATION_MODE,
        command_count=len(commands),
        total_copy_budget_ms=sum_value(commands, "set_copy_queue_budget"),
        total_prefetch_window_ms=sum_value(commands, "reserve_prefetch_window"),
        commands=commands,
    )


def command_from_action(
    sequence: int, action: FeedbackAction
) -> ActuationCommand | None:
    if action.action == "preserve-prefetch-window":
        return command(
            sequence=sequence,
            action=action,
            command_name="reserve_prefetch_window",
            target="prefetch",
            value=action.evidence.get("suggested_prefetch_window_ms", 0.0),
            unit="ms",
            reason="Reserve predictable transfer time before draw-critical work.",
        )
    if action.action == "cap-copy-queue":
        return command(
            sequence=sequence,
            action=action,
            command_name="set_copy_queue_budget",
            target="copy",
            value=action.evidence.get("suggested_copy_budget_ms", 0.0),
            unit="ms",
            reason="Limit late copy queue work in the next frame.",
        )
    if action.action == "maintain-reuse-dedupe":
        return command(
            sequence=sequence,
            action=action,
            command_name="enable_reuse_dedupe",
            target="control-plane",
            value=1.0,
            unit="enabled",
            reason="Keep reuse and dedupe gates active for redundant work.",
        )
    if action.action == "protect-hot-path-headroom":
        return command(
            sequence=sequence,
            action=action,
            command_name="protect_hot_path_headroom",
            target="frame",
            value=action.evidence.get("target_frame_ms", 0.0),
            unit="ms",
            reason="Protect the next frame from non-critical queue pressure.",
        )
    return None


def command(
    *,
    sequence: int,
    action: FeedbackAction,
    command_name: str,
    target: str,
    value: float,
    unit: str,
    reason: str,
) -> ActuationCommand:
    return ActuationCommand(
        sequence=sequence,
        command=command_name,
        frame=action.frame,
        target=target,
        value=value,
        unit=unit,
        source_action=action.action,
        reason=reason,
    )


def sum_value(commands: list[ActuationCommand], command_name: str) -> float:
    return sum(command.value for command in commands if command.command == command_name)
