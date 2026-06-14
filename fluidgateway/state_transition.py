from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state_accumulator import RuntimeStateAccumulator


STATE_TRANSITION_MODE = "runtime-state-transition-v0.42"


@dataclass(frozen=True)
class RuntimeStateTransition:
    mode: str
    has_previous_state: bool
    previous_cycle_count: int | None
    current_cycle_count: int
    cycle_delta: int
    previous_pressure_index: float
    current_pressure_index: float
    pressure_delta: float
    profile_transition: str
    policy_transition: str
    convergence_transition: str
    drift_transition: str
    active_policy_delta: int
    frame_budget_delta_ms: float
    hot_path_budget_delta_ms: float
    copy_queue_budget_delta_ms: float
    pre_frame_window_delta_ms: float
    memory_relief_delta_mb: float
    memory_headroom_delta_mb: float
    trend: str
    transition_action: str
    confidence: str
    reason: str
    previous_state_digest: str | None
    current_state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "has_previous_state": self.has_previous_state,
            "previous_cycle_count": self.previous_cycle_count,
            "current_cycle_count": self.current_cycle_count,
            "cycle_delta": self.cycle_delta,
            "previous_pressure_index": round(self.previous_pressure_index, 4),
            "current_pressure_index": round(self.current_pressure_index, 4),
            "pressure_delta": round(self.pressure_delta, 4),
            "profile_transition": self.profile_transition,
            "policy_transition": self.policy_transition,
            "convergence_transition": self.convergence_transition,
            "drift_transition": self.drift_transition,
            "active_policy_delta": self.active_policy_delta,
            "frame_budget_delta_ms": round(self.frame_budget_delta_ms, 4),
            "hot_path_budget_delta_ms": round(self.hot_path_budget_delta_ms, 4),
            "copy_queue_budget_delta_ms": round(self.copy_queue_budget_delta_ms, 4),
            "pre_frame_window_delta_ms": round(self.pre_frame_window_delta_ms, 4),
            "memory_relief_delta_mb": round(self.memory_relief_delta_mb, 4),
            "memory_headroom_delta_mb": round(self.memory_headroom_delta_mb, 4),
            "trend": self.trend,
            "transition_action": self.transition_action,
            "confidence": self.confidence,
            "reason": self.reason,
            "previous_state_digest": self.previous_state_digest,
            "current_state_digest": self.current_state_digest,
        }


def build_runtime_state_transition(
    previous: RuntimeStateAccumulator | None,
    current: RuntimeStateAccumulator,
) -> RuntimeStateTransition:
    previous_index = pressure_index(previous) if previous is not None else 0.0
    current_index = pressure_index(current)
    pressure_delta = current_index - previous_index if previous is not None else 0.0
    trend = transition_trend(previous, pressure_delta)
    return RuntimeStateTransition(
        mode=STATE_TRANSITION_MODE,
        has_previous_state=previous is not None,
        previous_cycle_count=previous.cycle_count if previous is not None else None,
        current_cycle_count=current.cycle_count,
        cycle_delta=cycle_delta(previous, current),
        previous_pressure_index=previous_index,
        current_pressure_index=current_index,
        pressure_delta=pressure_delta,
        profile_transition=state_transition_value(previous, current, "profile"),
        policy_transition=state_transition_value(previous, current, "policy_action"),
        convergence_transition=state_transition_value(
            previous,
            current,
            "convergence_status",
        ),
        drift_transition=state_transition_value(previous, current, "drift_risk"),
        active_policy_delta=numeric_delta(previous, current, "active_policy_count"),
        frame_budget_delta_ms=numeric_delta(
            previous,
            current,
            "next_frame_budget_ms",
        ),
        hot_path_budget_delta_ms=numeric_delta(
            previous,
            current,
            "hot_path_budget_ms",
        ),
        copy_queue_budget_delta_ms=numeric_delta(
            previous,
            current,
            "copy_queue_budget_ms",
        ),
        pre_frame_window_delta_ms=numeric_delta(
            previous,
            current,
            "pre_frame_window_ms",
        ),
        memory_relief_delta_mb=numeric_delta(
            previous,
            current,
            "memory_relief_target_mb",
        ),
        memory_headroom_delta_mb=numeric_delta(
            previous,
            current,
            "memory_headroom_target_mb",
        ),
        trend=trend,
        transition_action=transition_action(current, trend),
        confidence=transition_confidence(previous, pressure_delta),
        reason=transition_reason(previous, pressure_delta, trend),
        previous_state_digest=previous.state_digest if previous is not None else None,
        current_state_digest=current.state_digest,
    )


def pressure_index(state: RuntimeStateAccumulator | None) -> float:
    if state is None:
        return 0.0
    index = 0.0
    if state.profile == "aggressive":
        index += 1.5
    if "pressure" in state.policy_action or "tighten" in state.policy_action:
        index += 2.0
    elif "preserve" in state.policy_action:
        index += 0.5
    if state.convergence_status == "diverging":
        index += 3.0
    elif state.convergence_status not in {"stable", "unknown"}:
        index += 2.0
    if state.drift_risk == "high":
        index += 3.0
    elif state.drift_risk == "medium":
        index += 1.5
    index += min(float(state.active_policy_count), 4.0) * 0.75
    index += min(max(state.memory_relief_target_mb, 0.0) / 20.0, 3.0)
    if state.copy_queue_budget_ms == 0.0 and state.active_policy_count > 0:
        index += 0.5
    return index


def transition_trend(
    previous: RuntimeStateAccumulator | None,
    pressure_delta: float,
) -> str:
    if previous is None:
        return "baseline"
    if pressure_delta <= -2.0:
        return "improving"
    if pressure_delta >= 2.0:
        return "worsening"
    return "stable"


def transition_action(current: RuntimeStateAccumulator, trend: str) -> str:
    if trend == "baseline":
        return "establish-runtime-baseline"
    if trend == "improving":
        if current.profile == "stable":
            return "relax-after-pressure-relief"
        return "hold-recovery-guardband"
    if trend == "worsening":
        return "tighten-after-pressure-regression"
    if current.drift_risk == "low":
        return "preserve-runtime-state"
    return "monitor-runtime-state"


def transition_confidence(
    previous: RuntimeStateAccumulator | None,
    pressure_delta: float,
) -> str:
    if previous is None:
        return "low"
    magnitude = abs(pressure_delta)
    if magnitude >= 4.0:
        return "high"
    if magnitude >= 2.0:
        return "medium"
    return "medium"


def transition_reason(
    previous: RuntimeStateAccumulator | None,
    pressure_delta: float,
    trend: str,
) -> str:
    if previous is None:
        return "No prior runtime state was provided, so this cycle becomes the baseline."
    if trend == "improving":
        return "The current cycle has a lower pressure index than the previous state."
    if trend == "worsening":
        return "The current cycle has a higher pressure index than the previous state."
    return "The current cycle pressure index is close to the previous state."


def cycle_delta(
    previous: RuntimeStateAccumulator | None,
    current: RuntimeStateAccumulator,
) -> int:
    if previous is None:
        return 0
    return current.cycle_count - previous.cycle_count


def state_transition_value(
    previous: RuntimeStateAccumulator | None,
    current: RuntimeStateAccumulator,
    field: str,
) -> str:
    current_value = str(getattr(current, field))
    if previous is None:
        return f"none->{current_value}"
    return f"{getattr(previous, field)}->{current_value}"


def numeric_delta(
    previous: RuntimeStateAccumulator | None,
    current: RuntimeStateAccumulator,
    field: str,
) -> float:
    if previous is None:
        return 0.0
    return float(getattr(current, field)) - float(getattr(previous, field))
