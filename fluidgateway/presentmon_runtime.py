from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AnalysisReport, ManagementAction, MetricSummary
from .policy import DEFAULT_FRAME_BUDGET_MS


PRESENTMON_RUNTIME_MODE = "presentmon-runtime-event-ingest-v0.59"


@dataclass(frozen=True)
class PresentMonRuntimeEventStream:
    mode: str
    source: str
    application: str
    session_id: str
    target_frame_ms: float
    finding_count: int
    management_action_count: int
    resource_event_count: int
    operation_event_count: int
    event_count: int
    events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source": self.source,
            "application": self.application,
            "session_id": self.session_id,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "finding_count": self.finding_count,
            "management_action_count": self.management_action_count,
            "resource_event_count": self.resource_event_count,
            "operation_event_count": self.operation_event_count,
            "event_count": self.event_count,
            "events": self.events,
        }


def build_presentmon_runtime_event_stream(
    report: AnalysisReport,
) -> PresentMonRuntimeEventStream:
    target_frame_ms = frame_budget_from_report(report)
    session_id = f"presentmon-{slug(report.summary.application or 'trace')}"
    resource_events: list[dict[str, Any]] = []
    operation_events: list[dict[str, Any]] = []

    for index, action in enumerate(report.management_plan.actions, start=1):
        resources, operation = action_to_events(index, action, target_frame_ms)
        resource_events.extend(resources)
        operation_events.append(operation)

    events: list[dict[str, Any]] = [
        {
            "event": "session",
            "action": "begin",
            "id": session_id,
            "mode": PRESENTMON_RUNTIME_MODE,
            "source": report.summary.source,
            "application": report.summary.application,
            "finding_count": len(report.findings),
            "management_action_count": len(report.management_plan.actions),
            "budgets": runtime_budgets(target_frame_ms, report.management_plan.actions),
            "disclaimer": report.disclaimer,
        },
        {
            "event": "frame",
            "action": "begin",
            "frame": 0,
            "target_frame_ms": round(target_frame_ms, 4),
        },
    ]
    events.extend(resource_events)
    events.extend(operation_events)
    events.append({"event": "state", "action": "snapshot"})
    events.append({"event": "frame", "action": "end", "frame": 0})
    events.append({"event": "session", "action": "end"})

    return PresentMonRuntimeEventStream(
        mode=PRESENTMON_RUNTIME_MODE,
        source=report.summary.source,
        application=report.summary.application,
        session_id=session_id,
        target_frame_ms=target_frame_ms,
        finding_count=len(report.findings),
        management_action_count=len(report.management_plan.actions),
        resource_event_count=len(resource_events),
        operation_event_count=len(operation_events),
        event_count=len(events),
        events=events,
    )


def write_presentmon_runtime_events(
    stream: PresentMonRuntimeEventStream,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".jsonl":
        path = path.with_suffix(".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in stream.events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")
    return path


def frame_budget_from_report(report: AnalysisReport) -> float:
    for metric_name in ("MsBetweenPresents", "DisplayedTime"):
        metric = report.summary.metrics.get(metric_name)
        value = metric_value(metric, "p50")
        if value is not None and value > 0:
            return value
    if report.summary.approx_fps and report.summary.approx_fps > 0:
        return 1000.0 / report.summary.approx_fps
    return DEFAULT_FRAME_BUDGET_MS


def action_to_events(
    index: int,
    action: ManagementAction,
    target_frame_ms: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    action_slug = slug(action.id)
    base_id = f"pm_{index:02d}_{action_slug}"
    cost_ms = action_cost_ms(action, target_frame_ms)
    size_mb = action_size_mb(action)
    common = {
        "management_action_id": action.id,
        "source_findings": action.source_findings,
        "confidence": action.confidence,
        "priority": action.priority,
    }

    if action.id == "ram-vram-residency-manager":
        ram_id = f"{base_id}_ram"
        vram_id = f"{base_id}_vram"
        return (
            [
                resource_event(ram_id, "texture", "ram", size_mb, action),
                resource_event(vram_id, "texture", "vram", size_mb, action),
            ],
            {
                "event": "operation",
                "id": f"{base_id}_upload",
                "operation_type": "upload",
                "source": ram_id,
                "target": vram_id,
                "queue": "copy",
                "reason": action.objective,
                "cost_ms": round(cost_ms, 4),
                "size_mb": round(size_mb, 4),
                **common,
            },
        )

    if action.id in {"zero-copy-presentation-route", "pacing-stability-controller"}:
        backbuffer_id = f"{base_id}_backbuffer"
        return (
            [resource_event(backbuffer_id, "framebuffer", "swapchain", 32.0, action)],
            {
                "event": "operation",
                "id": f"{base_id}_present",
                "operation_type": "present",
                "target": backbuffer_id,
                "queue": "present",
                "reason": action.objective,
                "cost_ms": round(cost_ms, 4),
                "size_mb": 0.0,
                **common,
            },
        )

    if action.id == "gpu-work-prefetch-budget":
        command_id = f"{base_id}_commands"
        return (
            [resource_event(command_id, "command", "vram", size_mb, action)],
            {
                "event": "operation",
                "id": f"{base_id}_prepare",
                "operation_type": "draw",
                "source": command_id,
                "target": command_id,
                "queue": "graphics",
                "reason": action.objective,
                "cost_ms": round(cost_ms, 4),
                "size_mb": 0.0,
                **common,
            },
        )

    signal_id = f"{base_id}_signal"
    queue = "present" if action.id == "adaptive-frame-queue-depth" else "graphics"
    operation_type = "sync"
    return (
        [resource_event(signal_id, "buffer", "shared", size_mb, action)],
        {
            "event": "operation",
            "id": f"{base_id}_{operation_type}",
            "operation_type": operation_type,
            "source": signal_id,
            "target": signal_id,
            "queue": queue,
            "reason": action.objective,
            "cost_ms": round(cost_ms, 4),
            "size_mb": 0.0,
            **common,
        },
    )


def resource_event(
    resource_id: str,
    kind: str,
    memory: str,
    size_mb: float,
    action: ManagementAction,
) -> dict[str, Any]:
    return {
        "event": "resource",
        "id": resource_id,
        "kind": kind,
        "memory": memory,
        "size_mb": round(size_mb, 4),
        "lifetime": "frame",
        "aliases": [action.id, *action.source_findings],
        "management_action_id": action.id,
    }


def runtime_budgets(
    target_frame_ms: float,
    actions: list[ManagementAction],
) -> dict[str, float]:
    has_residency = any(action.id == "ram-vram-residency-manager" for action in actions)
    has_presentation = any(
        action.id in {"zero-copy-presentation-route", "pacing-stability-controller"}
        for action in actions
    )
    return {
        "frame_ms": round(target_frame_ms, 4),
        "ram_mb": 48.0 if has_residency else 128.0,
        "vram_mb": 48.0 if has_residency else 128.0,
        "shared_mb": 64.0,
        "swapchain_mb": 24.0 if has_presentation else 64.0,
    }


def action_cost_ms(action: ManagementAction, target_frame_ms: float) -> float:
    labels_by_action = {
        "adaptive-frame-queue-depth": ("MsInPresentAPI p95",),
        "early-handoff-scheduler": ("MsCPUWait p95", "MsGPUWait p95"),
        "gpu-work-prefetch-budget": ("MsGPUWait p95", "MsGPUTime p95"),
        "pacing-stability-controller": (
            "MsBetweenPresents p99",
            "MsBetweenPresents stdev",
        ),
        "ram-vram-residency-manager": ("MsGPUWait p95", "MsBetweenPresents p99"),
        "zero-copy-presentation-route": ("DisplayLatency p95",),
    }
    candidates = [
        evidence_ms(action, label)
        for label in labels_by_action.get(action.id, ())
    ]
    numeric = [value for value in candidates if value is not None]
    if numeric:
        return max(0.25, max(numeric))
    priority_cost = max(0.25, action.priority / 10.0)
    return min(priority_cost, max(target_frame_ms, DEFAULT_FRAME_BUDGET_MS))


def action_size_mb(action: ManagementAction) -> float:
    if action.id == "ram-vram-residency-manager":
        return max(64.0, min(256.0, action.priority * 1.5))
    if action.id == "gpu-work-prefetch-budget":
        return max(16.0, min(96.0, action.priority))
    return max(8.0, min(48.0, action.priority / 2.0))


def evidence_ms(action: ManagementAction, label: str) -> float | None:
    for item in action.evidence:
        if item.label != label:
            continue
        match = re.search(r"-?\d+(?:[.,]\d+)?", item.value)
        if not match:
            return None
        return float(match.group(0).replace(",", "."))
    return None


def metric_value(metric: MetricSummary | None, field: str) -> float | None:
    if metric is None:
        return None
    value = getattr(metric, field)
    return float(value) if value is not None else None


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return text.strip("-") or "unknown"
