from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_actions import RuntimeDaemonActionQueue, RuntimeDaemonQueuedAction
from .daemon_execution import (
    RuntimeDaemonActionExecution,
    RuntimeDaemonActionExecutionResult,
)


NATIVE_BACKEND_PREFLIGHT_MODE = "runtime-native-backend-preflight-v0.51"
NATIVE_BACKEND_PREFLIGHT_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeNativeBackendCapability:
    capability_id: str
    domain: str
    backend: str
    required_interface: str
    capability_status: str
    available_now: bool
    requires_native_backend: bool
    requires_privilege: bool
    requires_safety_review: bool
    native_promotion_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "domain": self.domain,
            "backend": self.backend,
            "required_interface": self.required_interface,
            "capability_status": self.capability_status,
            "available_now": self.available_now,
            "requires_native_backend": self.requires_native_backend,
            "requires_privilege": self.requires_privilege,
            "requires_safety_review": self.requires_safety_review,
            "native_promotion_allowed": self.native_promotion_allowed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeNativeBackendRequirement:
    queue_id: str
    source_action_id: str
    domain: str
    backend: str
    operation: str
    required_capability: str
    preflight_status: str
    can_execute_now: bool
    can_promote_to_native: bool
    blocked_by: list[str]
    requires_native_backend: bool
    requires_privilege: bool
    requires_safety_review: bool
    would_modify_system: bool
    safety_boundary: str
    expected_signal: str
    execution_status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "source_action_id": self.source_action_id,
            "domain": self.domain,
            "backend": self.backend,
            "operation": self.operation,
            "required_capability": self.required_capability,
            "preflight_status": self.preflight_status,
            "can_execute_now": self.can_execute_now,
            "can_promote_to_native": self.can_promote_to_native,
            "blocked_by": self.blocked_by,
            "requires_native_backend": self.requires_native_backend,
            "requires_privilege": self.requires_privilege,
            "requires_safety_review": self.requires_safety_review,
            "would_modify_system": self.would_modify_system,
            "safety_boundary": self.safety_boundary,
            "expected_signal": self.expected_signal,
            "execution_status": self.execution_status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeNativeBackendPreflight:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    native_promotion_allowed: bool
    source_queue_policy: str
    source_execution_policy: str
    backend_policy: str
    requirement_count: int
    advisory_safe_count: int
    blocked_requirement_count: int
    missing_native_backend_count: int
    privilege_required_count: int
    safety_review_required_count: int
    telemetry_requirement_count: int
    scheduler_requirement_count: int
    memory_requirement_count: int
    gpu_requirement_count: int
    safety_requirement_count: int
    capabilities: list[RuntimeNativeBackendCapability]
    requirements: list[RuntimeNativeBackendRequirement]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "native_promotion_allowed": self.native_promotion_allowed,
            "source_queue_policy": self.source_queue_policy,
            "source_execution_policy": self.source_execution_policy,
            "backend_policy": self.backend_policy,
            "requirement_count": self.requirement_count,
            "advisory_safe_count": self.advisory_safe_count,
            "blocked_requirement_count": self.blocked_requirement_count,
            "missing_native_backend_count": self.missing_native_backend_count,
            "privilege_required_count": self.privilege_required_count,
            "safety_review_required_count": self.safety_review_required_count,
            "telemetry_requirement_count": self.telemetry_requirement_count,
            "scheduler_requirement_count": self.scheduler_requirement_count,
            "memory_requirement_count": self.memory_requirement_count,
            "gpu_requirement_count": self.gpu_requirement_count,
            "safety_requirement_count": self.safety_requirement_count,
            "capabilities": [
                capability.to_dict() for capability in self.capabilities
            ],
            "requirements": [
                requirement.to_dict() for requirement in self.requirements
            ],
        }


def build_runtime_native_backend_preflight(
    action_queue: RuntimeDaemonActionQueue,
    action_execution: RuntimeDaemonActionExecution,
) -> RuntimeNativeBackendPreflight:
    execution_by_queue_id = {
        result.queue_id: result for result in action_execution.results
    }
    capabilities = [
        capability_from_action(action)
        for action in action_queue.actions
    ]
    requirements = [
        requirement_from_action(
            action,
            execution_by_queue_id.get(action.queue_id),
        )
        for action in action_queue.actions
    ]
    blocked_requirement_count = sum(
        1 for requirement in requirements if not requirement.can_execute_now
    )
    missing_native_backend_count = sum(
        1 for requirement in requirements if requirement.requires_native_backend
    )
    privilege_required_count = sum(
        1 for requirement in requirements if requirement.requires_privilege
    )
    safety_review_required_count = sum(
        1 for requirement in requirements if requirement.requires_safety_review
    )
    return RuntimeNativeBackendPreflight(
        mode=NATIVE_BACKEND_PREFLIGHT_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=NATIVE_BACKEND_PREFLIGHT_GUARD,
        native_promotion_allowed=False,
        source_queue_policy=action_queue.queue_policy,
        source_execution_policy=action_execution.execution_policy,
        backend_policy=backend_policy(
            blocked_requirement_count=blocked_requirement_count,
            missing_native_backend_count=missing_native_backend_count,
        ),
        requirement_count=len(requirements),
        advisory_safe_count=sum(
            1 for requirement in requirements if requirement.can_execute_now
        ),
        blocked_requirement_count=blocked_requirement_count,
        missing_native_backend_count=missing_native_backend_count,
        privilege_required_count=privilege_required_count,
        safety_review_required_count=safety_review_required_count,
        telemetry_requirement_count=count_domain(requirements, "telemetry"),
        scheduler_requirement_count=count_domain(requirements, "scheduler"),
        memory_requirement_count=count_domain(requirements, "memory"),
        gpu_requirement_count=count_domain(requirements, "gpu"),
        safety_requirement_count=count_domain(requirements, "safety"),
        capabilities=capabilities,
        requirements=requirements,
    )


def capability_from_action(
    action: RuntimeDaemonQueuedAction,
) -> RuntimeNativeBackendCapability:
    requires_safety_review = (
        action.requires_native_backend
        or action.requires_privilege
        or action.would_modify_system
    )
    return RuntimeNativeBackendCapability(
        capability_id=f"{action.domain}:{action.backend}",
        domain=action.domain,
        backend=action.backend,
        required_interface=required_interface(action),
        capability_status=capability_status(action),
        available_now=not requires_safety_review,
        requires_native_backend=action.requires_native_backend,
        requires_privilege=action.requires_privilege,
        requires_safety_review=requires_safety_review,
        native_promotion_allowed=False,
        reason=capability_reason(action, requires_safety_review),
    )


def requirement_from_action(
    action: RuntimeDaemonQueuedAction,
    execution_result: RuntimeDaemonActionExecutionResult | None,
) -> RuntimeNativeBackendRequirement:
    blocked_by = preflight_blockers(action)
    can_execute_now = not blocked_by
    return RuntimeNativeBackendRequirement(
        queue_id=action.queue_id,
        source_action_id=action.source_action_id,
        domain=action.domain,
        backend=action.backend,
        operation=action.operation,
        required_capability=f"{action.domain}:{action.backend}",
        preflight_status=preflight_status(action, blocked_by),
        can_execute_now=can_execute_now,
        can_promote_to_native=False,
        blocked_by=blocked_by,
        requires_native_backend=action.requires_native_backend,
        requires_privilege=action.requires_privilege,
        requires_safety_review=bool(blocked_by),
        would_modify_system=False,
        safety_boundary=action.safety_boundary,
        expected_signal=action.expected_signal,
        execution_status=execution_status(execution_result),
        reason=preflight_reason(action, blocked_by),
    )


def required_interface(action: RuntimeDaemonQueuedAction) -> str:
    if action.requires_native_backend:
        return "native-host-control-backend"
    if action.dry_run_status == "would-apply-readonly":
        return "python-stdlib-readonly-probe"
    return "daemon-advisory-loop"


def capability_status(action: RuntimeDaemonQueuedAction) -> str:
    if action.requires_native_backend and action.requires_privilege:
        return "missing-privileged-native-backend"
    if action.requires_native_backend:
        return "missing-native-backend"
    if action.dry_run_status == "would-apply-readonly":
        return "available-readonly-dry-run"
    return "available-advisory-dry-run"


def capability_reason(
    action: RuntimeDaemonQueuedAction,
    requires_safety_review: bool,
) -> str:
    if requires_safety_review:
        return (
            "Native host control is not implemented in v0.51; capability is "
            "blocked until a backend and safety review exist."
        )
    if action.dry_run_status == "would-apply-readonly":
        return "Read-only capability can be evaluated by the Python dry-run loop."
    return "Advisory capability can be evaluated without mutating the host."


def preflight_blockers(action: RuntimeDaemonQueuedAction) -> list[str]:
    blockers: list[str] = []
    if not action.would_apply:
        blockers.append("action-queue")
    if action.requires_native_backend:
        blockers.append("native-backend")
    if action.requires_privilege:
        blockers.append("privilege")
    if action.requires_native_backend or action.requires_privilege:
        blockers.append("safety-review")
    return blockers


def preflight_status(
    action: RuntimeDaemonQueuedAction,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        if "native-backend" in blocked_by and "privilege" in blocked_by:
            return "blocked-privileged-native-backend-required"
        if "native-backend" in blocked_by:
            return "blocked-native-backend-required"
        return "blocked-by-advisory-guard"
    if action.dry_run_status == "would-apply-readonly":
        return "passed-readonly-dry-run"
    return "passed-advisory-dry-run"


def preflight_reason(
    action: RuntimeDaemonQueuedAction,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        blockers = ", ".join(blocked_by)
        return (
            f"Native promotion denied by preflight blockers [{blockers}]: "
            f"{action.reason}"
        )
    if action.dry_run_status == "would-apply-readonly":
        return f"Read-only dry-run requirement satisfied: {action.reason}"
    return f"Advisory dry-run requirement satisfied: {action.reason}"


def execution_status(
    execution_result: RuntimeDaemonActionExecutionResult | None,
) -> str:
    if execution_result is None:
        return "missing-execution-result"
    return str(execution_result.execution_status)


def backend_policy(
    blocked_requirement_count: int,
    missing_native_backend_count: int,
) -> str:
    if missing_native_backend_count:
        return "hold-native-backend-promotion"
    if blocked_requirement_count:
        return "hold-advisory-guard"
    return "advisory-preflight-passed"


def count_domain(
    requirements: list[RuntimeNativeBackendRequirement],
    domain: str,
) -> int:
    return sum(1 for requirement in requirements if requirement.domain == domain)
