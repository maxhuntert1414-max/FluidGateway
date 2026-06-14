from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control_packet import RuntimeControlCommand, RuntimeControlPacket, is_active


CONTROL_STATE_MODE = "runtime-control-state-v0.35"


@dataclass
class FrameControlState:
    frame: int
    next_frame_budget_ms: float = 0.0
    hot_path_budget_ms: float = 0.0
    copy_queue_budget_ms: float = 0.0
    pre_frame_window_ms: float = 0.0
    admission_mode: str | None = None
    scheduler_mode: str | None = None
    priority: str = "low"
    command_count: int = 0
    active_command_count: int = 0

    def apply(self, command: RuntimeControlCommand) -> None:
        self.command_count += 1
        if is_active(command):
            self.active_command_count += 1
        self.priority = stronger_priority(self.priority, command.priority)
        if command.command == "set_next_frame_budget":
            self.next_frame_budget_ms = command.value_ms
        elif command.command == "set_hot_path_budget":
            self.hot_path_budget_ms = command.value_ms
        elif command.command == "set_copy_queue_budget":
            self.copy_queue_budget_ms = command.value_ms
        elif command.command == "reserve_pre_frame_window":
            self.pre_frame_window_ms = command.value_ms
        elif command.command == "set_admission_mode":
            self.admission_mode = command.setting
        elif command.command == "set_scheduler_mode":
            self.scheduler_mode = command.setting

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "admission_mode": self.admission_mode,
            "scheduler_mode": self.scheduler_mode,
            "priority": self.priority,
            "command_count": self.command_count,
            "active_command_count": self.active_command_count,
        }


@dataclass
class MemoryControlState:
    memory: str
    command: str
    setting: str | None
    expected_relief_mb: float
    reserve_headroom_mb: float
    active: bool
    priority: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory,
            "command": self.command,
            "setting": self.setting,
            "expected_relief_mb": round(self.expected_relief_mb, 4),
            "reserve_headroom_mb": round(self.reserve_headroom_mb, 4),
            "active": self.active,
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeControlState:
    mode: str
    profile: str
    next_frame_policy: str
    dispatch_action: str
    command_count: int
    active_command_count: int
    frame_count: int
    memory_layer_count: int
    applied_frame_budget_count: int
    applied_queue_budget_count: int
    applied_scheduler_mode_count: int
    memory_action_count: int
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    total_expected_memory_relief_mb: float
    frames: list[FrameControlState]
    memory_layers: list[MemoryControlState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "dispatch_action": self.dispatch_action,
            "command_count": self.command_count,
            "active_command_count": self.active_command_count,
            "frame_count": self.frame_count,
            "memory_layer_count": self.memory_layer_count,
            "applied_frame_budget_count": self.applied_frame_budget_count,
            "applied_queue_budget_count": self.applied_queue_budget_count,
            "applied_scheduler_mode_count": self.applied_scheduler_mode_count,
            "memory_action_count": self.memory_action_count,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "total_expected_memory_relief_mb": round(
                self.total_expected_memory_relief_mb, 4
            ),
            "frames": [frame.to_dict() for frame in self.frames],
            "memory_layers": [layer.to_dict() for layer in self.memory_layers],
        }


def apply_runtime_control_packet(packet: RuntimeControlPacket) -> RuntimeControlState:
    frames: dict[int, FrameControlState] = {}
    memory_layers: list[MemoryControlState] = []

    for command in packet.commands:
        if (
            command.domain in {"frame", "queue", "scheduler"}
            and command.frame is not None
        ):
            frames.setdefault(command.frame, FrameControlState(command.frame)).apply(
                command
            )
        elif command.domain == "memory" and command.memory is not None:
            memory_layers.append(memory_state_from_command(command))

    frame_states = [frames[key] for key in sorted(frames)]
    return RuntimeControlState(
        mode=CONTROL_STATE_MODE,
        profile=packet.profile,
        next_frame_policy=packet.next_frame_policy,
        dispatch_action=packet.dispatch_action,
        command_count=packet.command_count,
        active_command_count=packet.active_command_count,
        frame_count=len(frame_states),
        memory_layer_count=len(memory_layers),
        applied_frame_budget_count=count_domain(packet.commands, "frame"),
        applied_queue_budget_count=count_domain(packet.commands, "queue"),
        applied_scheduler_mode_count=count_domain(packet.commands, "scheduler"),
        memory_action_count=sum(1 for layer in memory_layers if layer.active),
        next_frame_budget_ms=packet.next_frame_budget_ms,
        hot_path_budget_ms=packet.hot_path_budget_ms,
        copy_queue_budget_ms=packet.copy_queue_budget_ms,
        pre_frame_window_ms=packet.pre_frame_window_ms,
        total_expected_memory_relief_mb=packet.total_expected_memory_relief_mb,
        frames=frame_states,
        memory_layers=memory_layers,
    )


def memory_state_from_command(command: RuntimeControlCommand) -> MemoryControlState:
    expected_relief_mb = 0.0
    reserve_headroom_mb = 0.0
    if command.command == "evict_or_defer_residency":
        expected_relief_mb = command.value_mb
    elif command.command == "reserve_memory_headroom":
        reserve_headroom_mb = command.value_mb
    return MemoryControlState(
        memory=command.memory or command.target,
        command=command.command,
        setting=command.setting,
        expected_relief_mb=expected_relief_mb,
        reserve_headroom_mb=reserve_headroom_mb,
        active=is_active(command),
        priority=command.priority,
        reason=command.reason,
    )


def count_domain(commands: list[RuntimeControlCommand], domain: str) -> int:
    return sum(1 for command in commands if command.domain == domain)


def stronger_priority(current: str, incoming: str) -> str:
    rank = {"low": 0, "normal": 1, "high": 2}
    return incoming if rank.get(incoming, 0) > rank.get(current, 0) else current
