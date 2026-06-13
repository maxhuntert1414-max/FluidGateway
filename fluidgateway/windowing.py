from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .routing import MemoryRouteDirective, MemoryRoutePlan


FRAME_WINDOW_MODE = "frame-window-plan-v0.24"


WINDOW_ORDER = {
    "never": 0,
    "pre-frame": 1,
    "setup": 2,
    "hot-path": 3,
    "post-present": 4,
}


@dataclass(frozen=True)
class FrameWindowSlot:
    sequence: int
    window: str
    phase: str
    directive: str
    operation_id: str
    frame: int | None
    path: str
    target_resource_id: str | None
    value_mb: float
    cost_ms: float
    expected_saved_ms: float
    expected_saved_mb: float
    rationale: str
    expected_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "window": self.window,
            "phase": self.phase,
            "directive": self.directive,
            "operation_id": self.operation_id,
            "frame": self.frame,
            "path": self.path,
            "target_resource_id": self.target_resource_id,
            "value_mb": round(self.value_mb, 4),
            "cost_ms": round(self.cost_ms, 4),
            "expected_saved_ms": round(self.expected_saved_ms, 4),
            "expected_saved_mb": round(self.expected_saved_mb, 4),
            "rationale": self.rationale,
            "expected_effect": self.expected_effect,
        }


@dataclass(frozen=True)
class FrameWindowSummary:
    frame: int
    slot_count: int
    never_count: int
    pre_frame_count: int
    setup_count: int
    hot_path_count: int
    post_present_count: int
    estimated_saved_ms: float
    estimated_saved_mb: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "slot_count": self.slot_count,
            "never_count": self.never_count,
            "pre_frame_count": self.pre_frame_count,
            "setup_count": self.setup_count,
            "hot_path_count": self.hot_path_count,
            "post_present_count": self.post_present_count,
            "estimated_saved_ms": round(self.estimated_saved_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
        }


@dataclass(frozen=True)
class FrameWindowPlan:
    mode: str
    slot_count: int
    frame_count: int
    never_count: int
    pre_frame_count: int
    setup_count: int
    hot_path_count: int
    post_present_count: int
    estimated_hot_path_relief_ms: float
    estimated_saved_mb: float
    frames: list[FrameWindowSummary]
    slots: list[FrameWindowSlot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "slot_count": self.slot_count,
            "frame_count": self.frame_count,
            "never_count": self.never_count,
            "pre_frame_count": self.pre_frame_count,
            "setup_count": self.setup_count,
            "hot_path_count": self.hot_path_count,
            "post_present_count": self.post_present_count,
            "estimated_hot_path_relief_ms": round(
                self.estimated_hot_path_relief_ms, 4
            ),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
            "frames": [frame.to_dict() for frame in self.frames],
            "slots": [slot.to_dict() for slot in self.slots],
        }


def build_frame_window_plan(route_plan: MemoryRoutePlan) -> FrameWindowPlan:
    slots = [
        slot
        for slot in (
            slot_from_directive(directive) for directive in route_plan.directives
        )
        if slot is not None
    ]
    slots = [
        FrameWindowSlot(sequence=index, **slot_payload(slot))
        for index, slot in enumerate(sort_slots(slots), start=1)
    ]
    return FrameWindowPlan(
        mode=FRAME_WINDOW_MODE,
        slot_count=len(slots),
        frame_count=len({slot.frame for slot in slots if slot.frame is not None}),
        never_count=count_window(slots, "never"),
        pre_frame_count=count_window(slots, "pre-frame"),
        setup_count=count_window(slots, "setup"),
        hot_path_count=count_window(slots, "hot-path"),
        post_present_count=count_window(slots, "post-present"),
        estimated_hot_path_relief_ms=sum(slot.expected_saved_ms for slot in slots),
        estimated_saved_mb=sum(slot.expected_saved_mb for slot in slots),
        frames=summarize_frames(slots),
        slots=slots,
    )


def slot_from_directive(
    directive: MemoryRouteDirective,
) -> FrameWindowSlot | None:
    window, phase = classify_window(directive.directive)
    if window is None:
        return None
    return FrameWindowSlot(
        sequence=0,
        window=window,
        phase=phase,
        directive=directive.directive,
        operation_id=directive.operation_id,
        frame=directive.frame,
        path=directive.path,
        target_resource_id=directive.target_resource_id,
        value_mb=directive.value_mb,
        cost_ms=directive.cost_ms,
        expected_saved_ms=directive.expected_saved_ms,
        expected_saved_mb=directive.expected_saved_mb,
        rationale=directive.rationale,
        expected_effect=directive.expected_effect,
    )


def classify_window(directive: str) -> tuple[str | None, str]:
    if directive == "suppress_redundant_hop":
        return "never", "suppress"
    if directive == "reuse_transient_allocation":
        return "never", "reuse"
    if directive == "remove_sync_wait":
        return "never", "remove-sync"
    if directive == "prestage_cross_memory_transfer":
        return "pre-frame", "prefetch"
    if directive == "pool_transient_allocation":
        return "setup", "pool"
    if directive == "protect_presentation_route":
        return "hot-path", "present"
    return None, "unknown"


def sort_slots(slots: list[FrameWindowSlot]) -> list[FrameWindowSlot]:
    return sorted(
        slots,
        key=lambda slot: (
            slot.frame if slot.frame is not None else -1,
            WINDOW_ORDER.get(slot.window, 99),
            slot.operation_id,
        ),
    )


def slot_payload(slot: FrameWindowSlot) -> dict[str, Any]:
    payload = slot.to_dict()
    payload.pop("sequence", None)
    return payload


def summarize_frames(slots: list[FrameWindowSlot]) -> list[FrameWindowSummary]:
    frames: dict[int, list[FrameWindowSlot]] = {}
    for slot in slots:
        if slot.frame is not None:
            frames.setdefault(slot.frame, []).append(slot)

    summaries: list[FrameWindowSummary] = []
    for frame, frame_slots in sorted(frames.items()):
        summaries.append(
            FrameWindowSummary(
                frame=frame,
                slot_count=len(frame_slots),
                never_count=count_window(frame_slots, "never"),
                pre_frame_count=count_window(frame_slots, "pre-frame"),
                setup_count=count_window(frame_slots, "setup"),
                hot_path_count=count_window(frame_slots, "hot-path"),
                post_present_count=count_window(frame_slots, "post-present"),
                estimated_saved_ms=sum(
                    slot.expected_saved_ms for slot in frame_slots
                ),
                estimated_saved_mb=sum(
                    slot.expected_saved_mb for slot in frame_slots
                ),
            )
        )
    return summaries


def count_window(slots: list[FrameWindowSlot], window: str) -> int:
    return sum(1 for slot in slots if slot.window == window)
