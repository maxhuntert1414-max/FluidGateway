from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Iterable

from .admission import build_admission_plan
from .efficiency import build_efficiency_ledger
from .events import iter_jsonl
from .feedback import build_feedback_plan


CLIENT_MODE = "runtime-event-client-v0.20"


class RuntimeEventClient:
    """Client for the local FluidGateway TCP JSONL runtime endpoint."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._reader = None

    def __enter__(self) -> RuntimeEventClient:
        return self.connect()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def connect(self) -> RuntimeEventClient:
        if self._socket is None:
            self._socket = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
            self._reader = self._socket.makefile("r", encoding="utf-8")
        return self

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def send_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Runtime event payload must be a dict.")
        self.connect()
        assert self._socket is not None
        assert self._reader is not None
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._socket.sendall(line.encode("utf-8"))
        response_line = self._reader.readline()
        if not response_line:
            raise ConnectionError("Runtime event server closed without a response.")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise ValueError("Runtime event server returned invalid JSON.") from exc
        if not isinstance(response, dict):
            raise ValueError("Runtime event server response must be a JSON object.")
        return response

    def send_events(self, payloads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.send_event(payload) for payload in payloads]

    def send_jsonl(self, path: str | Path) -> list[dict[str, Any]]:
        return [self.send_event(payload) for _, payload in iter_jsonl(path)]

    def register_resource(
        self,
        resource_id: str,
        kind: str = "unknown",
        memory: str = "ram",
        size_mb: float = 0.0,
        lifetime: str = "unknown",
        aliases: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        return self.send_event(
            {
                "event": "resource",
                "id": resource_id,
                "kind": kind,
                "memory": memory,
                "size_mb": size_mb,
                "lifetime": lifetime,
                "aliases": list(aliases or []),
            }
        )

    def submit_operation(
        self,
        operation_id: str,
        operation_type: str,
        source: str | None = None,
        target: str | None = None,
        queue: str = "unknown",
        reason: str = "",
        cost_ms: float = 0.0,
        size_mb: float = 0.0,
        frame: int | None = None,
        depends_on: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "operation",
            "id": operation_id,
            "operation_type": operation_type,
            "queue": queue,
            "reason": reason,
            "cost_ms": cost_ms,
            "size_mb": size_mb,
            "depends_on": list(depends_on or []),
        }
        if source is not None:
            payload["source"] = source
        if target is not None:
            payload["target"] = target
        if frame is not None:
            payload["frame"] = frame
        return self.send_event(payload)


def summarize_client_responses(
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    operation_responses = [
        response for response in responses if response.get("event") == "operation"
    ]
    resource_responses = [
        response for response in responses if response.get("event") == "resource"
    ]
    session_responses = [
        response for response in responses if response.get("event") == "session"
    ]
    frame_responses = [
        response for response in responses if response.get("event") == "frame"
    ]
    state_responses = [
        response for response in responses if response.get("event") == "state"
    ]
    decisions = [
        response
        for response in operation_responses
        if response.get("result", {}).get("decision") is not None
    ]
    policy_action_count = sum(
        len(response.get("policy_actions") or []) for response in responses
    )
    lifetime_plan_action_count = sum(
        (response.get("lifetime_plan") or {}).get("plan_action_count", 0)
        for response in responses
    )
    schedule_step_count = sum(
        (response.get("schedule_plan") or {}).get("scheduled_step_count", 0)
        for response in responses
    )
    enforcement_command_count = sum(
        (response.get("enforcement_plan") or {}).get("command_count", 0)
        for response in responses
    )
    live_command_count = sum(1 for response in responses if response.get("live_command"))
    state_snapshot_count = sum(
        1 for response in responses if response.get("state_snapshot")
    )
    policy_loop_directive_count = sum(
        len(response.get("policy_loop_directives") or [])
        for response in responses
    )
    execution_gate_count = sum(
        1 for response in responses if response.get("execution_gate")
    )
    admission_decision_count = sum(
        1 for response in responses if response.get("admission_decision")
    )
    efficiency_impact_count = sum(
        1 for response in responses if response.get("efficiency_impact")
    )
    operation_results = [
        response.get("result")
        for response in operation_responses
        if isinstance(response.get("result"), dict)
    ]
    admission_plan = build_admission_plan(operation_results)
    efficiency_ledger = build_efficiency_ledger(admission_plan)
    frame_targets = frame_targets_from_responses(frame_responses)
    failed = [response for response in responses if not response.get("ok")]
    return {
        "mode": CLIENT_MODE,
        "events_sent": len(responses),
        "session_responses": len(session_responses),
        "frame_responses": len(frame_responses),
        "resource_responses": len(resource_responses),
        "operation_responses": len(operation_responses),
        "state_response_count": len(state_responses),
        "decision_count": len(decisions),
        "policy_action_count": policy_action_count,
        "lifetime_plan_action_count": lifetime_plan_action_count,
        "schedule_step_count": schedule_step_count,
        "enforcement_command_count": enforcement_command_count,
        "live_command_count": live_command_count,
        "state_snapshot_count": state_snapshot_count,
        "policy_loop_directive_count": policy_loop_directive_count,
        "execution_gate_count": execution_gate_count,
        "admission_decision_count": admission_decision_count,
        "admission_plan": admission_plan.to_dict(),
        "efficiency_impact_count": efficiency_impact_count,
        "efficiency_ledger": efficiency_ledger.to_dict(),
        "feedback_plan": build_feedback_plan(efficiency_ledger, frame_targets).to_dict(),
        "failed_responses": len(failed),
        "responses": responses,
    }


def frame_targets_from_responses(responses: list[dict[str, Any]]) -> dict[int, float]:
    targets: dict[int, float] = {}
    for response in responses:
        frame = response.get("frame")
        state = response.get("frame_state") or {}
        target = state.get("target_frame_ms")
        if frame is None or target is None:
            continue
        targets[int(frame)] = float(target)
    return targets


def write_client_responses(
    responses: list[dict[str, Any]], output_path: str | Path
) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            summarize_client_responses(responses), indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return path
