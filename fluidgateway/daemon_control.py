from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_arbitration import (
    RuntimeDaemonArbitrationLane,
    RuntimeDaemonArbitrationPlan,
)
from .native_backend import (
    RuntimeNativeBackendPreflight,
    RuntimeNativeBackendRequirement,
)
from .state_accumulator import RuntimeStateAccumulator


DAEMON_CONTROL_PLAN_MODE = "runtime-daemon-control-plan-v0.53"
DAEMON_CONTROL_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonControlIntent:
    intent_id: str
    source_lane_id: str
    source_action_id: str
    domain: str
    control_surface: str
    backend_requirement: str
    control_action: str
    control_status: str
    dry_run: bool
    would_modify_system: bool
    can_execute_now: bool
    native_promotion_allowed: bool
    blocked_by: list[str]
    pressure_score: int
    expected_signal: str
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "source_lane_id": self.source_lane_id,
            "source_action_id": self.source_action_id,
            "domain": self.domain,
            "control_surface": self.control_surface,
            "backend_requirement": self.backend_requirement,
            "control_action": self.control_action,
            "control_status": self.control_status,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "can_execute_now": self.can_execute_now,
            "native_promotion_allowed": self.native_promotion_allowed,
            "blocked_by": self.blocked_by,
            "pressure_score": self.pressure_score,
            "expected_signal": self.expected_signal,
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class RuntimeDaemonControlPlan:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_arbitration_policy: str
    source_backend_policy: str
    source_state_profile: str
    pressure_score: int
    control_policy: str
    intent_count: int
    ready_intent_count: int
    blocked_intent_count: int
    readonly_intent_count: int
    advisory_intent_count: int
    native_blocked_intent_count: int
    cpu_surface_count: int
    gpu_surface_count: int
    ram_surface_count: int
    vram_surface_count: int
    scheduler_surface_count: int
    telemetry_surface_count: int
    safety_surface_count: int
    intents: list[RuntimeDaemonControlIntent]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_arbitration_policy": self.source_arbitration_policy,
            "source_backend_policy": self.source_backend_policy,
            "source_state_profile": self.source_state_profile,
            "pressure_score": self.pressure_score,
            "control_policy": self.control_policy,
            "intent_count": self.intent_count,
            "ready_intent_count": self.ready_intent_count,
            "blocked_intent_count": self.blocked_intent_count,
            "readonly_intent_count": self.readonly_intent_count,
            "advisory_intent_count": self.advisory_intent_count,
            "native_blocked_intent_count": self.native_blocked_intent_count,
            "cpu_surface_count": self.cpu_surface_count,
            "gpu_surface_count": self.gpu_surface_count,
            "ram_surface_count": self.ram_surface_count,
            "vram_surface_count": self.vram_surface_count,
            "scheduler_surface_count": self.scheduler_surface_count,
            "telemetry_surface_count": self.telemetry_surface_count,
            "safety_surface_count": self.safety_surface_count,
            "intents": [intent.to_dict() for intent in self.intents],
        }


def build_runtime_daemon_control_plan(
    *,
    final_state: RuntimeStateAccumulator,
    arbitration_plan: RuntimeDaemonArbitrationPlan,
    native_backend_preflight: RuntimeNativeBackendPreflight,
) -> RuntimeDaemonControlPlan:
    requirements_by_action = {
        requirement.source_action_id: requirement
        for requirement in native_backend_preflight.requirements
    }
    intents = [
        control_intent(
            index + 1,
            lane,
            requirements_by_action.get(lane.source_action_id),
        )
        for index, lane in enumerate(arbitration_plan.lanes)
    ]
    return RuntimeDaemonControlPlan(
        mode=DAEMON_CONTROL_PLAN_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_CONTROL_GUARD,
        source_arbitration_policy=arbitration_plan.arbitration_policy,
        source_backend_policy=native_backend_preflight.backend_policy,
        source_state_profile=final_state.profile,
        pressure_score=arbitration_plan.pressure_score,
        control_policy=control_policy(intents, arbitration_plan),
        intent_count=len(intents),
        ready_intent_count=sum(1 for intent in intents if intent.can_execute_now),
        blocked_intent_count=sum(1 for intent in intents if not intent.can_execute_now),
        readonly_intent_count=count_status(intents, "ready-readonly"),
        advisory_intent_count=count_status(intents, "ready-advisory"),
        native_blocked_intent_count=count_status(
            intents,
            "blocked-native-preflight",
        ),
        cpu_surface_count=count_surface(intents, "cpu"),
        gpu_surface_count=count_surface(intents, "gpu"),
        ram_surface_count=count_surface(intents, "ram"),
        vram_surface_count=count_surface(intents, "vram"),
        scheduler_surface_count=count_surface(intents, "scheduler"),
        telemetry_surface_count=count_surface(intents, "telemetry"),
        safety_surface_count=count_surface(intents, "safety"),
        intents=intents,
    )


def control_intent(
    index: int,
    lane: RuntimeDaemonArbitrationLane,
    requirement: RuntimeNativeBackendRequirement | None,
) -> RuntimeDaemonControlIntent:
    blocked_by = requirement.blocked_by if requirement else ["missing-preflight"]
    control_status = intent_status(lane, requirement, blocked_by)
    return RuntimeDaemonControlIntent(
        intent_id=f"daemon.control.{index:03d}",
        source_lane_id=lane.lane_id,
        source_action_id=lane.source_action_id,
        domain=lane.domain,
        control_surface=control_surface(lane),
        backend_requirement=backend_requirement(lane, requirement),
        control_action=control_action(lane, control_status),
        control_status=control_status,
        dry_run=True,
        would_modify_system=False,
        can_execute_now=not blocked_by,
        native_promotion_allowed=False,
        blocked_by=list(blocked_by),
        pressure_score=lane.pressure_score,
        expected_signal=lane.expected_signal,
        reason=control_reason(lane, blocked_by),
        expected_effect=control_expected_effect(lane, blocked_by),
    )


def intent_status(
    lane: RuntimeDaemonArbitrationLane,
    requirement: RuntimeNativeBackendRequirement | None,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        if "native-backend" in blocked_by:
            return "blocked-native-preflight"
        return "blocked-advisory-preflight"
    if lane.domain == "telemetry":
        return "ready-readonly"
    return "ready-advisory"


def control_surface(lane: RuntimeDaemonArbitrationLane) -> str:
    if lane.domain == "telemetry":
        return "telemetry"
    if lane.domain == "scheduler":
        return "scheduler"
    if lane.domain == "safety":
        return "safety"
    if lane.domain == "gpu":
        return "gpu"
    if lane.domain == "memory":
        target = lane.target.lower()
        if "vram" in target and "ram" not in target.replace("vram", ""):
            return "vram"
        if "ram" in target and "vram" not in target:
            return "ram"
        return "ram-vram"
    return lane.domain


def backend_requirement(
    lane: RuntimeDaemonArbitrationLane,
    requirement: RuntimeNativeBackendRequirement | None,
) -> str:
    if requirement is None:
        return "missing-preflight"
    if requirement.requires_native_backend:
        return "native-host-control-backend"
    if lane.domain == "telemetry":
        return "python-stdlib-readonly-probe"
    return "daemon-advisory-loop"


def control_action(
    lane: RuntimeDaemonArbitrationLane,
    control_status: str,
) -> str:
    if control_status.startswith("blocked"):
        return "hold-control-surface"
    if lane.domain == "telemetry":
        return "collect-control-surface-evidence"
    if lane.domain == "scheduler":
        return "maintain-advisory-scheduler-loop"
    if lane.domain == "safety":
        return "preserve-safety-hold"
    if lane.domain == "gpu":
        return "observe-gpu-vram-queues"
    if lane.domain == "memory":
        return "observe-ram-vram-residency"
    return "observe-control-surface"


def control_reason(
    lane: RuntimeDaemonArbitrationLane,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        blockers = ", ".join(blocked_by)
        return f"Control intent held by blockers [{blockers}]: {lane.reason}"
    return lane.reason


def control_expected_effect(
    lane: RuntimeDaemonArbitrationLane,
    blocked_by: list[str],
) -> str:
    if blocked_by:
        return "Keep the future native control surface explicit without mutating the host."
    if lane.domain == "telemetry":
        return "Increase evidence quality before changing CPU/GPU/RAM/VRAM behavior."
    if lane.domain == "scheduler":
        return "Keep control-loop timing deterministic in advisory mode."
    if lane.domain == "memory":
        return "Prepare RAM/VRAM residency control without applying it."
    if lane.domain == "gpu":
        return "Prepare GPU/VRAM queue control without applying it."
    if lane.domain == "safety":
        return "Prevent unsafe promotion of blocked work."
    return lane.expected_effect


def control_policy(
    intents: list[RuntimeDaemonControlIntent],
    arbitration_plan: RuntimeDaemonArbitrationPlan,
) -> str:
    if any(intent.control_status == "blocked-native-preflight" for intent in intents):
        return "hold-native-control-surfaces"
    if any(intent.domain == "safety" for intent in intents):
        return "safety-control-hold"
    if arbitration_plan.pressure_score >= 60:
        return "pressure-aware-advisory-control"
    if any(intent.control_status == "ready-readonly" for intent in intents):
        return "collect-evidence-before-control"
    if intents:
        return "maintain-advisory-control-loop"
    return "observe"


def count_status(intents: list[RuntimeDaemonControlIntent], status: str) -> int:
    return sum(1 for intent in intents if intent.control_status == status)


def count_surface(intents: list[RuntimeDaemonControlIntent], surface: str) -> int:
    return sum(
        1
        for intent in intents
        if intent.control_surface == surface
        or (
            surface in {"ram", "vram"}
            and intent.control_surface == "ram-vram"
        )
    )
