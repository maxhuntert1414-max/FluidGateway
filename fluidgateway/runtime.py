from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MEMORY_LAYERS = {"ram", "vram", "shared", "staging", "swapchain", "display"}
RESOURCE_TYPES = {"buffer", "texture", "framebuffer", "command", "unknown"}
OPERATION_TYPES = {"copy", "sync", "allocate", "upload", "present", "compute", "draw"}


@dataclass(frozen=True)
class RuntimeResource:
    id: str
    kind: str
    memory: str
    size_mb: float
    lifetime: str
    aliases: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "memory": self.memory,
            "size_mb": self.size_mb,
            "lifetime": self.lifetime,
            "aliases": self.aliases,
        }


@dataclass(frozen=True)
class RuntimeOperation:
    id: str
    type: str
    source: str | None
    target: str | None
    queue: str
    reason: str
    cost_ms: float
    size_mb: float
    frame: int | None
    depends_on: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "target": self.target,
            "queue": self.queue,
            "reason": self.reason,
            "cost_ms": self.cost_ms,
            "size_mb": self.size_mb,
            "frame": self.frame,
            "depends_on": self.depends_on,
        }


@dataclass(frozen=True)
class RuntimeDecision:
    operation_id: str
    action: str
    policy: str
    rationale: str
    estimated_saved_ms: float
    estimated_saved_mb: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action": self.action,
            "policy": self.policy,
            "rationale": self.rationale,
            "estimated_saved_ms": self.estimated_saved_ms,
            "estimated_saved_mb": self.estimated_saved_mb,
        }


@dataclass(frozen=True)
class RuntimePlan:
    mode: str
    manifest_name: str
    original_operations: int
    optimized_operations: int
    estimated_saved_ms: float
    estimated_saved_mb: float
    kept_operations: list[RuntimeOperation]
    decisions: list[RuntimeDecision]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "manifest_name": self.manifest_name,
            "original_operations": self.original_operations,
            "optimized_operations": self.optimized_operations,
            "estimated_saved_ms": self.estimated_saved_ms,
            "estimated_saved_mb": self.estimated_saved_mb,
            "kept_operations": [operation.to_dict() for operation in self.kept_operations],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class RuntimeManifest:
    name: str
    resources: dict[str, RuntimeResource]
    operations: list[RuntimeOperation]


def load_manifest(path: str | Path) -> RuntimeManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Runtime manifest must be a JSON object.")

    resources_payload = payload.get("resources", [])
    operations_payload = payload.get("operations", [])
    if not isinstance(resources_payload, list):
        raise ValueError("Runtime manifest field 'resources' must be a list.")
    if not isinstance(operations_payload, list):
        raise ValueError("Runtime manifest field 'operations' must be a list.")

    resources = {}
    for item in resources_payload:
        resource = parse_resource(item)
        if resource.id in resources:
            raise ValueError(f"Duplicate resource id: {resource.id}")
        resources[resource.id] = resource

    operations = [parse_operation(item) for item in operations_payload]
    return RuntimeManifest(
        name=str(payload.get("name") or manifest_path.stem),
        resources=resources,
        operations=operations,
    )


def optimize_manifest(manifest: RuntimeManifest) -> RuntimePlan:
    decisions: list[RuntimeDecision] = []
    kept: list[RuntimeOperation] = []
    warnings = validate_manifest(manifest)
    removed_ids: set[str] = set()
    last_copy_by_target: dict[str, RuntimeOperation] = {}
    active_buffers: dict[tuple[str | None, float], RuntimeOperation] = {}

    for operation in manifest.operations:
        decision = decide_operation(
            operation=operation,
            resources=manifest.resources,
            last_copy_by_target=last_copy_by_target,
            active_buffers=active_buffers,
            removed_ids=removed_ids,
        )
        if decision:
            decisions.append(decision)
            removed_ids.add(operation.id)
            continue

        kept.append(operation)
        if operation.type in {"copy", "upload"} and operation.target:
            last_copy_by_target[operation.target] = operation
        if operation.type == "allocate":
            active_buffers[(operation.target, operation.size_mb)] = operation

    saved_ms = round(sum(decision.estimated_saved_ms for decision in decisions), 4)
    saved_mb = round(sum(decision.estimated_saved_mb for decision in decisions), 4)
    return RuntimePlan(
        mode="runtime-optimizer-v0.4-manifest",
        manifest_name=manifest.name,
        original_operations=len(manifest.operations),
        optimized_operations=len(kept),
        estimated_saved_ms=saved_ms,
        estimated_saved_mb=saved_mb,
        kept_operations=kept,
        decisions=decisions,
        warnings=warnings,
    )


def write_runtime_plan(plan: RuntimePlan, output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def decide_operation(
    operation: RuntimeOperation,
    resources: dict[str, RuntimeResource],
    last_copy_by_target: dict[str, RuntimeOperation],
    active_buffers: dict[tuple[str | None, float], RuntimeOperation],
    removed_ids: set[str],
) -> RuntimeDecision | None:
    if operation.type in {"copy", "upload"}:
        if operation.source == operation.target:
            return RuntimeDecision(
                operation.id,
                "remove",
                "eliminate-self-copy",
                "Source and target are the same resource; the transfer does no useful movement.",
                operation.cost_ms,
                operation.size_mb,
            )

        target_resource = resources.get(operation.target or "")
        source_resource = resources.get(operation.source or "")
        if target_resource and source_resource:
            same_memory = target_resource.memory == source_resource.memory
            same_alias = bool(set(target_resource.aliases) & set(source_resource.aliases))
            if same_memory and same_alias:
                return RuntimeDecision(
                    operation.id,
                    "remove",
                    "collapse-aliased-resource-copy",
                    "Source and target alias the same data in the same memory layer.",
                    operation.cost_ms,
                    operation.size_mb,
                )

        previous = last_copy_by_target.get(operation.target or "")
        if previous and previous.source == operation.source and previous.size_mb == operation.size_mb:
            return RuntimeDecision(
                operation.id,
                "remove",
                "deduplicate-identical-transfer",
                "Previous transfer already populated the same target from the same source.",
                operation.cost_ms,
                operation.size_mb,
            )

    if operation.type == "sync":
        if operation.depends_on and all(dep in removed_ids for dep in operation.depends_on):
            return RuntimeDecision(
                operation.id,
                "remove",
                "remove-orphan-sync",
                "Synchronization only waits on operations already removed by earlier policies.",
                operation.cost_ms,
                0,
            )
        if operation.cost_ms <= 0 and not operation.depends_on:
            return RuntimeDecision(
                operation.id,
                "remove",
                "remove-empty-sync",
                "Synchronization has no dependency and no measured cost.",
                0,
                0,
            )

    if operation.type == "allocate":
        key = (operation.target, operation.size_mb)
        previous = active_buffers.get(key)
        if previous and is_transient_reason(operation.reason):
            return RuntimeDecision(
                operation.id,
                "reuse",
                "reuse-transient-buffer",
                "A transient buffer with the same target and size is already available for reuse.",
                operation.cost_ms,
                operation.size_mb,
            )

    return None


def validate_manifest(manifest: RuntimeManifest) -> list[str]:
    warnings = []
    known = set(manifest.resources)
    for operation in manifest.operations:
        for role, resource_id in (("source", operation.source), ("target", operation.target)):
            if resource_id and resource_id not in known:
                warnings.append(
                    f"Operation {operation.id} references unknown {role} resource {resource_id}."
                )
    if not manifest.operations:
        warnings.append("Manifest contains no operations.")
    return warnings


def parse_resource(payload: Any) -> RuntimeResource:
    if not isinstance(payload, dict):
        raise ValueError("Resource entries must be objects.")
    resource_id = str(payload.get("id") or "").strip()
    if not resource_id:
        raise ValueError("Resource id is required.")
    kind = normalized_choice(payload.get("kind"), RESOURCE_TYPES, "unknown")
    memory = normalized_choice(payload.get("memory"), MEMORY_LAYERS, "ram")
    aliases = payload.get("aliases") or []
    if not isinstance(aliases, list):
        raise ValueError(f"Resource {resource_id} aliases must be a list.")
    return RuntimeResource(
        id=resource_id,
        kind=kind,
        memory=memory,
        size_mb=float(payload.get("size_mb") or 0),
        lifetime=str(payload.get("lifetime") or "unknown"),
        aliases=[str(alias) for alias in aliases],
    )


def parse_operation(payload: Any) -> RuntimeOperation:
    if not isinstance(payload, dict):
        raise ValueError("Operation entries must be objects.")
    operation_id = str(payload.get("id") or "").strip()
    if not operation_id:
        raise ValueError("Operation id is required.")
    depends_on = payload.get("depends_on") or []
    if not isinstance(depends_on, list):
        raise ValueError(f"Operation {operation_id} depends_on must be a list.")
    frame = payload.get("frame")
    return RuntimeOperation(
        id=operation_id,
        type=normalized_choice(payload.get("type"), OPERATION_TYPES, "compute"),
        source=optional_text(payload.get("source")),
        target=optional_text(payload.get("target")),
        queue=str(payload.get("queue") or "unknown"),
        reason=str(payload.get("reason") or ""),
        cost_ms=float(payload.get("cost_ms") or 0),
        size_mb=float(payload.get("size_mb") or 0),
        frame=int(frame) if frame is not None else None,
        depends_on=[str(item) for item in depends_on],
    )


def normalized_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or default).strip().lower()
    return text if text in allowed else default


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_transient_reason(reason: str) -> bool:
    text = reason.lower()
    return any(token in text for token in ("transient", "scratch", "temporary", "staging"))
