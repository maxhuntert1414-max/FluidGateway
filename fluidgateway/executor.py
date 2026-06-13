from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .packet import ExecutionCommand, ExecutionPacket


EXECUTION_SIMULATION_MODE = "runtime-execution-simulation-v0.26"


@dataclass(frozen=True)
class CommandExecutionResult:
    sequence: int
    operation_id: str
    action: str
    window: str
    frame: int | None
    status: str
    effect: str
    cost_ms: float
    saved_mb: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "operation_id": self.operation_id,
            "action": self.action,
            "window": self.window,
            "frame": self.frame,
            "status": self.status,
            "effect": self.effect,
            "cost_ms": round(self.cost_ms, 4),
            "saved_mb": round(self.saved_mb, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutionFrameResult:
    frame: int
    command_count: int
    applied_count: int
    ignored_count: int
    removed_cost_ms: float
    prestaged_cost_ms: float
    setup_cost_ms: float
    protected_hot_path_cost_ms: float
    hot_path_before_ms: float
    hot_path_after_ms: float
    hot_path_relief_ms: float
    estimated_saved_mb: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "command_count": self.command_count,
            "applied_count": self.applied_count,
            "ignored_count": self.ignored_count,
            "removed_cost_ms": round(self.removed_cost_ms, 4),
            "prestaged_cost_ms": round(self.prestaged_cost_ms, 4),
            "setup_cost_ms": round(self.setup_cost_ms, 4),
            "protected_hot_path_cost_ms": round(
                self.protected_hot_path_cost_ms, 4
            ),
            "hot_path_before_ms": round(self.hot_path_before_ms, 4),
            "hot_path_after_ms": round(self.hot_path_after_ms, 4),
            "hot_path_relief_ms": round(self.hot_path_relief_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
        }


@dataclass(frozen=True)
class ExecutionSimulation:
    mode: str
    command_count: int
    frame_count: int
    applied_count: int
    ignored_count: int
    removed_cost_ms: float
    prestaged_cost_ms: float
    setup_cost_ms: float
    protected_hot_path_cost_ms: float
    hot_path_before_ms: float
    hot_path_after_ms: float
    hot_path_relief_ms: float
    estimated_saved_mb: float
    frames: list[ExecutionFrameResult]
    command_results: list[CommandExecutionResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "command_count": self.command_count,
            "frame_count": self.frame_count,
            "applied_count": self.applied_count,
            "ignored_count": self.ignored_count,
            "removed_cost_ms": round(self.removed_cost_ms, 4),
            "prestaged_cost_ms": round(self.prestaged_cost_ms, 4),
            "setup_cost_ms": round(self.setup_cost_ms, 4),
            "protected_hot_path_cost_ms": round(
                self.protected_hot_path_cost_ms, 4
            ),
            "hot_path_before_ms": round(self.hot_path_before_ms, 4),
            "hot_path_after_ms": round(self.hot_path_after_ms, 4),
            "hot_path_relief_ms": round(self.hot_path_relief_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
            "frames": [frame.to_dict() for frame in self.frames],
            "command_results": [result.to_dict() for result in self.command_results],
        }


def simulate_execution(packet: ExecutionPacket) -> ExecutionSimulation:
    command_results = [
        simulate_command(command) for command in packet.commands
    ]
    frames = summarize_frames(command_results)
    return ExecutionSimulation(
        mode=EXECUTION_SIMULATION_MODE,
        command_count=len(command_results),
        frame_count=len(frames),
        applied_count=count_status(command_results, "applied"),
        ignored_count=count_status(command_results, "ignored"),
        removed_cost_ms=sum_frame_value(frames, "removed_cost_ms"),
        prestaged_cost_ms=sum_frame_value(frames, "prestaged_cost_ms"),
        setup_cost_ms=sum_frame_value(frames, "setup_cost_ms"),
        protected_hot_path_cost_ms=sum_frame_value(
            frames, "protected_hot_path_cost_ms"
        ),
        hot_path_before_ms=sum_frame_value(frames, "hot_path_before_ms"),
        hot_path_after_ms=sum_frame_value(frames, "hot_path_after_ms"),
        hot_path_relief_ms=sum_frame_value(frames, "hot_path_relief_ms"),
        estimated_saved_mb=sum_frame_value(frames, "estimated_saved_mb"),
        frames=frames,
        command_results=command_results,
    )


def simulate_command(command: ExecutionCommand) -> CommandExecutionResult:
    effect = effect_for_action(command.action)
    status = "ignored" if effect == "ignored" else "applied"
    return CommandExecutionResult(
        sequence=command.sequence,
        operation_id=command.operation_id,
        action=command.action,
        window=command.window,
        frame=command.frame,
        status=status,
        effect=effect,
        cost_ms=command.cost_ms,
        saved_mb=command.expected_saved_mb if effect == "removed" else 0.0,
        reason=command.reason,
    )


def effect_for_action(action: str) -> str:
    effects = {
        "skip_transfer": "removed",
        "reuse_allocation": "removed",
        "drop_sync_wait": "removed",
        "prestage_transfer": "prestaged",
        "pool_allocation": "setup",
        "execute_protected": "protected",
    }
    return effects.get(action, "ignored")


def summarize_frames(
    command_results: list[CommandExecutionResult],
) -> list[ExecutionFrameResult]:
    by_frame: dict[int, list[CommandExecutionResult]] = {}
    for result in command_results:
        if result.frame is not None:
            by_frame.setdefault(result.frame, []).append(result)

    frames: list[ExecutionFrameResult] = []
    for frame, results in sorted(by_frame.items()):
        removed = sum_cost(results, "removed")
        prestaged = sum_cost(results, "prestaged")
        setup = sum_cost(results, "setup")
        protected = sum_cost(results, "protected")
        before = removed + prestaged + setup + protected
        after = protected
        frames.append(
            ExecutionFrameResult(
                frame=frame,
                command_count=len(results),
                applied_count=count_status(results, "applied"),
                ignored_count=count_status(results, "ignored"),
                removed_cost_ms=removed,
                prestaged_cost_ms=prestaged,
                setup_cost_ms=setup,
                protected_hot_path_cost_ms=protected,
                hot_path_before_ms=before,
                hot_path_after_ms=after,
                hot_path_relief_ms=max(0.0, before - after),
                estimated_saved_mb=sum(result.saved_mb for result in results),
            )
        )
    return frames


def sum_cost(results: list[CommandExecutionResult], effect: str) -> float:
    return sum(result.cost_ms for result in results if result.effect == effect)


def count_status(results: list[CommandExecutionResult], status: str) -> int:
    return sum(1 for result in results if result.status == status)


def sum_frame_value(frames: list[ExecutionFrameResult], field: str) -> float:
    return sum(float(getattr(frame, field)) for frame in frames)
