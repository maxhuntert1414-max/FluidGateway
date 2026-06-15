from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_actions import RuntimeDaemonActionQueue, RuntimeDaemonQueuedAction


DAEMON_ACTION_EXECUTION_MODE = "runtime-daemon-action-execution-v0.50"
DAEMON_ACTION_EXECUTION_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonActionExecutionResult:
    queue_id: str
    source_action_id: str
    domain: str
    backend: str
    operation: str
    execution_status: str
    dry_run: bool
    would_modify_system: bool
    blocked: bool
    observed_signal: str
    safety_boundary: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "source_action_id": self.source_action_id,
            "domain": self.domain,
            "backend": self.backend,
            "operation": self.operation,
            "execution_status": self.execution_status,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "blocked": self.blocked,
            "observed_signal": self.observed_signal,
            "safety_boundary": self.safety_boundary,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeDaemonActionExecution:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_queue_policy: str
    execution_policy: str
    action_count: int
    executed_readonly_count: int
    executed_advisory_count: int
    blocked_native_count: int
    blocked_privileged_count: int
    blocked_count: int
    telemetry_execution_count: int
    scheduler_execution_count: int
    memory_execution_count: int
    gpu_execution_count: int
    safety_execution_count: int
    results: list[RuntimeDaemonActionExecutionResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_queue_policy": self.source_queue_policy,
            "execution_policy": self.execution_policy,
            "action_count": self.action_count,
            "executed_readonly_count": self.executed_readonly_count,
            "executed_advisory_count": self.executed_advisory_count,
            "blocked_native_count": self.blocked_native_count,
            "blocked_privileged_count": self.blocked_privileged_count,
            "blocked_count": self.blocked_count,
            "telemetry_execution_count": self.telemetry_execution_count,
            "scheduler_execution_count": self.scheduler_execution_count,
            "memory_execution_count": self.memory_execution_count,
            "gpu_execution_count": self.gpu_execution_count,
            "safety_execution_count": self.safety_execution_count,
            "results": [result.to_dict() for result in self.results],
        }


def dry_run_runtime_daemon_action_queue(
    action_queue: RuntimeDaemonActionQueue,
) -> RuntimeDaemonActionExecution:
    results = [
        dry_run_runtime_daemon_action(action)
        for action in action_queue.actions
    ]
    executed_readonly_count = count_status(results, "executed-readonly-dry-run")
    executed_advisory_count = count_status(results, "executed-advisory-dry-run")
    blocked_native_count = sum(
        1
        for action, result in zip(action_queue.actions, results)
        if result.blocked and action.requires_native_backend
    )
    blocked_privileged_count = sum(
        1
        for action, result in zip(action_queue.actions, results)
        if result.blocked and action.requires_privilege
    )
    blocked_count = sum(1 for result in results if result.blocked)
    return RuntimeDaemonActionExecution(
        mode=DAEMON_ACTION_EXECUTION_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_ACTION_EXECUTION_GUARD,
        source_queue_policy=action_queue.queue_policy,
        execution_policy=execution_policy(
            executed_readonly_count=executed_readonly_count,
            executed_advisory_count=executed_advisory_count,
            blocked_native_count=blocked_native_count,
        ),
        action_count=len(results),
        executed_readonly_count=executed_readonly_count,
        executed_advisory_count=executed_advisory_count,
        blocked_native_count=blocked_native_count,
        blocked_privileged_count=blocked_privileged_count,
        blocked_count=blocked_count,
        telemetry_execution_count=count_executed_domain(results, "telemetry"),
        scheduler_execution_count=count_executed_domain(results, "scheduler"),
        memory_execution_count=count_executed_domain(results, "memory"),
        gpu_execution_count=count_executed_domain(results, "gpu"),
        safety_execution_count=count_executed_domain(results, "safety"),
        results=results,
    )


def dry_run_runtime_daemon_action(
    action: RuntimeDaemonQueuedAction,
) -> RuntimeDaemonActionExecutionResult:
    blocked = (
        not action.would_apply
        or action.requires_native_backend
        or action.requires_privilege
    )
    return RuntimeDaemonActionExecutionResult(
        queue_id=action.queue_id,
        source_action_id=action.source_action_id,
        domain=action.domain,
        backend=action.backend,
        operation=action.operation,
        execution_status=action_execution_status(action, blocked),
        dry_run=True,
        would_modify_system=False,
        blocked=blocked,
        observed_signal=action.expected_signal,
        safety_boundary=action.safety_boundary,
        reason=action_execution_reason(action, blocked),
    )


def action_execution_status(
    action: RuntimeDaemonQueuedAction,
    blocked: bool,
) -> str:
    if blocked:
        if action.requires_native_backend and action.requires_privilege:
            return "blocked-privileged-native-backend-required"
        if action.requires_native_backend:
            return "blocked-native-backend-required"
        if action.requires_privilege:
            return "blocked-privilege-required"
        return "blocked-by-action-queue"
    if action.dry_run_status == "would-apply-readonly":
        return "executed-readonly-dry-run"
    return "executed-advisory-dry-run"


def action_execution_reason(
    action: RuntimeDaemonQueuedAction,
    blocked: bool,
) -> str:
    if blocked:
        return (
            "Execution held by advisory-only guard before any system mutation: "
            f"{action.reason}"
        )
    if action.dry_run_status == "would-apply-readonly":
        return f"Read-only probe evaluated by dry-run executor: {action.reason}"
    return f"Advisory action evaluated by dry-run executor: {action.reason}"


def execution_policy(
    executed_readonly_count: int,
    executed_advisory_count: int,
    blocked_native_count: int,
) -> str:
    if blocked_native_count:
        return "hold-native-backend-actions"
    if executed_readonly_count:
        return "execute-readonly-telemetry"
    if executed_advisory_count:
        return "execute-advisory-loop"
    return "observe-only"


def count_status(
    results: list[RuntimeDaemonActionExecutionResult],
    status: str,
) -> int:
    return sum(1 for result in results if result.execution_status == status)


def count_executed_domain(
    results: list[RuntimeDaemonActionExecutionResult],
    domain: str,
) -> int:
    return sum(
        1
        for result in results
        if result.domain == domain and not result.blocked
    )
