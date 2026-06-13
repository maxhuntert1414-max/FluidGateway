from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .transit import MemoryTransitHop, MemoryTransitMap


MEMORY_ROUTE_MODE = "memory-route-plan-v0.23"


@dataclass(frozen=True)
class MemoryRouteDirective:
    directive: str
    priority: int
    operation_id: str
    frame: int | None
    path: str
    source_memory: str
    target_memory: str
    target_resource_id: str | None
    value_mb: float
    expected_saved_ms: float
    expected_saved_mb: float
    source_classification: str
    rationale: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "directive": self.directive,
            "priority": self.priority,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "path": self.path,
            "source_memory": self.source_memory,
            "target_memory": self.target_memory,
            "target_resource_id": self.target_resource_id,
            "value_mb": round(self.value_mb, 4),
            "expected_saved_ms": round(self.expected_saved_ms, 4),
            "expected_saved_mb": round(self.expected_saved_mb, 4),
            "source_classification": self.source_classification,
            "rationale": self.rationale,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class MemoryRoutePlan:
    mode: str
    directive_count: int
    suppress_count: int
    prefetch_count: int
    residency_count: int
    sync_count: int
    estimated_saved_ms: float
    estimated_saved_mb: float
    directives: list[MemoryRouteDirective]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "directive_count": self.directive_count,
            "suppress_count": self.suppress_count,
            "prefetch_count": self.prefetch_count,
            "residency_count": self.residency_count,
            "sync_count": self.sync_count,
            "estimated_saved_ms": round(self.estimated_saved_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
            "directives": [directive.to_dict() for directive in self.directives],
        }


def build_memory_route_plan(transit_map: MemoryTransitMap) -> MemoryRoutePlan:
    directives = [
        directive
        for directive in (directive_from_hop(hop) for hop in transit_map.hops)
        if directive is not None
    ]
    directives = sorted(
        directives,
        key=lambda item: (
            -item.priority,
            item.frame if item.frame is not None else -1,
            item.operation_id,
        ),
    )
    return MemoryRoutePlan(
        mode=MEMORY_ROUTE_MODE,
        directive_count=len(directives),
        suppress_count=count_directives(
            directives,
            {"suppress_redundant_hop", "reuse_transient_allocation"},
        ),
        prefetch_count=count_directive(directives, "prestage_cross_memory_transfer"),
        residency_count=count_directive(directives, "protect_presentation_route"),
        sync_count=count_directive(directives, "remove_sync_wait"),
        estimated_saved_ms=sum(directive.expected_saved_ms for directive in directives),
        estimated_saved_mb=sum(directive.expected_saved_mb for directive in directives),
        directives=directives,
    )


def directive_from_hop(hop: MemoryTransitHop) -> MemoryRouteDirective | None:
    if hop.classification in {
        "duplicate-transfer",
        "same-layer-aliased-copy",
        "self-transfer",
    }:
        return route_directive(
            hop,
            directive="suppress_redundant_hop",
            priority=96,
            expected_saved_ms=hop.cost_ms,
            expected_saved_mb=hop.size_mb,
            rationale="Suppress a data movement hop already proven redundant.",
            expected_effect="Remove useless transfer pressure from the CPU/GPU memory path.",
        )
    if hop.classification == "redundant-allocation":
        return route_directive(
            hop,
            directive="reuse_transient_allocation",
            priority=88,
            expected_saved_ms=hop.cost_ms,
            expected_saved_mb=hop.size_mb,
            rationale="Reuse an equivalent transient allocation instead of allocating again.",
            expected_effect="Reduce allocator churn and transient VRAM/RAM pressure.",
        )
    if hop.classification in {"orphan-sync", "empty-sync"}:
        return route_directive(
            hop,
            directive="remove_sync_wait",
            priority=92,
            expected_saved_ms=hop.cost_ms,
            expected_saved_mb=0.0,
            rationale="Remove synchronization that no longer gates useful work.",
            expected_effect="Lower CPU/GPU wait time caused by useless synchronization.",
        )
    if is_cross_memory_transfer(hop) and is_large_or_expensive(hop):
        return route_directive(
            hop,
            directive="prestage_cross_memory_transfer",
            priority=82,
            expected_saved_ms=0.0,
            expected_saved_mb=0.0,
            rationale="Route this cross-memory movement before draw-critical work.",
            expected_effect="Move RAM/VRAM traffic out of the hot frame path.",
        )
    if hop.classification == "allocation" and hop.size_mb >= 16:
        return route_directive(
            hop,
            directive="pool_transient_allocation",
            priority=72,
            expected_saved_ms=0.0,
            expected_saved_mb=0.0,
            rationale="Pool this allocation shape for reuse across nearby frames.",
            expected_effect="Reduce late allocation work and memory allocator pressure.",
        )
    if hop.classification == "presentation-path":
        return route_directive(
            hop,
            directive="protect_presentation_route",
            priority=70,
            expected_saved_ms=0.0,
            expected_saved_mb=0.0,
            rationale="Protect the final frame presentation path from extra hops.",
            expected_effect="Keep display-facing work predictable and avoid late copies.",
        )
    return None


def route_directive(
    hop: MemoryTransitHop,
    *,
    directive: str,
    priority: int,
    expected_saved_ms: float,
    expected_saved_mb: float,
    rationale: str,
    expected_effect: str,
) -> MemoryRouteDirective:
    return MemoryRouteDirective(
        directive=directive,
        priority=priority,
        operation_id=hop.operation_id,
        frame=hop.frame,
        path=hop.path,
        source_memory=hop.source_memory,
        target_memory=hop.target_memory,
        target_resource_id=hop.target_resource_id,
        value_mb=hop.size_mb,
        expected_saved_ms=expected_saved_ms,
        expected_saved_mb=expected_saved_mb,
        source_classification=hop.classification,
        rationale=rationale,
        expected_effect=expected_effect,
    )


def is_cross_memory_transfer(hop: MemoryTransitHop) -> bool:
    return (
        hop.classification == "cross-memory-transfer"
        and hop.executed
        and hop.source_memory != "unknown"
        and hop.target_memory != "unknown"
    )


def is_large_or_expensive(hop: MemoryTransitHop) -> bool:
    return hop.size_mb >= 16 or hop.cost_ms >= 1.0


def count_directive(
    directives: list[MemoryRouteDirective], directive_name: str
) -> int:
    return sum(1 for directive in directives if directive.directive == directive_name)


def count_directives(
    directives: list[MemoryRouteDirective], directive_names: set[str]
) -> int:
    return sum(1 for directive in directives if directive.directive in directive_names)
