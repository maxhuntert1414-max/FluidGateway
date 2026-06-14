from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manager import (
    FrameManagerDirective,
    MemoryManagerDirective,
    RuntimeManagerDirective,
)


CONTROL_PACKET_MODE = "runtime-control-packet-v0.34"


@dataclass(frozen=True)
class RuntimeControlCommand:
    sequence: int
    domain: str
    command: str
    target: str
    frame: int | None
    memory: str | None
    value_ms: float
    value_mb: float
    setting: str | None
    priority: str
    source_action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "domain": self.domain,
            "command": self.command,
            "target": self.target,
            "frame": self.frame,
            "memory": self.memory,
            "value_ms": round(self.value_ms, 4),
            "value_mb": round(self.value_mb, 4),
            "setting": self.setting,
            "priority": self.priority,
            "source_action": self.source_action,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeControlPacket:
    mode: str
    profile: str
    next_frame_policy: str
    dispatch_action: str
    command_count: int
    active_command_count: int
    frame_command_count: int
    queue_command_count: int
    scheduler_command_count: int
    memory_command_count: int
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    total_expected_memory_relief_mb: float
    commands: list[RuntimeControlCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "dispatch_action": self.dispatch_action,
            "command_count": self.command_count,
            "active_command_count": self.active_command_count,
            "frame_command_count": self.frame_command_count,
            "queue_command_count": self.queue_command_count,
            "scheduler_command_count": self.scheduler_command_count,
            "memory_command_count": self.memory_command_count,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "total_expected_memory_relief_mb": round(
                self.total_expected_memory_relief_mb, 4
            ),
            "commands": [command.to_dict() for command in self.commands],
        }


def build_runtime_control_packet(
    manager: RuntimeManagerDirective,
) -> RuntimeControlPacket:
    commands = build_control_commands(manager)
    return RuntimeControlPacket(
        mode=CONTROL_PACKET_MODE,
        profile=manager.profile,
        next_frame_policy=manager.next_frame_policy,
        dispatch_action=manager.dispatch_action,
        command_count=len(commands),
        active_command_count=sum(1 for command in commands if is_active(command)),
        frame_command_count=count_domain(commands, "frame"),
        queue_command_count=count_domain(commands, "queue"),
        scheduler_command_count=count_domain(commands, "scheduler"),
        memory_command_count=count_domain(commands, "memory"),
        next_frame_budget_ms=manager.next_frame_budget_ms,
        hot_path_budget_ms=manager.hot_path_budget_ms,
        copy_queue_budget_ms=manager.copy_queue_budget_ms,
        pre_frame_window_ms=manager.pre_frame_window_ms,
        total_expected_memory_relief_mb=manager.total_expected_memory_relief_mb,
        commands=commands,
    )


def build_control_commands(
    manager: RuntimeManagerDirective,
) -> list[RuntimeControlCommand]:
    payloads: list[RuntimeControlCommand] = []
    for frame in manager.frames:
        payloads.extend(frame_commands(frame, manager.dispatch_action))
    for directive in manager.memory_directives:
        payloads.append(memory_command(directive, manager.dispatch_action))
    return [
        RuntimeControlCommand(sequence=index, **command_payload(command))
        for index, command in enumerate(payloads, start=1)
    ]


def frame_commands(
    frame: FrameManagerDirective,
    dispatch_action: str,
) -> list[RuntimeControlCommand]:
    priority = priority_for_frame(frame)
    target = f"frame:{frame.frame}"
    return [
        RuntimeControlCommand(
            sequence=0,
            domain="frame",
            command="set_next_frame_budget",
            target=target,
            frame=frame.frame,
            memory=None,
            value_ms=frame.next_frame_budget_ms,
            value_mb=0.0,
            setting=None,
            priority=priority,
            source_action=dispatch_action,
            reason=frame.reason,
        ),
        RuntimeControlCommand(
            sequence=0,
            domain="frame",
            command="set_hot_path_budget",
            target=target,
            frame=frame.frame,
            memory=None,
            value_ms=frame.hot_path_budget_ms,
            value_mb=0.0,
            setting=None,
            priority=priority,
            source_action=dispatch_action,
            reason=frame.reason,
        ),
        RuntimeControlCommand(
            sequence=0,
            domain="queue",
            command="set_copy_queue_budget",
            target=target,
            frame=frame.frame,
            memory=None,
            value_ms=frame.copy_queue_budget_ms,
            value_mb=0.0,
            setting=None,
            priority=priority,
            source_action=frame.queue_policy,
            reason=frame.reason,
        ),
        RuntimeControlCommand(
            sequence=0,
            domain="queue",
            command="reserve_pre_frame_window",
            target=target,
            frame=frame.frame,
            memory=None,
            value_ms=frame.pre_frame_window_ms,
            value_mb=0.0,
            setting=None,
            priority=priority,
            source_action=frame.calibration_action,
            reason=frame.reason,
        ),
        RuntimeControlCommand(
            sequence=0,
            domain="scheduler",
            command="set_admission_mode",
            target=target,
            frame=frame.frame,
            memory=None,
            value_ms=0.0,
            value_mb=0.0,
            setting=frame.admission_mode,
            priority=priority,
            source_action=frame.calibration_action,
            reason=frame.reason,
        ),
        RuntimeControlCommand(
            sequence=0,
            domain="scheduler",
            command="set_scheduler_mode",
            target=target,
            frame=frame.frame,
            memory=None,
            value_ms=0.0,
            value_mb=0.0,
            setting=frame.scheduler_mode,
            priority=priority,
            source_action=frame.calibration_action,
            reason=frame.reason,
        ),
    ]


def memory_command(
    directive: MemoryManagerDirective,
    dispatch_action: str,
) -> RuntimeControlCommand:
    command = memory_command_name(directive.action)
    value_mb = (
        directive.expected_relief_mb
        if directive.expected_relief_mb > 0.0
        else directive.reserve_headroom_mb
    )
    return RuntimeControlCommand(
        sequence=0,
        domain="memory",
        command=command,
        target=directive.memory,
        frame=None,
        memory=directive.memory,
        value_ms=0.0,
        value_mb=value_mb,
        setting=directive.action,
        priority=priority_for_memory(directive),
        source_action=dispatch_action,
        reason=directive.reason,
    )


def memory_command_name(action: str) -> str:
    if action == "reserve-headroom":
        return "reserve_memory_headroom"
    return action.replace("-", "_")


def priority_for_frame(frame: FrameManagerDirective) -> str:
    if frame.scheduler_mode in {"closed-loop-aggressive", "guardband-tightening"}:
        return "high"
    if frame.scheduler_mode == "closed-loop-stable":
        return "normal"
    return "low"


def priority_for_memory(directive: MemoryManagerDirective) -> str:
    if directive.action == "evict-or-defer-residency":
        return "high"
    if directive.action == "reserve-headroom":
        return "normal"
    return "low"


def is_active(command: RuntimeControlCommand) -> bool:
    return command.command not in {"hold_residency", "observe_residency"}


def count_domain(commands: list[RuntimeControlCommand], domain: str) -> int:
    return sum(1 for command in commands if command.domain == domain)


def command_payload(command: RuntimeControlCommand) -> dict[str, Any]:
    payload = command.to_dict()
    payload.pop("sequence", None)
    return payload
