from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyzer import analyze_trace
from .models import AnalysisReport, TraceData, TraceRecord


REGISTRY_VERSION = 1
DEFAULT_REGISTRY = Path(".fluidgateway") / "traces.json"


@dataclass(frozen=True)
class TrackResult:
    record: TraceRecord
    registry_path: Path
    duplicate: bool


def track_trace(
    trace: TraceData,
    registry_path: str | Path | None = None,
    label: str | None = None,
    tags: list[str] | None = None,
    notes: str = "",
) -> TrackResult:
    output_path = Path(registry_path) if registry_path else DEFAULT_REGISTRY
    report = analyze_trace(trace)
    digest = file_sha256(trace.source)
    registry = load_registry(output_path)
    duplicate = any(record.get("sha256") == digest for record in registry["records"])
    record = build_record(
        trace=trace,
        report=report,
        digest=digest,
        label=label,
        tags=tags or [],
        notes=notes,
    )
    registry["records"].append(record.to_dict())
    save_registry(output_path, registry)
    return TrackResult(record=record, registry_path=output_path, duplicate=duplicate)


def load_registry(registry_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(registry_path) if registry_path else DEFAULT_REGISTRY
    if not path.exists():
        return {"version": REGISTRY_VERSION, "records": []}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a valid FluidGateway trace registry.")
    payload.setdefault("version", REGISTRY_VERSION)
    payload.setdefault("records", [])
    if not isinstance(payload["records"], list):
        raise ValueError(f"{path} has an invalid records field.")
    return payload


def save_registry(registry_path: str | Path, registry: dict[str, Any]) -> None:
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2, ensure_ascii=False)


def summarize_registry(registry_path: str | Path | None = None) -> list[dict[str, Any]]:
    registry = load_registry(registry_path)
    rows = []
    for record in registry["records"]:
        summary = record.get("summary", {})
        rows.append(
            {
                "id": record.get("id", ""),
                "added_at": record.get("added_at", ""),
                "label": record.get("label", ""),
                "application": summary.get("application", "Unknown"),
                "frames": summary.get("frame_count", 0),
                "fps": summary.get("approx_fps"),
                "max_finding_score": record.get("max_finding_score", 0),
                "max_management_priority": record.get("max_management_priority", 0),
                "findings": len(record.get("finding_ids", [])),
                "actions": len(record.get("management_action_ids", [])),
                "tags": record.get("tags", []),
            }
        )
    return rows


def build_record(
    trace: TraceData,
    report: AnalysisReport,
    digest: str,
    label: str | None,
    tags: list[str],
    notes: str,
) -> TraceRecord:
    finding_scores = [finding.score for finding in report.findings]
    action_priorities = [action.priority for action in report.management_plan.actions]
    record_id = digest[:12]
    return TraceRecord(
        id=record_id,
        added_at=datetime.now(timezone.utc).isoformat(),
        label=label or report.summary.application or Path(trace.source).stem,
        source=str(trace.source),
        sha256=digest,
        summary=report.summary,
        finding_ids=[finding.id for finding in report.findings],
        management_action_ids=[
            action.id for action in report.management_plan.actions
        ],
        max_finding_score=max(finding_scores) if finding_scores else 0,
        max_management_priority=max(action_priorities) if action_priorities else 0,
        tags=sorted(set(tags)),
        notes=notes,
    )


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
