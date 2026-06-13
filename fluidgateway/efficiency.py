from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .admission import AdmissionDecision, AdmissionPlan


EFFICIENCY_MODE = "frame-efficiency-ledger-v0.19"


@dataclass(frozen=True)
class EfficiencyImpact:
    mode: str
    operation_id: str
    frame: int | None
    impact: str
    relief_cost_ms: float
    relief_transfer_mb: float
    hot_path_cost_ms: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "impact": self.impact,
            "relief_cost_ms": round(self.relief_cost_ms, 4),
            "relief_transfer_mb": round(self.relief_transfer_mb, 4),
            "hot_path_cost_ms": round(self.hot_path_cost_ms, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FrameEfficiency:
    frame: int
    operation_count: int
    hot_path_cost_ms: float
    shifted_cost_ms: float
    avoided_cost_ms: float
    held_cost_ms: float
    transfer_relief_mb: float
    efficiency_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "operation_count": self.operation_count,
            "hot_path_cost_ms": round(self.hot_path_cost_ms, 4),
            "shifted_cost_ms": round(self.shifted_cost_ms, 4),
            "avoided_cost_ms": round(self.avoided_cost_ms, 4),
            "held_cost_ms": round(self.held_cost_ms, 4),
            "transfer_relief_mb": round(self.transfer_relief_mb, 4),
            "efficiency_score": round(self.efficiency_score, 4),
        }


@dataclass(frozen=True)
class EfficiencyLedger:
    mode: str
    operation_count: int
    hot_path_cost_ms: float
    shifted_cost_ms: float
    avoided_cost_ms: float
    held_cost_ms: float
    transfer_relief_mb: float
    managed_cost_ms: float
    relief_cost_ms: float
    efficiency_score: float
    frames: list[FrameEfficiency]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "operation_count": self.operation_count,
            "hot_path_cost_ms": round(self.hot_path_cost_ms, 4),
            "shifted_cost_ms": round(self.shifted_cost_ms, 4),
            "avoided_cost_ms": round(self.avoided_cost_ms, 4),
            "held_cost_ms": round(self.held_cost_ms, 4),
            "transfer_relief_mb": round(self.transfer_relief_mb, 4),
            "managed_cost_ms": round(self.managed_cost_ms, 4),
            "relief_cost_ms": round(self.relief_cost_ms, 4),
            "efficiency_score": round(self.efficiency_score, 4),
            "frames": [frame.to_dict() for frame in self.frames],
        }


def build_efficiency_impact(decision: AdmissionDecision) -> EfficiencyImpact:
    if decision.contribution == "prestaged":
        return impact(
            decision,
            impact_name="shifted-off-hot-path",
            relief_cost_ms=decision.cost_ms,
            relief_transfer_mb=decision.size_mb,
            hot_path_cost_ms=0.0,
            reason="Transfer work was admitted into prefetch instead of the hot frame path.",
        )
    if decision.contribution in {"avoided", "reused"}:
        return impact(
            decision,
            impact_name="avoided-waste",
            relief_cost_ms=decision.cost_ms,
            relief_transfer_mb=decision.size_mb,
            hot_path_cost_ms=0.0,
            reason="Redundant or reusable work was kept out of the executable queue.",
        )
    if decision.contribution == "held":
        return impact(
            decision,
            impact_name="held-out-of-hot-frame",
            relief_cost_ms=decision.cost_ms,
            relief_transfer_mb=decision.size_mb,
            hot_path_cost_ms=0.0,
            reason="Non-critical work was held for a later frame.",
        )
    return impact(
        decision,
        impact_name="hot-path-work",
        relief_cost_ms=0.0,
        relief_transfer_mb=0.0,
        hot_path_cost_ms=decision.cost_ms,
        reason="Required work remained on the current frame path.",
    )


def build_efficiency_ledger(admission_plan: AdmissionPlan) -> EfficiencyLedger:
    hot_path = admission_plan.estimated_hot_path_cost_ms
    shifted = admission_plan.estimated_prestaged_cost_ms
    avoided = admission_plan.estimated_avoided_cost_ms
    held = admission_plan.estimated_held_cost_ms
    transfer_relief = (
        admission_plan.estimated_prestaged_transfer_mb
        + admission_plan.estimated_avoided_transfer_mb
        + admission_plan.estimated_held_transfer_mb
    )
    relief = shifted + avoided + held
    managed = hot_path + relief
    frames = build_frame_efficiency(admission_plan.slots)
    return EfficiencyLedger(
        mode=EFFICIENCY_MODE,
        operation_count=admission_plan.operation_count,
        hot_path_cost_ms=hot_path,
        shifted_cost_ms=shifted,
        avoided_cost_ms=avoided,
        held_cost_ms=held,
        transfer_relief_mb=transfer_relief,
        managed_cost_ms=managed,
        relief_cost_ms=relief,
        efficiency_score=score(relief, managed),
        frames=frames,
    )


def build_frame_efficiency(slots: list[AdmissionDecision]) -> list[FrameEfficiency]:
    frames: dict[int, list[AdmissionDecision]] = {}
    for slot in slots:
        if slot.frame is None:
            continue
        frames.setdefault(slot.frame, []).append(slot)

    result: list[FrameEfficiency] = []
    for frame, frame_slots in sorted(frames.items()):
        hot_path = sum(
            slot.cost_ms for slot in frame_slots if slot.contribution == "hot-path"
        )
        shifted = sum(
            slot.cost_ms for slot in frame_slots if slot.contribution == "prestaged"
        )
        avoided = sum(
            slot.cost_ms
            for slot in frame_slots
            if slot.contribution in {"avoided", "reused"}
        )
        held = sum(slot.cost_ms for slot in frame_slots if slot.contribution == "held")
        transfer_relief = sum(
            slot.size_mb
            for slot in frame_slots
            if slot.contribution in {"prestaged", "avoided", "reused", "held"}
        )
        relief = shifted + avoided + held
        managed = hot_path + relief
        result.append(
            FrameEfficiency(
                frame=frame,
                operation_count=len(frame_slots),
                hot_path_cost_ms=hot_path,
                shifted_cost_ms=shifted,
                avoided_cost_ms=avoided,
                held_cost_ms=held,
                transfer_relief_mb=transfer_relief,
                efficiency_score=score(relief, managed),
            )
        )
    return result


def impact(
    decision: AdmissionDecision,
    *,
    impact_name: str,
    relief_cost_ms: float,
    relief_transfer_mb: float,
    hot_path_cost_ms: float,
    reason: str,
) -> EfficiencyImpact:
    return EfficiencyImpact(
        mode=EFFICIENCY_MODE,
        operation_id=decision.operation_id,
        frame=decision.frame,
        impact=impact_name,
        relief_cost_ms=relief_cost_ms,
        relief_transfer_mb=relief_transfer_mb,
        hot_path_cost_ms=hot_path_cost_ms,
        reason=reason,
    )


def score(relief_cost_ms: float, managed_cost_ms: float) -> float:
    if managed_cost_ms <= 0:
        return 0.0
    return (relief_cost_ms / managed_cost_ms) * 100.0
