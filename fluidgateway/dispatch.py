from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .arbiter import BudgetArbitrationPlan, CommandArbitration, MemoryArbitration
from .packet import ExecutionCommand, ExecutionPacket


DISPATCH_PLAN_MODE = "runtime-dispatch-plan-v0.30"

PHASE_ORDER = {
    "control": 0,
    "memory": 1,
    "setup": 2,
    "pre-frame": 3,
    "hot-path": 4,
    "next-frame": 5,
}


@dataclass(frozen=True)
class DispatchCommand:
    sequence: int
    phase_order: int
    phase: str
    command: str
    status: str
    source_decision: str
    operation_id: str | None
    memory: str | None
    frame: int | None
    target_resource_id: str | None
    path: str | None
    cost_ms: float
    value_mb: float
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "phase_order": self.phase_order,
            "phase": self.phase,
            "command": self.command,
            "status": self.status,
            "source_decision": self.source_decision,
            "operation_id": self.operation_id,
            "memory": self.memory,
            "frame": self.frame,
            "target_resource_id": self.target_resource_id,
            "path": self.path,
            "cost_ms": round(self.cost_ms, 4),
            "value_mb": round(self.value_mb, 4),
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class RuntimeDispatchPlan:
    mode: str
    profile: str
    next_frame_policy: str
    command_count: int
    control_count: int
    memory_count: int
    setup_count: int
    pre_frame_count: int
    hot_path_count: int
    next_frame_count: int
    dropped_count: int
    deferred_count: int
    total_cost_ms: float
    total_memory_pressure_mb: float
    commands: list[DispatchCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "command_count": self.command_count,
            "control_count": self.control_count,
            "memory_count": self.memory_count,
            "setup_count": self.setup_count,
            "pre_frame_count": self.pre_frame_count,
            "hot_path_count": self.hot_path_count,
            "next_frame_count": self.next_frame_count,
            "dropped_count": self.dropped_count,
            "deferred_count": self.deferred_count,
            "total_cost_ms": round(self.total_cost_ms, 4),
            "total_memory_pressure_mb": round(self.total_memory_pressure_mb, 4),
            "commands": [command.to_dict() for command in self.commands],
        }


def build_runtime_dispatch_plan(
    arbitration: BudgetArbitrationPlan,
    packet: ExecutionPacket,
) -> RuntimeDispatchPlan:
    packet_by_operation = {command.operation_id: command for command in packet.commands}
    commands = [
        dispatch
        for dispatch in (
            dispatch_from_arbitration(command, packet_by_operation)
            for command in arbitration.commands
        )
        if dispatch is not None
    ]
    commands.extend(
        dispatch_from_memory(action) for action in arbitration.memory_actions
    )
    commands = [
        DispatchCommand(sequence=index, **dispatch_payload(command))
        for index, command in enumerate(sort_dispatch(commands), start=1)
    ]
    return RuntimeDispatchPlan(
        mode=DISPATCH_PLAN_MODE,
        profile=arbitration.profile,
        next_frame_policy=arbitration.next_frame_policy,
        command_count=len(commands),
        control_count=count_phase(commands, "control"),
        memory_count=count_phase(commands, "memory"),
        setup_count=count_phase(commands, "setup"),
        pre_frame_count=count_phase(commands, "pre-frame"),
        hot_path_count=count_phase(commands, "hot-path"),
        next_frame_count=count_phase(commands, "next-frame"),
        dropped_count=count_status(commands, "dropped"),
        deferred_count=count_status(commands, "deferred"),
        total_cost_ms=sum(command.cost_ms for command in commands),
        total_memory_pressure_mb=sum(
            command.value_mb for command in commands if command.phase == "memory"
        ),
        commands=commands,
    )


def dispatch_from_arbitration(
    arbitration: CommandArbitration,
    packet_by_operation: dict[str, ExecutionCommand],
) -> DispatchCommand | None:
    packet_command = packet_by_operation.get(arbitration.operation_id)
    target_resource_id = packet_command.target_resource_id if packet_command else None
    path = packet_command.path if packet_command else None
    value_mb = packet_command.value_mb if packet_command else 0.0

    phase, command, status = dispatch_shape(arbitration)
    if phase is None:
        return None
    return DispatchCommand(
        sequence=0,
        phase_order=PHASE_ORDER[phase],
        phase=phase,
        command=command,
        status=status,
        source_decision=arbitration.decision,
        operation_id=arbitration.operation_id,
        memory=None,
        frame=arbitration.frame,
        target_resource_id=target_resource_id,
        path=path,
        cost_ms=arbitration.cost_ms,
        value_mb=value_mb,
        reason=arbitration.reason,
        expected_effect=arbitration.expected_effect,
    )


def dispatch_shape(
    arbitration: CommandArbitration,
) -> tuple[str | None, str, str]:
    if arbitration.decision == "drop-waste":
        return "control", "drop_operation", "dropped"
    if arbitration.decision == "prestage-before-frame":
        return "pre-frame", "prestage_operation", "scheduled"
    if arbitration.decision == "prepare-before-hot-path":
        return "setup", "prepare_operation", "scheduled"
    if arbitration.decision == "admit-hot-path":
        return "hot-path", "execute_operation", "scheduled"
    if arbitration.decision in {
        "split-or-defer-hot-path",
        "defer-pre-frame-overflow",
    }:
        return "next-frame", "defer_or_split_operation", "deferred"
    if arbitration.decision == "admit-current-path":
        return "hot-path", "execute_operation", "scheduled"
    return None, "ignore", "ignored"


def dispatch_from_memory(action: MemoryArbitration) -> DispatchCommand:
    command = (
        "evict_or_defer_residency"
        if action.decision == "evict-or-defer-residency"
        else "reserve_memory_headroom"
    )
    return DispatchCommand(
        sequence=0,
        phase_order=PHASE_ORDER["memory"],
        phase="memory",
        command=command,
        status="scheduled",
        source_decision=action.decision,
        operation_id=None,
        memory=action.memory,
        frame=None,
        target_resource_id=None,
        path=None,
        cost_ms=0.0,
        value_mb=action.pressure_mb,
        reason=action.reason,
        expected_effect=action.expected_effect,
    )


def sort_dispatch(commands: list[DispatchCommand]) -> list[DispatchCommand]:
    return sorted(
        commands,
        key=lambda command: (
            command.phase_order,
            command.frame if command.frame is not None else -1,
            command.operation_id or command.memory or "",
            command.command,
        ),
    )


def dispatch_payload(command: DispatchCommand) -> dict[str, Any]:
    payload = command.to_dict()
    payload.pop("sequence", None)
    return payload


def count_phase(commands: list[DispatchCommand], phase: str) -> int:
    return sum(1 for command in commands if command.phase == phase)


def count_status(commands: list[DispatchCommand], status: str) -> int:
    return sum(1 for command in commands if command.status == status)
