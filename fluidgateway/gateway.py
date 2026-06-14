from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control_state import FrameControlState, MemoryControlState, RuntimeControlState


GATEWAY_TICK_MODE = "runtime-gateway-tick-v0.36"


@dataclass(frozen=True)
class RuntimeGatewayStep:
    sequence: int
    domain: str
    lane: str
    action: str
    frame: int | None
    memory: str | None
    budget_ms: float
    budget_mb: float
    setting: str | None
    active: bool
    priority: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "domain": self.domain,
            "lane": self.lane,
            "action": self.action,
            "frame": self.frame,
            "memory": self.memory,
            "budget_ms": round(self.budget_ms, 4),
            "budget_mb": round(self.budget_mb, 4),
            "setting": self.setting,
            "active": self.active,
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeGatewayTick:
    mode: str
    profile: str
    tick_policy: str
    next_frame_policy: str
    dispatch_action: str
    step_count: int
    active_step_count: int
    frame_count: int
    memory_layer_count: int
    display_lane_step_count: int
    cpu_lane_step_count: int
    gpu_lane_step_count: int
    copy_queue_step_count: int
    scheduler_step_count: int
    memory_lane_step_count: int
    memory_active_step_count: int
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    memory_relief_target_mb: float
    steps: list[RuntimeGatewayStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "tick_policy": self.tick_policy,
            "next_frame_policy": self.next_frame_policy,
            "dispatch_action": self.dispatch_action,
            "step_count": self.step_count,
            "active_step_count": self.active_step_count,
            "frame_count": self.frame_count,
            "memory_layer_count": self.memory_layer_count,
            "display_lane_step_count": self.display_lane_step_count,
            "cpu_lane_step_count": self.cpu_lane_step_count,
            "gpu_lane_step_count": self.gpu_lane_step_count,
            "copy_queue_step_count": self.copy_queue_step_count,
            "scheduler_step_count": self.scheduler_step_count,
            "memory_lane_step_count": self.memory_lane_step_count,
            "memory_active_step_count": self.memory_active_step_count,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "memory_relief_target_mb": round(self.memory_relief_target_mb, 4),
            "steps": [step.to_dict() for step in self.steps],
        }


def build_runtime_gateway_tick(state: RuntimeControlState) -> RuntimeGatewayTick:
    steps: list[RuntimeGatewayStep] = []
    for frame in state.frames:
        steps.extend(frame_steps(frame))
    for layer in state.memory_layers:
        steps.append(memory_step(layer))
    sequenced_steps = [
        RuntimeGatewayStep(sequence=index, **step_payload(step))
        for index, step in enumerate(steps, start=1)
    ]
    return RuntimeGatewayTick(
        mode=GATEWAY_TICK_MODE,
        profile=state.profile,
        tick_policy=tick_policy(state),
        next_frame_policy=state.next_frame_policy,
        dispatch_action=state.dispatch_action,
        step_count=len(sequenced_steps),
        active_step_count=sum(1 for step in sequenced_steps if step.active),
        frame_count=state.frame_count,
        memory_layer_count=state.memory_layer_count,
        display_lane_step_count=count_lane(sequenced_steps, "display-frame"),
        cpu_lane_step_count=count_lane_prefix(sequenced_steps, "cpu-"),
        gpu_lane_step_count=count_lane(sequenced_steps, "gpu-hot-path"),
        copy_queue_step_count=count_lane(sequenced_steps, "copy-queue"),
        scheduler_step_count=count_lane(sequenced_steps, "scheduler"),
        memory_lane_step_count=count_lane_prefix(sequenced_steps, "memory:"),
        memory_active_step_count=sum(
            1
            for step in sequenced_steps
            if step.lane.startswith("memory:") and step.active
        ),
        next_frame_budget_ms=state.next_frame_budget_ms,
        hot_path_budget_ms=state.hot_path_budget_ms,
        copy_queue_budget_ms=state.copy_queue_budget_ms,
        pre_frame_window_ms=state.pre_frame_window_ms,
        memory_relief_target_mb=state.total_expected_memory_relief_mb,
        steps=sequenced_steps,
    )


def frame_steps(frame: FrameControlState) -> list[RuntimeGatewayStep]:
    reason = "Apply consolidated frame control state in the next gateway tick."
    return [
        RuntimeGatewayStep(
            sequence=0,
            domain="frame",
            lane="display-frame",
            action="protect_next_frame_budget",
            frame=frame.frame,
            memory=None,
            budget_ms=frame.next_frame_budget_ms,
            budget_mb=0.0,
            setting=None,
            active=True,
            priority=frame.priority,
            reason=reason,
        ),
        RuntimeGatewayStep(
            sequence=0,
            domain="frame",
            lane="gpu-hot-path",
            action="protect_gpu_hot_path",
            frame=frame.frame,
            memory=None,
            budget_ms=frame.hot_path_budget_ms,
            budget_mb=0.0,
            setting=None,
            active=True,
            priority=frame.priority,
            reason=reason,
        ),
        RuntimeGatewayStep(
            sequence=0,
            domain="queue",
            lane="copy-queue",
            action=copy_queue_action(frame),
            frame=frame.frame,
            memory=None,
            budget_ms=frame.copy_queue_budget_ms,
            budget_mb=0.0,
            setting=None,
            active=True,
            priority=frame.priority,
            reason=reason,
        ),
        RuntimeGatewayStep(
            sequence=0,
            domain="queue",
            lane="cpu-pre-frame",
            action="reserve_pre_frame_window",
            frame=frame.frame,
            memory=None,
            budget_ms=frame.pre_frame_window_ms,
            budget_mb=0.0,
            setting=None,
            active=True,
            priority=frame.priority,
            reason=reason,
        ),
        RuntimeGatewayStep(
            sequence=0,
            domain="scheduler",
            lane="cpu-admission",
            action="apply_admission_mode",
            frame=frame.frame,
            memory=None,
            budget_ms=0.0,
            budget_mb=0.0,
            setting=frame.admission_mode,
            active=True,
            priority=frame.priority,
            reason=reason,
        ),
        RuntimeGatewayStep(
            sequence=0,
            domain="scheduler",
            lane="scheduler",
            action="apply_scheduler_mode",
            frame=frame.frame,
            memory=None,
            budget_ms=0.0,
            budget_mb=0.0,
            setting=frame.scheduler_mode,
            active=True,
            priority=frame.priority,
            reason=reason,
        ),
    ]


def memory_step(layer: MemoryControlState) -> RuntimeGatewayStep:
    return RuntimeGatewayStep(
        sequence=0,
        domain="memory",
        lane=f"memory:{layer.memory}",
        action=memory_action(layer),
        frame=None,
        memory=layer.memory,
        budget_ms=0.0,
        budget_mb=memory_budget_mb(layer),
        setting=layer.setting,
        active=layer.active,
        priority=layer.priority,
        reason=layer.reason,
    )


def tick_policy(state: RuntimeControlState) -> str:
    if state.profile == "aggressive" or state.memory_action_count > 0:
        return "closed-loop-pressure-management"
    if state.profile == "stable":
        return "stable-budget-guard"
    return "observe-only"


def copy_queue_action(frame: FrameControlState) -> str:
    if frame.copy_queue_budget_ms <= 0.0:
        return "block_late_copy_queue"
    return "budget_copy_queue"


def memory_action(layer: MemoryControlState) -> str:
    if layer.command == "evict_or_defer_residency":
        return "relieve_memory_residency"
    if layer.command == "reserve_memory_headroom":
        return "reserve_memory_headroom"
    if layer.command == "hold_residency":
        return "hold_memory_residency"
    return "observe_memory_residency"


def memory_budget_mb(layer: MemoryControlState) -> float:
    return max(layer.expected_relief_mb, layer.reserve_headroom_mb)


def count_lane(steps: list[RuntimeGatewayStep], lane: str) -> int:
    return sum(1 for step in steps if step.lane == lane)


def count_lane_prefix(steps: list[RuntimeGatewayStep], prefix: str) -> int:
    return sum(1 for step in steps if step.lane.startswith(prefix))


def step_payload(step: RuntimeGatewayStep) -> dict[str, Any]:
    payload = step.to_dict()
    payload.pop("sequence", None)
    return payload
