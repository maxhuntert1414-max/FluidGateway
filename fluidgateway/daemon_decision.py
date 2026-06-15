from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .host import HostCapabilitySnapshot
from .state_accumulator import RuntimeStateAccumulator


DAEMON_DECISION_PLAN_MODE = "runtime-daemon-decision-plan-v0.48"
DAEMON_DECISION_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonDecisionAction:
    action_id: str
    domain: str
    phase: str
    priority: str
    action: str
    target: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "domain": self.domain,
            "phase": self.phase,
            "priority": self.priority,
            "action": self.action,
            "target": self.target,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeDaemonDecisionPlan:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_host_profile: str
    source_host_manager_hint: str
    source_execution_action: str
    source_supervisor_action: str
    source_state_digest: str
    decision_action: str
    risk_level: str
    confidence: str
    action_count: int
    scheduler_action_count: int
    memory_action_count: int
    gpu_action_count: int
    telemetry_action_count: int
    safety_action_count: int
    actions: list[RuntimeDaemonDecisionAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_host_profile": self.source_host_profile,
            "source_host_manager_hint": self.source_host_manager_hint,
            "source_execution_action": self.source_execution_action,
            "source_supervisor_action": self.source_supervisor_action,
            "source_state_digest": self.source_state_digest,
            "decision_action": self.decision_action,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "action_count": self.action_count,
            "scheduler_action_count": self.scheduler_action_count,
            "memory_action_count": self.memory_action_count,
            "gpu_action_count": self.gpu_action_count,
            "telemetry_action_count": self.telemetry_action_count,
            "safety_action_count": self.safety_action_count,
            "actions": [action.to_dict() for action in self.actions],
        }


def build_runtime_daemon_decision_plan(
    *,
    final_state: RuntimeStateAccumulator,
    host_snapshot: HostCapabilitySnapshot | None,
    final_execution_action: str,
    final_supervisor_action: str,
    total_would_block_count: int,
) -> RuntimeDaemonDecisionPlan:
    actions: list[RuntimeDaemonDecisionAction] = []
    host_profile = host_snapshot.host_profile if host_snapshot else "unknown-host"
    host_hint = host_snapshot.manager_hint if host_snapshot else "collect-host-telemetry"
    telemetry_confidence = (
        host_snapshot.telemetry_confidence if host_snapshot else "low"
    )

    if host_snapshot is None or telemetry_confidence == "low":
        actions.append(
            decision_action(
                "daemon.telemetry.collect-host",
                "telemetry",
                "next-cycle",
                "high",
                "collect-host-telemetry",
                "cpu-ram-gpu-vram",
                "Host evidence is missing or too weak for host-aware management.",
            )
        )

    if host_hint == "collect-more-host-telemetry":
        actions.append(
            decision_action(
                "daemon.telemetry.expand-host",
                "telemetry",
                "next-cycle",
                "medium",
                "collect-more-host-telemetry",
                "host-capability-model",
                "The host snapshot exists but does not yet prove a specific gaming-host class.",
            )
        )

    if memory_pressure_required(final_state, host_snapshot):
        actions.append(
            decision_action(
                "daemon.memory.tighten-residency",
                "memory",
                "next-cycle",
                "high",
                "tighten-memory-residency-observation",
                "ram-vram-residency",
                "Runtime or host evidence indicates memory pressure or active memory relief.",
            )
        )

    if low_residency_required(host_snapshot):
        actions.append(
            decision_action(
                "daemon.admission.low-residency",
                "memory",
                "next-cycle",
                "medium",
                "prefer-low-residency-and-short-hot-path",
                "copy-and-upload-admission",
                "Host capability suggests tighter residency and shorter hot-path work.",
            )
        )

    if supervisor_loop_allowed(host_snapshot, final_execution_action):
        actions.append(
            decision_action(
                "daemon.scheduler.allow-supervisor-loop",
                "scheduler",
                "next-cycle",
                "medium",
                "allow-daemon-supervisor-loop",
                "runtime-supervisor",
                "Host and supervisor evidence allow the daemon to continue the advisory supervisor loop.",
            )
        )

    if gpu_telemetry_required(host_snapshot):
        actions.append(
            decision_action(
                "daemon.gpu.collect-telemetry",
                "gpu",
                "next-cycle",
                "medium",
                "collect-gpu-telemetry-before-gpu-specific-actions",
                "gpu-vram-queues",
                "GPU-specific management should wait for better GPU and VRAM telemetry.",
            )
        )

    if total_would_block_count > 0:
        actions.append(
            decision_action(
                "daemon.safety.hold-blocking-commands",
                "safety",
                "next-cycle",
                "high",
                "hold-blocking-supervisor-commands",
                "runtime-supervisor-execution",
                "The supervisor dry-run marked commands as blocking, so the daemon should not promote them.",
            )
        )

    if not actions:
        actions.append(
            decision_action(
                "daemon.scheduler.preserve-loop",
                "scheduler",
                "next-cycle",
                "low",
                "preserve-observed-daemon-loop",
                "runtime-daemon",
                "No host or supervisor pressure requires a posture change.",
            )
        )

    return RuntimeDaemonDecisionPlan(
        mode=DAEMON_DECISION_PLAN_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_DECISION_GUARD,
        source_host_profile=host_profile,
        source_host_manager_hint=host_hint,
        source_execution_action=final_execution_action,
        source_supervisor_action=final_supervisor_action,
        source_state_digest=final_state.state_digest,
        decision_action=plan_decision_action(actions),
        risk_level=plan_risk_level(actions),
        confidence=plan_confidence(telemetry_confidence, actions),
        action_count=len(actions),
        scheduler_action_count=count_domain(actions, "scheduler"),
        memory_action_count=count_domain(actions, "memory"),
        gpu_action_count=count_domain(actions, "gpu"),
        telemetry_action_count=count_domain(actions, "telemetry"),
        safety_action_count=count_domain(actions, "safety"),
        actions=actions,
    )


def decision_action(
    action_id: str,
    domain: str,
    phase: str,
    priority: str,
    action: str,
    target: str,
    reason: str,
) -> RuntimeDaemonDecisionAction:
    return RuntimeDaemonDecisionAction(
        action_id=action_id,
        domain=domain,
        phase=phase,
        priority=priority,
        action=action,
        target=target,
        reason=reason,
    )


def memory_pressure_required(
    state: RuntimeStateAccumulator,
    host_snapshot: HostCapabilitySnapshot | None,
) -> bool:
    if state.memory_relief_target_mb > 0 or state.memory_headroom_target_mb > 0:
        return True
    if state.policy_action in {
        "continue-runtime-pressure-policy",
        "tighten-runtime-pressure-policy",
    }:
        return True
    if host_snapshot is None:
        return False
    return host_snapshot.manager_hint == "tighten-memory-residency-observation"


def low_residency_required(host_snapshot: HostCapabilitySnapshot | None) -> bool:
    if host_snapshot is None:
        return False
    return host_snapshot.manager_hint == "prefer-low-residency-and-short-hot-path"


def supervisor_loop_allowed(
    host_snapshot: HostCapabilitySnapshot | None,
    final_execution_action: str,
) -> bool:
    if host_snapshot is None:
        return False
    if host_snapshot.manager_hint != "allow-daemon-supervisor-loop":
        return False
    return final_execution_action in {
        "dry-run-relaxed-supervisor-commands",
        "dry-run-preserved-supervisor-commands",
        "dry-run-monitored-supervisor-commands",
        "dry-run-observation-supervisor-commands",
    }


def gpu_telemetry_required(host_snapshot: HostCapabilitySnapshot | None) -> bool:
    if host_snapshot is None:
        return False
    return host_snapshot.manager_hint == "collect-gpu-telemetry-before-gpu-specific-actions"


def plan_decision_action(actions: list[RuntimeDaemonDecisionAction]) -> str:
    if any(action.domain == "safety" for action in actions):
        return "hold-daemon-supervisor-promotion"
    if any(action.action == "tighten-memory-residency-observation" for action in actions):
        return "tighten-daemon-memory-observation"
    if any(action.action == "allow-daemon-supervisor-loop" for action in actions):
        return "continue-host-aware-supervisor-loop"
    if any(action.domain == "telemetry" for action in actions):
        return "expand-daemon-telemetry"
    return "preserve-daemon-loop"


def plan_risk_level(actions: list[RuntimeDaemonDecisionAction]) -> str:
    priorities = {action.priority for action in actions}
    if "high" in priorities:
        return "high"
    if "medium" in priorities:
        return "medium"
    return "low"


def plan_confidence(
    telemetry_confidence: str,
    actions: list[RuntimeDaemonDecisionAction],
) -> str:
    if any(action.domain == "telemetry" for action in actions):
        return "medium" if telemetry_confidence == "high" else "low"
    return telemetry_confidence if telemetry_confidence in {"high", "medium"} else "low"


def count_domain(actions: list[RuntimeDaemonDecisionAction], domain: str) -> int:
    return sum(1 for action in actions if action.domain == domain)
