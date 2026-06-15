from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .adapter import replay_adapter_event_stream
from .daemon_actions import (
    RuntimeDaemonActionQueue,
    build_runtime_daemon_action_queue,
)
from .daemon_decision import (
    RuntimeDaemonDecisionPlan,
    build_runtime_daemon_decision_plan,
)
from .daemon_execution import (
    RuntimeDaemonActionExecution,
    dry_run_runtime_daemon_action_queue,
)
from .host import HostCapabilitySnapshot
from .native_backend import (
    RuntimeNativeBackendPreflight,
    build_runtime_native_backend_preflight,
)
from .state_accumulator import RuntimeStateAccumulator


DAEMON_MODE = "runtime-daemon-dry-run-v0.51"
DAEMON_EXECUTION_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeDaemonCycle:
    cycle_index: int
    events_path: str
    session_id: str
    events_processed: int
    lifecycle_events: int
    resource_events: int
    operation_events: int
    previous_cycle_count: int | None
    previous_state_digest: str | None
    current_cycle_count: int
    transition_trend: str
    supervisor_action: str
    plan_action: str
    execution_action: str
    would_apply_count: int
    would_block_count: int
    state_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_index": self.cycle_index,
            "events_path": self.events_path,
            "session_id": self.session_id,
            "events_processed": self.events_processed,
            "lifecycle_events": self.lifecycle_events,
            "resource_events": self.resource_events,
            "operation_events": self.operation_events,
            "previous_cycle_count": self.previous_cycle_count,
            "previous_state_digest": self.previous_state_digest,
            "current_cycle_count": self.current_cycle_count,
            "transition_trend": self.transition_trend,
            "supervisor_action": self.supervisor_action,
            "plan_action": self.plan_action,
            "execution_action": self.execution_action,
            "would_apply_count": self.would_apply_count,
            "would_block_count": self.would_block_count,
            "state_digest": self.state_digest,
        }


@dataclass(frozen=True)
class RuntimeDaemonReport:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    configured_iterations: int
    cycle_count: int
    events_stream_count: int
    events_processed: int
    lifecycle_events: int
    resource_events: int
    operation_events: int
    initial_state_loaded: bool
    initial_state_digest: str | None
    host_snapshot_loaded: bool
    host_profile: str | None
    host_manager_hint: str | None
    final_cycle_count: int
    final_state_digest: str
    total_would_apply_count: int
    total_would_block_count: int
    final_execution_action: str
    final_supervisor_action: str
    final_plan_action: str
    daemon_decision_action: str
    daemon_decision_risk_level: str
    daemon_action_queue_policy: str
    daemon_action_blocked_count: int
    daemon_action_execution_policy: str
    daemon_action_execution_blocked_count: int
    native_backend_policy: str
    native_backend_blocked_count: int
    native_promotion_allowed: bool
    cycles: list[RuntimeDaemonCycle]
    final_state: RuntimeStateAccumulator
    host_snapshot: HostCapabilitySnapshot | None
    daemon_decision_plan: RuntimeDaemonDecisionPlan
    daemon_action_queue: RuntimeDaemonActionQueue
    daemon_action_execution: RuntimeDaemonActionExecution
    native_backend_preflight: RuntimeNativeBackendPreflight

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "configured_iterations": self.configured_iterations,
            "cycle_count": self.cycle_count,
            "events_stream_count": self.events_stream_count,
            "events_processed": self.events_processed,
            "lifecycle_events": self.lifecycle_events,
            "resource_events": self.resource_events,
            "operation_events": self.operation_events,
            "initial_state_loaded": self.initial_state_loaded,
            "initial_state_digest": self.initial_state_digest,
            "host_snapshot_loaded": self.host_snapshot_loaded,
            "host_profile": self.host_profile,
            "host_manager_hint": self.host_manager_hint,
            "final_cycle_count": self.final_cycle_count,
            "final_state_digest": self.final_state_digest,
            "total_would_apply_count": self.total_would_apply_count,
            "total_would_block_count": self.total_would_block_count,
            "final_execution_action": self.final_execution_action,
            "final_supervisor_action": self.final_supervisor_action,
            "final_plan_action": self.final_plan_action,
            "daemon_decision_action": self.daemon_decision_action,
            "daemon_decision_risk_level": self.daemon_decision_risk_level,
            "daemon_action_queue_policy": self.daemon_action_queue_policy,
            "daemon_action_blocked_count": self.daemon_action_blocked_count,
            "daemon_action_execution_policy": (
                self.daemon_action_execution_policy
            ),
            "daemon_action_execution_blocked_count": (
                self.daemon_action_execution_blocked_count
            ),
            "native_backend_policy": self.native_backend_policy,
            "native_backend_blocked_count": self.native_backend_blocked_count,
            "native_promotion_allowed": self.native_promotion_allowed,
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "final_state": self.final_state.to_dict(),
            "host_snapshot": self.host_snapshot.to_dict()
            if self.host_snapshot is not None
            else None,
            "daemon_decision_plan": self.daemon_decision_plan.to_dict(),
            "daemon_action_queue": self.daemon_action_queue.to_dict(),
            "daemon_action_execution": self.daemon_action_execution.to_dict(),
            "native_backend_preflight": (
                self.native_backend_preflight.to_dict()
            ),
        }


def run_runtime_daemon(
    events_paths: Sequence[str | Path],
    iterations: int = 1,
    initial_state: RuntimeStateAccumulator | None = None,
    host_snapshot: HostCapabilitySnapshot | None = None,
) -> RuntimeDaemonReport:
    paths = [Path(path) for path in events_paths]
    if not paths:
        raise ValueError("Runtime daemon requires at least one events path.")
    if iterations < 1:
        raise ValueError("Runtime daemon iterations must be at least 1.")

    loop_count = max(iterations, len(paths))
    previous_state = initial_state
    cycles: list[RuntimeDaemonCycle] = []
    last_result = None

    for index in range(loop_count):
        path = paths[min(index, len(paths) - 1)]
        previous_cycle_count = (
            previous_state.cycle_count if previous_state is not None else None
        )
        previous_state_digest = (
            previous_state.state_digest if previous_state is not None else None
        )
        result = replay_adapter_event_stream(path, previous_state=previous_state)
        current_state = result.runtime_state_accumulator
        cycles.append(
            RuntimeDaemonCycle(
                cycle_index=index + 1,
                events_path=str(path),
                session_id=result.session_id,
                events_processed=result.events_processed,
                lifecycle_events=result.lifecycle_events,
                resource_events=result.resource_events,
                operation_events=result.operation_events,
                previous_cycle_count=previous_cycle_count,
                previous_state_digest=previous_state_digest,
                current_cycle_count=current_state.cycle_count,
                transition_trend=result.runtime_state_transition.trend,
                supervisor_action=(
                    result.runtime_supervisor_directive.directive_action
                ),
                plan_action=result.runtime_supervisor_plan.plan_action,
                execution_action=(
                    result.runtime_supervisor_execution.execution_action
                ),
                would_apply_count=result.runtime_supervisor_execution.would_apply_count,
                would_block_count=result.runtime_supervisor_execution.would_block_count,
                state_digest=current_state.state_digest,
            )
        )
        previous_state = current_state
        last_result = result

    if last_result is None or previous_state is None:
        raise ValueError("Runtime daemon did not execute any cycles.")

    final_execution_action = (
        last_result.runtime_supervisor_execution.execution_action
    )
    final_supervisor_action = (
        last_result.runtime_supervisor_directive.directive_action
    )
    total_would_block_count = sum(cycle.would_block_count for cycle in cycles)
    decision_plan = build_runtime_daemon_decision_plan(
        final_state=previous_state,
        host_snapshot=host_snapshot,
        final_execution_action=final_execution_action,
        final_supervisor_action=final_supervisor_action,
        total_would_block_count=total_would_block_count,
    )
    action_queue = build_runtime_daemon_action_queue(decision_plan)
    action_execution = dry_run_runtime_daemon_action_queue(action_queue)
    native_backend_preflight = build_runtime_native_backend_preflight(
        action_queue,
        action_execution,
    )

    return RuntimeDaemonReport(
        mode=DAEMON_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=DAEMON_EXECUTION_GUARD,
        configured_iterations=iterations,
        cycle_count=len(cycles),
        events_stream_count=len(paths),
        events_processed=sum(cycle.events_processed for cycle in cycles),
        lifecycle_events=sum(cycle.lifecycle_events for cycle in cycles),
        resource_events=sum(cycle.resource_events for cycle in cycles),
        operation_events=sum(cycle.operation_events for cycle in cycles),
        initial_state_loaded=initial_state is not None,
        initial_state_digest=initial_state.state_digest
        if initial_state is not None
        else None,
        host_snapshot_loaded=host_snapshot is not None,
        host_profile=host_snapshot.host_profile if host_snapshot is not None else None,
        host_manager_hint=host_snapshot.manager_hint
        if host_snapshot is not None
        else None,
        final_cycle_count=previous_state.cycle_count,
        final_state_digest=previous_state.state_digest,
        total_would_apply_count=sum(cycle.would_apply_count for cycle in cycles),
        total_would_block_count=total_would_block_count,
        final_execution_action=final_execution_action,
        final_supervisor_action=final_supervisor_action,
        final_plan_action=last_result.runtime_supervisor_plan.plan_action,
        daemon_decision_action=decision_plan.decision_action,
        daemon_decision_risk_level=decision_plan.risk_level,
        daemon_action_queue_policy=action_queue.queue_policy,
        daemon_action_blocked_count=action_queue.blocked_action_count,
        daemon_action_execution_policy=action_execution.execution_policy,
        daemon_action_execution_blocked_count=action_execution.blocked_count,
        native_backend_policy=native_backend_preflight.backend_policy,
        native_backend_blocked_count=(
            native_backend_preflight.blocked_requirement_count
        ),
        native_promotion_allowed=(
            native_backend_preflight.native_promotion_allowed
        ),
        cycles=cycles,
        final_state=previous_state,
        host_snapshot=host_snapshot,
        daemon_decision_plan=decision_plan,
        daemon_action_queue=action_queue,
        daemon_action_execution=action_execution,
        native_backend_preflight=native_backend_preflight,
    )


def write_runtime_daemon_report(
    report: RuntimeDaemonReport,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
