from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_json
from .runtime import (
    RuntimeDecision,
    RuntimeOperation,
    RuntimeOptimizationState,
    RuntimeResource,
    parse_operation,
    parse_resource,
)


@dataclass(frozen=True)
class ControllerResult:
    operation: RuntimeOperation
    decision: RuntimeDecision | None
    executed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.to_dict(),
            "decision": self.decision.to_dict() if self.decision else None,
            "executed": self.executed,
        }


class FluidGatewayController:
    """Incremental runtime control plane for engine/app integration prototypes."""

    def __init__(self) -> None:
        self.resources: dict[str, RuntimeResource] = {}
        self.executed_operations: list[RuntimeOperation] = []
        self.decisions: list[RuntimeDecision] = []
        self._optimization = RuntimeOptimizationState(self.resources)

    def register_resource(
        self,
        resource_id: str,
        kind: str,
        memory: str,
        size_mb: float = 0,
        lifetime: str = "unknown",
        aliases: list[str] | None = None,
    ) -> RuntimeResource:
        resource = parse_resource(
            {
                "id": resource_id,
                "kind": kind,
                "memory": memory,
                "size_mb": size_mb,
                "lifetime": lifetime,
                "aliases": aliases or [],
            }
        )
        if resource.id in self.resources:
            raise ValueError(f"Duplicate resource id: {resource.id}")
        self.resources[resource.id] = resource
        return resource

    def submit_operation(
        self,
        operation_id: str,
        operation_type: str,
        source: str | None = None,
        target: str | None = None,
        queue: str = "unknown",
        reason: str = "",
        cost_ms: float = 0,
        size_mb: float = 0,
        frame: int | None = None,
        depends_on: list[str] | None = None,
    ) -> ControllerResult:
        operation = parse_operation(
            {
                "id": operation_id,
                "type": operation_type,
                "source": source,
                "target": target,
                "queue": queue,
                "reason": reason,
                "cost_ms": cost_ms,
                "size_mb": size_mb,
                "frame": frame,
                "depends_on": depends_on or [],
            }
        )
        operation, decision = self._optimization.process(operation)
        if decision:
            self.decisions.append(decision)
            return ControllerResult(operation=operation, decision=decision, executed=False)

        self.executed_operations.append(operation)
        return ControllerResult(operation=operation, decision=None, executed=True)

    def snapshot(self) -> dict[str, Any]:
        saved_ms = round(sum(decision.estimated_saved_ms for decision in self.decisions), 4)
        saved_mb = round(sum(decision.estimated_saved_mb for decision in self.decisions), 4)
        return {
            "mode": "runtime-control-plane-v0.5",
            "resources": [resource.to_dict() for resource in self.resources.values()],
            "executed_operations": [
                operation.to_dict() for operation in self.executed_operations
            ],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "estimated_saved_ms": saved_ms,
            "estimated_saved_mb": saved_mb,
        }

    def write_snapshot(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        atomic_write_json(path, self.snapshot())
        return path

    def release_resource(self, resource_id: str) -> RuntimeResource | None:
        return self._optimization.release_resource(resource_id)
