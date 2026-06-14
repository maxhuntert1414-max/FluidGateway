from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .applier import DispatchExecutionReport
from .policy import DEFAULT_FRAME_BUDGET_MS


CALIBRATION_MODE = "runtime-calibration-report-v0.32"


@dataclass(frozen=True)
class FrameCalibration:
    frame: int
    target_frame_ms: float
    observed_frame_cost_ms: float
    planned_current_frame_cost_ms: float
    planned_pre_frame_cost_ms: float
    planned_deferred_cost_ms: float
    planned_avoided_cost_ms: float
    planned_frame_relief_ms: float
    guardband_ms: float
    recommended_next_frame_budget_ms: float
    observed_pressure_status: str
    planned_pressure_status: str
    action: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "observed_frame_cost_ms": round(self.observed_frame_cost_ms, 4),
            "planned_current_frame_cost_ms": round(
                self.planned_current_frame_cost_ms, 4
            ),
            "planned_pre_frame_cost_ms": round(self.planned_pre_frame_cost_ms, 4),
            "planned_deferred_cost_ms": round(self.planned_deferred_cost_ms, 4),
            "planned_avoided_cost_ms": round(self.planned_avoided_cost_ms, 4),
            "planned_frame_relief_ms": round(self.planned_frame_relief_ms, 4),
            "guardband_ms": round(self.guardband_ms, 4),
            "recommended_next_frame_budget_ms": round(
                self.recommended_next_frame_budget_ms, 4
            ),
            "observed_pressure_status": self.observed_pressure_status,
            "planned_pressure_status": self.planned_pressure_status,
            "action": self.action,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RuntimeCalibrationReport:
    mode: str
    frame_count: int
    over_budget_observed_count: int
    over_budget_planned_count: int
    total_observed_frame_cost_ms: float
    total_planned_current_frame_cost_ms: float
    total_planned_frame_relief_ms: float
    total_pre_frame_cost_ms: float
    total_deferred_cost_ms: float
    total_avoided_cost_ms: float
    total_memory_relief_mb: float
    max_guardband_ms: float
    recommended_next_frame_budget_ms: float
    action_count: int
    frames: list[FrameCalibration]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "frame_count": self.frame_count,
            "over_budget_observed_count": self.over_budget_observed_count,
            "over_budget_planned_count": self.over_budget_planned_count,
            "total_observed_frame_cost_ms": round(
                self.total_observed_frame_cost_ms, 4
            ),
            "total_planned_current_frame_cost_ms": round(
                self.total_planned_current_frame_cost_ms, 4
            ),
            "total_planned_frame_relief_ms": round(
                self.total_planned_frame_relief_ms, 4
            ),
            "total_pre_frame_cost_ms": round(self.total_pre_frame_cost_ms, 4),
            "total_deferred_cost_ms": round(self.total_deferred_cost_ms, 4),
            "total_avoided_cost_ms": round(self.total_avoided_cost_ms, 4),
            "total_memory_relief_mb": round(self.total_memory_relief_mb, 4),
            "max_guardband_ms": round(self.max_guardband_ms, 4),
            "recommended_next_frame_budget_ms": round(
                self.recommended_next_frame_budget_ms, 4
            ),
            "action_count": self.action_count,
            "frames": [frame.to_dict() for frame in self.frames],
        }


def build_runtime_calibration(
    dispatch_execution: DispatchExecutionReport,
    frames: list[Any],
) -> RuntimeCalibrationReport:
    frame_calibrations = [
        calibrate_frame(dispatch_execution, frame) for frame in frames
    ]
    recommended_next_frame_budget_ms = 0.0
    if frame_calibrations:
        recommended_next_frame_budget_ms = min(
            frame.recommended_next_frame_budget_ms for frame in frame_calibrations
        )
    return RuntimeCalibrationReport(
        mode=CALIBRATION_MODE,
        frame_count=len(frame_calibrations),
        over_budget_observed_count=sum(
            1
            for frame in frame_calibrations
            if frame.observed_pressure_status == "over-budget"
        ),
        over_budget_planned_count=sum(
            1
            for frame in frame_calibrations
            if frame.planned_pressure_status == "over-budget"
        ),
        total_observed_frame_cost_ms=sum(
            frame.observed_frame_cost_ms for frame in frame_calibrations
        ),
        total_planned_current_frame_cost_ms=sum(
            frame.planned_current_frame_cost_ms for frame in frame_calibrations
        ),
        total_planned_frame_relief_ms=sum(
            frame.planned_frame_relief_ms for frame in frame_calibrations
        ),
        total_pre_frame_cost_ms=dispatch_execution.pre_frame_cost_ms,
        total_deferred_cost_ms=dispatch_execution.deferred_cost_ms,
        total_avoided_cost_ms=dispatch_execution.avoided_cost_ms,
        total_memory_relief_mb=dispatch_execution.memory_relief_mb,
        max_guardband_ms=max(
            (frame.guardband_ms for frame in frame_calibrations), default=0.0
        ),
        recommended_next_frame_budget_ms=recommended_next_frame_budget_ms,
        action_count=sum(1 for frame in frame_calibrations if frame.action != "monitor"),
        frames=frame_calibrations,
    )


def calibrate_frame(
    dispatch_execution: DispatchExecutionReport,
    frame: Any,
) -> FrameCalibration:
    frame_id = int(read_field(frame, "frame", 0))
    target_frame_ms = float(
        read_field(frame, "target_frame_ms", DEFAULT_FRAME_BUDGET_MS)
    )
    observed_frame_cost_ms = float(read_field(frame, "estimated_total_cost_ms", 0.0))
    frame_steps = [step for step in dispatch_execution.steps if step.frame == frame_id]
    planned_current_frame_cost_ms = sum(
        step.current_frame_cost_ms for step in frame_steps
    )
    planned_pre_frame_cost_ms = sum(step.pre_frame_cost_ms for step in frame_steps)
    planned_deferred_cost_ms = sum(step.deferred_cost_ms for step in frame_steps)
    planned_avoided_cost_ms = sum(step.avoided_cost_ms for step in frame_steps)
    planned_frame_relief_ms = max(
        0.0, observed_frame_cost_ms - planned_current_frame_cost_ms
    )
    observed_pressure_status = pressure_status(
        observed_frame_cost_ms, target_frame_ms
    )
    planned_pressure_status = pressure_status(
        planned_current_frame_cost_ms, target_frame_ms
    )
    guardband_ms = next_guardband(
        observed_frame_cost_ms,
        target_frame_ms,
        planned_frame_relief_ms,
    )
    return FrameCalibration(
        frame=frame_id,
        target_frame_ms=target_frame_ms,
        observed_frame_cost_ms=observed_frame_cost_ms,
        planned_current_frame_cost_ms=planned_current_frame_cost_ms,
        planned_pre_frame_cost_ms=planned_pre_frame_cost_ms,
        planned_deferred_cost_ms=planned_deferred_cost_ms,
        planned_avoided_cost_ms=planned_avoided_cost_ms,
        planned_frame_relief_ms=planned_frame_relief_ms,
        guardband_ms=guardband_ms,
        recommended_next_frame_budget_ms=max(0.0, target_frame_ms - guardband_ms),
        observed_pressure_status=observed_pressure_status,
        planned_pressure_status=planned_pressure_status,
        action=calibration_action(
            observed_pressure_status,
            planned_pressure_status,
            planned_frame_relief_ms,
        ),
        confidence="medium" if frame_steps else "low",
    )


def pressure_status(cost_ms: float, target_frame_ms: float) -> str:
    return "over-budget" if cost_ms > target_frame_ms else "within-budget"


def next_guardband(
    observed_frame_cost_ms: float,
    target_frame_ms: float,
    planned_frame_relief_ms: float,
) -> float:
    if observed_frame_cost_ms <= target_frame_ms:
        return 0.0
    return min(target_frame_ms * 0.25, max(0.5, planned_frame_relief_ms * 0.25))


def calibration_action(
    observed_pressure_status: str,
    planned_pressure_status: str,
    planned_frame_relief_ms: float,
) -> str:
    if planned_pressure_status == "over-budget":
        return "tighten-dispatch-guardband"
    if observed_pressure_status == "over-budget":
        return "apply-dispatch-before-next-frame"
    if planned_frame_relief_ms > 0.0:
        return "preserve-dispatch-shape"
    return "monitor"


def read_field(frame: Any, field: str, default: Any) -> Any:
    if isinstance(frame, dict):
        return frame.get(field, default)
    return getattr(frame, field, default)
