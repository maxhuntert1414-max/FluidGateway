from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adaptive import AdaptiveExecutorDirective, AdaptiveExecutorLoop
from .policy import DEFAULT_FRAME_BUDGET_MS
from .state import LiveStateSnapshot


BUDGET_ENVELOPE_MODE = "runtime-budget-envelope-v0.28"
KNOWN_MEMORY_LAYERS = ("ram", "vram", "shared", "staging", "swapchain")


@dataclass(frozen=True)
class MemoryBudgetEnvelope:
    memory: str
    active_mb: float
    budget_mb: float | None
    headroom_mb: float | None
    pressure_mb: float
    status: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory,
            "active_mb": round(self.active_mb, 4),
            "budget_mb": rounded_or_none(self.budget_mb),
            "headroom_mb": rounded_or_none(self.headroom_mb),
            "pressure_mb": round(self.pressure_mb, 4),
            "status": self.status,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class FrameBudgetEnvelope:
    frame: int
    profile: str
    pressure_status: str
    target_frame_ms: float
    max_hot_path_ms: float
    copy_queue_budget_ms: float
    pre_frame_window_ms: float
    budget_delta_ms: float
    admission_policy: str
    memory_policy: str
    directive_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "profile": self.profile,
            "pressure_status": self.pressure_status,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "max_hot_path_ms": round(self.max_hot_path_ms, 4),
            "copy_queue_budget_ms": round(self.copy_queue_budget_ms, 4),
            "pre_frame_window_ms": round(self.pre_frame_window_ms, 4),
            "budget_delta_ms": round(self.budget_delta_ms, 4),
            "admission_policy": self.admission_policy,
            "memory_policy": self.memory_policy,
            "directive_count": self.directive_count,
        }


@dataclass(frozen=True)
class RuntimeBudgetEnvelope:
    mode: str
    profile: str
    next_frame_policy: str
    frame_count: int
    over_budget_frame_count: int
    memory_layer_count: int
    constrained_memory_count: int
    total_memory_pressure_mb: float
    frames: list[FrameBudgetEnvelope]
    memory_layers: list[MemoryBudgetEnvelope]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profile": self.profile,
            "next_frame_policy": self.next_frame_policy,
            "frame_count": self.frame_count,
            "over_budget_frame_count": self.over_budget_frame_count,
            "memory_layer_count": self.memory_layer_count,
            "constrained_memory_count": self.constrained_memory_count,
            "total_memory_pressure_mb": round(self.total_memory_pressure_mb, 4),
            "frames": [frame.to_dict() for frame in self.frames],
            "memory_layers": [layer.to_dict() for layer in self.memory_layers],
        }


def build_runtime_budget_envelope(
    adaptive_loop: AdaptiveExecutorLoop,
    state_snapshot: LiveStateSnapshot | dict[str, Any] | None = None,
    memory_budgets_mb: dict[str, float] | None = None,
) -> RuntimeBudgetEnvelope:
    memory_layers = build_memory_layers(state_snapshot, memory_budgets_mb)
    constrained_memory_count = sum(
        1
        for layer in memory_layers
        if layer.status in {"near-budget", "over-budget"}
    )
    memory_constrained = constrained_memory_count > 0
    frames = [
        build_frame_envelope(frame, adaptive_loop.directives, memory_constrained)
        for frame in adaptive_loop.frames
    ]
    over_budget_count = sum(
        1 for frame in frames if frame.pressure_status == "over-budget"
    )
    profile = "aggressive" if over_budget_count or memory_constrained else "stable"
    return RuntimeBudgetEnvelope(
        mode=BUDGET_ENVELOPE_MODE,
        profile=profile,
        next_frame_policy=next_frame_policy(profile, memory_constrained),
        frame_count=len(frames),
        over_budget_frame_count=over_budget_count,
        memory_layer_count=len(memory_layers),
        constrained_memory_count=constrained_memory_count,
        total_memory_pressure_mb=sum(layer.pressure_mb for layer in memory_layers),
        frames=frames,
        memory_layers=memory_layers,
    )


def build_frame_envelope(
    frame: Any,
    directives: list[AdaptiveExecutorDirective],
    memory_constrained: bool,
) -> FrameBudgetEnvelope:
    frame_directives = [item for item in directives if item.frame == frame.frame]
    over_budget = frame.pressure_status == "over-budget"
    pre_frame_window = directive_value(
        frame_directives,
        "expand-pre-frame-window",
        "preserve-pre-frame-window",
    )
    if over_budget:
        copy_budget = 0.0
        admission_policy = "block-noncritical-hot-path"
    else:
        copy_budget = suggest_copy_queue_budget(
            frame.target_frame_ms,
            frame.budget_delta_ms,
        )
        admission_policy = "allow-budgeted-hot-path"

    return FrameBudgetEnvelope(
        frame=frame.frame,
        profile="aggressive" if over_budget or memory_constrained else "stable",
        pressure_status=frame.pressure_status,
        target_frame_ms=frame.target_frame_ms,
        max_hot_path_ms=frame.target_frame_ms,
        copy_queue_budget_ms=copy_budget,
        pre_frame_window_ms=pre_frame_window,
        budget_delta_ms=frame.budget_delta_ms,
        admission_policy=admission_policy,
        memory_policy=(
            "evict-or-defer-residency"
            if memory_constrained
            else "hold-current-residency"
        ),
        directive_count=len(frame_directives),
    )


def build_memory_layers(
    state_snapshot: LiveStateSnapshot | dict[str, Any] | None,
    memory_budgets_mb: dict[str, float] | None,
) -> list[MemoryBudgetEnvelope]:
    totals = snapshot_map(state_snapshot, "memory_totals_mb")
    budgets = dict(memory_budgets_mb or {})
    budgets.update(snapshot_map(state_snapshot, "memory_budgets_mb"))
    memories = sorted(set(KNOWN_MEMORY_LAYERS) | set(totals) | set(budgets))
    return [
        build_memory_layer(memory, totals.get(memory, 0.0), budgets.get(memory))
        for memory in memories
        if totals.get(memory, 0.0) > 0 or memory in budgets
    ]


def build_memory_layer(
    memory: str, active_mb: float, budget_mb: float | None
) -> MemoryBudgetEnvelope:
    if budget_mb is None:
        return MemoryBudgetEnvelope(
            memory=memory,
            active_mb=active_mb,
            budget_mb=None,
            headroom_mb=None,
            pressure_mb=0.0,
            status="unbounded",
            recommendation="observe-residency",
        )

    headroom = budget_mb - active_mb
    pressure = max(0.0, active_mb - budget_mb)
    if pressure > 0:
        status = "over-budget"
        recommendation = "evict-or-defer-residency"
    elif active_mb >= budget_mb * 0.85:
        status = "near-budget"
        recommendation = "reserve-headroom"
    else:
        status = "within-budget"
        recommendation = "hold-residency"

    return MemoryBudgetEnvelope(
        memory=memory,
        active_mb=active_mb,
        budget_mb=budget_mb,
        headroom_mb=headroom,
        pressure_mb=pressure,
        status=status,
        recommendation=recommendation,
    )


def next_frame_policy(profile: str, memory_constrained: bool) -> str:
    if profile == "aggressive" and memory_constrained:
        return "tighten-frame-and-memory-admission"
    if profile == "aggressive":
        return "tighten-frame-admission"
    if memory_constrained:
        return "tighten-memory-admission"
    return "maintain-current-envelope"


def suggest_copy_queue_budget(target_frame_ms: float, budget_delta_ms: float) -> float:
    if budget_delta_ms <= 0:
        return 0.0
    return min(target_frame_ms * 0.15, budget_delta_ms * 0.25)


def directive_value(
    directives: list[AdaptiveExecutorDirective], *actions: str
) -> float:
    wanted = set(actions)
    values = [directive.value for directive in directives if directive.action in wanted]
    return max(values, default=0.0)


def snapshot_map(
    state_snapshot: LiveStateSnapshot | dict[str, Any] | None, key: str
) -> dict[str, float]:
    if state_snapshot is None:
        return {}
    values = (
        getattr(state_snapshot, key)
        if isinstance(state_snapshot, LiveStateSnapshot)
        else state_snapshot.get(key)
    )
    if not isinstance(values, dict):
        return {}
    return {
        str(item_key): float(item_value)
        for item_key, item_value in values.items()
        if item_value is not None
    }


def rounded_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)
