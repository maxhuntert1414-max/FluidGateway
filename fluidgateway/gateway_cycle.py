from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gateway import RuntimeGatewayStep, RuntimeGatewayTick


GATEWAY_CYCLE_MODE = "runtime-gateway-cycle-v0.37"


@dataclass(frozen=True)
class RuntimeGatewayStepResult:
    sequence: int
    domain: str
    lane: str
    action: str
    frame: int | None
    memory: str | None
    status: str
    active: bool
    priority: str
    protected_budget_ms: float
    reserved_window_ms: float
    copy_queue_budget_ms: float
    memory_relief_mb: float
    memory_headroom_mb: float
    drift_risk: str
    feedback: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "domain": self.domain,
            "lane": self.lane,
            "action": self.action,
            "frame": self.frame,
            "memory": self.memory,
            "status": self.status,
            "active": self.active,
            "priority": self.priority,
            "protected_budget_ms": round(self.protected_budget_ms, 4),
            "reserved_window_ms": round(self.reserved_window_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "memory_relief_mb": round(self.memory_relief_mb, 4),
            "memory_headroom_mb": round(self.memory_headroom_mb, 4),
            "drift_risk": self.drift_risk,
            "feedback": self.feedback,
        }


@dataclass(frozen=True)
class RuntimeGatewayCycleReport:
    mode: str
    profile: str
    tick_policy: str
    next_cycle_action: str
    drift_risk: str
    step_count: int
    applied_step_count: int
    observed_step_count: int
    frame_count: int
    memory_layer_count: int
    high_priority_step_count: int
    protected_budget_ms: float
    reserved_pre_frame_ms: float
    copy_queue_budget_ms: float
    blocked_copy_queue_count: int
    admission_mode_count: int
    scheduler_mode_count: int
    memory_relief_applied_mb: float
    memory_headroom_reserved_mb: float
    memory_observed_count: int
    step_results: list[RuntimeGatewayStepResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "tick_policy": self.tick_policy,
            "next_cycle_action": self.next_cycle_action,
            "drift_risk": self.drift_risk,
            "step_count": self.step_count,
            "applied_step_count": self.applied_step_count,
            "observed_step_count": self.observed_step_count,
            "frame_count": self.frame_count,
            "memory_layer_count": self.memory_layer_count,
            "high_priority_step_count": self.high_priority_step_count,
            "protected_budget_ms": round(self.protected_budget_ms, 4),
            "reserved_pre_frame_ms": round(self.reserved_pre_frame_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "blocked_copy_queue_count": self.blocked_copy_queue_count,
            "admission_mode_count": self.admission_mode_count,
            "scheduler_mode_count": self.scheduler_mode_count,
            "memory_relief_applied_mb": round(self.memory_relief_applied_mb, 4),
            "memory_headroom_reserved_mb": round(
                self.memory_headroom_reserved_mb, 4
            ),
            "memory_observed_count": self.memory_observed_count,
            "step_results": [result.to_dict() for result in self.step_results],
        }


def execute_runtime_gateway_tick(
    tick: RuntimeGatewayTick,
) -> RuntimeGatewayCycleReport:
    results = [step_result(step) for step in tick.steps]
    memory_relief = sum(result.memory_relief_mb for result in results)
    memory_headroom = sum(result.memory_headroom_mb for result in results)
    blocked_copy_count = sum(
        1 for result in results if result.action == "block_late_copy_queue"
    )
    return RuntimeGatewayCycleReport(
        mode=GATEWAY_CYCLE_MODE,
        profile=tick.profile,
        tick_policy=tick.tick_policy,
        next_cycle_action=next_cycle_action(
            memory_relief,
            memory_headroom,
            blocked_copy_count,
        ),
        drift_risk=cycle_drift_risk(
            tick.profile,
            memory_relief,
            memory_headroom,
            blocked_copy_count,
        ),
        step_count=len(results),
        applied_step_count=sum(1 for result in results if result.status == "applied"),
        observed_step_count=sum(1 for result in results if result.status == "observed"),
        frame_count=tick.frame_count,
        memory_layer_count=tick.memory_layer_count,
        high_priority_step_count=sum(
            1 for result in results if result.priority == "high"
        ),
        protected_budget_ms=sum(result.protected_budget_ms for result in results),
        reserved_pre_frame_ms=sum(result.reserved_window_ms for result in results),
        copy_queue_budget_ms=sum(result.copy_queue_budget_ms for result in results),
        blocked_copy_queue_count=blocked_copy_count,
        admission_mode_count=count_action(results, "apply_admission_mode"),
        scheduler_mode_count=count_action(results, "apply_scheduler_mode"),
        memory_relief_applied_mb=memory_relief,
        memory_headroom_reserved_mb=memory_headroom,
        memory_observed_count=sum(
            1
            for result in results
            if result.domain == "memory" and result.status == "observed"
        ),
        step_results=results,
    )


def step_result(step: RuntimeGatewayStep) -> RuntimeGatewayStepResult:
    status = "applied" if step.active else "observed"
    return RuntimeGatewayStepResult(
        sequence=step.sequence,
        domain=step.domain,
        lane=step.lane,
        action=step.action,
        frame=step.frame,
        memory=step.memory,
        status=status,
        active=step.active,
        priority=step.priority,
        protected_budget_ms=protected_budget_ms(step),
        reserved_window_ms=reserved_window_ms(step),
        copy_queue_budget_ms=copy_queue_budget_ms(step),
        memory_relief_mb=memory_relief_mb(step),
        memory_headroom_mb=memory_headroom_mb(step),
        drift_risk=step_drift_risk(step),
        feedback=step_feedback(step),
    )


def protected_budget_ms(step: RuntimeGatewayStep) -> float:
    if step.action in {"protect_next_frame_budget", "protect_gpu_hot_path"}:
        return step.budget_ms
    return 0.0


def reserved_window_ms(step: RuntimeGatewayStep) -> float:
    if step.action == "reserve_pre_frame_window":
        return step.budget_ms
    return 0.0


def copy_queue_budget_ms(step: RuntimeGatewayStep) -> float:
    if step.lane == "copy-queue":
        return step.budget_ms
    return 0.0


def memory_relief_mb(step: RuntimeGatewayStep) -> float:
    if step.action == "relieve_memory_residency":
        return step.budget_mb
    return 0.0


def memory_headroom_mb(step: RuntimeGatewayStep) -> float:
    if step.action == "reserve_memory_headroom":
        return step.budget_mb
    return 0.0


def step_drift_risk(step: RuntimeGatewayStep) -> str:
    if not step.active:
        return "low"
    if step.action in {"block_late_copy_queue", "relieve_memory_residency"}:
        return "medium"
    if step.priority == "high":
        return "medium"
    return "low"


def step_feedback(step: RuntimeGatewayStep) -> str:
    if not step.active:
        return "Observed lane only; no runtime mutation is simulated."
    if step.action == "block_late_copy_queue":
        return "Late copy queue work is blocked for this simulated cycle."
    if step.action == "budget_copy_queue":
        return "Copy queue work is admitted inside the simulated budget."
    if step.action == "relieve_memory_residency":
        return "Memory residency relief is applied in the simulated cycle."
    if step.action == "reserve_memory_headroom":
        return "Memory headroom is reserved for the next simulated cycle."
    if step.action == "reserve_pre_frame_window":
        return "Pre-frame work window is reserved before the hot path."
    if step.action.startswith("protect_"):
        return "Critical frame budget is protected in the simulated cycle."
    return "Runtime mode is applied in the simulated cycle."


def next_cycle_action(
    memory_relief_mb: float,
    memory_headroom_mb: float,
    blocked_copy_queue_count: int,
) -> str:
    if memory_relief_mb > 0.0 or blocked_copy_queue_count > 0:
        return "continue-pressure-management"
    if memory_headroom_mb > 0.0:
        return "monitor-headroom"
    return "maintain-cycle"


def cycle_drift_risk(
    profile: str,
    memory_relief_mb: float,
    memory_headroom_mb: float,
    blocked_copy_queue_count: int,
) -> str:
    if (
        profile == "aggressive"
        and memory_relief_mb > 0.0
        and blocked_copy_queue_count > 0
    ):
        return "high"
    if (
        memory_relief_mb > 0.0
        or memory_headroom_mb > 0.0
        or blocked_copy_queue_count > 0
    ):
        return "medium"
    return "low"


def count_action(results: list[RuntimeGatewayStepResult], action: str) -> int:
    return sum(1 for result in results if result.action == action)
