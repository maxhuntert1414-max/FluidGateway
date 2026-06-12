from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .control import FluidGatewayController
from .events import iter_jsonl, register_resource_event, submit_operation_event


ADAPTER_MODE = "runtime-adapter-session-v0.9"


@dataclass
class AdapterFrameStats:
    frame: int
    begin_event_index: int | None = None
    end_event_index: int | None = None
    operation_count: int = 0
    decision_count: int = 0
    estimated_saved_ms: float = 0.0
    estimated_saved_mb: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "begin_event_index": self.begin_event_index,
            "end_event_index": self.end_event_index,
            "operation_count": self.operation_count,
            "decision_count": self.decision_count,
            "estimated_saved_ms": round(self.estimated_saved_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
        }


@dataclass(frozen=True)
class AdapterSessionResult:
    mode: str
    session_id: str
    events_processed: int
    lifecycle_events: int
    resource_events: int
    operation_events: int
    released_resources: list[str]
    frames: list[AdapterFrameStats]
    results: list[dict[str, Any]]
    snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "session_id": self.session_id,
            "events_processed": self.events_processed,
            "lifecycle_events": self.lifecycle_events,
            "resource_events": self.resource_events,
            "operation_events": self.operation_events,
            "released_resources": self.released_resources,
            "frames": [frame.to_dict() for frame in self.frames],
            "results": self.results,
            "snapshot": self.snapshot,
        }


class RuntimeAdapterSession:
    """Lifecycle-aware runtime session for engine and adapter prototypes."""

    def __init__(self, session_id: str = "default") -> None:
        self.session_id = session_id
        self.controller = FluidGatewayController()
        self.current_frame: int | None = None
        self.events_processed = 0
        self.lifecycle_events = 0
        self.resource_events = 0
        self.operation_events = 0
        self.released_resources: list[str] = []
        self.frames: dict[int, AdapterFrameStats] = {}
        self.results: list[dict[str, Any]] = []
        self.closed = False

    def process_event(
        self, payload: dict[str, Any], event_index: int | None = None
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Adapter event must be a JSON object.")
        self.events_processed += 1
        event_type = str(payload.get("event") or payload.get("type") or "").strip().lower()
        if event_type == "session":
            return self._process_session_event(payload, event_index)
        if event_type == "frame":
            return self._process_frame_event(payload, event_index)
        if event_type == "resource":
            return self._process_resource_event(payload, event_index)
        if event_type == "operation":
            return self._process_operation_event(payload, event_index)
        raise ValueError(f"Unsupported adapter event type: {event_type or 'missing'}")

    def to_result(self) -> AdapterSessionResult:
        return AdapterSessionResult(
            mode=ADAPTER_MODE,
            session_id=self.session_id,
            events_processed=self.events_processed,
            lifecycle_events=self.lifecycle_events,
            resource_events=self.resource_events,
            operation_events=self.operation_events,
            released_resources=list(self.released_resources),
            frames=[self.frames[key] for key in sorted(self.frames)],
            results=list(self.results),
            snapshot=self.controller.snapshot(),
        )

    def _process_session_event(
        self, payload: dict[str, Any], event_index: int | None
    ) -> dict[str, Any]:
        self.lifecycle_events += 1
        action = normalized_action(payload.get("action"), {"begin", "end"}, "begin")
        if action == "begin":
            self.session_id = str(
                payload.get("id") or payload.get("session_id") or self.session_id
            )
            self.closed = False
        else:
            if self.current_frame is not None:
                raise ValueError(
                    f"Cannot end session while frame {self.current_frame} is open."
                )
            self.closed = True
        response = {
            "ok": True,
            "event": "session",
            "action": action,
            "session_id": self.session_id,
            "closed": self.closed,
        }
        return with_event_index(response, event_index)

    def _process_frame_event(
        self, payload: dict[str, Any], event_index: int | None
    ) -> dict[str, Any]:
        self.lifecycle_events += 1
        frame = parse_frame(payload)
        action = normalized_action(payload.get("action"), {"begin", "end"}, "begin")
        stats = self._frame_stats(frame)
        if action == "begin":
            if self.current_frame is not None:
                raise ValueError(f"Frame {self.current_frame} is already open.")
            if stats.begin_event_index is not None and stats.end_event_index is None:
                raise ValueError(f"Frame {frame} is already open.")
            self.current_frame = frame
            stats.begin_event_index = event_index
        else:
            if self.current_frame != frame:
                raise ValueError(
                    f"Cannot end frame {frame}; current open frame is {self.current_frame}."
                )
            stats.end_event_index = event_index
            self.current_frame = None
        response = {
            "ok": True,
            "event": "frame",
            "action": action,
            "frame": frame,
            "frame_state": stats.to_dict(),
        }
        return with_event_index(response, event_index)

    def _process_resource_event(
        self, payload: dict[str, Any], event_index: int | None
    ) -> dict[str, Any]:
        self.resource_events += 1
        action = normalized_action(
            payload.get("action"), {"register", "release"}, "register"
        )
        if action == "release":
            resource_id = str(payload.get("id") or payload.get("resource_id") or "").strip()
            if not resource_id:
                raise ValueError("Resource release event requires 'id' or 'resource_id'.")
            released = self.controller.resources.pop(resource_id, None) is not None
            if released:
                self.released_resources.append(resource_id)
            response = {
                "ok": True,
                "event": "resource",
                "action": "release",
                "resource_id": resource_id,
                "released": released,
            }
            return with_event_index(response, event_index)

        resource = register_resource_event(self.controller, payload)
        response = {
            "ok": True,
            "event": "resource",
            "action": "register",
            "resource": resource.to_dict(),
        }
        return with_event_index(response, event_index)

    def _process_operation_event(
        self, payload: dict[str, Any], event_index: int | None
    ) -> dict[str, Any]:
        self.operation_events += 1
        operation_payload = dict(payload)
        if operation_payload.get("frame") is None and self.current_frame is not None:
            operation_payload["frame"] = self.current_frame
        result = submit_operation_event(self.controller, operation_payload)
        result_payload = result.to_dict()
        if event_index is not None:
            result_payload = {"event_index": event_index, **result_payload}
        self.results.append(result_payload)
        operation_frame = result.operation.frame
        if operation_frame is not None:
            stats = self._frame_stats(operation_frame)
            stats.operation_count += 1
            if result.decision is not None:
                stats.decision_count += 1
                stats.estimated_saved_ms += result.decision.estimated_saved_ms
                stats.estimated_saved_mb += result.decision.estimated_saved_mb
        response = {
            "ok": True,
            "event": "operation",
            "result": result_payload,
        }
        return with_event_index(response, event_index)

    def _frame_stats(self, frame: int) -> AdapterFrameStats:
        if frame not in self.frames:
            self.frames[frame] = AdapterFrameStats(frame=frame)
        return self.frames[frame]


def replay_adapter_event_stream(path: str | Path) -> AdapterSessionResult:
    session = RuntimeAdapterSession()
    for index, payload in iter_jsonl(path):
        session.process_event(payload, event_index=index)
    return session.to_result()


def write_adapter_session(result: AdapterSessionResult, output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def process_adapter_event_payload(
    session: RuntimeAdapterSession,
    payload: dict[str, Any],
    event_index: int | None = None,
) -> dict[str, Any]:
    return session.process_event(payload, event_index=event_index)


def normalized_action(value: Any, allowed: set[str], default: str) -> str:
    action = str(value or default).strip().lower()
    if action not in allowed:
        raise ValueError(f"Unsupported action: {action or 'missing'}.")
    return action


def parse_frame(payload: dict[str, Any]) -> int:
    value = payload.get("frame")
    if value is None:
        value = payload.get("frame_id")
    if value is None:
        raise ValueError("Frame event requires 'frame' or 'frame_id'.")
    return int(value)


def with_event_index(
    response: dict[str, Any], event_index: int | None
) -> dict[str, Any]:
    if event_index is not None:
        return {"event_index": event_index, **response}
    return response
