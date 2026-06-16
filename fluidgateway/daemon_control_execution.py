from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_control import RuntimeDaemonControlIntent, RuntimeDaemonControlPlan


DAEMON_CONTROL_EXECUTION_MODE = "runtime-daemon-control-execution-v0.54"
DAEMON_CONTROL_EXECUTION_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonControlExecutionStep:
    intent_id: str
    source_lane_id: str
    domain: str
    control_surface: str
    backend_requirement: str
    execution_status: str
    dry_run: bool
    would_modify_system: bool
    executed: bool
    blocked: bool
    blocked_by: list[str]
    observed_signal: str
    effect: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "source_lane_id": self.source_lane_id,
            "domain": self.domain,
            "control_surface": self.control_surface,
            "backend_requirement": self.backend_requirement,
            "execution_status": self.execution_status,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "executed": self.executed,
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "observed_signal": self.observed_signal,
            "effect": self.effect,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeDaemonControlExecution:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_control_policy: str
    execution_policy: str
    step_count: int
    executed_count: int
    blocked_count: int
    readonly_execution_count: int
    advisory_execution_count: int
    native_blocked_execution_count: int
    telemetry_step_count: int
    scheduler_step_count: int
    ram_surface_count: int
    vram_surface_count: int
    gpu_surface_count: int
    safety_step_count: int
    steps: list[RuntimeDaemonControlExecutionStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_control_policy": self.source_control_policy,
            "execution_policy": self.execution_policy,
            "step_count": self.step_count,
            "executed_count": self.executed_count,
            "blocked_count": self.blocked_count,
            "readonly_execution_count": self.readonly_execution_count,
            "advisory_execution_count": self.advisory_execution_count,
            "native_blocked_execution_count": self.native_blocked_execution_count,
            "telemetry_step_count": self.telemetry_step_count,
            "scheduler_step_count": self.scheduler_step_count,
            "ram_surface_count": self.ram_surface_count,
            "vram_surface_count": self.vram_surface_count,
            "gpu_surface_count": self.gpu_surface_count,
            "safety_step_count": self.safety_step_count,
            "steps": [step.to_dict() for step in self.steps],
        }


def dry_run_runtime_daemon_control_plan(
    control_plan: RuntimeDaemonControlPlan,
) -> RuntimeDaemonControlExecution:
    steps = [dry_run_control_intent(intent) for intent in control_plan.intents]
    return RuntimeDaemonControlExecution(
        mode=DAEMON_CONTROL_EXECUTION_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_CONTROL_EXECUTION_GUARD,
        source_control_policy=control_plan.control_policy,
        execution_policy=execution_policy(steps),
        step_count=len(steps),
        executed_count=sum(1 for step in steps if step.executed),
        blocked_count=sum(1 for step in steps if step.blocked),
        readonly_execution_count=count_status(
            steps,
            "executed-readonly-control-dry-run",
        ),
        advisory_execution_count=count_status(
            steps,
            "executed-advisory-control-dry-run",
        ),
        native_blocked_execution_count=count_status(
            steps,
            "blocked-native-control-surface",
        ),
        telemetry_step_count=count_domain(steps, "telemetry"),
        scheduler_step_count=count_domain(steps, "scheduler"),
        ram_surface_count=count_surface(steps, "ram"),
        vram_surface_count=count_surface(steps, "vram"),
        gpu_surface_count=count_surface(steps, "gpu"),
        safety_step_count=count_domain(steps, "safety"),
        steps=steps,
    )


def dry_run_control_intent(
    intent: RuntimeDaemonControlIntent,
) -> RuntimeDaemonControlExecutionStep:
    blocked = not intent.can_execute_now or bool(intent.blocked_by)
    return RuntimeDaemonControlExecutionStep(
        intent_id=intent.intent_id,
        source_lane_id=intent.source_lane_id,
        domain=intent.domain,
        control_surface=intent.control_surface,
        backend_requirement=intent.backend_requirement,
        execution_status=control_execution_status(intent, blocked),
        dry_run=True,
        would_modify_system=False,
        executed=not blocked,
        blocked=blocked,
        blocked_by=list(intent.blocked_by),
        observed_signal=intent.expected_signal,
        effect=control_effect(intent, blocked),
        reason=control_execution_reason(intent, blocked),
    )


def control_execution_status(
    intent: RuntimeDaemonControlIntent,
    blocked: bool,
) -> str:
    if blocked:
        if "native-backend" in intent.blocked_by:
            return "blocked-native-control-surface"
        return "blocked-advisory-control-surface"
    if intent.control_status == "ready-readonly":
        return "executed-readonly-control-dry-run"
    return "executed-advisory-control-dry-run"


def control_effect(
    intent: RuntimeDaemonControlIntent,
    blocked: bool,
) -> str:
    if blocked:
        return "hold-control-surface-before-host-mutation"
    if intent.control_status == "ready-readonly":
        return "observe-control-surface-signal"
    return "simulate-advisory-control-loop"


def control_execution_reason(
    intent: RuntimeDaemonControlIntent,
    blocked: bool,
) -> str:
    if blocked:
        blockers = ", ".join(intent.blocked_by)
        return (
            f"Control execution held by blockers [{blockers}]: "
            f"{intent.reason}"
        )
    return f"Dry-run control execution: {intent.reason}"


def execution_policy(steps: list[RuntimeDaemonControlExecutionStep]) -> str:
    if any(step.execution_status == "blocked-native-control-surface" for step in steps):
        return "hold-native-control-surfaces"
    if any(
        step.execution_status == "executed-readonly-control-dry-run"
        for step in steps
    ):
        return "execute-readonly-control"
    if any(
        step.execution_status == "executed-advisory-control-dry-run"
        for step in steps
    ):
        return "execute-advisory-control"
    return "observe"


def count_status(
    steps: list[RuntimeDaemonControlExecutionStep],
    status: str,
) -> int:
    return sum(1 for step in steps if step.execution_status == status)


def count_domain(
    steps: list[RuntimeDaemonControlExecutionStep],
    domain: str,
) -> int:
    return sum(1 for step in steps if step.domain == domain)


def count_surface(
    steps: list[RuntimeDaemonControlExecutionStep],
    surface: str,
) -> int:
    return sum(
        1
        for step in steps
        if step.control_surface == surface
        or (
            surface in {"ram", "vram"}
            and step.control_surface == "ram-vram"
        )
    )
