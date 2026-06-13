from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .efficiency import EfficiencyLedger
from .policy import DEFAULT_FRAME_BUDGET_MS


FEEDBACK_MODE = "adaptive-feedback-controller-v0.20"


@dataclass(frozen=True)
class FeedbackAction:
    action: str
    priority: int
    frame: int
    target: str
    recommendation: str
    evidence: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "priority": self.priority,
            "frame": self.frame,
            "target": self.target,
            "recommendation": self.recommendation,
            "evidence": {
                key: round(value, 4) for key, value in sorted(self.evidence.items())
            },
        }


@dataclass(frozen=True)
class FrameFeedback:
    frame: int
    target_frame_ms: float
    hot_path_cost_ms: float
    hot_path_headroom_ms: float
    suggested_copy_budget_ms: float
    suggested_prefetch_window_ms: float
    transfer_relief_mb: float
    efficiency_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "hot_path_cost_ms": round(self.hot_path_cost_ms, 4),
            "hot_path_headroom_ms": round(self.hot_path_headroom_ms, 4),
            "suggested_copy_budget_ms": round(self.suggested_copy_budget_ms, 4),
            "suggested_prefetch_window_ms": round(
                self.suggested_prefetch_window_ms, 4
            ),
            "transfer_relief_mb": round(self.transfer_relief_mb, 4),
            "efficiency_score": round(self.efficiency_score, 4),
        }


@dataclass(frozen=True)
class FeedbackPlan:
    mode: str
    frame_count: int
    action_count: int
    average_efficiency_score: float
    frames: list[FrameFeedback]
    actions: list[FeedbackAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "frame_count": self.frame_count,
            "action_count": self.action_count,
            "average_efficiency_score": round(self.average_efficiency_score, 4),
            "frames": [frame.to_dict() for frame in self.frames],
            "actions": [action.to_dict() for action in self.actions],
        }


def build_feedback_plan(
    ledger: EfficiencyLedger, frame_targets_ms: dict[int, float] | None = None
) -> FeedbackPlan:
    targets = frame_targets_ms or {}
    frames: list[FrameFeedback] = []
    actions: list[FeedbackAction] = []

    for frame in ledger.frames:
        target = targets.get(frame.frame, DEFAULT_FRAME_BUDGET_MS)
        headroom = max(0.0, target - frame.hot_path_cost_ms)
        feedback = FrameFeedback(
            frame=frame.frame,
            target_frame_ms=target,
            hot_path_cost_ms=frame.hot_path_cost_ms,
            hot_path_headroom_ms=headroom,
            suggested_copy_budget_ms=suggest_copy_budget(target, headroom),
            suggested_prefetch_window_ms=suggest_prefetch_window(
                target,
                frame.shifted_cost_ms + frame.held_cost_ms,
                frame.transfer_relief_mb,
            ),
            transfer_relief_mb=frame.transfer_relief_mb,
            efficiency_score=frame.efficiency_score,
        )
        frames.append(feedback)
        actions.extend(actions_for_frame(frame, feedback))

    average = (
        sum(frame.efficiency_score for frame in frames) / len(frames)
        if frames
        else 0.0
    )
    return FeedbackPlan(
        mode=FEEDBACK_MODE,
        frame_count=len(frames),
        action_count=len(actions),
        average_efficiency_score=average,
        frames=frames,
        actions=actions,
    )


def suggest_copy_budget(target_frame_ms: float, hot_path_headroom_ms: float) -> float:
    if hot_path_headroom_ms <= 0:
        return 0.0
    return min(target_frame_ms * 0.15, hot_path_headroom_ms * 0.25)


def suggest_prefetch_window(
    target_frame_ms: float, shifted_or_held_ms: float, transfer_relief_mb: float
) -> float:
    if transfer_relief_mb <= 0:
        return max(0.0, shifted_or_held_ms)
    return max(target_frame_ms * 0.20, shifted_or_held_ms)


def actions_for_frame(frame: Any, feedback: FrameFeedback) -> list[FeedbackAction]:
    actions: list[FeedbackAction] = []
    if frame.shifted_cost_ms > 0:
        actions.append(
            feedback_action(
                "preserve-prefetch-window",
                90,
                frame.frame,
                "prefetch",
                "Keep predictable transfers in a prefetch phase before draw-critical work.",
                shifted_cost_ms=frame.shifted_cost_ms,
                suggested_prefetch_window_ms=feedback.suggested_prefetch_window_ms,
            )
        )
    if frame.avoided_cost_ms > 0:
        actions.append(
            feedback_action(
                "maintain-reuse-dedupe",
                85,
                frame.frame,
                "control-plane",
                "Keep rejecting redundant transfers and reusing transient resources.",
                avoided_cost_ms=frame.avoided_cost_ms,
                transfer_relief_mb=frame.transfer_relief_mb,
            )
        )
    if frame.transfer_relief_mb > 0:
        actions.append(
            feedback_action(
                "cap-copy-queue",
                80,
                frame.frame,
                "copy",
                "Limit late copy queue work to the suggested budget in the next frame.",
                suggested_copy_budget_ms=feedback.suggested_copy_budget_ms,
                transfer_relief_mb=frame.transfer_relief_mb,
            )
        )
    if frame.hot_path_cost_ms >= feedback.target_frame_ms * 0.80:
        actions.append(
            feedback_action(
                "protect-hot-path-headroom",
                95,
                frame.frame,
                "frame",
                "Protect the next frame by holding non-critical work earlier.",
                hot_path_cost_ms=frame.hot_path_cost_ms,
                target_frame_ms=feedback.target_frame_ms,
            )
        )
    return actions


def feedback_action(
    action: str,
    priority: int,
    frame: int,
    target: str,
    recommendation: str,
    **evidence: float,
) -> FeedbackAction:
    return FeedbackAction(
        action=action,
        priority=priority,
        frame=frame,
        target=target,
        recommendation=recommendation,
        evidence=evidence,
    )
