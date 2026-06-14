from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import FrameBudgetEnvelope, MemoryBudgetEnvelope, RuntimeBudgetEnvelope
from .calibration import FrameCalibration, RuntimeCalibrationReport


MANAGER_DIRECTIVE_MODE = "runtime-manager-directive-v0.33"


@dataclass(frozen=True)
class FrameManagerDirective:
    frame: int
    target_frame_ms: float
    observed_frame_cost_ms: float
    planned_current_frame_cost_ms: float
    expected_frame_relief_ms: float
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    guardband_ms: float
    admission_mode: str
    scheduler_mode: str
    queue_policy: str
    calibration_action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "observed_frame_cost_ms": round(self.observed_frame_cost_ms, 4),
            "planned_current_frame_cost_ms": round(
                self.planned_current_frame_cost_ms, 4
            ),
            "expected_frame_relief_ms": round(self.expected_frame_relief_ms, 4),
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "guardband_ms": round(self.guardband_ms, 4),
            "admission_mode": self.admission_mode,
            "scheduler_mode": self.scheduler_mode,
            "queue_policy": self.queue_policy,
            "calibration_action": self.calibration_action,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MemoryManagerDirective:
    memory: str
    active_mb: float
    budget_mb: float | None
    pressure_mb: float
    status: str
    action: str
    expected_relief_mb: float
    reserve_headroom_mb: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory,
            "active_mb": round(self.active_mb, 4),
            "budget_mb": rounded_or_none(self.budget_mb),
            "pressure_mb": round(self.pressure_mb, 4),
            "status": self.status,
            "action": self.action,
            "expected_relief_mb": round(self.expected_relief_mb, 4),
            "reserve_headroom_mb": round(self.reserve_headroom_mb, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeManagerDirective:
    mode: str
    profile: str
    next_frame_policy: str
    dispatch_action: str
    frame_count: int
    memory_layer_count: int
    memory_action_count: int
    control_action_count: int
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    total_expected_memory_relief_mb: float
    frames: list[FrameManagerDirective]
    memory_directives: list[MemoryManagerDirective]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "dispatch_action": self.dispatch_action,
            "frame_count": self.frame_count,
            "memory_layer_count": self.memory_layer_count,
            "memory_action_count": self.memory_action_count,
            "control_action_count": self.control_action_count,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "total_expected_memory_relief_mb": round(
                self.total_expected_memory_relief_mb, 4
            ),
            "frames": [frame.to_dict() for frame in self.frames],
            "memory_directives": [
                directive.to_dict() for directive in self.memory_directives
            ],
        }


def build_runtime_manager_directive(
    calibration: RuntimeCalibrationReport,
    budget_envelope: RuntimeBudgetEnvelope,
) -> RuntimeManagerDirective:
    frame_envelopes = {frame.frame: frame for frame in budget_envelope.frames}
    frames = [
        build_frame_directive(frame, frame_envelopes.get(frame.frame))
        for frame in calibration.frames
    ]
    memory_directives = [
        build_memory_directive(layer) for layer in budget_envelope.memory_layers
    ]
    memory_action_count = sum(
        1
        for directive in memory_directives
        if directive.action not in {"hold-residency", "observe-residency"}
    )
    frame_action_count = sum(
        1 for frame in frames if frame.calibration_action != "monitor"
    )
    return RuntimeManagerDirective(
        mode=MANAGER_DIRECTIVE_MODE,
        profile=budget_envelope.profile,
        next_frame_policy=budget_envelope.next_frame_policy,
        dispatch_action=dispatch_action(calibration.frames),
        frame_count=len(frames),
        memory_layer_count=len(memory_directives),
        memory_action_count=memory_action_count,
        control_action_count=frame_action_count + memory_action_count,
        next_frame_budget_ms=min_value(frames, "next_frame_budget_ms"),
        hot_path_budget_ms=min_value(frames, "hot_path_budget_ms"),
        copy_queue_budget_ms=min_value(frames, "copy_queue_budget_ms"),
        pre_frame_window_ms=max_value(frames, "pre_frame_window_ms"),
        total_expected_memory_relief_mb=sum(
            directive.expected_relief_mb for directive in memory_directives
        ),
        frames=frames,
        memory_directives=memory_directives,
    )


def build_frame_directive(
    calibration: FrameCalibration,
    envelope: FrameBudgetEnvelope | None,
) -> FrameManagerDirective:
    next_budget = calibration.recommended_next_frame_budget_ms
    max_hot_path = envelope.max_hot_path_ms if envelope else calibration.target_frame_ms
    copy_budget = envelope.copy_queue_budget_ms if envelope else 0.0
    if calibration.action in {
        "apply-dispatch-before-next-frame",
        "tighten-dispatch-guardband",
    }:
        copy_budget = 0.0
    pre_frame_window = max(
        envelope.pre_frame_window_ms if envelope else 0.0,
        calibration.planned_pre_frame_cost_ms,
    )
    return FrameManagerDirective(
        frame=calibration.frame,
        target_frame_ms=calibration.target_frame_ms,
        observed_frame_cost_ms=calibration.observed_frame_cost_ms,
        planned_current_frame_cost_ms=calibration.planned_current_frame_cost_ms,
        expected_frame_relief_ms=calibration.planned_frame_relief_ms,
        next_frame_budget_ms=next_budget,
        hot_path_budget_ms=min(max_hot_path, next_budget),
        copy_queue_budget_ms=copy_budget,
        pre_frame_window_ms=pre_frame_window,
        guardband_ms=calibration.guardband_ms,
        admission_mode=admission_mode(calibration),
        scheduler_mode=scheduler_mode(calibration),
        queue_policy=queue_policy(copy_budget),
        calibration_action=calibration.action,
        reason=frame_reason(calibration),
    )


def build_memory_directive(layer: MemoryBudgetEnvelope) -> MemoryManagerDirective:
    if layer.status == "over-budget":
        return MemoryManagerDirective(
            memory=layer.memory,
            active_mb=layer.active_mb,
            budget_mb=layer.budget_mb,
            pressure_mb=layer.pressure_mb,
            status=layer.status,
            action="evict-or-defer-residency",
            expected_relief_mb=layer.pressure_mb,
            reserve_headroom_mb=0.0,
            reason="Active residency exceeds the configured memory budget.",
        )
    if layer.status == "near-budget":
        return MemoryManagerDirective(
            memory=layer.memory,
            active_mb=layer.active_mb,
            budget_mb=layer.budget_mb,
            pressure_mb=layer.pressure_mb,
            status=layer.status,
            action="reserve-headroom",
            expected_relief_mb=0.0,
            reserve_headroom_mb=max(0.0, (layer.budget_mb or 0.0) * 0.15),
            reason="Active residency is close to the configured memory budget.",
        )
    if layer.status == "unbounded":
        action = "observe-residency"
        reason = "No configured budget exists for this memory layer."
    else:
        action = "hold-residency"
        reason = "Active residency is inside the configured memory budget."
    return MemoryManagerDirective(
        memory=layer.memory,
        active_mb=layer.active_mb,
        budget_mb=layer.budget_mb,
        pressure_mb=layer.pressure_mb,
        status=layer.status,
        action=action,
        expected_relief_mb=0.0,
        reserve_headroom_mb=0.0,
        reason=reason,
    )


def admission_mode(calibration: FrameCalibration) -> str:
    if calibration.planned_pressure_status == "over-budget":
        return "tighten-hot-path-admission"
    if calibration.observed_pressure_status == "over-budget":
        return "prestage-and-defer-noncritical"
    if calibration.action == "preserve-dispatch-shape":
        return "preserve-budgeted-hot-path"
    return "observe-admission"


def scheduler_mode(calibration: FrameCalibration) -> str:
    if calibration.action == "tighten-dispatch-guardband":
        return "guardband-tightening"
    if calibration.action == "apply-dispatch-before-next-frame":
        return "closed-loop-aggressive"
    if calibration.action == "preserve-dispatch-shape":
        return "closed-loop-stable"
    return "observe"


def queue_policy(copy_queue_budget_ms: float) -> str:
    if copy_queue_budget_ms <= 0.0:
        return "block-late-copy-queue"
    return "budget-copy-queue"


def dispatch_action(frames: list[FrameCalibration]) -> str:
    actions = {frame.action for frame in frames}
    if "tighten-dispatch-guardband" in actions:
        return "tighten-dispatch-guardband"
    if "apply-dispatch-before-next-frame" in actions:
        return "activate-dispatch-profile"
    if "preserve-dispatch-shape" in actions:
        return "preserve-dispatch-profile"
    return "monitor-runtime"


def frame_reason(calibration: FrameCalibration) -> str:
    if calibration.action == "apply-dispatch-before-next-frame":
        return "Observed frame pressure can be relieved by the planned dispatch shape."
    if calibration.action == "tighten-dispatch-guardband":
        return "Planned current-frame work still exceeds the target budget."
    if calibration.action == "preserve-dispatch-shape":
        return "Observed work fits the frame while dispatch keeps useful relief."
    return "No stronger manager action is supported by the current evidence."


def min_value(frames: list[FrameManagerDirective], field: str) -> float:
    return min((float(getattr(frame, field)) for frame in frames), default=0.0)


def max_value(frames: list[FrameManagerDirective], field: str) -> float:
    return max((float(getattr(frame, field)) for frame in frames), default=0.0)


def rounded_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)
