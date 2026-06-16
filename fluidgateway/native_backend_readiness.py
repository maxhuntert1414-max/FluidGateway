from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .native_backend_probe import (
    RuntimeNativeBackendProbeReport,
    RuntimeNativeBackendProbeStep,
)


NATIVE_BACKEND_READINESS_MODE = "runtime-native-backend-readiness-v0.57"
NATIVE_BACKEND_READINESS_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeNativeBackendReadinessAssessment:
    assessment_id: str
    source_step_id: str
    backend_id: str
    control_surface: str
    readiness_status: str
    readiness_score: int
    risk_level: str
    signal_quality: str
    native_action_allowed: bool
    would_modify_system: bool
    blocker_count: int
    blockers: list[str]
    signal_count: int
    required_next_evidence: list[str]
    recommended_next_step: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "source_step_id": self.source_step_id,
            "backend_id": self.backend_id,
            "control_surface": self.control_surface,
            "readiness_status": self.readiness_status,
            "readiness_score": self.readiness_score,
            "risk_level": self.risk_level,
            "signal_quality": self.signal_quality,
            "native_action_allowed": self.native_action_allowed,
            "would_modify_system": self.would_modify_system,
            "blocker_count": self.blocker_count,
            "blockers": self.blockers,
            "signal_count": self.signal_count,
            "required_next_evidence": self.required_next_evidence,
            "recommended_next_step": self.recommended_next_step,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeNativeBackendReadinessReport:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_probe_policy: str
    readiness_policy: str
    native_action_allowed: bool
    assessment_count: int
    ready_observation_count: int
    advisory_ready_count: int
    needs_evidence_count: int
    native_blocked_count: int
    high_risk_count: int
    total_signal_count: int
    cpu_signal_ready: bool
    memory_signal_ready: bool
    gpu_signal_ready: bool
    assessments: list[RuntimeNativeBackendReadinessAssessment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_probe_policy": self.source_probe_policy,
            "readiness_policy": self.readiness_policy,
            "native_action_allowed": self.native_action_allowed,
            "assessment_count": self.assessment_count,
            "ready_observation_count": self.ready_observation_count,
            "advisory_ready_count": self.advisory_ready_count,
            "needs_evidence_count": self.needs_evidence_count,
            "native_blocked_count": self.native_blocked_count,
            "high_risk_count": self.high_risk_count,
            "total_signal_count": self.total_signal_count,
            "cpu_signal_ready": self.cpu_signal_ready,
            "memory_signal_ready": self.memory_signal_ready,
            "gpu_signal_ready": self.gpu_signal_ready,
            "assessments": [
                assessment.to_dict() for assessment in self.assessments
            ],
        }


def assess_runtime_native_backend_readiness(
    probe_report: RuntimeNativeBackendProbeReport,
) -> RuntimeNativeBackendReadinessReport:
    assessments = [
        assess_probe_step(index + 1, step)
        for index, step in enumerate(probe_report.steps)
    ]
    return RuntimeNativeBackendReadinessReport(
        mode=NATIVE_BACKEND_READINESS_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=NATIVE_BACKEND_READINESS_GUARD,
        source_probe_policy=probe_report.probe_policy,
        readiness_policy=readiness_policy(assessments),
        native_action_allowed=False,
        assessment_count=len(assessments),
        ready_observation_count=count_status(
            assessments,
            "ready-readonly-observation",
        ),
        advisory_ready_count=count_status(
            assessments,
            "ready-advisory-loop",
        ),
        needs_evidence_count=count_needs_evidence(assessments),
        native_blocked_count=count_status(
            assessments,
            "blocked-native-safety-boundary",
        ),
        high_risk_count=sum(
            1 for assessment in assessments if assessment.risk_level == "high"
        ),
        total_signal_count=sum(
            assessment.signal_count for assessment in assessments
        ),
        cpu_signal_ready=any(cpu_signal_ready(step) for step in probe_report.steps),
        memory_signal_ready=probe_report.memory_signal_count >= 4,
        gpu_signal_ready=probe_report.gpu_signal_count >= 3,
        assessments=assessments,
    )


def assess_probe_step(
    index: int,
    step: RuntimeNativeBackendProbeStep,
) -> RuntimeNativeBackendReadinessAssessment:
    status = readiness_status(step)
    score = readiness_score(step, status)
    blockers = readiness_blockers(step, status)
    return RuntimeNativeBackendReadinessAssessment(
        assessment_id=f"native.readiness.{index:03d}",
        source_step_id=step.step_id,
        backend_id=step.backend_id,
        control_surface=step.control_surface,
        readiness_status=status,
        readiness_score=score,
        risk_level=risk_level(status, score),
        signal_quality=signal_quality(step, status),
        native_action_allowed=False,
        would_modify_system=False,
        blocker_count=len(blockers),
        blockers=blockers,
        signal_count=step.signal_count,
        required_next_evidence=required_next_evidence(step, status),
        recommended_next_step=recommended_next_step(status),
        reason=readiness_reason(step, status, score),
    )


def readiness_status(step: RuntimeNativeBackendProbeStep) -> str:
    if step.probe_status == "blocked-native-backend-probe":
        return "blocked-native-safety-boundary"
    if step.probe_status == "blocked-missing-host-snapshot":
        return "needs-host-snapshot"
    if step.probe_status == "executed-readonly-host-snapshot-probe":
        if host_signal_complete(step):
            return "ready-readonly-observation"
        return "partial-readonly-evidence"
    if step.probe_status == "executed-advisory-contract-probe":
        if step.signal_count >= 5:
            return "ready-advisory-loop"
        return "partial-advisory-evidence"
    return "blocked-advisory-evidence"


def readiness_score(
    step: RuntimeNativeBackendProbeStep,
    status: str,
) -> int:
    if status == "ready-readonly-observation":
        return 80
    if status == "ready-advisory-loop":
        return 70
    if status in {"partial-readonly-evidence", "partial-advisory-evidence"}:
        return min(45 + step.signal_count * 3, 65)
    if status == "needs-host-snapshot":
        return 10
    if status == "blocked-native-safety-boundary":
        return 0
    return 20


def risk_level(status: str, score: int) -> str:
    if status == "blocked-native-safety-boundary":
        return "high"
    if status.startswith("partial") or status == "needs-host-snapshot":
        return "medium"
    if score >= 70:
        return "low"
    return "medium"


def signal_quality(
    step: RuntimeNativeBackendProbeStep,
    status: str,
) -> str:
    if status == "blocked-native-safety-boundary":
        return "blocked"
    if step.signal_count == 0:
        return "none"
    if status.startswith("partial"):
        return "partial"
    return "sufficient"


def readiness_blockers(
    step: RuntimeNativeBackendProbeStep,
    status: str,
) -> list[str]:
    blockers = list(step.blocked_by)
    if status == "partial-readonly-evidence":
        blockers.extend(missing_host_signal_groups(step))
    if status == "partial-advisory-evidence":
        blockers.append("daemon-contract-signals")
    return blockers


def required_next_evidence(
    step: RuntimeNativeBackendProbeStep,
    status: str,
) -> list[str]:
    if status == "blocked-native-safety-boundary":
        return [
            "native-backend-implementation",
            "privilege-model",
            "safety-review",
        ]
    if status == "needs-host-snapshot":
        return ["host-capability-snapshot"]
    if status == "partial-readonly-evidence":
        return missing_host_signal_groups(step)
    if status == "partial-advisory-evidence":
        return ["daemon-contract-signals"]
    return []


def recommended_next_step(status: str) -> str:
    if status == "ready-readonly-observation":
        return "continue-readonly-telemetry-loop"
    if status == "ready-advisory-loop":
        return "continue-advisory-daemon-loop"
    if status == "blocked-native-safety-boundary":
        return "keep-native-control-blocked"
    if status == "needs-host-snapshot":
        return "collect-host-snapshot-before-control"
    return "collect-more-readonly-evidence"


def readiness_reason(
    step: RuntimeNativeBackendProbeStep,
    status: str,
    score: int,
) -> str:
    if status == "blocked-native-safety-boundary":
        return (
            "Native surface remains blocked before host mutation; "
            f"readiness score {score}."
        )
    if status == "needs-host-snapshot":
        return (
            "Read-only readiness cannot be assessed until host capability "
            f"evidence exists; readiness score {score}."
        )
    return (
        f"Probe status {step.probe_status} produced {step.signal_count} "
        f"signals; readiness score {score}."
    )


def readiness_policy(
    assessments: list[RuntimeNativeBackendReadinessAssessment],
) -> str:
    native_blocked = any(
        assessment.readiness_status == "blocked-native-safety-boundary"
        for assessment in assessments
    )
    ready = any(
        assessment.readiness_status
        in {"ready-readonly-observation", "ready-advisory-loop"}
        for assessment in assessments
    )
    needs_evidence = any(
        assessment.readiness_status
        in {
            "needs-host-snapshot",
            "partial-readonly-evidence",
            "partial-advisory-evidence",
        }
        for assessment in assessments
    )
    if native_blocked and ready:
        return "continue-safe-observation-hold-native"
    if native_blocked:
        return "hold-native-until-safety-review"
    if needs_evidence:
        return "collect-readonly-evidence"
    if any(
        assessment.readiness_status == "ready-readonly-observation"
        for assessment in assessments
    ):
        return "readonly-evidence-ready"
    if any(
        assessment.readiness_status == "ready-advisory-loop"
        for assessment in assessments
    ):
        return "advisory-loop-ready"
    return "observe"


def count_status(
    assessments: list[RuntimeNativeBackendReadinessAssessment],
    status: str,
) -> int:
    return sum(
        1 for assessment in assessments if assessment.readiness_status == status
    )


def count_needs_evidence(
    assessments: list[RuntimeNativeBackendReadinessAssessment],
) -> int:
    return sum(
        1
        for assessment in assessments
        if assessment.readiness_status
        in {
            "needs-host-snapshot",
            "partial-readonly-evidence",
            "partial-advisory-evidence",
        }
    )


def host_signal_complete(step: RuntimeNativeBackendProbeStep) -> bool:
    return (
        cpu_signal_ready(step)
        and memory_signal_ready(step)
        and gpu_signal_ready(step)
    )


def cpu_signal_ready(step: RuntimeNativeBackendProbeStep) -> bool:
    return step.signals.get("cpu_logical_count") is not None


def memory_signal_ready(step: RuntimeNativeBackendProbeStep) -> bool:
    keys = {
        "total_ram_mb",
        "available_ram_mb",
        "ram_pressure_pct",
        "ram_pressure_class",
    }
    return all(step.signals.get(key) is not None for key in keys)


def gpu_signal_ready(step: RuntimeNativeBackendProbeStep) -> bool:
    keys = {"gpu_count", "gpu_class", "total_reported_vram_mb"}
    return all(step.signals.get(key) is not None for key in keys)


def missing_host_signal_groups(step: RuntimeNativeBackendProbeStep) -> list[str]:
    missing: list[str] = []
    if not cpu_signal_ready(step):
        missing.append("cpu-signal")
    if not memory_signal_ready(step):
        missing.append("memory-signal")
    if not gpu_signal_ready(step):
        missing.append("gpu-vram-signal")
    return missing
