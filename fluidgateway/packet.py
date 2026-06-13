from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .windowing import FrameWindowPlan, FrameWindowSlot


EXECUTION_PACKET_MODE = "runtime-execution-packet-v0.25"


@dataclass(frozen=True)
class ExecutionCommand:
    sequence: int
    action: str
    window: str
    phase: str
    operation_id: str
    frame: int | None
    path: str
    target_resource_id: str | None
    value_mb: float
    expected_saved_ms: float
    expected_saved_mb: float
    source_directive: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "action": self.action,
            "window": self.window,
            "phase": self.phase,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "path": self.path,
            "target_resource_id": self.target_resource_id,
            "value_mb": round(self.value_mb, 4),
            "expected_saved_ms": round(self.expected_saved_ms, 4),
            "expected_saved_mb": round(self.expected_saved_mb, 4),
            "source_directive": self.source_directive,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutionFrameSummary:
    frame: int
    command_count: int
    skip_count: int
    pre_frame_count: int
    setup_count: int
    hot_path_count: int
    post_present_count: int
    estimated_saved_ms: float
    estimated_saved_mb: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "command_count": self.command_count,
            "skip_count": self.skip_count,
            "pre_frame_count": self.pre_frame_count,
            "setup_count": self.setup_count,
            "hot_path_count": self.hot_path_count,
            "post_present_count": self.post_present_count,
            "estimated_saved_ms": round(self.estimated_saved_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
        }


@dataclass(frozen=True)
class ExecutionPacket:
    mode: str
    command_count: int
    frame_count: int
    skip_count: int
    pre_frame_count: int
    setup_count: int
    hot_path_count: int
    post_present_count: int
    estimated_hot_path_relief_ms: float
    estimated_saved_mb: float
    frames: list[ExecutionFrameSummary]
    commands: list[ExecutionCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "command_count": self.command_count,
            "frame_count": self.frame_count,
            "skip_count": self.skip_count,
            "pre_frame_count": self.pre_frame_count,
            "setup_count": self.setup_count,
            "hot_path_count": self.hot_path_count,
            "post_present_count": self.post_present_count,
            "estimated_hot_path_relief_ms": round(
                self.estimated_hot_path_relief_ms, 4
            ),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
            "frames": [frame.to_dict() for frame in self.frames],
            "commands": [command.to_dict() for command in self.commands],
        }


def build_execution_packet(window_plan: FrameWindowPlan) -> ExecutionPacket:
    commands = [
        command_from_slot(index, slot)
        for index, slot in enumerate(window_plan.slots, start=1)
    ]
    return ExecutionPacket(
        mode=EXECUTION_PACKET_MODE,
        command_count=len(commands),
        frame_count=len(
            {command.frame for command in commands if command.frame is not None}
        ),
        skip_count=count_window(commands, "never"),
        pre_frame_count=count_window(commands, "pre-frame"),
        setup_count=count_window(commands, "setup"),
        hot_path_count=count_window(commands, "hot-path"),
        post_present_count=count_window(commands, "post-present"),
        estimated_hot_path_relief_ms=sum(
            command.expected_saved_ms for command in commands
        ),
        estimated_saved_mb=sum(command.expected_saved_mb for command in commands),
        frames=summarize_frames(commands),
        commands=commands,
    )


def command_from_slot(sequence: int, slot: FrameWindowSlot) -> ExecutionCommand:
    return ExecutionCommand(
        sequence=sequence,
        action=action_for_slot(slot),
        window=slot.window,
        phase=slot.phase,
        operation_id=slot.operation_id,
        frame=slot.frame,
        path=slot.path,
        target_resource_id=slot.target_resource_id,
        value_mb=slot.value_mb,
        expected_saved_ms=slot.expected_saved_ms,
        expected_saved_mb=slot.expected_saved_mb,
        source_directive=slot.directive,
        reason=slot.rationale,
    )


def action_for_slot(slot: FrameWindowSlot) -> str:
    actions = {
        "suppress": "skip_transfer",
        "reuse": "reuse_allocation",
        "remove-sync": "drop_sync_wait",
        "prefetch": "prestage_transfer",
        "pool": "pool_allocation",
        "present": "execute_protected",
    }
    return actions.get(slot.phase, "execute")


def summarize_frames(commands: list[ExecutionCommand]) -> list[ExecutionFrameSummary]:
    frames: dict[int, list[ExecutionCommand]] = {}
    for command in commands:
        if command.frame is not None:
            frames.setdefault(command.frame, []).append(command)

    summaries: list[ExecutionFrameSummary] = []
    for frame, frame_commands in sorted(frames.items()):
        summaries.append(
            ExecutionFrameSummary(
                frame=frame,
                command_count=len(frame_commands),
                skip_count=count_window(frame_commands, "never"),
                pre_frame_count=count_window(frame_commands, "pre-frame"),
                setup_count=count_window(frame_commands, "setup"),
                hot_path_count=count_window(frame_commands, "hot-path"),
                post_present_count=count_window(frame_commands, "post-present"),
                estimated_saved_ms=sum(
                    command.expected_saved_ms for command in frame_commands
                ),
                estimated_saved_mb=sum(
                    command.expected_saved_mb for command in frame_commands
                ),
            )
        )
    return summaries


def count_window(commands: list[ExecutionCommand], window: str) -> int:
    return sum(1 for command in commands if command.window == window)
