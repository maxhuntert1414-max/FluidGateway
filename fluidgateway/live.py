from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control import ControllerResult


LIVE_COMMAND_MODE = "live-command-contract-v0.14"


@dataclass(frozen=True)
class LiveCommand:
    mode: str
    action: str
    operation_id: str
    frame: int | None
    queue: str
    resource_id: str | None
    reason: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "queue": self.queue,
            "resource_id": self.resource_id,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def build_live_command(
    result: ControllerResult, target_frame_ms: float
) -> LiveCommand:
    operation = result.operation
    if result.decision is not None:
        if result.decision.action == "reuse":
            return LiveCommand(
                mode=LIVE_COMMAND_MODE,
                action="reuse",
                operation_id=operation.id,
                frame=operation.frame,
                queue=operation.queue,
                resource_id=operation.target,
                reason=result.decision.rationale,
                confidence="high",
            )
        return LiveCommand(
            mode=LIVE_COMMAND_MODE,
            action="defer",
            operation_id=operation.id,
            frame=operation.frame,
            queue=operation.queue,
            resource_id=operation.target,
            reason=result.decision.rationale,
            confidence="high",
        )

    if operation.type in {"copy", "upload"} and is_heavy_transfer(
        operation.cost_ms, operation.size_mb, target_frame_ms
    ):
        return LiveCommand(
            mode=LIVE_COMMAND_MODE,
            action="prefetch_now",
            operation_id=operation.id,
            frame=operation.frame,
            queue=operation.queue,
            resource_id=operation.target,
            reason="Transfer is large enough to move before frame-critical work.",
            confidence="medium",
        )

    return LiveCommand(
        mode=LIVE_COMMAND_MODE,
        action="execute_now",
        operation_id=operation.id,
        frame=operation.frame,
        queue=operation.queue,
        resource_id=operation.target,
        reason="No earlier FluidGateway policy blocked this operation.",
        confidence="medium",
    )


def is_heavy_transfer(cost_ms: float, size_mb: float, target_frame_ms: float) -> bool:
    threshold_ms = max(1.0, target_frame_ms * 0.20)
    return cost_ms >= threshold_ms or size_mb >= 16
