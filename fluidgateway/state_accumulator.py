from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .policy_update import FramePolicyUpdate, MemoryPolicyUpdate, RuntimePolicyUpdate


STATE_ACCUMULATOR_MODE = "runtime-state-accumulator-v0.40"


@dataclass(frozen=True)
class FrameAccumulatedState:
    frame: int
    action: str
    admission_policy: str
    scheduler_policy: str
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    guardband_ms: float
    cycle_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "action": self.action,
            "admission_policy": self.admission_policy,
            "scheduler_policy": self.scheduler_policy,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "guardband_ms": round(self.guardband_ms, 4),
            "cycle_count": self.cycle_count,
        }


@dataclass(frozen=True)
class MemoryAccumulatedState:
    action: str
    residency_policy: str
    relief_target_mb: float
    headroom_target_mb: float
    memory_delta_mb: float
    active: bool
    cycle_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "residency_policy": self.residency_policy,
            "relief_target_mb": round(self.relief_target_mb, 4),
            "headroom_target_mb": round(self.headroom_target_mb, 4),
            "memory_delta_mb": round(self.memory_delta_mb, 4),
            "active": self.active,
            "cycle_count": self.cycle_count,
        }


@dataclass(frozen=True)
class RuntimeStateAccumulator:
    mode: str
    profile: str
    policy_action: str
    convergence_status: str
    drift_risk: str
    cycle_count: int
    frame_state_count: int
    memory_state_count: int
    active_policy_count: int
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    memory_relief_target_mb: float
    memory_headroom_target_mb: float
    state_digest: str
    frames: list[FrameAccumulatedState]
    memory: list[MemoryAccumulatedState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "policy_action": self.policy_action,
            "convergence_status": self.convergence_status,
            "drift_risk": self.drift_risk,
            "cycle_count": self.cycle_count,
            "frame_state_count": self.frame_state_count,
            "memory_state_count": self.memory_state_count,
            "active_policy_count": self.active_policy_count,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "memory_relief_target_mb": round(self.memory_relief_target_mb, 4),
            "memory_headroom_target_mb": round(self.memory_headroom_target_mb, 4),
            "state_digest": self.state_digest,
            "frames": [frame.to_dict() for frame in self.frames],
            "memory": [memory.to_dict() for memory in self.memory],
        }


def build_runtime_state_accumulator(
    update: RuntimePolicyUpdate,
    previous: RuntimeStateAccumulator | None = None,
) -> RuntimeStateAccumulator:
    cycle_count = (previous.cycle_count + 1) if previous else 1
    frames = [
        build_frame_state(frame_update, previous, cycle_count)
        for frame_update in update.frame_updates
    ]
    memory = [
        build_memory_state(memory_update, previous, cycle_count)
        for memory_update in update.memory_updates
    ]
    return RuntimeStateAccumulator(
        mode=STATE_ACCUMULATOR_MODE,
        profile=update.next_profile,
        policy_action=update.policy_action,
        convergence_status=update.convergence_status,
        drift_risk=update.drift_risk,
        cycle_count=cycle_count,
        frame_state_count=len(frames),
        memory_state_count=len(memory),
        active_policy_count=update.active_update_count,
        next_frame_budget_ms=update.next_frame_budget_ms,
        hot_path_budget_ms=update.hot_path_budget_ms,
        copy_queue_budget_ms=update.copy_queue_budget_ms,
        pre_frame_window_ms=update.pre_frame_window_ms,
        memory_relief_target_mb=update.memory_relief_target_mb,
        memory_headroom_target_mb=update.memory_headroom_target_mb,
        state_digest=build_state_digest(update, cycle_count),
        frames=frames,
        memory=memory,
    )


def build_frame_state(
    update: FramePolicyUpdate,
    previous: RuntimeStateAccumulator | None,
    cycle_count: int,
) -> FrameAccumulatedState:
    previous_frame = None
    if previous is not None:
        previous_frame = next(
            (state for state in previous.frames if state.frame == update.frame),
            None,
        )
    return FrameAccumulatedState(
        frame=update.frame,
        action=update.action,
        admission_policy=update.admission_policy,
        scheduler_policy=update.scheduler_policy,
        next_frame_budget_ms=update.next_frame_budget_ms,
        hot_path_budget_ms=update.hot_path_budget_ms,
        copy_queue_budget_ms=update.copy_queue_budget_ms,
        pre_frame_window_ms=update.pre_frame_window_ms,
        guardband_ms=update.guardband_ms,
        cycle_count=(previous_frame.cycle_count + 1) if previous_frame else cycle_count,
    )


def build_memory_state(
    update: MemoryPolicyUpdate,
    previous: RuntimeStateAccumulator | None,
    cycle_count: int,
) -> MemoryAccumulatedState:
    previous_memory = previous.memory[0] if previous and previous.memory else None
    return MemoryAccumulatedState(
        action=update.action,
        residency_policy=update.residency_policy,
        relief_target_mb=update.relief_target_mb,
        headroom_target_mb=update.headroom_target_mb,
        memory_delta_mb=update.memory_delta_mb,
        active=update.action != "hold-memory-residency",
        cycle_count=(previous_memory.cycle_count + 1) if previous_memory else cycle_count,
    )


def build_state_digest(update: RuntimePolicyUpdate, cycle_count: int) -> str:
    return (
        f"profile:{update.next_profile}|"
        f"policy:{update.policy_action}|"
        f"frames:{update.frame_update_count}|"
        f"memory:{update.memory_relief_target_mb:.4f}:{update.memory_headroom_target_mb:.4f}|"
        f"cycle:{cycle_count}"
    )
