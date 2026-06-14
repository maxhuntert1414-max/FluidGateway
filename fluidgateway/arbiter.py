from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import FrameBudgetEnvelope, MemoryBudgetEnvelope, RuntimeBudgetEnvelope
from .packet import ExecutionCommand, ExecutionPacket


BUDGET_ARBITER_MODE = "runtime-budget-arbiter-v0.29"


@dataclass(frozen=True)
class CommandArbitration:
    sequence: int
    operation_id: str
    frame: int | None
    window: str
    action: str
    decision: str
    status: str
    cost_ms: float
    budget_used_ms: float
    budget_limit_ms: float
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "window": self.window,
            "action": self.action,
            "decision": self.decision,
            "status": self.status,
            "cost_ms": round(self.cost_ms, 4),
            "budget_used_ms": round(self.budget_used_ms, 4),
            "budget_limit_ms": round(self.budget_limit_ms, 4),
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class MemoryArbitration:
    memory: str
    decision: str
    status: str
    active_mb: float
    budget_mb: float | None
    pressure_mb: float
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory,
            "decision": self.decision,
            "status": self.status,
            "active_mb": round(self.active_mb, 4),
            "budget_mb": round(self.budget_mb, 4)
            if self.budget_mb is not None
            else None,
            "pressure_mb": round(self.pressure_mb, 4),
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class BudgetArbitrationPlan:
    mode: str
    profile: str
    next_frame_policy: str
    command_count: int
    admitted_count: int
    deferred_count: int
    dropped_count: int
    prestaged_count: int
    memory_action_count: int
    admitted_hot_path_cost_ms: float
    deferred_hot_path_cost_ms: float
    prestaged_cost_ms: float
    dropped_cost_ms: float
    total_memory_pressure_mb: float
    commands: list[CommandArbitration]
    memory_actions: list[MemoryArbitration]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "command_count": self.command_count,
            "admitted_count": self.admitted_count,
            "deferred_count": self.deferred_count,
            "dropped_count": self.dropped_count,
            "prestaged_count": self.prestaged_count,
            "memory_action_count": self.memory_action_count,
            "admitted_hot_path_cost_ms": round(self.admitted_hot_path_cost_ms, 4),
            "deferred_hot_path_cost_ms": round(self.deferred_hot_path_cost_ms, 4),
            "prestaged_cost_ms": round(self.prestaged_cost_ms, 4),
            "dropped_cost_ms": round(self.dropped_cost_ms, 4),
            "total_memory_pressure_mb": round(self.total_memory_pressure_mb, 4),
            "commands": [command.to_dict() for command in self.commands],
            "memory_actions": [action.to_dict() for action in self.memory_actions],
        }


def build_budget_arbitration(
    packet: ExecutionPacket,
    envelope: RuntimeBudgetEnvelope,
) -> BudgetArbitrationPlan:
    frames = {frame.frame: frame for frame in envelope.frames}
    hot_path_used: dict[int, float] = {}
    pre_frame_used: dict[int, float] = {}
    commands: list[CommandArbitration] = []

    for command in packet.commands:
        frame_envelope = frames.get(command.frame)
        arbitration = arbitrate_command(
            command,
            frame_envelope,
            hot_path_used,
            pre_frame_used,
        )
        commands.append(arbitration)

    memory_actions = [
        action
        for action in (
            arbitrate_memory_layer(layer) for layer in envelope.memory_layers
        )
        if action is not None
    ]
    return BudgetArbitrationPlan(
        mode=BUDGET_ARBITER_MODE,
        profile=envelope.profile,
        next_frame_policy=envelope.next_frame_policy,
        command_count=len(commands),
        admitted_count=count_status(commands, "admitted"),
        deferred_count=count_status(commands, "deferred"),
        dropped_count=count_status(commands, "dropped"),
        prestaged_count=count_status(commands, "prestaged"),
        memory_action_count=len(memory_actions),
        admitted_hot_path_cost_ms=sum_cost(commands, "admitted", "hot-path"),
        deferred_hot_path_cost_ms=sum_cost(commands, "deferred", "hot-path"),
        prestaged_cost_ms=sum_cost(commands, "prestaged", "pre-frame"),
        dropped_cost_ms=sum_cost(commands, "dropped", "never"),
        total_memory_pressure_mb=sum(action.pressure_mb for action in memory_actions),
        commands=commands,
        memory_actions=memory_actions,
    )


def arbitrate_command(
    command: ExecutionCommand,
    envelope: FrameBudgetEnvelope | None,
    hot_path_used: dict[int, float],
    pre_frame_used: dict[int, float],
) -> CommandArbitration:
    if command.window == "never":
        return command_arbitration(
            command,
            decision="drop-waste",
            status="dropped",
            used=0.0,
            limit=0.0,
            reason="The packet already classified this work as removable.",
            expected_effect="Keep redundant copies, allocations, and sync waits out of the runtime path.",
        )

    if command.window == "pre-frame":
        limit = envelope.pre_frame_window_ms if envelope else command.cost_ms
        used = pre_frame_used.get(command.frame or -1, 0.0) + command.cost_ms
        pre_frame_used[command.frame or -1] = used
        if used <= limit:
            return command_arbitration(
                command,
                decision="prestage-before-frame",
                status="prestaged",
                used=used,
                limit=limit,
                reason="The command fits in the pre-frame window.",
                expected_effect="Move predictable RAM/VRAM traffic before draw-critical work.",
            )
        return command_arbitration(
            command,
            decision="defer-pre-frame-overflow",
            status="deferred",
            used=used,
            limit=limit,
            reason="Pre-frame work exceeds the reserved budget window.",
            expected_effect="Keep the pre-frame queue from becoming the next source of stutter.",
        )

    if command.window == "setup":
        return command_arbitration(
            command,
            decision="prepare-before-hot-path",
            status="admitted",
            used=command.cost_ms,
            limit=envelope.max_hot_path_ms if envelope else command.cost_ms,
            reason="Setup work should happen before protected hot-path execution.",
            expected_effect="Reduce allocator and preparation pressure during the frame.",
        )

    if command.window == "hot-path":
        limit = envelope.max_hot_path_ms if envelope else command.cost_ms
        used = hot_path_used.get(command.frame or -1, 0.0) + command.cost_ms
        hot_path_used[command.frame or -1] = used
        if used <= limit:
            return command_arbitration(
                command,
                decision="admit-hot-path",
                status="admitted",
                used=used,
                limit=limit,
                reason="Protected work still fits inside the frame budget envelope.",
                expected_effect="Allow required draw/present work while earlier layers suppress waste.",
            )
        return command_arbitration(
            command,
            decision="split-or-defer-hot-path",
            status="deferred",
            used=used,
            limit=limit,
            reason="Protected hot-path work exceeds the frame budget envelope.",
            expected_effect="Force the next runtime layer to split, simplify, cache, or move work earlier.",
        )

    return command_arbitration(
        command,
        decision="admit-current-path",
        status="admitted",
        used=command.cost_ms,
        limit=envelope.max_hot_path_ms if envelope else command.cost_ms,
        reason="No specific budget rule matched this command window.",
        expected_effect="Preserve work while upstream policies improve precision.",
    )


def arbitrate_memory_layer(
    layer: MemoryBudgetEnvelope,
) -> MemoryArbitration | None:
    if layer.status == "over-budget":
        return MemoryArbitration(
            memory=layer.memory,
            decision="evict-or-defer-residency",
            status=layer.status,
            active_mb=layer.active_mb,
            budget_mb=layer.budget_mb,
            pressure_mb=layer.pressure_mb,
            reason="Active residency exceeds the configured memory budget.",
            expected_effect="Reduce RAM/VRAM pressure by evicting transient resources or deferring uploads.",
        )
    if layer.status == "near-budget":
        return MemoryArbitration(
            memory=layer.memory,
            decision="reserve-memory-headroom",
            status=layer.status,
            active_mb=layer.active_mb,
            budget_mb=layer.budget_mb,
            pressure_mb=layer.pressure_mb,
            reason="Active residency is close to the configured budget.",
            expected_effect="Avoid late eviction pressure when the next frame allocates or uploads.",
        )
    return None


def command_arbitration(
    command: ExecutionCommand,
    *,
    decision: str,
    status: str,
    used: float,
    limit: float,
    reason: str,
    expected_effect: str,
) -> CommandArbitration:
    return CommandArbitration(
        sequence=command.sequence,
        operation_id=command.operation_id,
        frame=command.frame,
        window=command.window,
        action=command.action,
        decision=decision,
        status=status,
        cost_ms=command.cost_ms,
        budget_used_ms=used,
        budget_limit_ms=limit,
        reason=reason,
        expected_effect=expected_effect,
    )


def count_status(commands: list[CommandArbitration], status: str) -> int:
    return sum(1 for command in commands if command.status == status)


def sum_cost(
    commands: list[CommandArbitration],
    status: str,
    window: str,
) -> float:
    return sum(
        command.cost_ms
        for command in commands
        if command.status == status and command.window == window
    )
