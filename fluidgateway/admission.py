from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ADMISSION_MODE = "adaptive-admission-controller-v0.18"


@dataclass(frozen=True)
class AdmissionDecision:
    mode: str
    action: str
    operation_id: str
    frame: int | None
    queue: str
    resource_id: str | None
    phase: str
    admitted: bool
    contribution: str
    cost_ms: float
    size_mb: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "queue": self.queue,
            "resource_id": self.resource_id,
            "phase": self.phase,
            "admitted": self.admitted,
            "contribution": self.contribution,
            "cost_ms": round(self.cost_ms, 4),
            "size_mb": round(self.size_mb, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AdmissionPlan:
    mode: str
    operation_count: int
    immediate_count: int
    prefetch_count: int
    deferred_count: int
    reused_count: int
    held_count: int
    estimated_hot_path_cost_ms: float
    estimated_prestaged_cost_ms: float
    estimated_prestaged_transfer_mb: float
    estimated_avoided_cost_ms: float
    estimated_avoided_transfer_mb: float
    estimated_held_cost_ms: float
    estimated_held_transfer_mb: float
    slots: list[AdmissionDecision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "operation_count": self.operation_count,
            "immediate_count": self.immediate_count,
            "prefetch_count": self.prefetch_count,
            "deferred_count": self.deferred_count,
            "reused_count": self.reused_count,
            "held_count": self.held_count,
            "estimated_hot_path_cost_ms": round(self.estimated_hot_path_cost_ms, 4),
            "estimated_prestaged_cost_ms": round(self.estimated_prestaged_cost_ms, 4),
            "estimated_prestaged_transfer_mb": round(
                self.estimated_prestaged_transfer_mb, 4
            ),
            "estimated_avoided_cost_ms": round(self.estimated_avoided_cost_ms, 4),
            "estimated_avoided_transfer_mb": round(
                self.estimated_avoided_transfer_mb, 4
            ),
            "estimated_held_cost_ms": round(self.estimated_held_cost_ms, 4),
            "estimated_held_transfer_mb": round(self.estimated_held_transfer_mb, 4),
            "slots": [slot.to_dict() for slot in self.slots],
        }


def build_admission_decision(result_payload: dict[str, Any]) -> AdmissionDecision:
    operation = result_payload.get("operation") or {}
    gate = result_payload.get("execution_gate") or {}
    gate_action = str(gate.get("action") or "execute_now")
    operation_id = str(operation.get("id") or gate.get("operation_id") or "")
    operation_type = str(operation.get("type") or "")
    cost_ms = number(operation.get("cost_ms"))
    size_mb = number(operation.get("size_mb"))
    frame = operation.get("frame", gate.get("frame"))
    if frame is not None:
        frame = int(frame)

    if gate_action == "prestage_before_draw":
        return decision(
            action="admit-prefetch",
            operation_id=operation_id,
            frame=frame,
            queue=str(operation.get("queue") or gate.get("queue") or "unknown"),
            resource_id=operation.get("target") or gate.get("resource_id"),
            phase="prefetch",
            admitted=True,
            contribution="prestaged",
            cost_ms=cost_ms,
            size_mb=transfer_size(operation_type, size_mb),
            reason="Admit operation into the prefetch phase before draw-critical work.",
        )

    if gate_action == "defer_redundant_work":
        return decision(
            action="reject-redundant",
            operation_id=operation_id,
            frame=frame,
            queue=str(operation.get("queue") or gate.get("queue") or "unknown"),
            resource_id=operation.get("target") or gate.get("resource_id"),
            phase="deferred",
            admitted=False,
            contribution="avoided",
            cost_ms=cost_ms,
            size_mb=size_mb,
            reason="Reject redundant work from the executable queue.",
        )

    if gate_action == "reuse_existing_resource":
        return decision(
            action="reuse-existing",
            operation_id=operation_id,
            frame=frame,
            queue=str(operation.get("queue") or gate.get("queue") or "unknown"),
            resource_id=operation.get("target") or gate.get("resource_id"),
            phase="reuse",
            admitted=False,
            contribution="reused",
            cost_ms=cost_ms,
            size_mb=size_mb,
            reason="Use an existing resource instead of executing equivalent work.",
        )

    if gate_action == "hold_noncritical_work":
        return decision(
            action="hold-next-frame",
            operation_id=operation_id,
            frame=frame,
            queue=str(operation.get("queue") or gate.get("queue") or "unknown"),
            resource_id=operation.get("target") or gate.get("resource_id"),
            phase="next-frame",
            admitted=False,
            contribution="held",
            cost_ms=cost_ms,
            size_mb=transfer_size(operation_type, size_mb),
            reason="Hold non-critical work outside the current hot frame.",
        )

    phase = str(gate.get("preferred_phase") or "current-frame")
    return decision(
        action="admit-now",
        operation_id=operation_id,
        frame=frame,
        queue=str(operation.get("queue") or gate.get("queue") or "unknown"),
        resource_id=operation.get("target") or gate.get("resource_id"),
        phase=phase,
        admitted=True,
        contribution="hot-path",
        cost_ms=cost_ms,
        size_mb=0.0,
        reason="Admit operation into the current executable frame path.",
    )


def build_admission_plan(results: list[dict[str, Any]]) -> AdmissionPlan:
    slots = [
        build_admission_decision(result)
        for result in results
        if isinstance(result, dict) and result.get("operation")
    ]
    return AdmissionPlan(
        mode=ADMISSION_MODE,
        operation_count=len(slots),
        immediate_count=count(slots, "admit-now"),
        prefetch_count=count(slots, "admit-prefetch"),
        deferred_count=count(slots, "reject-redundant"),
        reused_count=count(slots, "reuse-existing"),
        held_count=count(slots, "hold-next-frame"),
        estimated_hot_path_cost_ms=sum_cost(slots, "hot-path"),
        estimated_prestaged_cost_ms=sum_cost(slots, "prestaged"),
        estimated_prestaged_transfer_mb=sum_size(slots, "prestaged"),
        estimated_avoided_cost_ms=(
            sum_cost(slots, "avoided") + sum_cost(slots, "reused")
        ),
        estimated_avoided_transfer_mb=(
            sum_size(slots, "avoided") + sum_size(slots, "reused")
        ),
        estimated_held_cost_ms=sum_cost(slots, "held"),
        estimated_held_transfer_mb=sum_size(slots, "held"),
        slots=slots,
    )


def decision(
    *,
    action: str,
    operation_id: str,
    frame: int | None,
    queue: str,
    resource_id: str | None,
    phase: str,
    admitted: bool,
    contribution: str,
    cost_ms: float,
    size_mb: float,
    reason: str,
) -> AdmissionDecision:
    return AdmissionDecision(
        mode=ADMISSION_MODE,
        action=action,
        operation_id=operation_id,
        frame=frame,
        queue=queue,
        resource_id=resource_id,
        phase=phase,
        admitted=admitted,
        contribution=contribution,
        cost_ms=cost_ms,
        size_mb=size_mb,
        reason=reason,
    )


def count(slots: list[AdmissionDecision], action: str) -> int:
    return sum(1 for slot in slots if slot.action == action)


def sum_cost(slots: list[AdmissionDecision], contribution: str) -> float:
    return sum(slot.cost_ms for slot in slots if slot.contribution == contribution)


def sum_size(slots: list[AdmissionDecision], contribution: str) -> float:
    return sum(slot.size_mb for slot in slots if slot.contribution == contribution)


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def transfer_size(operation_type: str, size_mb: float) -> float:
    if operation_type in {"copy", "upload", "allocate"}:
        return size_mb
    return 0.0
