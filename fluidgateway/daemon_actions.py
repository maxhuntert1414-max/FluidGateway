from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_decision import (
    RuntimeDaemonDecisionAction,
    RuntimeDaemonDecisionPlan,
)


DAEMON_ACTION_QUEUE_MODE = "runtime-daemon-action-queue-v0.49"
DAEMON_ACTION_QUEUE_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonQueuedAction:
    queue_id: str
    source_action_id: str
    domain: str
    backend: str
    phase: str
    priority: str
    dry_run_status: str
    would_apply: bool
    would_modify_system: bool
    requires_native_backend: bool
    requires_privilege: bool
    target: str
    operation: str
    expected_signal: str
    safety_boundary: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "source_action_id": self.source_action_id,
            "domain": self.domain,
            "backend": self.backend,
            "phase": self.phase,
            "priority": self.priority,
            "dry_run_status": self.dry_run_status,
            "would_apply": self.would_apply,
            "would_modify_system": self.would_modify_system,
            "requires_native_backend": self.requires_native_backend,
            "requires_privilege": self.requires_privilege,
            "target": self.target,
            "operation": self.operation,
            "expected_signal": self.expected_signal,
            "safety_boundary": self.safety_boundary,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeDaemonActionQueue:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_decision_action: str
    source_risk_level: str
    queue_policy: str
    queued_action_count: int
    would_apply_count: int
    blocked_action_count: int
    native_backend_required_count: int
    privileged_action_count: int
    telemetry_action_count: int
    scheduler_action_count: int
    memory_action_count: int
    gpu_action_count: int
    safety_action_count: int
    actions: list[RuntimeDaemonQueuedAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_decision_action": self.source_decision_action,
            "source_risk_level": self.source_risk_level,
            "queue_policy": self.queue_policy,
            "queued_action_count": self.queued_action_count,
            "would_apply_count": self.would_apply_count,
            "blocked_action_count": self.blocked_action_count,
            "native_backend_required_count": self.native_backend_required_count,
            "privileged_action_count": self.privileged_action_count,
            "telemetry_action_count": self.telemetry_action_count,
            "scheduler_action_count": self.scheduler_action_count,
            "memory_action_count": self.memory_action_count,
            "gpu_action_count": self.gpu_action_count,
            "safety_action_count": self.safety_action_count,
            "actions": [action.to_dict() for action in self.actions],
        }


def build_runtime_daemon_action_queue(
    decision_plan: RuntimeDaemonDecisionPlan,
) -> RuntimeDaemonActionQueue:
    actions = [
        queued_action_from_decision(index + 1, action)
        for index, action in enumerate(decision_plan.actions)
    ]
    blocked_count = sum(1 for action in actions if not action.would_apply)
    native_required_count = sum(
        1 for action in actions if action.requires_native_backend
    )
    privileged_count = sum(1 for action in actions if action.requires_privilege)
    return RuntimeDaemonActionQueue(
        mode=DAEMON_ACTION_QUEUE_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_ACTION_QUEUE_GUARD,
        source_decision_action=decision_plan.decision_action,
        source_risk_level=decision_plan.risk_level,
        queue_policy=queue_policy(actions, blocked_count),
        queued_action_count=len(actions),
        would_apply_count=sum(1 for action in actions if action.would_apply),
        blocked_action_count=blocked_count,
        native_backend_required_count=native_required_count,
        privileged_action_count=privileged_count,
        telemetry_action_count=count_domain(actions, "telemetry"),
        scheduler_action_count=count_domain(actions, "scheduler"),
        memory_action_count=count_domain(actions, "memory"),
        gpu_action_count=count_domain(actions, "gpu"),
        safety_action_count=count_domain(actions, "safety"),
        actions=actions,
    )


def queued_action_from_decision(
    index: int,
    action: RuntimeDaemonDecisionAction,
) -> RuntimeDaemonQueuedAction:
    shape = action_shape(action)
    blocked = bool(shape["blocked"])
    return RuntimeDaemonQueuedAction(
        queue_id=f"daemon.queue.{index:03d}",
        source_action_id=action.action_id,
        domain=action.domain,
        backend=str(shape["backend"]),
        phase=action.phase,
        priority=action.priority,
        dry_run_status=str(shape["dry_run_status"]),
        would_apply=not blocked,
        would_modify_system=False,
        requires_native_backend=bool(shape["requires_native_backend"]),
        requires_privilege=bool(shape["requires_privilege"]),
        target=action.target,
        operation=str(shape["operation"]),
        expected_signal=str(shape["expected_signal"]),
        safety_boundary=str(shape["safety_boundary"]),
        reason=action.reason,
    )


def action_shape(action: RuntimeDaemonDecisionAction) -> dict[str, str | bool]:
    if action.action == "collect-host-telemetry":
        return readonly_shape(
            "host-telemetry-probe",
            "probe-host-capabilities",
            "updated-host-snapshot",
        )
    if action.action == "collect-more-host-telemetry":
        return readonly_shape(
            "host-telemetry-probe",
            "probe-extended-host-capabilities",
            "expanded-host-snapshot",
        )
    if action.action == "collect-gpu-telemetry-before-gpu-specific-actions":
        return readonly_shape(
            "gpu-telemetry-probe",
            "probe-gpu-vram-and-queue-signals",
            "updated-gpu-telemetry",
        )
    if action.action == "allow-daemon-supervisor-loop":
        return advisory_shape(
            "advisory-supervisor-loop",
            "continue-supervisor-loop",
            "next-daemon-cycle",
        )
    if action.action == "preserve-observed-daemon-loop":
        return advisory_shape(
            "advisory-daemon-loop",
            "preserve-current-loop",
            "next-daemon-cycle",
        )
    if action.action == "hold-blocking-supervisor-commands":
        return advisory_shape(
            "safety-gate",
            "hold-blocking-commands",
            "blocked-command-report",
        )
    if action.action in {
        "tighten-memory-residency-observation",
        "prefer-low-residency-and-short-hot-path",
    }:
        return native_blocked_shape(
            "native-memory-adapter",
            action.action,
            "native-memory-backend-required",
        )
    return advisory_shape(
        "advisory-daemon-loop",
        action.action,
        "queued-advisory-action",
    )


def readonly_shape(
    backend: str,
    operation: str,
    expected_signal: str,
) -> dict[str, str | bool]:
    return {
        "backend": backend,
        "operation": operation,
        "expected_signal": expected_signal,
        "dry_run_status": "would-apply-readonly",
        "blocked": False,
        "requires_native_backend": False,
        "requires_privilege": False,
        "safety_boundary": "read-only-host-probe",
    }


def advisory_shape(
    backend: str,
    operation: str,
    expected_signal: str,
) -> dict[str, str | bool]:
    return {
        "backend": backend,
        "operation": operation,
        "expected_signal": expected_signal,
        "dry_run_status": "would-apply-advisory",
        "blocked": False,
        "requires_native_backend": False,
        "requires_privilege": False,
        "safety_boundary": "advisory-only",
    }


def native_blocked_shape(
    backend: str,
    operation: str,
    expected_signal: str,
) -> dict[str, str | bool]:
    return {
        "backend": backend,
        "operation": operation,
        "expected_signal": expected_signal,
        "dry_run_status": "blocked-native-backend-required",
        "blocked": True,
        "requires_native_backend": True,
        "requires_privilege": True,
        "safety_boundary": "blocked-before-system-mutation",
    }


def queue_policy(
    actions: list[RuntimeDaemonQueuedAction],
    blocked_count: int,
) -> str:
    if any(action.domain == "safety" for action in actions):
        return "hold-native-promotion"
    if blocked_count:
        return "queue-native-backend-work"
    if any(action.domain == "telemetry" for action in actions):
        return "run-readonly-telemetry-before-native-work"
    if any(action.domain == "scheduler" for action in actions):
        return "continue-advisory-loop"
    return "observe-only"


def count_domain(actions: list[RuntimeDaemonQueuedAction], domain: str) -> int:
    return sum(1 for action in actions if action.domain == domain)
