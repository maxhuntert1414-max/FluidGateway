from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .calibration import FrameCalibration, RuntimeCalibrationReport
from .gateway_cycle import RuntimeGatewayCycleReport, RuntimeGatewayStepResult


GATEWAY_FEEDBACK_MODE = "runtime-gateway-feedback-delta-v0.38"


@dataclass(frozen=True)
class RuntimeGatewayFrameFeedback:
    frame: int
    target_frame_ms: float
    observed_frame_cost_ms: float
    planned_current_frame_cost_ms: float
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    observed_over_budget_ms: float
    planned_over_budget_ms: float
    protected_gap_ms: float
    planned_frame_relief_ms: float
    feedback_action: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "observed_frame_cost_ms": round(self.observed_frame_cost_ms, 4),
            "planned_current_frame_cost_ms": round(
                self.planned_current_frame_cost_ms, 4
            ),
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "observed_over_budget_ms": round(self.observed_over_budget_ms, 4),
            "planned_over_budget_ms": round(self.planned_over_budget_ms, 4),
            "protected_gap_ms": round(self.protected_gap_ms, 4),
            "planned_frame_relief_ms": round(self.planned_frame_relief_ms, 4),
            "feedback_action": self.feedback_action,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RuntimeGatewayFeedbackDelta:
    mode: str
    profile: str
    feedback_action: str
    convergence_status: str
    drift_risk: str
    confidence: str
    frame_count: int
    memory_layer_count: int
    pressure_frame_count: int
    protected_gap_frame_count: int
    observed_frame_cost_ms: float
    target_frame_budget_ms: float
    planned_current_frame_cost_ms: float
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    observed_over_budget_ms: float
    planned_over_budget_ms: float
    protected_gap_ms: float
    planned_frame_relief_ms: float
    memory_relief_expected_mb: float
    memory_relief_applied_mb: float
    memory_headroom_reserved_mb: float
    memory_delta_mb: float
    next_cycle_action: str
    frame_feedbacks: list[RuntimeGatewayFrameFeedback]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "feedback_action": self.feedback_action,
            "convergence_status": self.convergence_status,
            "drift_risk": self.drift_risk,
            "confidence": self.confidence,
            "frame_count": self.frame_count,
            "memory_layer_count": self.memory_layer_count,
            "pressure_frame_count": self.pressure_frame_count,
            "protected_gap_frame_count": self.protected_gap_frame_count,
            "observed_frame_cost_ms": round(self.observed_frame_cost_ms, 4),
            "target_frame_budget_ms": round(self.target_frame_budget_ms, 4),
            "planned_current_frame_cost_ms": round(
                self.planned_current_frame_cost_ms, 4
            ),
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "observed_over_budget_ms": round(self.observed_over_budget_ms, 4),
            "planned_over_budget_ms": round(self.planned_over_budget_ms, 4),
            "protected_gap_ms": round(self.protected_gap_ms, 4),
            "planned_frame_relief_ms": round(self.planned_frame_relief_ms, 4),
            "memory_relief_expected_mb": round(self.memory_relief_expected_mb, 4),
            "memory_relief_applied_mb": round(self.memory_relief_applied_mb, 4),
            "memory_headroom_reserved_mb": round(
                self.memory_headroom_reserved_mb, 4
            ),
            "memory_delta_mb": round(self.memory_delta_mb, 4),
            "next_cycle_action": self.next_cycle_action,
            "frame_feedbacks": [
                feedback.to_dict() for feedback in self.frame_feedbacks
            ],
        }


def build_runtime_gateway_feedback(
    cycle: RuntimeGatewayCycleReport,
    calibration: RuntimeCalibrationReport,
) -> RuntimeGatewayFeedbackDelta:
    frame_feedbacks = [
        frame_feedback(frame, cycle.step_results)
        for frame in calibration.frames
    ]
    observed_over = sum(feedback.observed_over_budget_ms for feedback in frame_feedbacks)
    planned_over = sum(feedback.planned_over_budget_ms for feedback in frame_feedbacks)
    protected_gap = sum(feedback.protected_gap_ms for feedback in frame_feedbacks)
    memory_delta = cycle.memory_relief_applied_mb - calibration.total_memory_relief_mb
    return RuntimeGatewayFeedbackDelta(
        mode=GATEWAY_FEEDBACK_MODE,
        profile=cycle.profile,
        feedback_action=feedback_action(cycle, frame_feedbacks),
        convergence_status=convergence_status(cycle, frame_feedbacks),
        drift_risk=cycle.drift_risk,
        confidence=feedback_confidence(cycle, calibration),
        frame_count=calibration.frame_count,
        memory_layer_count=cycle.memory_layer_count,
        pressure_frame_count=sum(
            1 for feedback in frame_feedbacks if feedback.observed_over_budget_ms > 0.0
        ),
        protected_gap_frame_count=sum(
            1 for feedback in frame_feedbacks if feedback.protected_gap_ms > 0.0
        ),
        observed_frame_cost_ms=calibration.total_observed_frame_cost_ms,
        target_frame_budget_ms=sum(
            feedback.target_frame_ms for feedback in frame_feedbacks
        ),
        planned_current_frame_cost_ms=calibration.total_planned_current_frame_cost_ms,
        next_frame_budget_ms=sum(
            feedback.next_frame_budget_ms for feedback in frame_feedbacks
        ),
        hot_path_budget_ms=sum(
            feedback.hot_path_budget_ms for feedback in frame_feedbacks
        ),
        observed_over_budget_ms=observed_over,
        planned_over_budget_ms=planned_over,
        protected_gap_ms=protected_gap,
        planned_frame_relief_ms=calibration.total_planned_frame_relief_ms,
        memory_relief_expected_mb=calibration.total_memory_relief_mb,
        memory_relief_applied_mb=cycle.memory_relief_applied_mb,
        memory_headroom_reserved_mb=cycle.memory_headroom_reserved_mb,
        memory_delta_mb=memory_delta,
        next_cycle_action=cycle.next_cycle_action,
        frame_feedbacks=frame_feedbacks,
    )


def frame_feedback(
    frame: FrameCalibration,
    step_results: list[RuntimeGatewayStepResult],
) -> RuntimeGatewayFrameFeedback:
    next_budget = frame_step_budget(
        frame.frame,
        step_results,
        "protect_next_frame_budget",
    )
    hot_path_budget = frame_step_budget(
        frame.frame,
        step_results,
        "protect_gpu_hot_path",
    )
    observed_over = max(0.0, frame.observed_frame_cost_ms - frame.target_frame_ms)
    planned_over = max(
        0.0, frame.planned_current_frame_cost_ms - frame.target_frame_ms
    )
    protected_gap = max(0.0, frame.observed_frame_cost_ms - next_budget)
    return RuntimeGatewayFrameFeedback(
        frame=frame.frame,
        target_frame_ms=frame.target_frame_ms,
        observed_frame_cost_ms=frame.observed_frame_cost_ms,
        planned_current_frame_cost_ms=frame.planned_current_frame_cost_ms,
        next_frame_budget_ms=next_budget,
        hot_path_budget_ms=hot_path_budget,
        observed_over_budget_ms=observed_over,
        planned_over_budget_ms=planned_over,
        protected_gap_ms=protected_gap,
        planned_frame_relief_ms=frame.planned_frame_relief_ms,
        feedback_action=frame_feedback_action(
            observed_over,
            planned_over,
            protected_gap,
            frame.planned_frame_relief_ms,
        ),
        confidence=frame.confidence,
    )


def frame_step_budget(
    frame: int,
    step_results: list[RuntimeGatewayStepResult],
    action: str,
) -> float:
    return sum(
        result.protected_budget_ms
        for result in step_results
        if result.frame == frame and result.action == action
    )


def frame_feedback_action(
    observed_over_budget_ms: float,
    planned_over_budget_ms: float,
    protected_gap_ms: float,
    planned_frame_relief_ms: float,
) -> str:
    if planned_over_budget_ms > 0.0:
        return "tighten-cycle-guardband"
    if observed_over_budget_ms > 0.0 or protected_gap_ms > 0.0:
        return "continue-pressure-management"
    if planned_frame_relief_ms > 0.0:
        return "preserve-cycle-shape"
    return "monitor-cycle"


def feedback_action(
    cycle: RuntimeGatewayCycleReport,
    frame_feedbacks: list[RuntimeGatewayFrameFeedback],
) -> str:
    actions = {feedback.feedback_action for feedback in frame_feedbacks}
    if "tighten-cycle-guardband" in actions:
        return "tighten-cycle-guardband"
    if "continue-pressure-management" in actions:
        return "continue-pressure-management"
    if cycle.next_cycle_action == "monitor-headroom":
        return "monitor-headroom"
    if "preserve-cycle-shape" in actions:
        return "preserve-cycle-shape"
    return "maintain-cycle"


def convergence_status(
    cycle: RuntimeGatewayCycleReport,
    frame_feedbacks: list[RuntimeGatewayFrameFeedback],
) -> str:
    if cycle.drift_risk == "high":
        return "diverging"
    if any(feedback.protected_gap_ms > 0.0 for feedback in frame_feedbacks):
        return "needs-correction"
    if cycle.memory_headroom_reserved_mb > 0.0:
        return "watching-headroom"
    return "stable"


def feedback_confidence(
    cycle: RuntimeGatewayCycleReport,
    calibration: RuntimeCalibrationReport,
) -> str:
    if cycle.step_count == 0 or calibration.frame_count == 0:
        return "low"
    if any(frame.confidence == "low" for frame in calibration.frames):
        return "medium"
    return "medium"
