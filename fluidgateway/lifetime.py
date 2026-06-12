from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime import RuntimeOperation, RuntimeResource


LIFETIME_PLAN_MODE = "resource-lifetime-plan-v0.11"


@dataclass(frozen=True)
class LifetimePlanAction:
    action: str
    resource_id: str
    target_frame: int | None
    memory: str
    size_mb: float
    priority: int
    rationale: str
    expected_effect: str
    source_operation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "resource_id": self.resource_id,
            "target_frame": self.target_frame,
            "memory": self.memory,
            "size_mb": self.size_mb,
            "priority": self.priority,
            "rationale": self.rationale,
            "expected_effect": self.expected_effect,
            "source_operation_id": self.source_operation_id,
        }


@dataclass(frozen=True)
class ResourceLifetimePlan:
    mode: str
    plan_action_count: int
    estimated_reduced_transfer_mb: float
    estimated_release_mb: float
    actions: list[LifetimePlanAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "plan_action_count": self.plan_action_count,
            "estimated_reduced_transfer_mb": round(self.estimated_reduced_transfer_mb, 4),
            "estimated_release_mb": round(self.estimated_release_mb, 4),
            "actions": [action.to_dict() for action in self.actions],
        }


class ResourceLifetimePlanner:
    """Builds an advisory RAM/VRAM residency plan from adapter activity."""

    def __init__(self) -> None:
        self.resources: dict[str, RuntimeResource] = {}
        self.first_use_frame: dict[str, int] = {}
        self.last_use_frame: dict[str, int] = {}
        self.released_resources: dict[str, RuntimeResource] = {}
        self.transfer_operations: list[RuntimeOperation] = []
        self.actions: list[LifetimePlanAction] = []
        self._action_keys: set[tuple[str, str, str | None]] = set()

    def register_resource(self, resource: RuntimeResource, frame: int | None) -> None:
        self.resources[resource.id] = resource
        if frame is not None:
            self._record_use(resource.id, frame)

    def release_resource(self, resource: RuntimeResource | None, resource_id: str) -> None:
        if resource is not None:
            self.released_resources[resource_id] = resource

    def record_operation(self, operation: RuntimeOperation, executed: bool) -> None:
        if not executed:
            return
        if operation.frame is not None:
            for resource_id in (operation.source, operation.target):
                if resource_id:
                    self._record_use(resource_id, operation.frame)
        if operation.type in {"copy", "upload"}:
            self.transfer_operations.append(operation)

    def finalize(self) -> ResourceLifetimePlan:
        for resource_id, resource in self.resources.items():
            first_frame = self.first_use_frame.get(resource_id)
            last_frame = self.last_use_frame.get(resource_id)
            if resource.memory == "vram" and resource.kind in {"texture", "buffer"}:
                if resource.lifetime in {"frame", "transient"} and first_frame is not None:
                    self._add_action(
                        LifetimePlanAction(
                            action="keep-resident",
                            resource_id=resource_id,
                            target_frame=first_frame,
                            memory=resource.memory,
                            size_mb=resource.size_mb,
                            priority=85 if resource.kind == "texture" else 70,
                            rationale=(
                                "Resource is consumed from VRAM during frame work and should avoid late re-upload."
                            ),
                            expected_effect=(
                                "Lower copy pressure before draw/compute work and fewer RAM to VRAM transfers."
                            ),
                        )
                    )
            if resource.lifetime == "transient":
                self._add_action(
                    LifetimePlanAction(
                        action="release-after-frame",
                        resource_id=resource_id,
                        target_frame=last_frame,
                        memory=resource.memory,
                        size_mb=resource.size_mb,
                        priority=80,
                        rationale=(
                            "Transient resource should not stay resident after its last observed frame use."
                        ),
                        expected_effect=(
                            "Reduce memory pressure and make staging/scratch capacity available earlier."
                        ),
                    )
                )

        for operation in self.transfer_operations:
            if operation.frame is None:
                continue
            if operation.cost_ms >= 1.0 or operation.size_mb >= 16:
                target_resource = self.resources.get(operation.target or "")
                self._add_action(
                    LifetimePlanAction(
                        action="prefetch-before-frame",
                        resource_id=operation.id,
                        target_frame=operation.frame,
                        memory=target_resource.memory if target_resource else "unknown",
                        size_mb=operation.size_mb,
                        priority=90 if operation.cost_ms >= 4 else 75,
                        rationale=(
                            "Transfer is large enough to be scheduled before frame-critical work."
                        ),
                        expected_effect=(
                            "Move upload/copy pressure away from the frame's draw-critical path."
                        ),
                        source_operation_id=operation.id,
                    )
                )
                self._add_action(
                    LifetimePlanAction(
                        action="defer-upload",
                        resource_id=operation.id,
                        target_frame=operation.frame,
                        memory=target_resource.memory if target_resource else "unknown",
                        size_mb=operation.size_mb,
                        priority=65,
                        rationale=(
                            "If the resource is not needed by the current frame, this transfer should be delayed."
                        ),
                        expected_effect=(
                            "Avoid moving data that could be unused, overwritten, or better batched later."
                        ),
                        source_operation_id=operation.id,
                    )
                )

        reduced_transfer_mb_by_operation: dict[str, float] = {}
        for action in self.actions:
            if action.action in {"prefetch-before-frame", "defer-upload"}:
                key = action.source_operation_id or action.resource_id
                reduced_transfer_mb_by_operation[key] = max(
                    action.size_mb,
                    reduced_transfer_mb_by_operation.get(key, 0.0),
                )
        reduced_transfer_mb = sum(reduced_transfer_mb_by_operation.values())
        release_mb = sum(
            action.size_mb
            for action in self.actions
            if action.action == "release-after-frame"
        )
        return ResourceLifetimePlan(
            mode=LIFETIME_PLAN_MODE,
            plan_action_count=len(self.actions),
            estimated_reduced_transfer_mb=reduced_transfer_mb,
            estimated_release_mb=release_mb,
            actions=sorted(
                self.actions,
                key=lambda action: (-action.priority, action.action, action.resource_id),
            ),
        )

    def _record_use(self, resource_id: str, frame: int) -> None:
        if resource_id not in self.first_use_frame:
            self.first_use_frame[resource_id] = frame
        self.last_use_frame[resource_id] = frame

    def _add_action(self, action: LifetimePlanAction) -> None:
        key = (action.action, action.resource_id, action.source_operation_id)
        if key in self._action_keys:
            return
        self._action_keys.add(key)
        self.actions.append(action)
