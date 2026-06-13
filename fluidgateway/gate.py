from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control import ControllerResult
from .governor import GovernorDirective
from .live import LiveCommand
from .state import LiveStateSnapshot


EXECUTION_GATE_MODE = "adaptive-execution-gate-v0.17"
CRITICAL_OPERATION_TYPES = {"draw", "compute", "present"}


@dataclass(frozen=True)
class ExecutionGateEvidence:
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
class ExecutionGateDecision:
    mode: str
    action: str
    operation_id: str
    frame: int | None
    queue: str
    resource_id: str | None
    should_execute: bool
    preferred_phase: str
    reason: str
    expected_effect: str
    source_directives: list[str]
    evidence: list[ExecutionGateEvidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "queue": self.queue,
            "resource_id": self.resource_id,
            "should_execute": self.should_execute,
            "preferred_phase": self.preferred_phase,
            "reason": self.reason,
            "expected_effect": self.expected_effect,
            "source_directives": self.source_directives,
            "evidence": [item.to_dict() for item in self.evidence],
        }


def build_execution_gate(
    *,
    result: ControllerResult,
    live_command: LiveCommand,
    directives: list[GovernorDirective],
    snapshot: LiveStateSnapshot,
    target_frame_ms: float,
) -> ExecutionGateDecision:
    operation = result.operation
    directive_actions = [directive.action for directive in directives]
    base_evidence = [
        ExecutionGateEvidence(
            "Live command",
            live_command.action,
            "Immediate command produced for this operation.",
        ),
        ExecutionGateEvidence(
            "Current frame work",
            f"{snapshot.estimated_total_cost_ms_current_frame:.4f} ms",
            "Accumulated executed work in the open frame when the gate was evaluated.",
        ),
        ExecutionGateEvidence(
            "Target frame budget",
            f"{target_frame_ms:.4f} ms",
            "Frame budget used by the adaptive execution gate.",
        ),
    ]

    if live_command.action == "reuse":
        return gate(
            action="reuse_existing_resource",
            operation_id=operation.id,
            frame=operation.frame,
            queue=operation.queue,
            resource_id=operation.target,
            should_execute=False,
            preferred_phase="reuse",
            reason="The control plane found an existing resource or allocation to reuse.",
            expected_effect="Avoid redundant buffer allocation or transfer work.",
            source_directives=directive_actions,
            evidence=base_evidence,
        )

    if live_command.action == "defer":
        return gate(
            action="defer_redundant_work",
            operation_id=operation.id,
            frame=operation.frame,
            queue=operation.queue,
            resource_id=operation.target,
            should_execute=False,
            preferred_phase="deferred",
            reason="The control plane classified this operation as redundant or removable.",
            expected_effect="Prevent unnecessary CPU/GPU/RAM/VRAM movement from reaching the frame path.",
            source_directives=directive_actions,
            evidence=base_evidence,
        )

    if should_hold_noncritical_work(operation.type, snapshot, target_frame_ms):
        return gate(
            action="hold_noncritical_work",
            operation_id=operation.id,
            frame=operation.frame,
            queue=operation.queue,
            resource_id=operation.target,
            should_execute=False,
            preferred_phase="next-frame",
            reason="The frame is near budget and this operation is not frame-critical.",
            expected_effect="Keep late uploads, syncs, and allocations from adding stutter pressure.",
            source_directives=directive_actions,
            evidence=base_evidence,
        )

    if live_command.action == "prefetch_now" or (
        "prefetch-before-critical-path" in directive_actions
    ):
        return gate(
            action="prestage_before_draw",
            operation_id=operation.id,
            frame=operation.frame,
            queue=operation.queue,
            resource_id=operation.target,
            should_execute=True,
            preferred_phase="prefetch",
            reason="This transfer should run before draw-critical work instead of late in the frame.",
            expected_effect="Shorten the hot frame path by moving predictable data movement earlier.",
            source_directives=directive_actions,
            evidence=base_evidence,
        )

    preferred_phase = "critical" if operation.type in CRITICAL_OPERATION_TYPES else "current-frame"
    return gate(
        action="execute_now",
        operation_id=operation.id,
        frame=operation.frame,
        queue=operation.queue,
        resource_id=operation.target,
        should_execute=True,
        preferred_phase=preferred_phase,
        reason="No FluidGateway gate blocked, deferred, or prestaged this operation.",
        expected_effect="Allow required frame work to continue while higher layers reduce waste.",
        source_directives=directive_actions,
        evidence=base_evidence,
    )


def should_hold_noncritical_work(
    operation_type: str, snapshot: LiveStateSnapshot, target_frame_ms: float
) -> bool:
    if operation_type in CRITICAL_OPERATION_TYPES:
        return False
    if not snapshot.open_frame:
        return False
    return snapshot.estimated_total_cost_ms_current_frame >= target_frame_ms * 0.90


def gate(
    *,
    action: str,
    operation_id: str,
    frame: int | None,
    queue: str,
    resource_id: str | None,
    should_execute: bool,
    preferred_phase: str,
    reason: str,
    expected_effect: str,
    source_directives: list[str],
    evidence: list[ExecutionGateEvidence],
) -> ExecutionGateDecision:
    return ExecutionGateDecision(
        mode=EXECUTION_GATE_MODE,
        action=action,
        operation_id=operation_id,
        frame=frame,
        queue=queue,
        resource_id=resource_id,
        should_execute=should_execute,
        preferred_phase=preferred_phase,
        reason=reason,
        expected_effect=expected_effect,
        source_directives=source_directives,
        evidence=evidence,
    )
