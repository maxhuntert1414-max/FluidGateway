from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_decision import RuntimeDaemonDecisionAction, RuntimeDaemonDecisionPlan
from .daemon_execution import RuntimeDaemonActionExecution
from .native_backend import (
    RuntimeNativeBackendPreflight,
    RuntimeNativeBackendRequirement,
)
from .state_accumulator import RuntimeStateAccumulator


DAEMON_ARBITRATION_MODE = "runtime-daemon-arbitration-plan-v0.52"
DAEMON_ARBITRATION_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonArbitrationLane:
    lane_id: str
    source_action_id: str
    domain: str
    priority: str
    target: str
    arbitration_action: str
    arbitration_status: str
    pressure_score: int
    can_execute_now: bool
    native_promotion_allowed: bool
    blocked_by: list[str]
    expected_signal: str
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "source_action_id": self.source_action_id,
            "domain": self.domain,
            "priority": self.priority,
            "target": self.target,
            "arbitration_action": self.arbitration_action,
            "arbitration_status": self.arbitration_status,
            "pressure_score": self.pressure_score,
            "can_execute_now": self.can_execute_now,
            "native_promotion_allowed": self.native_promotion_allowed,
            "blocked_by": self.blocked_by,
            "expected_signal": self.expected_signal,
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class RuntimeDaemonArbitrationPlan:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_state_profile: str
    source_policy_action: str
    source_execution_policy: str
    source_backend_policy: str
    pressure_score: int
    arbitration_policy: str
    lane_count: int
    executable_lane_count: int
    blocked_lane_count: int
    native_promotable_lane_count: int
    telemetry_lane_count: int
    scheduler_lane_count: int
    memory_lane_count: int
    gpu_lane_count: int
    safety_lane_count: int
    lanes: list[RuntimeDaemonArbitrationLane]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_state_profile": self.source_state_profile,
            "source_policy_action": self.source_policy_action,
            "source_execution_policy": self.source_execution_policy,
            "source_backend_policy": self.source_backend_policy,
            "pressure_score": self.pressure_score,
            "arbitration_policy": self.arbitration_policy,
            "lane_count": self.lane_count,
            "executable_lane_count": self.executable_lane_count,
            "blocked_lane_count": self.blocked_lane_count,
            "native_promotable_lane_count": self.native_promotable_lane_count,
            "telemetry_lane_count": self.telemetry_lane_count,
            "scheduler_lane_count": self.scheduler_lane_count,
            "memory_lane_count": self.memory_lane_count,
            "gpu_lane_count": self.gpu_lane_count,
            "safety_lane_count": self.safety_lane_count,
            "lanes": [lane.to_dict() for lane in self.lanes],
        }


def build_runtime_daemon_arbitration_plan(
    *,
    final_state: RuntimeStateAccumulator,
    decision_plan: RuntimeDaemonDecisionPlan,
    action_execution: RuntimeDaemonActionExecution,
    native_backend_preflight: RuntimeNativeBackendPreflight,
) -> RuntimeDaemonArbitrationPlan:
    score = pressure_score(final_state)
    lanes = sorted_lanes(
        [
            arbitration_lane(
                index + 1,
                action,
                score,
                native_backend_preflight,
            )
            for index, action in enumerate(decision_plan.actions)
        ]
    )
    return RuntimeDaemonArbitrationPlan(
        mode=DAEMON_ARBITRATION_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_ARBITRATION_GUARD,
        source_state_profile=final_state.profile,
        source_policy_action=final_state.policy_action,
        source_execution_policy=action_execution.execution_policy,
        source_backend_policy=native_backend_preflight.backend_policy,
        pressure_score=score,
        arbitration_policy=arbitration_policy(
            decision_plan,
            native_backend_preflight,
            score,
        ),
        lane_count=len(lanes),
        executable_lane_count=sum(1 for lane in lanes if lane.can_execute_now),
        blocked_lane_count=sum(1 for lane in lanes if not lane.can_execute_now),
        native_promotable_lane_count=sum(
            1 for lane in lanes if lane.native_promotion_allowed
        ),
        telemetry_lane_count=count_domain(lanes, "telemetry"),
        scheduler_lane_count=count_domain(lanes, "scheduler"),
        memory_lane_count=count_domain(lanes, "memory"),
        gpu_lane_count=count_domain(lanes, "gpu"),
        safety_lane_count=count_domain(lanes, "safety"),
        lanes=lanes,
    )


def arbitration_lane(
    index: int,
    action: RuntimeDaemonDecisionAction,
    score: int,
    native_backend_preflight: RuntimeNativeBackendPreflight,
) -> RuntimeDaemonArbitrationLane:
    requirement = requirement_for_action(native_backend_preflight, action.action_id)
    blocked_by = requirement.blocked_by if requirement else []
    can_execute_now = requirement.can_execute_now if requirement else False
    native_promotion_allowed = (
        requirement.can_promote_to_native if requirement else False
    )
    return RuntimeDaemonArbitrationLane(
        lane_id=f"daemon.arbitration.{index:03d}",
        source_action_id=action.action_id,
        domain=action.domain,
        priority=action.priority,
        target=action.target,
        arbitration_action=lane_action(action, blocked_by),
        arbitration_status=lane_status(action, blocked_by),
        pressure_score=score,
        can_execute_now=can_execute_now,
        native_promotion_allowed=native_promotion_allowed,
        blocked_by=list(blocked_by),
        expected_signal=requirement.expected_signal if requirement else "missing-preflight",
        reason=lane_reason(action, blocked_by),
        expected_effect=lane_expected_effect(action, blocked_by),
    )


def pressure_score(state: RuntimeStateAccumulator) -> int:
    score = 0
    if state.profile == "aggressive":
        score += 30
    if state.drift_risk == "high":
        score += 15
    score += min(state.active_policy_count * 5, 20)
    score += min(int(state.memory_relief_target_mb / 4), 20)
    score += min(int(state.memory_headroom_target_mb / 4), 20)
    if state.hot_path_budget_ms < state.next_frame_budget_ms:
        score += 5
    if state.copy_queue_budget_ms == 0.0 and state.active_policy_count > 0:
        score += 10
    return min(score, 100)


def arbitration_policy(
    decision_plan: RuntimeDaemonDecisionPlan,
    native_backend_preflight: RuntimeNativeBackendPreflight,
    score: int,
) -> str:
    if decision_plan.safety_action_count:
        return "safety-first"
    if native_backend_preflight.blocked_requirement_count:
        return "hold-native-and-prioritize-telemetry"
    if score >= 60:
        return "pressure-recovery"
    if decision_plan.telemetry_action_count:
        return "telemetry-first"
    if decision_plan.scheduler_action_count:
        return "continue-supervisor-loop"
    return "observe"


def requirement_for_action(
    native_backend_preflight: RuntimeNativeBackendPreflight,
    action_id: str,
) -> RuntimeNativeBackendRequirement | None:
    return next(
        (
            requirement
            for requirement in native_backend_preflight.requirements
            if requirement.source_action_id == action_id
        ),
        None,
    )


def lane_action(
    action: RuntimeDaemonDecisionAction,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        return "hold-native-backend"
    if action.domain == "telemetry":
        return "collect-evidence-before-control"
    if action.domain == "scheduler":
        return "continue-advisory-supervisor-loop"
    if action.domain == "safety":
        return "hold-supervisor-promotion"
    return "continue-advisory-management"


def lane_status(
    action: RuntimeDaemonDecisionAction,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        return "blocked-by-native-preflight"
    if action.domain == "telemetry":
        return "read-only-ready"
    return "advisory-ready"


def lane_reason(
    action: RuntimeDaemonDecisionAction,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        blockers = ", ".join(blocked_by)
        return f"Lane is held by preflight blockers [{blockers}]: {action.reason}"
    return action.reason


def lane_expected_effect(
    action: RuntimeDaemonDecisionAction,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        return "Prevent unsafe native promotion while preserving the required backend contract."
    if action.domain == "telemetry":
        return "Improve CPU/GPU/RAM/VRAM evidence before deeper management."
    if action.domain == "memory":
        return "Prepare RAM/VRAM residency decisions for a future native backend."
    if action.domain == "scheduler":
        return "Keep the advisory manager loop moving without host mutation."
    if action.domain == "gpu":
        return "Improve GPU and VRAM queue evidence before GPU-specific control."
    if action.domain == "safety":
        return "Keep blocking supervisor commands from being promoted."
    return "Preserve advisory progress while collecting stronger evidence."


def sorted_lanes(
    lanes: list[RuntimeDaemonArbitrationLane],
) -> list[RuntimeDaemonArbitrationLane]:
    return sorted(
        lanes,
        key=lambda lane: (
            priority_rank(lane.priority),
            domain_rank(lane.domain),
            lane.lane_id,
        ),
    )


def priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def domain_rank(domain: str) -> int:
    return {
        "safety": 0,
        "telemetry": 1,
        "memory": 2,
        "gpu": 3,
        "scheduler": 4,
    }.get(domain, 5)


def count_domain(lanes: list[RuntimeDaemonArbitrationLane], domain: str) -> int:
    return sum(1 for lane in lanes if lane.domain == domain)
