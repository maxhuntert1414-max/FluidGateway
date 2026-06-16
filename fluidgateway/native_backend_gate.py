from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .native_backend_readiness import (
    RuntimeNativeBackendReadinessAssessment,
    RuntimeNativeBackendReadinessReport,
)


NATIVE_BACKEND_GATE_MODE = "runtime-native-backend-gate-v0.58"
NATIVE_BACKEND_GATE_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeNativeBackendGateDecision:
    decision_id: str
    source_assessment_id: str
    backend_id: str
    control_surface: str
    gate_status: str
    gate_action: str
    promotion_scope: str
    advance_allowed: bool
    native_promotion_allowed: bool
    would_modify_system: bool
    blocked: bool
    blocked_by: list[str]
    readiness_score: int
    risk_level: str
    required_next_evidence: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "source_assessment_id": self.source_assessment_id,
            "backend_id": self.backend_id,
            "control_surface": self.control_surface,
            "gate_status": self.gate_status,
            "gate_action": self.gate_action,
            "promotion_scope": self.promotion_scope,
            "advance_allowed": self.advance_allowed,
            "native_promotion_allowed": self.native_promotion_allowed,
            "would_modify_system": self.would_modify_system,
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "readiness_score": self.readiness_score,
            "risk_level": self.risk_level,
            "required_next_evidence": self.required_next_evidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeNativeBackendGate:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_readiness_policy: str
    gate_policy: str
    native_promotion_allowed: bool
    decision_count: int
    advance_count: int
    blocked_count: int
    native_blocked_count: int
    evidence_blocked_count: int
    high_risk_count: int
    decisions: list[RuntimeNativeBackendGateDecision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_readiness_policy": self.source_readiness_policy,
            "gate_policy": self.gate_policy,
            "native_promotion_allowed": self.native_promotion_allowed,
            "decision_count": self.decision_count,
            "advance_count": self.advance_count,
            "blocked_count": self.blocked_count,
            "native_blocked_count": self.native_blocked_count,
            "evidence_blocked_count": self.evidence_blocked_count,
            "high_risk_count": self.high_risk_count,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


def build_runtime_native_backend_gate(
    readiness: RuntimeNativeBackendReadinessReport,
) -> RuntimeNativeBackendGate:
    decisions = [
        build_gate_decision(index + 1, assessment)
        for index, assessment in enumerate(readiness.assessments)
    ]
    return RuntimeNativeBackendGate(
        mode=NATIVE_BACKEND_GATE_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=NATIVE_BACKEND_GATE_GUARD,
        source_readiness_policy=readiness.readiness_policy,
        gate_policy=gate_policy(decisions),
        native_promotion_allowed=False,
        decision_count=len(decisions),
        advance_count=sum(1 for decision in decisions if decision.advance_allowed),
        blocked_count=sum(1 for decision in decisions if decision.blocked),
        native_blocked_count=sum(
            1
            for decision in decisions
            if decision.gate_status == "block-native-promotion"
        ),
        evidence_blocked_count=sum(
            1
            for decision in decisions
            if decision.gate_status == "block-for-evidence"
        ),
        high_risk_count=sum(
            1 for decision in decisions if decision.risk_level == "high"
        ),
        decisions=decisions,
    )


def build_gate_decision(
    index: int,
    assessment: RuntimeNativeBackendReadinessAssessment,
) -> RuntimeNativeBackendGateDecision:
    gate_status = decision_gate_status(assessment)
    blocked = gate_status in {"block-for-evidence", "block-native-promotion"}
    return RuntimeNativeBackendGateDecision(
        decision_id=f"native.gate.{index:03d}",
        source_assessment_id=assessment.assessment_id,
        backend_id=assessment.backend_id,
        control_surface=assessment.control_surface,
        gate_status=gate_status,
        gate_action=decision_gate_action(gate_status),
        promotion_scope=decision_promotion_scope(gate_status),
        advance_allowed=not blocked,
        native_promotion_allowed=False,
        would_modify_system=False,
        blocked=blocked,
        blocked_by=decision_blockers(assessment, gate_status),
        readiness_score=assessment.readiness_score,
        risk_level=assessment.risk_level,
        required_next_evidence=assessment.required_next_evidence,
        reason=decision_reason(assessment, gate_status),
    )


def decision_gate_status(
    assessment: RuntimeNativeBackendReadinessAssessment,
) -> str:
    if assessment.readiness_status == "ready-readonly-observation":
        return "allow-readonly-observation"
    if assessment.readiness_status == "ready-advisory-loop":
        return "allow-advisory-loop"
    if assessment.readiness_status == "blocked-native-safety-boundary":
        return "block-native-promotion"
    return "block-for-evidence"


def decision_gate_action(gate_status: str) -> str:
    if gate_status == "allow-readonly-observation":
        return "continue-readonly-telemetry"
    if gate_status == "allow-advisory-loop":
        return "continue-advisory-daemon-loop"
    if gate_status == "block-native-promotion":
        return "hold-native-control"
    return "collect-required-evidence"


def decision_promotion_scope(gate_status: str) -> str:
    if gate_status == "allow-readonly-observation":
        return "read-only-observation"
    if gate_status == "allow-advisory-loop":
        return "advisory-loop"
    if gate_status == "block-native-promotion":
        return "native-control"
    return "evidence-gathering"


def decision_blockers(
    assessment: RuntimeNativeBackendReadinessAssessment,
    gate_status: str,
) -> list[str]:
    blockers = list(assessment.blockers)
    if gate_status == "block-native-promotion":
        blockers.append("native-promotion-disabled")
    if gate_status == "block-for-evidence" and not blockers:
        blockers.extend(assessment.required_next_evidence)
    return blockers


def decision_reason(
    assessment: RuntimeNativeBackendReadinessAssessment,
    gate_status: str,
) -> str:
    if gate_status == "allow-readonly-observation":
        return (
            "Read-only host evidence is sufficient for observation, but native "
            "promotion remains disabled."
        )
    if gate_status == "allow-advisory-loop":
        return (
            "Advisory daemon contract has enough evidence to continue without "
            "mutating the host."
        )
    if gate_status == "block-native-promotion":
        return (
            "Native control is explicitly blocked until a real backend, "
            "privilege model, and safety review exist."
        )
    return (
        f"Readiness status {assessment.readiness_status} still needs evidence "
        "before any promotion gate can advance."
    )


def gate_policy(decisions: list[RuntimeNativeBackendGateDecision]) -> str:
    native_blocked = any(
        decision.gate_status == "block-native-promotion"
        for decision in decisions
    )
    evidence_blocked = any(
        decision.gate_status == "block-for-evidence" for decision in decisions
    )
    readonly_ready = any(
        decision.gate_status == "allow-readonly-observation"
        for decision in decisions
    )
    advisory_ready = any(
        decision.gate_status == "allow-advisory-loop" for decision in decisions
    )
    if native_blocked and (readonly_ready or advisory_ready):
        return "advance-safe-paths-hold-native"
    if native_blocked:
        return "hold-native-promotion"
    if evidence_blocked:
        return "collect-evidence-before-promotion"
    if readonly_ready:
        return "advance-readonly-observation"
    if advisory_ready:
        return "advance-advisory-loop"
    return "observe"
