from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state_accumulator import RuntimeStateAccumulator
from .state_transition import RuntimeStateTransition


SUPERVISOR_DIRECTIVE_MODE = "runtime-supervisor-directive-v0.43"


@dataclass(frozen=True)
class RuntimeSupervisorDirective:
    mode: str
    source_trend: str
    source_transition_action: str
    directive_action: str
    scheduler_posture: str
    admission_posture: str
    memory_posture: str
    frame_budget_posture: str
    guardband_posture: str
    escalation_level: int
    cooldown_cycles: int
    current_pressure_index: float
    pressure_delta: float
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    memory_relief_target_mb: float
    memory_headroom_target_mb: float
    confidence: str
    reason: str
    state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_trend": self.source_trend,
            "source_transition_action": self.source_transition_action,
            "directive_action": self.directive_action,
            "scheduler_posture": self.scheduler_posture,
            "admission_posture": self.admission_posture,
            "memory_posture": self.memory_posture,
            "frame_budget_posture": self.frame_budget_posture,
            "guardband_posture": self.guardband_posture,
            "escalation_level": self.escalation_level,
            "cooldown_cycles": self.cooldown_cycles,
            "current_pressure_index": round(self.current_pressure_index, 4),
            "pressure_delta": round(self.pressure_delta, 4),
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "memory_relief_target_mb": round(self.memory_relief_target_mb, 4),
            "memory_headroom_target_mb": round(self.memory_headroom_target_mb, 4),
            "confidence": self.confidence,
            "reason": self.reason,
            "state_digest": self.state_digest,
        }


def build_runtime_supervisor_directive(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> RuntimeSupervisorDirective:
    shape = directive_shape(state, transition)
    return RuntimeSupervisorDirective(
        mode=SUPERVISOR_DIRECTIVE_MODE,
        source_trend=transition.trend,
        source_transition_action=transition.transition_action,
        directive_action=shape["directive_action"],
        scheduler_posture=shape["scheduler_posture"],
        admission_posture=shape["admission_posture"],
        memory_posture=shape["memory_posture"],
        frame_budget_posture=shape["frame_budget_posture"],
        guardband_posture=shape["guardband_posture"],
        escalation_level=int(shape["escalation_level"]),
        cooldown_cycles=int(shape["cooldown_cycles"]),
        current_pressure_index=transition.current_pressure_index,
        pressure_delta=transition.pressure_delta,
        next_frame_budget_ms=supervised_frame_budget_ms(state, transition),
        hot_path_budget_ms=supervised_hot_path_budget_ms(state, transition),
        copy_queue_budget_ms=supervised_copy_queue_budget_ms(state, transition),
        pre_frame_window_ms=supervised_pre_frame_window_ms(state, transition),
        memory_relief_target_mb=supervised_memory_relief_target_mb(
            state,
            transition,
        ),
        memory_headroom_target_mb=state.memory_headroom_target_mb,
        confidence=transition.confidence,
        reason=shape["reason"],
        state_digest=state.state_digest,
    )


def directive_shape(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> dict[str, str | int]:
    if transition.trend == "baseline":
        return {
            "directive_action": "establish-supervisor-baseline",
            "scheduler_posture": "observe-runtime-cycle",
            "admission_posture": "observe-admission",
            "memory_posture": "observe-residency",
            "frame_budget_posture": "hold-current-budget",
            "guardband_posture": "record-guardband",
            "escalation_level": 0,
            "cooldown_cycles": 1,
            "reason": "First persisted state; supervisor should observe before changing posture.",
        }
    if transition.trend == "improving":
        if state.profile == "stable":
            return {
                "directive_action": "relax-supervisor-pressure",
                "scheduler_posture": "relax-to-stable-cycle",
                "admission_posture": "allow-budgeted-copy-queue",
                "memory_posture": "release-relief-watch",
                "frame_budget_posture": "restore-stable-budget",
                "guardband_posture": "decay-guardband",
                "escalation_level": 0,
                "cooldown_cycles": 2,
                "reason": "Pressure dropped and the state is stable enough to relax guarded pressure posture.",
            }
        return {
            "directive_action": "hold-recovery-supervision",
            "scheduler_posture": "hold-aggressive-recovery",
            "admission_posture": "keep-noncritical-deferred",
            "memory_posture": "continue-relief-watch",
            "frame_budget_posture": "hold-recovery-budget",
            "guardband_posture": "hold-guardband",
            "escalation_level": 1,
            "cooldown_cycles": 1,
            "reason": "Pressure dropped but the runtime is still aggressive, so recovery posture is retained.",
        }
    if transition.trend == "worsening":
        return {
            "directive_action": "escalate-supervisor-pressure",
            "scheduler_posture": "tighten-preframe-dispatch",
            "admission_posture": "block-noncritical-copy-queue",
            "memory_posture": "protect-residency-and-relief",
            "frame_budget_posture": "tighten-hot-path-budget",
            "guardband_posture": "increase-guardband",
            "escalation_level": 2,
            "cooldown_cycles": 0,
            "reason": "Pressure rose across persisted cycles; supervisor should tighten the next-cycle posture.",
        }
    if state.drift_risk == "low":
        return {
            "directive_action": "preserve-supervisor-state",
            "scheduler_posture": "preserve-stable-cycle",
            "admission_posture": "preserve-budgeted-admission",
            "memory_posture": "hold-residency",
            "frame_budget_posture": "preserve-budget",
            "guardband_posture": "preserve-guardband",
            "escalation_level": 0,
            "cooldown_cycles": 1,
            "reason": "Pressure is close to the previous state and drift risk is low.",
        }
    return {
        "directive_action": "monitor-supervisor-state",
        "scheduler_posture": "monitor-runtime-cycle",
        "admission_posture": "monitor-admission",
        "memory_posture": "monitor-residency",
        "frame_budget_posture": "hold-current-budget",
        "guardband_posture": "monitor-guardband",
        "escalation_level": 1,
        "cooldown_cycles": 0,
        "reason": "Pressure is close to the previous state but drift risk still needs supervision.",
    }


def supervised_frame_budget_ms(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> float:
    if transition.trend == "worsening":
        return max(0.0, min(state.next_frame_budget_ms, state.hot_path_budget_ms))
    return state.next_frame_budget_ms


def supervised_hot_path_budget_ms(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> float:
    if transition.trend == "worsening":
        return max(0.0, min(state.hot_path_budget_ms, state.next_frame_budget_ms))
    return state.hot_path_budget_ms


def supervised_copy_queue_budget_ms(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> float:
    if transition.trend == "worsening":
        return 0.0
    return state.copy_queue_budget_ms


def supervised_pre_frame_window_ms(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> float:
    if transition.trend == "worsening":
        return max(state.pre_frame_window_ms, state.hot_path_budget_ms * 0.75)
    return state.pre_frame_window_ms


def supervised_memory_relief_target_mb(
    state: RuntimeStateAccumulator,
    transition: RuntimeStateTransition,
) -> float:
    if transition.trend == "worsening":
        return max(state.memory_relief_target_mb, 0.0)
    if transition.trend == "improving" and state.profile == "stable":
        return 0.0
    return state.memory_relief_target_mb
