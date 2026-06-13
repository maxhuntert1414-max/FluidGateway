from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .live import LiveCommand
from .policy import DEFAULT_FRAME_BUDGET_MS
from .state import LiveStateSnapshot


LIVE_POLICY_LOOP_MODE = "live-policy-loop-v0.16"


@dataclass(frozen=True)
class GovernorEvidence:
    label: str
    value: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "value": self.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GovernorDirective:
    mode: str
    action: str
    priority: int
    frame: int | None
    queue: str
    operation_id: str | None
    resource_id: str | None
    reason: str
    expected_effect: str
    evidence: list[GovernorEvidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "priority": self.priority,
            "frame": self.frame,
            "queue": self.queue,
            "operation_id": self.operation_id,
            "resource_id": self.resource_id,
            "reason": self.reason,
            "expected_effect": self.expected_effect,
            "evidence": [item.to_dict() for item in self.evidence],
        }


class LivePolicyGovernor:
    """State-driven management loop for live adapter sessions."""

    def __init__(self) -> None:
        self._emitted: set[tuple[str, int | None, str]] = set()

    def evaluate(
        self,
        *,
        snapshot: LiveStateSnapshot,
        target_frame_ms: float | None = None,
        memory_budgets_mb: dict[str, float] | None = None,
        live_command: LiveCommand | None = None,
    ) -> list[GovernorDirective]:
        target_ms = target_frame_ms or DEFAULT_FRAME_BUDGET_MS
        budgets = memory_budgets_mb or {}
        directives: list[GovernorDirective] = []

        if (
            snapshot.open_frame
            and live_command is not None
            and live_command.action == "prefetch_now"
        ):
            directives.append(
                GovernorDirective(
                    mode=LIVE_POLICY_LOOP_MODE,
                    action="prefetch-before-critical-path",
                    priority=90,
                    frame=live_command.frame,
                    queue=live_command.queue,
                    operation_id=live_command.operation_id,
                    resource_id=live_command.resource_id,
                    reason="A streamed operation was classified as prefetchable while the frame is open.",
                    expected_effect="Move predictable transfer work away from draw-critical frame time.",
                    evidence=[
                        GovernorEvidence(
                            "Live command",
                            live_command.action,
                            "Immediate command emitted for this operation.",
                        ),
                        GovernorEvidence(
                            "Current frame work",
                            f"{snapshot.estimated_total_cost_ms_current_frame:.4f} ms",
                            "Accumulated executed work in the open frame.",
                        ),
                    ],
                )
            )

        copy_queue_ms = snapshot.queue_costs_ms.get("copy", 0.0)
        if snapshot.open_frame and copy_queue_ms >= max(1.0, target_ms * 0.25):
            directives.append(
                GovernorDirective(
                    mode=LIVE_POLICY_LOOP_MODE,
                    action="drain-copy-queue-before-draw",
                    priority=85,
                    frame=snapshot.current_frame,
                    queue="copy",
                    operation_id=live_command.operation_id if live_command else None,
                    resource_id=live_command.resource_id if live_command else None,
                    reason="Copy queue work is already a large slice of the active frame budget.",
                    expected_effect="Schedule remaining transfers earlier or outside the frame-critical section.",
                    evidence=[
                        GovernorEvidence(
                            "Copy queue cost",
                            f"{copy_queue_ms:.4f} ms",
                            "Accumulated copy queue work observed for the session.",
                        ),
                        GovernorEvidence(
                            "Target frame budget",
                            f"{target_ms:.4f} ms",
                            "Current budget used by the live policy loop.",
                        ),
                    ],
                )
            )

        current_frame_ms = snapshot.estimated_total_cost_ms_current_frame
        if snapshot.open_frame and current_frame_ms >= target_ms * 0.90:
            directives.append(
                GovernorDirective(
                    mode=LIVE_POLICY_LOOP_MODE,
                    action="protect-frame-budget",
                    priority=80,
                    frame=snapshot.current_frame,
                    queue="frame",
                    operation_id=live_command.operation_id if live_command else None,
                    resource_id=live_command.resource_id if live_command else None,
                    reason="The open frame is close to exhausting its configured budget.",
                    expected_effect="Defer non-critical uploads, syncs, and allocations until the frame is safe.",
                    evidence=[
                        GovernorEvidence(
                            "Current frame work",
                            f"{current_frame_ms:.4f} ms",
                            "Accumulated executed work in the open frame.",
                        ),
                        GovernorEvidence(
                            "Target frame budget",
                            f"{target_ms:.4f} ms",
                            "Current budget used by the live policy loop.",
                        ),
                    ],
                )
            )

        for memory, total_mb in snapshot.memory_totals_mb.items():
            budget_mb = budgets.get(memory)
            if budget_mb is None or total_mb <= budget_mb:
                continue
            directives.append(
                GovernorDirective(
                    mode=LIVE_POLICY_LOOP_MODE,
                    action="reduce-memory-residency",
                    priority=88,
                    frame=snapshot.current_frame,
                    queue="memory",
                    operation_id=None,
                    resource_id=memory,
                    reason=f"Active {memory.upper()} residency exceeds the declared budget.",
                    expected_effect="Release transient resources earlier or avoid duplicate residency.",
                    evidence=[
                        GovernorEvidence(
                            "Active residency",
                            f"{total_mb:.4f} MB",
                            f"Current active resources registered in {memory}.",
                        ),
                        GovernorEvidence(
                            "Memory budget",
                            f"{budget_mb:.4f} MB",
                            f"Configured budget for {memory}.",
                        ),
                    ],
                )
            )

        return [directive for directive in directives if self._mark_emitted(directive)]

    def _mark_emitted(self, directive: GovernorDirective) -> bool:
        if directive.action == "prefetch-before-critical-path":
            identity = directive.operation_id or directive.resource_id or directive.queue
        elif directive.action == "reduce-memory-residency":
            identity = directive.resource_id or directive.queue
        else:
            identity = directive.queue
        key = (
            directive.action,
            directive.frame,
            identity,
        )
        if key in self._emitted:
            return False
        self._emitted.add(key)
        return True
