from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .supervisor_plan import RuntimeSupervisorCommand, RuntimeSupervisorPlan


SUPERVISOR_EXECUTION_MODE = "runtime-supervisor-execution-v0.45"


@dataclass(frozen=True)
class RuntimeSupervisorCommandExecution:
    command_id: str
    domain: str
    action: str
    target: str
    dry_run_status: str
    would_apply: bool
    would_block: bool
    simulated_budget_ms: float | None
    simulated_target_mb: float | None
    effect: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "domain": self.domain,
            "action": self.action,
            "target": self.target,
            "dry_run_status": self.dry_run_status,
            "would_apply": self.would_apply,
            "would_block": self.would_block,
            "simulated_budget_ms": round(self.simulated_budget_ms, 4)
            if self.simulated_budget_ms is not None
            else None,
            "simulated_target_mb": round(self.simulated_target_mb, 4)
            if self.simulated_target_mb is not None
            else None,
            "effect": self.effect,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeSupervisorExecution:
    mode: str
    source_plan_action: str
    execution_action: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    command_count: int
    would_apply_count: int
    would_block_count: int
    scheduler_execution_count: int
    admission_execution_count: int
    memory_execution_count: int
    frame_budget_execution_count: int
    guardband_execution_count: int
    simulated_budget_ms: float
    simulated_memory_target_mb: float
    escalation_level: int
    cooldown_cycles: int
    confidence: str
    state_digest: str
    command_executions: list[RuntimeSupervisorCommandExecution]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_plan_action": self.source_plan_action,
            "execution_action": self.execution_action,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "command_count": self.command_count,
            "would_apply_count": self.would_apply_count,
            "would_block_count": self.would_block_count,
            "scheduler_execution_count": self.scheduler_execution_count,
            "admission_execution_count": self.admission_execution_count,
            "memory_execution_count": self.memory_execution_count,
            "frame_budget_execution_count": self.frame_budget_execution_count,
            "guardband_execution_count": self.guardband_execution_count,
            "simulated_budget_ms": round(self.simulated_budget_ms, 4),
            "simulated_memory_target_mb": round(
                self.simulated_memory_target_mb,
                4,
            ),
            "escalation_level": self.escalation_level,
            "cooldown_cycles": self.cooldown_cycles,
            "confidence": self.confidence,
            "state_digest": self.state_digest,
            "command_executions": [
                execution.to_dict() for execution in self.command_executions
            ],
        }


def dry_run_runtime_supervisor_plan(
    plan: RuntimeSupervisorPlan,
) -> RuntimeSupervisorExecution:
    command_executions = [
        dry_run_supervisor_command(command) for command in plan.commands
    ]
    return RuntimeSupervisorExecution(
        mode=SUPERVISOR_EXECUTION_MODE,
        source_plan_action=plan.plan_action,
        execution_action=execution_action(plan),
        dry_run=True,
        would_modify_system=False,
        execution_guard="advisory-only",
        command_count=len(command_executions),
        would_apply_count=sum(1 for item in command_executions if item.would_apply),
        would_block_count=sum(1 for item in command_executions if item.would_block),
        scheduler_execution_count=count_domain(command_executions, "scheduler"),
        admission_execution_count=count_domain(command_executions, "admission"),
        memory_execution_count=count_domain(command_executions, "memory"),
        frame_budget_execution_count=count_domain(command_executions, "frame-budget"),
        guardband_execution_count=count_domain(command_executions, "guardband"),
        simulated_budget_ms=sum(
            item.simulated_budget_ms or 0.0 for item in command_executions
        ),
        simulated_memory_target_mb=sum(
            item.simulated_target_mb or 0.0 for item in command_executions
        ),
        escalation_level=plan.escalation_level,
        cooldown_cycles=plan.cooldown_cycles,
        confidence=plan.confidence,
        state_digest=plan.state_digest,
        command_executions=command_executions,
    )


def dry_run_supervisor_command(
    command: RuntimeSupervisorCommand,
) -> RuntimeSupervisorCommandExecution:
    would_block = command.blocking
    return RuntimeSupervisorCommandExecution(
        command_id=command.command_id,
        domain=command.domain,
        action=command.action,
        target=command.target,
        dry_run_status="would-block" if would_block else "would-apply",
        would_apply=True,
        would_block=would_block,
        simulated_budget_ms=command.budget_ms,
        simulated_target_mb=command.target_mb,
        effect=simulated_effect(command),
        reason=f"Dry-run only: {command.reason}",
    )


def execution_action(plan: RuntimeSupervisorPlan) -> str:
    if plan.plan_action == "observe-next-cycle":
        return "dry-run-observation-supervisor-commands"
    if plan.plan_action == "apply-relaxed-next-cycle-posture":
        return "dry-run-relaxed-supervisor-commands"
    if plan.plan_action == "hold-recovery-next-cycle-posture":
        return "dry-run-recovery-supervisor-commands"
    if plan.plan_action == "apply-tightened-next-cycle-posture":
        return "dry-run-tightened-supervisor-commands"
    if plan.plan_action == "preserve-next-cycle-posture":
        return "dry-run-preserved-supervisor-commands"
    return "dry-run-monitored-supervisor-commands"


def simulated_effect(command: RuntimeSupervisorCommand) -> str:
    if command.domain == "scheduler":
        return "simulate-scheduler-posture"
    if command.domain == "admission":
        return "simulate-admission-gate"
    if command.domain == "memory":
        return "simulate-memory-residency"
    if command.domain == "frame-budget":
        return "simulate-frame-budget"
    if command.domain == "guardband":
        return "simulate-guardband"
    return "simulate-supervisor-command"


def count_domain(
    executions: list[RuntimeSupervisorCommandExecution],
    domain: str,
) -> int:
    return sum(1 for execution in executions if execution.domain == domain)
