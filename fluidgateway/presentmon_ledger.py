from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .daemon import RuntimeDaemonReport
from .presentmon_runtime import PresentMonRuntimeEventStream


PRESENTMON_OPERATIONAL_LEDGER_MODE = "presentmon-operational-ledger-v0.61"


@dataclass(frozen=True)
class OperationalLedgerEvidence:
    label: str
    value: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "value": self.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PresentMonOperationalLedger:
    mode: str
    dry_run: bool
    would_modify_system: bool
    presentmon_path: str
    events_path: str
    application: str
    source_event_mode: str
    daemon_mode: str
    manager_profile: str
    policy_action: str
    convergence_status: str
    drift_risk: str
    finding_count: int
    management_action_count: int
    adapter_event_count: int
    runtime_operation_count: int
    waste_pressure_score: int
    safe_progress_score: float
    native_blocker_score: float
    decision_action: str
    decision_risk_level: str
    gate_policy: str
    safe_advance_count: int
    blocked_count: int
    native_blocked_count: int
    native_promotion_allowed: bool
    next_frame_budget_ms: float
    memory_relief_target_mb: float
    safe_control_surfaces: list[str]
    native_blocked_surfaces: list[str]
    recommended_next_step: str
    evidence: list[OperationalLedgerEvidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "presentmon_path": self.presentmon_path,
            "events_path": self.events_path,
            "application": self.application,
            "source_event_mode": self.source_event_mode,
            "daemon_mode": self.daemon_mode,
            "manager_profile": self.manager_profile,
            "policy_action": self.policy_action,
            "convergence_status": self.convergence_status,
            "drift_risk": self.drift_risk,
            "finding_count": self.finding_count,
            "management_action_count": self.management_action_count,
            "adapter_event_count": self.adapter_event_count,
            "runtime_operation_count": self.runtime_operation_count,
            "waste_pressure_score": self.waste_pressure_score,
            "safe_progress_score": round(self.safe_progress_score, 4),
            "native_blocker_score": round(self.native_blocker_score, 4),
            "decision_action": self.decision_action,
            "decision_risk_level": self.decision_risk_level,
            "gate_policy": self.gate_policy,
            "safe_advance_count": self.safe_advance_count,
            "blocked_count": self.blocked_count,
            "native_blocked_count": self.native_blocked_count,
            "native_promotion_allowed": self.native_promotion_allowed,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "memory_relief_target_mb": round(self.memory_relief_target_mb, 4),
            "safe_control_surfaces": self.safe_control_surfaces,
            "native_blocked_surfaces": self.native_blocked_surfaces,
            "recommended_next_step": self.recommended_next_step,
            "evidence": [item.to_dict() for item in self.evidence],
        }


def build_presentmon_operational_ledger(
    *,
    presentmon_path: str | Path,
    events_path: str | Path,
    event_stream: PresentMonRuntimeEventStream,
    daemon_report: RuntimeDaemonReport,
) -> PresentMonOperationalLedger:
    safe_surfaces = [
        decision.control_surface
        for decision in daemon_report.native_backend_gate.decisions
        if decision.advance_allowed
    ]
    native_blocked_surfaces = [
        decision.control_surface
        for decision in daemon_report.native_backend_gate.decisions
        if decision.gate_status == "block-native-promotion"
    ]
    safe_count = daemon_report.native_backend_gate_advance_count
    blocked_count = daemon_report.native_backend_gate_blocked_count
    total_gate_count = max(1, safe_count + blocked_count)
    return PresentMonOperationalLedger(
        mode=PRESENTMON_OPERATIONAL_LEDGER_MODE,
        dry_run=True,
        would_modify_system=False,
        presentmon_path=str(presentmon_path),
        events_path=str(events_path),
        application=event_stream.application,
        source_event_mode=event_stream.mode,
        daemon_mode=daemon_report.mode,
        manager_profile=daemon_report.final_state.profile,
        policy_action=daemon_report.final_state.policy_action,
        convergence_status=daemon_report.final_state.convergence_status,
        drift_risk=daemon_report.final_state.drift_risk,
        finding_count=event_stream.finding_count,
        management_action_count=event_stream.management_action_count,
        adapter_event_count=event_stream.event_count,
        runtime_operation_count=event_stream.operation_event_count,
        waste_pressure_score=daemon_report.daemon_arbitration_pressure_score,
        safe_progress_score=(safe_count / total_gate_count) * 100.0,
        native_blocker_score=(
            daemon_report.native_backend_gate_native_blocked_count
            / total_gate_count
        )
        * 100.0,
        decision_action=daemon_report.daemon_decision_action,
        decision_risk_level=daemon_report.daemon_decision_risk_level,
        gate_policy=daemon_report.native_backend_gate_policy,
        safe_advance_count=safe_count,
        blocked_count=blocked_count,
        native_blocked_count=daemon_report.native_backend_gate_native_blocked_count,
        native_promotion_allowed=daemon_report.native_promotion_allowed,
        next_frame_budget_ms=daemon_report.final_state.next_frame_budget_ms,
        memory_relief_target_mb=daemon_report.final_state.memory_relief_target_mb,
        safe_control_surfaces=safe_surfaces,
        native_blocked_surfaces=native_blocked_surfaces,
        recommended_next_step=recommended_next_step(
            daemon_report,
            safe_count,
            blocked_count,
        ),
        evidence=ledger_evidence(event_stream, daemon_report),
    )


def write_presentmon_operational_ledger(
    ledger: PresentMonOperationalLedger,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def recommended_next_step(
    daemon_report: RuntimeDaemonReport,
    safe_count: int,
    blocked_count: int,
) -> str:
    if daemon_report.native_backend_gate_native_blocked_count and safe_count:
        return "continue-safe-manager-loop-and-build-native-backend"
    if daemon_report.native_backend_gate_native_blocked_count:
        return "build-native-backend-before-control"
    if blocked_count:
        return "collect-required-evidence"
    if daemon_report.daemon_arbitration_pressure_score >= 70:
        return "continue-pressure-management"
    return "observe-and-compare-next-trace"


def ledger_evidence(
    event_stream: PresentMonRuntimeEventStream,
    daemon_report: RuntimeDaemonReport,
) -> list[OperationalLedgerEvidence]:
    return [
        OperationalLedgerEvidence(
            "PresentMon management actions",
            str(event_stream.management_action_count),
            "Number of advisory actions converted into runtime adapter events.",
        ),
        OperationalLedgerEvidence(
            "Daemon pressure score",
            str(daemon_report.daemon_arbitration_pressure_score),
            "Pressure score used by daemon arbitration across runtime lanes.",
        ),
        OperationalLedgerEvidence(
            "Native backend gate policy",
            daemon_report.native_backend_gate_policy,
            "Safe/advisory advancement is separated from native backend promotion.",
        ),
        OperationalLedgerEvidence(
            "Native promotion allowed",
            str(daemon_report.native_promotion_allowed),
            "Native mutation remains disabled in the current runtime boundary.",
        ),
    ]
