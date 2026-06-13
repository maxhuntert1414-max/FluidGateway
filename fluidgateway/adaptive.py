from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .executor import ExecutionFrameResult, ExecutionSimulation
from .policy import DEFAULT_FRAME_BUDGET_MS


ADAPTIVE_EXECUTOR_MODE = "adaptive-executor-loop-v0.27"


@dataclass(frozen=True)
class AdaptiveExecutorDirective:
    action: str
    priority: int
    frame: int
    target: str
    value: float
    unit: str
    reason: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "priority": self.priority,
            "frame": self.frame,
            "target": self.target,
            "value": round(self.value, 4),
            "unit": self.unit,
            "reason": self.reason,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class AdaptiveExecutorFrame:
    frame: int
    target_frame_ms: float
    hot_path_before_ms: float
    hot_path_after_ms: float
    hot_path_relief_ms: float
    budget_delta_ms: float
    pressure_status: str
    profile: str
    directive_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "hot_path_before_ms": round(self.hot_path_before_ms, 4),
            "hot_path_after_ms": round(self.hot_path_after_ms, 4),
            "hot_path_relief_ms": round(self.hot_path_relief_ms, 4),
            "budget_delta_ms": round(self.budget_delta_ms, 4),
            "pressure_status": self.pressure_status,
            "profile": self.profile,
            "directive_count": self.directive_count,
        }


@dataclass(frozen=True)
class AdaptiveExecutorLoop:
    mode: str
    frame_count: int
    over_budget_count: int
    within_budget_count: int
    max_over_budget_ms: float
    total_hot_path_relief_ms: float
    adjustment_count: int
    profile: str
    frames: list[AdaptiveExecutorFrame]
    directives: list[AdaptiveExecutorDirective]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "frame_count": self.frame_count,
            "over_budget_count": self.over_budget_count,
            "within_budget_count": self.within_budget_count,
            "max_over_budget_ms": round(self.max_over_budget_ms, 4),
            "total_hot_path_relief_ms": round(self.total_hot_path_relief_ms, 4),
            "adjustment_count": self.adjustment_count,
            "profile": self.profile,
            "frames": [frame.to_dict() for frame in self.frames],
            "directives": [directive.to_dict() for directive in self.directives],
        }


def build_adaptive_executor_loop(
    simulation: ExecutionSimulation,
    frame_targets_ms: dict[int, float] | None = None,
) -> AdaptiveExecutorLoop:
    targets = frame_targets_ms or {}
    frames: list[AdaptiveExecutorFrame] = []
    directives: list[AdaptiveExecutorDirective] = []

    for frame in simulation.frames:
        target = targets.get(frame.frame, DEFAULT_FRAME_BUDGET_MS)
        budget_delta = target - frame.hot_path_after_ms
        pressure_status = "within-budget" if budget_delta >= 0 else "over-budget"
        profile = "stable" if pressure_status == "within-budget" else "aggressive"
        frame_directives = directives_for_frame(frame, target, budget_delta)
        frames.append(
            AdaptiveExecutorFrame(
                frame=frame.frame,
                target_frame_ms=target,
                hot_path_before_ms=frame.hot_path_before_ms,
                hot_path_after_ms=frame.hot_path_after_ms,
                hot_path_relief_ms=frame.hot_path_relief_ms,
                budget_delta_ms=budget_delta,
                pressure_status=pressure_status,
                profile=profile,
                directive_count=len(frame_directives),
            )
        )
        directives.extend(frame_directives)

    over_budget = [
        abs(frame.budget_delta_ms)
        for frame in frames
        if frame.pressure_status == "over-budget"
    ]
    return AdaptiveExecutorLoop(
        mode=ADAPTIVE_EXECUTOR_MODE,
        frame_count=len(frames),
        over_budget_count=sum(
            1 for frame in frames if frame.pressure_status == "over-budget"
        ),
        within_budget_count=sum(
            1 for frame in frames if frame.pressure_status == "within-budget"
        ),
        max_over_budget_ms=max(over_budget, default=0.0),
        total_hot_path_relief_ms=sum(frame.hot_path_relief_ms for frame in frames),
        adjustment_count=len(directives),
        profile="aggressive" if over_budget else "stable",
        frames=frames,
        directives=sorted(
            directives,
            key=lambda item: (-item.priority, item.frame, item.action),
        ),
    )


def directives_for_frame(
    frame: ExecutionFrameResult, target_frame_ms: float, budget_delta_ms: float
) -> list[AdaptiveExecutorDirective]:
    if budget_delta_ms < 0:
        over_budget_ms = abs(budget_delta_ms)
        directives = [
            directive(
                "tighten-hot-path-admission",
                95,
                frame.frame,
                "hot-path",
                over_budget_ms,
                "ms",
                "Simulated hot path remains over the frame target.",
                "Reject or defer more non-critical work before this frame executes.",
            ),
            directive(
                "expand-pre-frame-window",
                90,
                frame.frame,
                "pre-frame",
                frame.prestaged_cost_ms + over_budget_ms,
                "ms",
                "More work must move before the frame to recover target headroom.",
                "Increase the early transfer window for predictable RAM/VRAM movement.",
            ),
        ]
        if frame.protected_hot_path_cost_ms > target_frame_ms:
            directives.append(
                directive(
                    "split-protected-hot-path",
                    88,
                    frame.frame,
                    "hot-path",
                    frame.protected_hot_path_cost_ms - target_frame_ms,
                    "ms",
                    "Protected hot-path work alone exceeds the target frame budget.",
                    "Look for work that can be tiled, staged, cached, or moved earlier.",
                )
            )
        if frame.removed_cost_ms > 0:
            directives.append(
                directive(
                    "keep-suppression-active",
                    84,
                    frame.frame,
                    "never",
                    frame.removed_cost_ms,
                    "ms",
                    "Existing suppression is still buying measurable frame relief.",
                    "Keep redundant transfers, allocations, and sync waits out.",
                )
            )
        return directives

    directives = []
    if frame.prestaged_cost_ms > 0:
        directives.append(
            directive(
                "preserve-pre-frame-window",
                72,
                frame.frame,
                "pre-frame",
                frame.prestaged_cost_ms,
                "ms",
                "The simulated frame is within budget with prestaged work.",
                "Keep predictable transfer work outside the hot path.",
            )
        )
    if frame.removed_cost_ms > 0:
        directives.append(
            directive(
                "maintain-suppression-cache",
                70,
                frame.frame,
                "never",
                frame.removed_cost_ms,
                "ms",
                "Suppressed work contributes to the current headroom.",
                "Continue eliminating redundant copies, allocations, and waits.",
            )
        )
    directives.append(
        directive(
            "hold-current-packet",
            55,
            frame.frame,
            "packet",
            budget_delta_ms,
            "ms",
            "Simulation is within the frame target.",
            "Keep this packet shape unless later telemetry regresses.",
        )
    )
    return directives


def directive(
    action: str,
    priority: int,
    frame: int,
    target: str,
    value: float,
    unit: str,
    reason: str,
    expected_effect: str,
) -> AdaptiveExecutorDirective:
    return AdaptiveExecutorDirective(
        action=action,
        priority=priority,
        frame=frame,
        target=target,
        value=value,
        unit=unit,
        reason=reason,
        expected_effect=expected_effect,
    )
