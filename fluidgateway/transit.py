from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime import RuntimeResource


MEMORY_TRANSIT_MODE = "memory-transit-map-v0.22"


@dataclass(frozen=True)
class MemoryTransitHop:
    operation_id: str
    operation_type: str
    frame: int | None
    queue: str
    source_resource_id: str | None
    target_resource_id: str | None
    source_memory: str
    target_memory: str
    path: str
    size_mb: float
    cost_ms: float
    executed: bool
    avoided: bool
    classification: str
    waste_policy: str | None
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "frame": self.frame,
            "queue": self.queue,
            "source_resource_id": self.source_resource_id,
            "target_resource_id": self.target_resource_id,
            "source_memory": self.source_memory,
            "target_memory": self.target_memory,
            "path": self.path,
            "size_mb": round(self.size_mb, 4),
            "cost_ms": round(self.cost_ms, 4),
            "executed": self.executed,
            "avoided": self.avoided,
            "classification": self.classification,
            "waste_policy": self.waste_policy,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class MemoryPathSummary:
    path: str
    hop_count: int
    executed_hop_count: int
    avoided_hop_count: int
    attempted_mb: float
    executed_mb: float
    avoided_mb: float
    cost_ms: float
    avoided_cost_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "hop_count": self.hop_count,
            "executed_hop_count": self.executed_hop_count,
            "avoided_hop_count": self.avoided_hop_count,
            "attempted_mb": round(self.attempted_mb, 4),
            "executed_mb": round(self.executed_mb, 4),
            "avoided_mb": round(self.avoided_mb, 4),
            "cost_ms": round(self.cost_ms, 4),
            "avoided_cost_ms": round(self.avoided_cost_ms, 4),
        }


@dataclass(frozen=True)
class MemoryTransitMap:
    mode: str
    hop_count: int
    executed_hop_count: int
    avoided_hop_count: int
    attempted_transfer_mb: float
    executed_transfer_mb: float
    avoided_transfer_mb: float
    estimated_avoidable_cost_ms: float
    paths: list[MemoryPathSummary]
    hops: list[MemoryTransitHop]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hop_count": self.hop_count,
            "executed_hop_count": self.executed_hop_count,
            "avoided_hop_count": self.avoided_hop_count,
            "attempted_transfer_mb": round(self.attempted_transfer_mb, 4),
            "executed_transfer_mb": round(self.executed_transfer_mb, 4),
            "avoided_transfer_mb": round(self.avoided_transfer_mb, 4),
            "estimated_avoidable_cost_ms": round(
                self.estimated_avoidable_cost_ms, 4
            ),
            "paths": [path.to_dict() for path in self.paths],
            "hops": [hop.to_dict() for hop in self.hops],
        }


def build_memory_transit_map(
    operation_results: list[dict[str, Any]],
    resources: dict[str, RuntimeResource | dict[str, Any]],
) -> MemoryTransitMap:
    resource_map = normalize_resources(resources)
    hops = [
        hop
        for hop in (
            build_hop(result, resource_map) for result in operation_results
        )
        if hop is not None
    ]
    return MemoryTransitMap(
        mode=MEMORY_TRANSIT_MODE,
        hop_count=len(hops),
        executed_hop_count=sum(1 for hop in hops if hop.executed),
        avoided_hop_count=sum(1 for hop in hops if hop.avoided),
        attempted_transfer_mb=sum(hop.size_mb for hop in hops),
        executed_transfer_mb=sum(hop.size_mb for hop in hops if hop.executed),
        avoided_transfer_mb=sum(hop.size_mb for hop in hops if hop.avoided),
        estimated_avoidable_cost_ms=sum(hop.cost_ms for hop in hops if hop.avoided),
        paths=summarize_paths(hops),
        hops=hops,
    )


def build_hop(
    result: dict[str, Any],
    resources: dict[str, dict[str, Any]],
) -> MemoryTransitHop | None:
    operation = result.get("operation") or {}
    if not isinstance(operation, dict):
        return None

    operation_type = str(operation.get("type") or "unknown")
    source_id = optional_text(operation.get("source"))
    target_id = optional_text(operation.get("target"))
    if not is_transit_operation(operation_type, source_id, target_id):
        return None

    queue = str(operation.get("queue") or "unknown")
    decision = (
        result.get("decision") if isinstance(result.get("decision"), dict) else None
    )
    executed = bool(result.get("executed"))
    avoided = bool(decision) or not executed
    source_memory = resolve_source_memory(operation_type, source_id, resources)
    target_memory = resolve_target_memory(operation_type, target_id, queue, resources)
    classification = classify(operation_type, source_memory, target_memory, decision)
    rationale = str(
        (decision or {}).get("rationale")
        or operation.get("reason")
        or "Observed runtime data movement."
    )

    return MemoryTransitHop(
        operation_id=str(operation.get("id") or ""),
        operation_type=operation_type,
        frame=optional_int(operation.get("frame")),
        queue=queue,
        source_resource_id=source_id,
        target_resource_id=target_id,
        source_memory=source_memory,
        target_memory=target_memory,
        path=f"{source_memory}->{target_memory}",
        size_mb=transit_size_mb(operation, target_id, resources),
        cost_ms=number(operation.get("cost_ms")),
        executed=executed,
        avoided=avoided,
        classification=classification,
        waste_policy=(decision or {}).get("policy"),
        rationale=rationale,
    )


def summarize_paths(hops: list[MemoryTransitHop]) -> list[MemoryPathSummary]:
    by_path: dict[str, list[MemoryTransitHop]] = {}
    for hop in hops:
        by_path.setdefault(hop.path, []).append(hop)

    summaries = []
    for path, path_hops in sorted(by_path.items()):
        summaries.append(
            MemoryPathSummary(
                path=path,
                hop_count=len(path_hops),
                executed_hop_count=sum(1 for hop in path_hops if hop.executed),
                avoided_hop_count=sum(1 for hop in path_hops if hop.avoided),
                attempted_mb=sum(hop.size_mb for hop in path_hops),
                executed_mb=sum(hop.size_mb for hop in path_hops if hop.executed),
                avoided_mb=sum(hop.size_mb for hop in path_hops if hop.avoided),
                cost_ms=sum(hop.cost_ms for hop in path_hops),
                avoided_cost_ms=sum(hop.cost_ms for hop in path_hops if hop.avoided),
            )
        )
    return summaries


def normalize_resources(
    resources: dict[str, RuntimeResource | dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for resource_id, resource in resources.items():
        payload = (
            resource.to_dict() if isinstance(resource, RuntimeResource) else resource
        )
        if isinstance(payload, dict):
            normalized[str(resource_id)] = payload
    return normalized


def is_transit_operation(
    operation_type: str, source_id: str | None, target_id: str | None
) -> bool:
    if operation_type in {"copy", "upload", "allocate", "draw", "present", "sync"}:
        return True
    return bool(source_id or target_id)


def resolve_source_memory(
    operation_type: str,
    source_id: str | None,
    resources: dict[str, dict[str, Any]],
) -> str:
    if operation_type == "allocate":
        return "allocation"
    if operation_type == "sync":
        return "sync"
    if source_id and source_id in resources:
        return str(resources[source_id].get("memory") or "unknown")
    return "unknown"


def resolve_target_memory(
    operation_type: str,
    target_id: str | None,
    queue: str,
    resources: dict[str, dict[str, Any]],
) -> str:
    if operation_type == "sync":
        return queue
    if target_id and target_id in resources:
        return str(resources[target_id].get("memory") or "unknown")
    return "unknown"


def classify(
    operation_type: str,
    source_memory: str,
    target_memory: str,
    decision: dict[str, Any] | None,
) -> str:
    policy = str((decision or {}).get("policy") or "")
    policy_classifications = {
        "deduplicate-identical-transfer": "duplicate-transfer",
        "collapse-aliased-resource-copy": "same-layer-aliased-copy",
        "eliminate-self-copy": "self-transfer",
        "reuse-transient-buffer": "redundant-allocation",
        "remove-orphan-sync": "orphan-sync",
        "remove-empty-sync": "empty-sync",
    }
    if policy in policy_classifications:
        return policy_classifications[policy]
    if operation_type == "allocate":
        return "allocation"
    if operation_type == "sync":
        return "synchronization"
    if operation_type in {"draw", "present"}:
        return "presentation-path"
    if source_memory == target_memory:
        return "same-memory-transfer"
    return "cross-memory-transfer"


def transit_size_mb(
    operation: dict[str, Any],
    target_id: str | None,
    resources: dict[str, dict[str, Any]],
) -> float:
    size_mb = number(operation.get("size_mb"))
    if size_mb > 0:
        return size_mb
    if target_id and target_id in resources and operation.get("type") in {
        "draw",
        "present",
        "compute",
    }:
        return number(resources[target_id].get("size_mb"))
    return 0.0


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
