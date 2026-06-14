from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gateway_feedback import RuntimeGatewayFeedbackDelta, RuntimeGatewayFrameFeedback


POLICY_UPDATE_MODE = "runtime-policy-update-v0.39"


@dataclass(frozen=True)
class FramePolicyUpdate:
    frame: int
    action: str
    admission_policy: str
    scheduler_policy: str
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    guardband_ms: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "action": self.action,
            "admission_policy": self.admission_policy,
            "scheduler_policy": self.scheduler_policy,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "guardband_ms": round(self.guardband_ms, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MemoryPolicyUpdate:
    action: str
    residency_policy: str
    relief_target_mb: float
    headroom_target_mb: float
    memory_delta_mb: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "residency_policy": self.residency_policy,
            "relief_target_mb": round(self.relief_target_mb, 4),
            "headroom_target_mb": round(self.headroom_target_mb, 4),
            "memory_delta_mb": round(self.memory_delta_mb, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimePolicyUpdate:
    mode: str
    profile: str
    next_profile: str
    source_feedback_action: str
    policy_action: str
    convergence_status: str
    drift_risk: str
    update_count: int
    frame_update_count: int
    memory_update_count: int
    active_update_count: int
    next_frame_budget_ms: float
    hot_path_budget_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    memory_relief_target_mb: float
    memory_headroom_target_mb: float
    frame_updates: list[FramePolicyUpdate]
    memory_updates: list[MemoryPolicyUpdate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_profile": self.next_profile,
            "source_feedback_action": self.source_feedback_action,
            "policy_action": self.policy_action,
            "convergence_status": self.convergence_status,
            "drift_risk": self.drift_risk,
            "update_count": self.update_count,
            "frame_update_count": self.frame_update_count,
            "memory_update_count": self.memory_update_count,
            "active_update_count": self.active_update_count,
            "next_frame_budget_ms": round(self.next_frame_budget_ms, 4),
            "hot_path_budget_ms": round(self.hot_path_budget_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "memory_relief_target_mb": round(self.memory_relief_target_mb, 4),
            "memory_headroom_target_mb": round(self.memory_headroom_target_mb, 4),
            "frame_updates": [update.to_dict() for update in self.frame_updates],
            "memory_updates": [update.to_dict() for update in self.memory_updates],
        }


def build_runtime_policy_update(
    feedback: RuntimeGatewayFeedbackDelta,
) -> RuntimePolicyUpdate:
    frame_updates = [
        build_frame_policy_update(frame) for frame in feedback.frame_feedbacks
    ]
    memory_updates = [build_memory_policy_update(feedback)]
    return RuntimePolicyUpdate(
        mode=POLICY_UPDATE_MODE,
        profile=feedback.profile,
        next_profile=next_profile(feedback),
        source_feedback_action=feedback.feedback_action,
        policy_action=policy_action(feedback),
        convergence_status=feedback.convergence_status,
        drift_risk=feedback.drift_risk,
        update_count=len(frame_updates) + len(memory_updates),
        frame_update_count=len(frame_updates),
        memory_update_count=len(memory_updates),
        active_update_count=sum(1 for update in frame_updates if is_active_frame(update))
        + sum(1 for update in memory_updates if is_active_memory(update)),
        next_frame_budget_ms=min_value(frame_updates, "next_frame_budget_ms"),
        hot_path_budget_ms=min_value(frame_updates, "hot_path_budget_ms"),
        copy_queue_budget_ms=min_value(frame_updates, "copy_queue_budget_ms"),
        pre_frame_window_ms=max_value(frame_updates, "pre_frame_window_ms"),
        memory_relief_target_mb=sum(update.relief_target_mb for update in memory_updates),
        memory_headroom_target_mb=sum(
            update.headroom_target_mb for update in memory_updates
        ),
        frame_updates=frame_updates,
        memory_updates=memory_updates,
    )


def build_frame_policy_update(
    feedback: RuntimeGatewayFrameFeedback,
) -> FramePolicyUpdate:
    guardband = recommended_guardband(feedback)
    if feedback.feedback_action == "tighten-cycle-guardband":
        action = "tighten-frame-guardband"
        admission = "block-noncritical-hot-path"
        scheduler = "guardband-tightening"
        next_budget = max(0.0, feedback.target_frame_ms - guardband)
        copy_budget = 0.0
        pre_frame = max(feedback.planned_frame_relief_ms * 0.5, guardband)
    elif feedback.feedback_action == "continue-pressure-management":
        action = "continue-frame-pressure-management"
        admission = "prestage-and-defer-noncritical"
        scheduler = "closed-loop-aggressive"
        next_budget = feedback.next_frame_budget_ms
        copy_budget = 0.0
        pre_frame = max(feedback.planned_frame_relief_ms * 0.36, guardband)
    elif feedback.feedback_action == "preserve-cycle-shape":
        action = "preserve-cycle-shape"
        admission = "preserve-budgeted-hot-path"
        scheduler = "closed-loop-stable"
        next_budget = feedback.target_frame_ms
        copy_budget = feedback.target_frame_ms * 0.15
        pre_frame = feedback.planned_frame_relief_ms
    else:
        action = "monitor-cycle"
        admission = "observe-admission"
        scheduler = "observe"
        next_budget = feedback.target_frame_ms
        copy_budget = feedback.target_frame_ms * 0.15
        pre_frame = 0.0
    return FramePolicyUpdate(
        frame=feedback.frame,
        action=action,
        admission_policy=admission,
        scheduler_policy=scheduler,
        next_frame_budget_ms=next_budget,
        hot_path_budget_ms=min(next_budget, feedback.target_frame_ms),
        copy_queue_budget_ms=copy_budget,
        pre_frame_window_ms=pre_frame,
        guardband_ms=guardband,
        reason=frame_reason(feedback),
    )


def build_memory_policy_update(
    feedback: RuntimeGatewayFeedbackDelta,
) -> MemoryPolicyUpdate:
    if feedback.memory_relief_applied_mb > 0.0 or feedback.memory_delta_mb < 0.0:
        target = max(feedback.memory_relief_expected_mb, feedback.memory_relief_applied_mb)
        return MemoryPolicyUpdate(
            action="continue-memory-relief",
            residency_policy="evict-or-defer-residency",
            relief_target_mb=target,
            headroom_target_mb=0.0,
            memory_delta_mb=feedback.memory_delta_mb,
            reason="Memory pressure relief remains part of the next policy cycle.",
        )
    if feedback.memory_headroom_reserved_mb > 0.0:
        return MemoryPolicyUpdate(
            action="preserve-memory-headroom",
            residency_policy="reserve-headroom",
            relief_target_mb=0.0,
            headroom_target_mb=feedback.memory_headroom_reserved_mb,
            memory_delta_mb=feedback.memory_delta_mb,
            reason="Memory headroom was reserved and should be watched next cycle.",
        )
    return MemoryPolicyUpdate(
        action="hold-memory-residency",
        residency_policy="hold-residency",
        relief_target_mb=0.0,
        headroom_target_mb=0.0,
        memory_delta_mb=feedback.memory_delta_mb,
        reason="No memory pressure or headroom correction is required.",
    )


def recommended_guardband(feedback: RuntimeGatewayFrameFeedback) -> float:
    if feedback.planned_over_budget_ms > 0.0:
        return min(
            feedback.target_frame_ms * 0.25,
            max(0.5, feedback.planned_over_budget_ms * 0.5),
        )
    if feedback.protected_gap_ms > 0.0:
        return min(
            feedback.target_frame_ms * 0.25,
            max(0.5, feedback.protected_gap_ms * 0.25),
        )
    return 0.0


def policy_action(feedback: RuntimeGatewayFeedbackDelta) -> str:
    if feedback.feedback_action == "tighten-cycle-guardband":
        return "tighten-runtime-guardband-policy"
    if feedback.feedback_action == "continue-pressure-management":
        return "continue-runtime-pressure-policy"
    if feedback.feedback_action == "monitor-headroom":
        return "preserve-memory-headroom-policy"
    if feedback.feedback_action == "preserve-cycle-shape":
        return "preserve-runtime-cycle-policy"
    return "maintain-runtime-policy"


def next_profile(feedback: RuntimeGatewayFeedbackDelta) -> str:
    if feedback.feedback_action in {
        "tighten-cycle-guardband",
        "continue-pressure-management",
    }:
        return "aggressive"
    return "stable"


def frame_reason(feedback: RuntimeGatewayFrameFeedback) -> str:
    if feedback.planned_over_budget_ms > 0.0:
        return "Planned current-frame work still exceeds the target budget."
    if feedback.protected_gap_ms > 0.0:
        return "Observed frame cost still exceeds the protected next-frame budget."
    if feedback.planned_frame_relief_ms > 0.0:
        return "Cycle shape produced useful relief and can be preserved."
    return "No stronger frame policy change is supported by current feedback."


def is_active_frame(update: FramePolicyUpdate) -> bool:
    return update.action != "monitor-cycle"


def is_active_memory(update: MemoryPolicyUpdate) -> bool:
    return update.action != "hold-memory-residency"


def min_value(updates: list[FramePolicyUpdate], field: str) -> float:
    return min((float(getattr(update, field)) for update in updates), default=0.0)


def max_value(updates: list[FramePolicyUpdate], field: str) -> float:
    return max((float(getattr(update, field)) for update in updates), default=0.0)
