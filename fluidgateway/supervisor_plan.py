from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .supervisor import RuntimeSupervisorDirective


SUPERVISOR_PLAN_MODE = "runtime-supervisor-plan-v0.44"


@dataclass(frozen=True)
class RuntimeSupervisorCommand:
    command_id: str
    domain: str
    phase: str
    action: str
    target: str
    budget_ms: float | None
    target_mb: float | None
    blocking: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "domain": self.domain,
            "phase": self.phase,
            "action": self.action,
            "target": self.target,
            "budget_ms": round(self.budget_ms, 4)
            if self.budget_ms is not None
            else None,
            "target_mb": round(self.target_mb, 4)
            if self.target_mb is not None
            else None,
            "blocking": self.blocking,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeSupervisorPlan:
    mode: str
    source_directive_action: str
    plan_action: str
    command_count: int
    scheduler_command_count: int
    admission_command_count: int
    memory_command_count: int
    frame_budget_command_count: int
    guardband_command_count: int
    blocking_command_count: int
    escalation_level: int
    cooldown_cycles: int
    confidence: str
    state_digest: str
    commands: list[RuntimeSupervisorCommand]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_directive_action": self.source_directive_action,
            "plan_action": self.plan_action,
            "command_count": self.command_count,
            "scheduler_command_count": self.scheduler_command_count,
            "admission_command_count": self.admission_command_count,
            "memory_command_count": self.memory_command_count,
            "frame_budget_command_count": self.frame_budget_command_count,
            "guardband_command_count": self.guardband_command_count,
            "blocking_command_count": self.blocking_command_count,
            "escalation_level": self.escalation_level,
            "cooldown_cycles": self.cooldown_cycles,
            "confidence": self.confidence,
            "state_digest": self.state_digest,
            "commands": [command.to_dict() for command in self.commands],
        }


def build_runtime_supervisor_plan(
    directive: RuntimeSupervisorDirective,
) -> RuntimeSupervisorPlan:
    commands = build_supervisor_commands(directive)
    return RuntimeSupervisorPlan(
        mode=SUPERVISOR_PLAN_MODE,
        source_directive_action=directive.directive_action,
        plan_action=plan_action(directive),
        command_count=len(commands),
        scheduler_command_count=count_domain(commands, "scheduler"),
        admission_command_count=count_domain(commands, "admission"),
        memory_command_count=count_domain(commands, "memory"),
        frame_budget_command_count=count_domain(commands, "frame-budget"),
        guardband_command_count=count_domain(commands, "guardband"),
        blocking_command_count=sum(1 for command in commands if command.blocking),
        escalation_level=directive.escalation_level,
        cooldown_cycles=directive.cooldown_cycles,
        confidence=directive.confidence,
        state_digest=directive.state_digest,
        commands=commands,
    )


def build_supervisor_commands(
    directive: RuntimeSupervisorDirective,
) -> list[RuntimeSupervisorCommand]:
    return [
        scheduler_command(directive),
        admission_command(directive),
        memory_command(directive),
        frame_budget_command(directive),
        guardband_command(directive),
    ]


def scheduler_command(directive: RuntimeSupervisorDirective) -> RuntimeSupervisorCommand:
    return RuntimeSupervisorCommand(
        command_id="supervisor.scheduler.posture",
        domain="scheduler",
        phase="next-cycle",
        action=directive.scheduler_posture,
        target="runtime-dispatch",
        budget_ms=directive.pre_frame_window_ms,
        target_mb=None,
        blocking=directive.directive_action == "escalate-supervisor-pressure",
        reason="Apply the supervisor scheduler posture for the next gateway cycle.",
    )


def admission_command(directive: RuntimeSupervisorDirective) -> RuntimeSupervisorCommand:
    return RuntimeSupervisorCommand(
        command_id="supervisor.admission.posture",
        domain="admission",
        phase="next-cycle",
        action=directive.admission_posture,
        target="copy-queue",
        budget_ms=directive.copy_queue_budget_ms,
        target_mb=None,
        blocking="block" in directive.admission_posture,
        reason="Apply the supervised admission posture to copy-queue work.",
    )


def memory_command(directive: RuntimeSupervisorDirective) -> RuntimeSupervisorCommand:
    return RuntimeSupervisorCommand(
        command_id="supervisor.memory.posture",
        domain="memory",
        phase="next-cycle",
        action=directive.memory_posture,
        target="ram-vram-residency",
        budget_ms=None,
        target_mb=directive.memory_relief_target_mb
        or directive.memory_headroom_target_mb,
        blocking=directive.escalation_level >= 2,
        reason="Apply the supervised memory residency and relief posture.",
    )


def frame_budget_command(
    directive: RuntimeSupervisorDirective,
) -> RuntimeSupervisorCommand:
    return RuntimeSupervisorCommand(
        command_id="supervisor.frame-budget.posture",
        domain="frame-budget",
        phase="next-frame",
        action=directive.frame_budget_posture,
        target="frame-hot-path",
        budget_ms=directive.hot_path_budget_ms,
        target_mb=None,
        blocking=False,
        reason="Carry the supervised frame and hot-path budget into the next cycle.",
    )


def guardband_command(directive: RuntimeSupervisorDirective) -> RuntimeSupervisorCommand:
    return RuntimeSupervisorCommand(
        command_id="supervisor.guardband.posture",
        domain="guardband",
        phase="next-frame",
        action=directive.guardband_posture,
        target="frame-safety-margin",
        budget_ms=max(0.0, directive.pre_frame_window_ms - directive.hot_path_budget_ms),
        target_mb=None,
        blocking=False,
        reason="Carry the supervised guardband posture into the next cycle.",
    )


def plan_action(directive: RuntimeSupervisorDirective) -> str:
    if directive.directive_action == "establish-supervisor-baseline":
        return "observe-next-cycle"
    if directive.directive_action == "relax-supervisor-pressure":
        return "apply-relaxed-next-cycle-posture"
    if directive.directive_action == "hold-recovery-supervision":
        return "hold-recovery-next-cycle-posture"
    if directive.directive_action == "escalate-supervisor-pressure":
        return "apply-tightened-next-cycle-posture"
    if directive.directive_action == "preserve-supervisor-state":
        return "preserve-next-cycle-posture"
    return "monitor-next-cycle-posture"


def count_domain(commands: list[RuntimeSupervisorCommand], domain: str) -> int:
    return sum(1 for command in commands if command.domain == domain)
