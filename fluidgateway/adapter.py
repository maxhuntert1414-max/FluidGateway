from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .actuation import ActuationPlan, build_actuation_plan
from .adaptive import AdaptiveExecutorLoop, build_adaptive_executor_loop
from .admission import AdmissionPlan, build_admission_decision, build_admission_plan
from .applier import DispatchExecutionReport, execute_dispatch_plan
from .arbiter import BudgetArbitrationPlan, build_budget_arbitration
from .budget import RuntimeBudgetEnvelope, build_runtime_budget_envelope
from .calibration import RuntimeCalibrationReport, build_runtime_calibration
from .control import FluidGatewayController
from .control_packet import RuntimeControlPacket, build_runtime_control_packet
from .control_state import RuntimeControlState, apply_runtime_control_packet
from .dispatch import RuntimeDispatchPlan, build_runtime_dispatch_plan
from .enforcement import EnforcementPlan, build_enforcement_plan
from .events import iter_jsonl, register_resource_event, submit_operation_event
from .executor import ExecutionSimulation, simulate_execution
from .efficiency import (
    EfficiencyLedger,
    build_efficiency_impact,
    build_efficiency_ledger,
)
from .feedback import FeedbackPlan, build_feedback_plan
from .gateway import RuntimeGatewayTick, build_runtime_gateway_tick
from .gateway_cycle import RuntimeGatewayCycleReport, execute_runtime_gateway_tick
from .gateway_feedback import (
    RuntimeGatewayFeedbackDelta,
    build_runtime_gateway_feedback,
)
from .gate import ExecutionGateDecision, build_execution_gate
from .governor import GovernorDirective, LivePolicyGovernor
from .lifetime import ResourceLifetimePlan, ResourceLifetimePlanner
from .live import LiveCommand, build_live_command
from .manager import RuntimeManagerDirective, build_runtime_manager_directive
from .packet import ExecutionPacket, build_execution_packet
from .policy import DEFAULT_FRAME_BUDGET_MS, RuntimePolicyAction, RuntimePolicyEngine
from .policy_update import RuntimePolicyUpdate, build_runtime_policy_update
from .routing import MemoryRoutePlan, build_memory_route_plan
from .scheduler import SchedulerPlan, simulate_scheduler
from .state import LiveStateSnapshot, build_live_state_snapshot
from .state_accumulator import (
    RuntimeStateAccumulator,
    build_runtime_state_accumulator,
)
from .state_transition import (
    RuntimeStateTransition,
    build_runtime_state_transition,
)
from .supervisor import (
    RuntimeSupervisorDirective,
    build_runtime_supervisor_directive,
)
from .supervisor_plan import RuntimeSupervisorPlan, build_runtime_supervisor_plan
from .transit import MemoryTransitMap, build_memory_transit_map
from .windowing import FrameWindowPlan, build_frame_window_plan


ADAPTER_MODE = "runtime-adapter-session-v0.44"


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
    enforcement_plan: EnforcementPlan
    live_commands: list[LiveCommand]
    state_snapshot: LiveStateSnapshot
    policy_loop_directives: list[GovernorDirective]
    execution_gates: list[ExecutionGateDecision]
    admission_plan: AdmissionPlan
    efficiency_ledger: EfficiencyLedger
    feedback_plan: FeedbackPlan
    actuation_plan: ActuationPlan
    memory_transit_map: MemoryTransitMap
    memory_route_plan: MemoryRoutePlan
    frame_window_plan: FrameWindowPlan
    execution_packet: ExecutionPacket
    execution_simulation: ExecutionSimulation
    adaptive_executor_loop: AdaptiveExecutorLoop
    budget_envelope: RuntimeBudgetEnvelope
    budget_arbitration: BudgetArbitrationPlan
    dispatch_plan: RuntimeDispatchPlan
    dispatch_execution: DispatchExecutionReport
    runtime_calibration: RuntimeCalibrationReport
    runtime_manager: RuntimeManagerDirective
    runtime_control_packet: RuntimeControlPacket
    runtime_control_state: RuntimeControlState
    runtime_gateway_tick: RuntimeGatewayTick
    runtime_gateway_cycle: RuntimeGatewayCycleReport
    runtime_gateway_feedback: RuntimeGatewayFeedbackDelta
    runtime_policy_update: RuntimePolicyUpdate
    runtime_state_accumulator: RuntimeStateAccumulator
    runtime_state_transition: RuntimeStateTransition
    runtime_supervisor_directive: RuntimeSupervisorDirective
    runtime_supervisor_plan: RuntimeSupervisorPlan
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
            "enforcement_plan": self.enforcement_plan.to_dict(),
            "live_command_count": len(self.live_commands),
            "live_commands": [command.to_dict() for command in self.live_commands],
            "state_snapshot": self.state_snapshot.to_dict(),
            "policy_loop_directive_count": len(self.policy_loop_directives),
            "policy_loop_directives": [
                directive.to_dict() for directive in self.policy_loop_directives
            ],
            "execution_gate_count": len(self.execution_gates),
            "execution_gates": [gate.to_dict() for gate in self.execution_gates],
            "admission_plan": self.admission_plan.to_dict(),
            "efficiency_ledger": self.efficiency_ledger.to_dict(),
            "feedback_plan": self.feedback_plan.to_dict(),
            "actuation_plan": self.actuation_plan.to_dict(),
            "memory_transit_map": self.memory_transit_map.to_dict(),
            "memory_route_plan": self.memory_route_plan.to_dict(),
            "frame_window_plan": self.frame_window_plan.to_dict(),
            "execution_packet": self.execution_packet.to_dict(),
            "execution_simulation": self.execution_simulation.to_dict(),
            "adaptive_executor_loop": self.adaptive_executor_loop.to_dict(),
            "budget_envelope": self.budget_envelope.to_dict(),
            "budget_arbitration": self.budget_arbitration.to_dict(),
            "dispatch_plan": self.dispatch_plan.to_dict(),
            "dispatch_execution": self.dispatch_execution.to_dict(),
            "runtime_calibration": self.runtime_calibration.to_dict(),
            "runtime_manager": self.runtime_manager.to_dict(),
            "runtime_control_packet": self.runtime_control_packet.to_dict(),
            "runtime_control_state": self.runtime_control_state.to_dict(),
            "runtime_gateway_tick": self.runtime_gateway_tick.to_dict(),
            "runtime_gateway_cycle": self.runtime_gateway_cycle.to_dict(),
            "runtime_gateway_feedback": self.runtime_gateway_feedback.to_dict(),
            "runtime_policy_update": self.runtime_policy_update.to_dict(),
            "runtime_state_accumulator": self.runtime_state_accumulator.to_dict(),
            "runtime_state_transition": self.runtime_state_transition.to_dict(),
            "runtime_supervisor_directive": (
                self.runtime_supervisor_directive.to_dict()
            ),
            "runtime_supervisor_plan": self.runtime_supervisor_plan.to_dict(),
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
        self.policy_governor = LivePolicyGovernor()
        self.current_frame: int | None = None
        self.events_processed = 0
        self.lifecycle_events = 0
        self.resource_events = 0
        self.operation_events = 0
        self.released_resources: list[str] = []
        self.frames: dict[int, AdapterFrameStats] = {}
        self.live_commands: list[LiveCommand] = []
        self.policy_loop_directives: list[GovernorDirective] = []
        self.execution_gates: list[ExecutionGateDecision] = []
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
        if event_type == "state":
            return self._process_state_event(payload, event_index)
        raise ValueError(f"Unsupported adapter event type: {event_type or 'missing'}")

    def to_result(
        self,
        previous_state: RuntimeStateAccumulator | None = None,
    ) -> AdapterSessionResult:
        lifetime_plan = self.lifetime_planner.finalize()
        schedule_plan = self._build_schedule_plan(lifetime_plan)
        enforcement_plan = build_enforcement_plan(schedule_plan)
        admission_plan = build_admission_plan(self.results)
        efficiency_ledger = build_efficiency_ledger(admission_plan)
        frame_targets = {
            frame.frame: frame.target_frame_ms for frame in self.frames.values()
        }
        feedback_plan = build_feedback_plan(efficiency_ledger, frame_targets)
        memory_transit_map = build_memory_transit_map(
            self.results,
            self.lifetime_planner.resources,
        )
        memory_route_plan = build_memory_route_plan(memory_transit_map)
        frame_window_plan = build_frame_window_plan(memory_route_plan)
        execution_packet = build_execution_packet(frame_window_plan)
        execution_simulation = simulate_execution(execution_packet)
        adaptive_executor_loop = build_adaptive_executor_loop(
            execution_simulation,
            frame_targets,
        )
        state_snapshot = self._build_state_snapshot()
        budget_envelope = build_runtime_budget_envelope(
            adaptive_executor_loop,
            state_snapshot,
            self.policy_engine.memory_budgets_mb,
        )
        budget_arbitration = build_budget_arbitration(
            execution_packet,
            budget_envelope,
        )
        dispatch_plan = build_runtime_dispatch_plan(
            budget_arbitration,
            execution_packet,
        )
        dispatch_execution = execute_dispatch_plan(dispatch_plan)
        frames = [self.frames[key] for key in sorted(self.frames)]
        runtime_calibration = build_runtime_calibration(
            dispatch_execution,
            frames,
        )
        runtime_manager = build_runtime_manager_directive(
            runtime_calibration,
            budget_envelope,
        )
        runtime_control_packet = build_runtime_control_packet(runtime_manager)
        runtime_control_state = apply_runtime_control_packet(runtime_control_packet)
        runtime_gateway_tick = build_runtime_gateway_tick(runtime_control_state)
        runtime_gateway_cycle = execute_runtime_gateway_tick(runtime_gateway_tick)
        runtime_gateway_feedback = build_runtime_gateway_feedback(
            runtime_gateway_cycle,
            runtime_calibration,
        )
        runtime_policy_update = build_runtime_policy_update(runtime_gateway_feedback)
        runtime_state_accumulator = build_runtime_state_accumulator(
            runtime_policy_update,
            previous=previous_state,
        )
        runtime_state_transition = build_runtime_state_transition(
            previous_state,
            runtime_state_accumulator,
        )
        runtime_supervisor_directive = build_runtime_supervisor_directive(
            runtime_state_accumulator,
            runtime_state_transition,
        )
        runtime_supervisor_plan = build_runtime_supervisor_plan(
            runtime_supervisor_directive
        )
        return AdapterSessionResult(
            mode=ADAPTER_MODE,
            session_id=self.session_id,
            events_processed=self.events_processed,
            lifecycle_events=self.lifecycle_events,
            resource_events=self.resource_events,
            operation_events=self.operation_events,
            released_resources=list(self.released_resources),
            frames=frames,
            policy_actions=list(self.policy_engine.actions),
            lifetime_plan=lifetime_plan,
            schedule_plan=schedule_plan,
            enforcement_plan=enforcement_plan,
            live_commands=list(self.live_commands),
            state_snapshot=state_snapshot,
            policy_loop_directives=list(self.policy_loop_directives),
            execution_gates=list(self.execution_gates),
            admission_plan=admission_plan,
            efficiency_ledger=efficiency_ledger,
            feedback_plan=feedback_plan,
            actuation_plan=build_actuation_plan(feedback_plan),
            memory_transit_map=memory_transit_map,
            memory_route_plan=memory_route_plan,
            frame_window_plan=frame_window_plan,
            execution_packet=execution_packet,
            execution_simulation=execution_simulation,
            adaptive_executor_loop=adaptive_executor_loop,
            budget_envelope=budget_envelope,
            budget_arbitration=budget_arbitration,
            dispatch_plan=dispatch_plan,
            dispatch_execution=dispatch_execution,
            runtime_calibration=runtime_calibration,
            runtime_manager=runtime_manager,
            runtime_control_packet=runtime_control_packet,
            runtime_control_state=runtime_control_state,
            runtime_gateway_tick=runtime_gateway_tick,
            runtime_gateway_cycle=runtime_gateway_cycle,
            runtime_gateway_feedback=runtime_gateway_feedback,
            runtime_policy_update=runtime_policy_update,
            runtime_state_accumulator=runtime_state_accumulator,
            runtime_state_transition=runtime_state_transition,
            runtime_supervisor_directive=runtime_supervisor_directive,
            runtime_supervisor_plan=runtime_supervisor_plan,
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
        enforcement_plan = build_enforcement_plan(schedule_plan) if schedule_plan else None
        response = {
            "ok": True,
            "event": "session",
            "action": action,
            "session_id": self.session_id,
            "closed": self.closed,
            "policy_actions": [],
            "lifetime_plan": lifetime_plan.to_dict() if lifetime_plan else None,
            "schedule_plan": schedule_plan.to_dict() if schedule_plan else None,
            "enforcement_plan": enforcement_plan.to_dict() if enforcement_plan else None,
        }
        return self._with_state_snapshot(response, event_index)

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
        return self._with_state_snapshot(response, event_index)

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
            return self._with_state_snapshot(response, event_index)

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
        return self._with_state_snapshot(response, event_index)

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
        operation_frame = result.operation.frame
        target_frame_ms = (
            self._frame_stats(operation_frame).target_frame_ms
            if operation_frame is not None
            else self.policy_engine.target_frame_ms
        )
        live_command = build_live_command(result, target_frame_ms)
        self.live_commands.append(live_command)
        result_payload["live_command"] = live_command.to_dict()
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
            target_frame_ms,
        )
        self._record_policy_actions(policy_actions, operation_frame)
        response = {
            "ok": True,
            "event": "operation",
            "result": result_payload,
            "live_command": live_command.to_dict(),
            "policy_actions": [item.to_dict() for item in policy_actions],
        }
        return self._with_state_snapshot(
            response,
            event_index,
            live_command=live_command,
            operation_result=result,
        )

    def _process_state_event(
        self, payload: dict[str, Any], event_index: int | None
    ) -> dict[str, Any]:
        action = normalized_action(payload.get("action"), {"snapshot"}, "snapshot")
        response = {
            "ok": True,
            "event": "state",
            "action": action,
            "session_id": self.session_id,
        }
        return self._with_state_snapshot(response, event_index)

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

    def _build_state_snapshot(self) -> LiveStateSnapshot:
        return build_live_state_snapshot(
            session_id=self.session_id,
            current_frame=self.current_frame,
            frames=self.frames,
            active_resource_count=len(self.controller.resources),
            memory_totals_mb=self.policy_engine.memory_totals_mb,
            memory_budgets_mb=self.policy_engine.memory_budgets_mb,
            decisions_count=len(self.controller.decisions),
            events_processed=self.events_processed,
            operation_events=self.operation_events,
            resource_events=self.resource_events,
            policy_action_count=len(self.policy_engine.actions),
            live_command_count=len(self.live_commands),
        )

    def _with_state_snapshot(
        self,
        response: dict[str, Any],
        event_index: int | None,
        live_command: LiveCommand | None = None,
        operation_result: Any | None = None,
    ) -> dict[str, Any]:
        snapshot = self._build_state_snapshot()
        target_frame_ms = self._target_frame_ms(snapshot.current_frame, live_command)
        directives = self.policy_governor.evaluate(
            snapshot=snapshot,
            target_frame_ms=target_frame_ms,
            memory_budgets_mb=self.policy_engine.memory_budgets_mb,
            live_command=live_command,
        )
        self.policy_loop_directives.extend(directives)
        response["state_snapshot"] = snapshot.to_dict()
        response["policy_loop_directives"] = [
            directive.to_dict() for directive in directives
        ]
        if operation_result is not None and live_command is not None:
            execution_gate = build_execution_gate(
                result=operation_result,
                live_command=live_command,
                directives=directives,
                snapshot=snapshot,
                target_frame_ms=target_frame_ms,
            )
            self.execution_gates.append(execution_gate)
            response["execution_gate"] = execution_gate.to_dict()
            response["result"]["execution_gate"] = execution_gate.to_dict()
            admission_decision = build_admission_decision(response["result"])
            efficiency_impact = build_efficiency_impact(admission_decision)
            response["admission_decision"] = admission_decision.to_dict()
            response["result"]["admission_decision"] = admission_decision.to_dict()
            response["efficiency_impact"] = efficiency_impact.to_dict()
            response["result"]["efficiency_impact"] = efficiency_impact.to_dict()
            self.results.append(response["result"])
        return with_event_index(response, event_index)

    def _target_frame_ms(
        self, current_frame: int | None, live_command: LiveCommand | None
    ) -> float:
        if current_frame is not None:
            return self._frame_stats(current_frame).target_frame_ms
        if live_command is not None and live_command.frame is not None:
            return self._frame_stats(live_command.frame).target_frame_ms
        return self.policy_engine.target_frame_ms


def replay_adapter_event_stream(
    path: str | Path,
    previous_state: RuntimeStateAccumulator | None = None,
) -> AdapterSessionResult:
    session = RuntimeAdapterSession()
    for index, payload in iter_jsonl(path):
        session.process_event(payload, event_index=index)
    return session.to_result(previous_state=previous_state)


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
