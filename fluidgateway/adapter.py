from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .control import FluidGatewayController
from .events import iter_jsonl, register_resource_event, submit_operation_event
from .lifetime import ResourceLifetimePlan, ResourceLifetimePlanner
from .policy import DEFAULT_FRAME_BUDGET_MS, RuntimePolicyAction, RuntimePolicyEngine
from .scheduler import SchedulerPlan, simulate_scheduler


ADAPTER_MODE = "runtime-adapter-session-v0.12"


@dataclass
class AdapterFrameStats:
    frame: int
    target_frame_ms: float = DEFAULT_FRAME_BUDGET_MS
    begin_event_index: int | None = None
    end_event_index: int | None = None
    operation_count: int = 0
    decision_count: int = 0
    policy_action_count: int = 0
    policy_action_ids: list[str] | None = None
    estimated_total_cost_ms: float = 0.0
    estimated_saved_ms: float = 0.0
    estimated_saved_mb: float = 0.0
    transfer_mb: float = 0.0
    queue_costs: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "target_frame_ms": round(self.target_frame_ms, 4),
            "begin_event_index": self.begin_event_index,
            "end_event_index": self.end_event_index,
            "operation_count": self.operation_count,
            "decision_count": self.decision_count,
            "policy_action_count": self.policy_action_count,
            "policy_action_ids": self.policy_action_ids or [],
            "estimated_total_cost_ms": round(self.estimated_total_cost_ms, 4),
            "estimated_saved_ms": round(self.estimated_saved_ms, 4),
            "estimated_saved_mb": round(self.estimated_saved_mb, 4),
            "transfer_mb": round(self.transfer_mb, 4),
            "queue_costs": {
                queue: round(cost, 4)
                for queue, cost in sorted((self.queue_costs or {}).items())
            },
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
    policy_actions: list[RuntimePolicyAction]
    lifetime_plan: ResourceLifetimePlan
    schedule_plan: SchedulerPlan
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
            "policy_action_count": len(self.policy_actions),
            "policy_actions": [action.to_dict() for action in self.policy_actions],
            "lifetime_plan": self.lifetime_plan.to_dict(),
            "schedule_plan": self.schedule_plan.to_dict(),
            "results": self.results,
            "snapshot": self.snapshot,
        }


class RuntimeAdapterSession:
    """Lifecycle-aware runtime session for engine and adapter prototypes."""

    def __init__(self, session_id: str = "default") -> None:
        self.session_id = session_id
        self.controller = FluidGatewayController()
        self.policy_engine = RuntimePolicyEngine()
        self.lifetime_planner = ResourceLifetimePlanner()
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
        lifetime_plan = self.lifetime_planner.finalize()
        schedule_plan = self._build_schedule_plan(lifetime_plan)
        return AdapterSessionResult(
            mode=ADAPTER_MODE,
            session_id=self.session_id,
            events_processed=self.events_processed,
            lifecycle_events=self.lifecycle_events,
            resource_events=self.resource_events,
            operation_events=self.operation_events,
            released_resources=list(self.released_resources),
            frames=[self.frames[key] for key in sorted(self.frames)],
            policy_actions=list(self.policy_engine.actions),
            lifetime_plan=lifetime_plan,
            schedule_plan=schedule_plan,
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
            self.policy_engine.configure(payload)
            self.closed = False
        else:
            if self.current_frame is not None:
                raise ValueError(
                    f"Cannot end session while frame {self.current_frame} is open."
                )
            self.closed = True
        lifetime_plan = self.lifetime_planner.finalize() if self.closed else None
        schedule_plan = self._build_schedule_plan(lifetime_plan) if lifetime_plan else None
        response = {
            "ok": True,
            "event": "session",
            "action": action,
            "session_id": self.session_id,
            "closed": self.closed,
            "policy_actions": [],
            "lifetime_plan": lifetime_plan.to_dict() if lifetime_plan else None,
            "schedule_plan": schedule_plan.to_dict() if schedule_plan else None,
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
            stats.target_frame_ms = self.policy_engine.frame_budget_from(payload)
        else:
            if self.current_frame != frame:
                raise ValueError(
                    f"Cannot end frame {frame}; current open frame is {self.current_frame}."
                )
            policy_actions = self.policy_engine.finish_frame(
                frame=frame,
                target_frame_ms=stats.target_frame_ms,
                estimated_total_cost_ms=stats.estimated_total_cost_ms,
                queue_costs=stats.queue_costs or {},
            )
            self._record_policy_actions(policy_actions, frame)
            stats.end_event_index = event_index
            self.current_frame = None
        if action == "begin":
            policy_actions = []
        response = {
            "ok": True,
            "event": "frame",
            "action": action,
            "frame": frame,
            "frame_state": stats.to_dict(),
            "policy_actions": [item.to_dict() for item in policy_actions],
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
            released_resource = self.controller.resources.pop(resource_id, None)
            released = released_resource is not None
            if released:
                self.released_resources.append(resource_id)
                self.policy_engine.release_resource(resource_id)
                self.lifetime_planner.release_resource(
                    released_resource, resource_id
                )
            response = {
                "ok": True,
                "event": "resource",
                "action": "release",
                "resource_id": resource_id,
                "released": released,
                "policy_actions": [],
            }
            return with_event_index(response, event_index)

        resource = register_resource_event(self.controller, payload)
        self.lifetime_planner.register_resource(resource, self.current_frame)
        policy_actions = self.policy_engine.register_resource(
            resource, self.current_frame
        )
        self._record_policy_actions(policy_actions, self.current_frame)
        response = {
            "ok": True,
            "event": "resource",
            "action": "register",
            "resource": resource.to_dict(),
            "policy_actions": [item.to_dict() for item in policy_actions],
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
            if result.executed:
                stats.estimated_total_cost_ms += result.operation.cost_ms
                if stats.queue_costs is None:
                    stats.queue_costs = {}
                stats.queue_costs[result.operation.queue] = (
                    stats.queue_costs.get(result.operation.queue, 0.0)
                    + result.operation.cost_ms
                )
                if result.operation.type in {"copy", "upload"}:
                    stats.transfer_mb += result.operation.size_mb
            if result.decision is not None:
                stats.decision_count += 1
                stats.estimated_saved_ms += result.decision.estimated_saved_ms
                stats.estimated_saved_mb += result.decision.estimated_saved_mb
        self.lifetime_planner.record_operation(result.operation, result.executed)
        policy_actions = self.policy_engine.record_operation(
            result,
            operation_frame,
            self._frame_stats(operation_frame).target_frame_ms
            if operation_frame is not None
            else self.policy_engine.target_frame_ms,
        )
        self._record_policy_actions(policy_actions, operation_frame)
        response = {
            "ok": True,
            "event": "operation",
            "result": result_payload,
            "policy_actions": [item.to_dict() for item in policy_actions],
        }
        return with_event_index(response, event_index)

    def _frame_stats(self, frame: int) -> AdapterFrameStats:
        if frame not in self.frames:
            self.frames[frame] = AdapterFrameStats(frame=frame)
        return self.frames[frame]

    def _record_policy_actions(
        self, actions: list[RuntimePolicyAction], frame: int | None
    ) -> None:
        if frame is None:
            return
        stats = self._frame_stats(frame)
        action_ids = list(stats.policy_action_ids or [])
        for action in actions:
            stats.policy_action_count += 1
            action_ids.append(action.id)
        stats.policy_action_ids = action_ids

    def _build_schedule_plan(self, lifetime_plan: ResourceLifetimePlan) -> SchedulerPlan:
        return simulate_scheduler(
            operations=list(self.controller.executed_operations),
            frame_targets_ms={
                frame.frame: frame.target_frame_ms for frame in self.frames.values()
            },
            frame_costs_ms={
                frame.frame: frame.estimated_total_cost_ms
                for frame in self.frames.values()
            },
            lifetime_plan=lifetime_plan,
        )


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
