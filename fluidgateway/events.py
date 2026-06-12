from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .control import ControllerResult, FluidGatewayController


@dataclass(frozen=True)
class EventReplayResult:
    mode: str
    events_processed: int
    resource_events: int
    operation_events: int
    results: list[dict[str, Any]]
    snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "events_processed": self.events_processed,
            "resource_events": self.resource_events,
            "operation_events": self.operation_events,
            "results": self.results,
            "snapshot": self.snapshot,
        }


def replay_event_stream(path: str | Path) -> EventReplayResult:
    controller = FluidGatewayController()
    results: list[dict[str, Any]] = []
    resource_events = 0
    operation_events = 0
    events_processed = 0

    for index, payload in iter_jsonl(path):
        events_processed += 1
        event_type = str(payload.get("event") or payload.get("type") or "").strip().lower()
        if event_type == "resource":
            register_resource_event(controller, payload)
            resource_events += 1
        elif event_type == "operation":
            result = submit_operation_event(controller, payload)
            operation_events += 1
            results.append({"event_index": index, **result.to_dict()})
        else:
            raise ValueError(f"Unsupported event type on line {index}: {event_type or 'missing'}")

    return EventReplayResult(
        mode="runtime-event-stream-v0.6",
        events_processed=events_processed,
        resource_events=resource_events,
        operation_events=operation_events,
        results=results,
        snapshot=controller.snapshot(),
    )


def write_event_replay(result: EventReplayResult, output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def iter_jsonl(path: str | Path):
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {index}: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL event on line {index} must be an object.")
            yield index, payload


def register_resource_event(controller: FluidGatewayController, payload: dict[str, Any]) -> None:
    resource_id = payload.get("id") or payload.get("resource_id")
    if not resource_id:
        raise ValueError("Resource event requires 'id' or 'resource_id'.")
    controller.register_resource(
        resource_id=str(resource_id),
        kind=str(payload.get("kind") or "unknown"),
        memory=str(payload.get("memory") or "ram"),
        size_mb=float(payload.get("size_mb") or 0),
        lifetime=str(payload.get("lifetime") or "unknown"),
        aliases=as_string_list(payload.get("aliases") or []),
    )


def submit_operation_event(
    controller: FluidGatewayController, payload: dict[str, Any]
) -> ControllerResult:
    operation_id = payload.get("id") or payload.get("operation_id")
    if not operation_id:
        raise ValueError("Operation event requires 'id' or 'operation_id'.")
    operation_type = payload.get("operation_type") or payload.get("op") or payload.get("kind")
    if not operation_type:
        raise ValueError(f"Operation event {operation_id} requires an operation type.")
    frame = payload.get("frame")
    return controller.submit_operation(
        operation_id=str(operation_id),
        operation_type=str(operation_type),
        source=optional_text(payload.get("source")),
        target=optional_text(payload.get("target")),
        queue=str(payload.get("queue") or "unknown"),
        reason=str(payload.get("reason") or ""),
        cost_ms=float(payload.get("cost_ms") or 0),
        size_mb=float(payload.get("size_mb") or 0),
        frame=int(frame) if frame is not None else None,
        depends_on=as_string_list(payload.get("depends_on") or []),
    )


def as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Expected a list value.")
    return [str(item) for item in value]


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
