from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapter import AdapterSessionResult
from .client import summarize_client_responses
from .state_accumulator import RuntimeStateAccumulator


def print_runtime_client_summary(
    *,
    responses: list[dict[str, Any]],
    output_path: Path,
) -> int:
    summary = summarize_client_responses(responses)
    operation_responses = [
        response for response in responses if response.get("event") == "operation"
    ]
    decision_count = sum(
        1
        for response in operation_responses
        if response.get("result", {}).get("decision") is not None
    )
    failed_responses = sum(1 for response in responses if not response.get("ok"))

    print(f"FluidGateway server responses written: {output_path}")
    print_rows(
        [
            ("Events sent", len(responses), None),
            ("Operation responses", len(operation_responses), None),
            (
                "State responses",
                sum(1 for response in responses if response.get("event") == "state"),
                None,
            ),
            (
                "State snapshots",
                sum(1 for response in responses if response.get("state_snapshot")),
                None,
            ),
            (
                "Policy loop directives",
                sum(
                    len(response.get("policy_loop_directives") or [])
                    for response in responses
                ),
                None,
            ),
            (
                "Execution gates",
                sum(1 for response in responses if response.get("execution_gate")),
                None,
            ),
            (
                "Admission decisions",
                sum(
                    1
                    for response in responses
                    if response.get("admission_decision")
                ),
                None,
            ),
            (
                "Efficiency impacts",
                sum(1 for response in responses if response.get("efficiency_impact")),
                None,
            ),
            ("Actuation commands", summary["actuation_plan"]["command_count"], None),
            ("Memory transit hops", summary["memory_transit_map"]["hop_count"], None),
            (
                "Memory route directives",
                summary["memory_route_plan"]["directive_count"],
                None,
            ),
            ("Frame window slots", summary["frame_window_plan"]["slot_count"], None),
            (
                "Execution packet commands",
                summary["execution_packet"]["command_count"],
                None,
            ),
            (
                "Execution simulated hot-path after ms",
                summary["execution_simulation"]["hot_path_after_ms"],
                4,
            ),
            ("Adaptive executor profile", summary["adaptive_executor_loop"]["profile"], None),
            ("Budget envelope policy", summary["budget_envelope"]["next_frame_policy"], None),
            (
                "Budget envelope constrained memory layers",
                summary["budget_envelope"]["constrained_memory_count"],
                None,
            ),
            (
                "Budget arbitration deferred commands",
                summary["budget_arbitration"]["deferred_count"],
                None,
            ),
            (
                "Budget arbitration memory actions",
                summary["budget_arbitration"]["memory_action_count"],
                None,
            ),
            ("Dispatch commands", summary["dispatch_plan"]["command_count"], None),
            ("Dispatch pre-frame commands", summary["dispatch_plan"]["pre_frame_count"], None),
            ("Dispatch hot-path commands", summary["dispatch_plan"]["hot_path_count"], None),
            ("Dispatch next-frame commands", summary["dispatch_plan"]["next_frame_count"], None),
            (
                "Dispatch execution current-frame ms",
                summary["dispatch_execution"]["current_frame_cost_ms"],
                4,
            ),
            (
                "Dispatch execution pre-frame ms",
                summary["dispatch_execution"]["pre_frame_cost_ms"],
                4,
            ),
            (
                "Dispatch execution deferred ms",
                summary["dispatch_execution"]["deferred_cost_ms"],
                4,
            ),
            (
                "Dispatch execution memory relief MB",
                summary["dispatch_execution"]["memory_relief_mb"],
                4,
            ),
            (
                "Runtime calibration observed frame ms",
                summary["runtime_calibration"]["total_observed_frame_cost_ms"],
                4,
            ),
            (
                "Runtime calibration planned current-frame ms",
                summary["runtime_calibration"]["total_planned_current_frame_cost_ms"],
                4,
            ),
            (
                "Runtime calibration relief ms",
                summary["runtime_calibration"]["total_planned_frame_relief_ms"],
                4,
            ),
            (
                "Runtime calibration max guardband ms",
                summary["runtime_calibration"]["max_guardband_ms"],
                4,
            ),
            ("Runtime manager profile", summary["runtime_manager"]["profile"], None),
            (
                "Runtime manager next frame budget ms",
                summary["runtime_manager"]["next_frame_budget_ms"],
                4,
            ),
            (
                "Runtime manager memory actions",
                summary["runtime_manager"]["memory_action_count"],
                None,
            ),
            (
                "Runtime control packet commands",
                summary["runtime_control_packet"]["command_count"],
                None,
            ),
            (
                "Runtime control packet active commands",
                summary["runtime_control_packet"]["active_command_count"],
                None,
            ),
            (
                "Runtime control packet memory commands",
                summary["runtime_control_packet"]["memory_command_count"],
                None,
            ),
            (
                "Runtime control state frame budgets",
                summary["runtime_control_state"]["applied_frame_budget_count"],
                None,
            ),
            (
                "Runtime control state memory actions",
                summary["runtime_control_state"]["memory_action_count"],
                None,
            ),
            ("Runtime gateway tick policy", summary["runtime_gateway_tick"]["tick_policy"], None),
            ("Runtime gateway tick steps", summary["runtime_gateway_tick"]["step_count"], None),
            (
                "Runtime gateway tick memory active steps",
                summary["runtime_gateway_tick"]["memory_active_step_count"],
                None,
            ),
            (
                "Runtime gateway cycle next action",
                summary["runtime_gateway_cycle"]["next_cycle_action"],
                None,
            ),
            (
                "Runtime gateway cycle drift risk",
                summary["runtime_gateway_cycle"]["drift_risk"],
                None,
            ),
            (
                "Runtime gateway cycle memory relief MB",
                summary["runtime_gateway_cycle"]["memory_relief_applied_mb"],
                4,
            ),
            (
                "Runtime gateway feedback action",
                summary["runtime_gateway_feedback"]["feedback_action"],
                None,
            ),
            (
                "Runtime gateway feedback convergence",
                summary["runtime_gateway_feedback"]["convergence_status"],
                None,
            ),
            (
                "Runtime gateway feedback protected gap ms",
                summary["runtime_gateway_feedback"]["protected_gap_ms"],
                4,
            ),
            (
                "Runtime policy update action",
                summary["runtime_policy_update"]["policy_action"],
                None,
            ),
            (
                "Runtime policy update next profile",
                summary["runtime_policy_update"]["next_profile"],
                None,
            ),
            (
                "Runtime policy update next frame budget ms",
                summary["runtime_policy_update"]["next_frame_budget_ms"],
                4,
            ),
            (
                "Runtime state accumulator cycles",
                summary["runtime_state_accumulator"]["cycle_count"],
                None,
            ),
            (
                "Runtime state accumulator active policies",
                summary["runtime_state_accumulator"]["active_policy_count"],
                None,
            ),
            (
                "Runtime state accumulator digest",
                summary["runtime_state_accumulator"]["state_digest"],
                None,
            ),
            (
                "Runtime state transition trend",
                summary["runtime_state_transition"]["trend"],
                None,
            ),
            (
                "Runtime state transition action",
                summary["runtime_state_transition"]["transition_action"],
                None,
            ),
            (
                "Runtime state transition pressure delta",
                summary["runtime_state_transition"]["pressure_delta"],
                4,
            ),
            (
                "Runtime supervisor directive action",
                summary["runtime_supervisor_directive"]["directive_action"],
                None,
            ),
            (
                "Runtime supervisor scheduler posture",
                summary["runtime_supervisor_directive"]["scheduler_posture"],
                None,
            ),
            (
                "Runtime supervisor memory posture",
                summary["runtime_supervisor_directive"]["memory_posture"],
                None,
            ),
            (
                "Runtime supervisor plan action",
                summary["runtime_supervisor_plan"]["plan_action"],
                None,
            ),
            (
                "Runtime supervisor plan commands",
                summary["runtime_supervisor_plan"]["command_count"],
                None,
            ),
            (
                "Runtime supervisor plan blocking commands",
                summary["runtime_supervisor_plan"]["blocking_command_count"],
                None,
            ),
            (
                "Runtime supervisor execution action",
                summary["runtime_supervisor_execution"]["execution_action"],
                None,
            ),
            (
                "Runtime supervisor execution would apply",
                summary["runtime_supervisor_execution"]["would_apply_count"],
                None,
            ),
            (
                "Runtime supervisor execution guard",
                summary["runtime_supervisor_execution"]["execution_guard"],
                None,
            ),
            ("Decisions", decision_count, None),
            ("Failed responses", failed_responses, None),
        ]
    )
    return failed_responses


def print_runtime_adapter_summary(
    *,
    result: AdapterSessionResult,
    output_path: Path,
    previous_state: RuntimeStateAccumulator | None,
    state_output_path: Path | None,
) -> None:
    snapshot = result.snapshot
    print(f"FluidGateway adapter session written: {output_path}")
    if previous_state is not None:
        print(f"Runtime previous state cycles: {previous_state.cycle_count}")
    if state_output_path is not None:
        print(f"Runtime state accumulator written: {state_output_path}")
    print_rows(
        [
            ("Events processed", result.events_processed, None),
            ("Frames observed", len(result.frames), None),
            ("Operation events", result.operation_events, None),
            ("Decisions", len(snapshot["decisions"]), None),
            ("Policy actions", len(result.policy_actions), None),
            ("Lifetime plan actions", result.lifetime_plan.plan_action_count, None),
            ("Scheduled steps", result.schedule_plan.scheduled_step_count, None),
            ("Enforcement commands", result.enforcement_plan.command_count, None),
            ("Live commands", len(result.live_commands), None),
            ("Policy loop directives", len(result.policy_loop_directives), None),
            ("Execution gates", len(result.execution_gates), None),
            ("Admission operations", result.admission_plan.operation_count, None),
            (
                "Admission hot-path cost ms",
                result.admission_plan.estimated_hot_path_cost_ms,
                4,
            ),
            (
                "Admission avoided cost ms",
                result.admission_plan.estimated_avoided_cost_ms,
                4,
            ),
            ("Efficiency relief cost ms", result.efficiency_ledger.relief_cost_ms, 4),
            (
                "Efficiency transfer relief MB",
                result.efficiency_ledger.transfer_relief_mb,
                4,
            ),
            ("Feedback actions", result.feedback_plan.action_count, None),
        ]
    )
    if result.feedback_plan.frames:
        print(
            "Feedback next copy budget ms: "
            f"{result.feedback_plan.frames[0].suggested_copy_budget_ms:.4f}"
        )
    print_rows(
        [
            ("Actuation commands", result.actuation_plan.command_count, None),
            ("Actuation copy budget ms", result.actuation_plan.total_copy_budget_ms, 4),
            ("Memory transit hops", result.memory_transit_map.hop_count, None),
            (
                "Memory avoided transfer MB",
                result.memory_transit_map.avoided_transfer_mb,
                4,
            ),
            ("Memory route directives", result.memory_route_plan.directive_count, None),
            ("Memory route saved MB", result.memory_route_plan.estimated_saved_mb, 4),
            ("Frame window slots", result.frame_window_plan.slot_count, None),
            ("Frame pre-frame slots", result.frame_window_plan.pre_frame_count, None),
            ("Execution packet commands", result.execution_packet.command_count, None),
            ("Execution packet saved MB", result.execution_packet.estimated_saved_mb, 4),
            (
                "Execution simulated hot-path before ms",
                result.execution_simulation.hot_path_before_ms,
                4,
            ),
            (
                "Execution simulated hot-path after ms",
                result.execution_simulation.hot_path_after_ms,
                4,
            ),
            ("Adaptive executor profile", result.adaptive_executor_loop.profile, None),
            (
                "Adaptive executor over-budget frames",
                result.adaptive_executor_loop.over_budget_count,
                None,
            ),
            ("Budget envelope policy", result.budget_envelope.next_frame_policy, None),
            (
                "Budget envelope constrained memory layers",
                result.budget_envelope.constrained_memory_count,
                None,
            ),
            (
                "Budget arbitration deferred commands",
                result.budget_arbitration.deferred_count,
                None,
            ),
            (
                "Budget arbitration memory actions",
                result.budget_arbitration.memory_action_count,
                None,
            ),
            ("Dispatch commands", result.dispatch_plan.command_count, None),
            ("Dispatch pre-frame commands", result.dispatch_plan.pre_frame_count, None),
            ("Dispatch hot-path commands", result.dispatch_plan.hot_path_count, None),
            ("Dispatch next-frame commands", result.dispatch_plan.next_frame_count, None),
            (
                "Dispatch execution current-frame ms",
                result.dispatch_execution.current_frame_cost_ms,
                4,
            ),
            (
                "Dispatch execution pre-frame ms",
                result.dispatch_execution.pre_frame_cost_ms,
                4,
            ),
            (
                "Dispatch execution deferred ms",
                result.dispatch_execution.deferred_cost_ms,
                4,
            ),
            (
                "Dispatch execution memory relief MB",
                result.dispatch_execution.memory_relief_mb,
                4,
            ),
            (
                "Runtime calibration observed frame ms",
                result.runtime_calibration.total_observed_frame_cost_ms,
                4,
            ),
            (
                "Runtime calibration planned current-frame ms",
                result.runtime_calibration.total_planned_current_frame_cost_ms,
                4,
            ),
            (
                "Runtime calibration relief ms",
                result.runtime_calibration.total_planned_frame_relief_ms,
                4,
            ),
            (
                "Runtime calibration max guardband ms",
                result.runtime_calibration.max_guardband_ms,
                4,
            ),
            ("Runtime manager profile", result.runtime_manager.profile, None),
            (
                "Runtime manager next frame budget ms",
                result.runtime_manager.next_frame_budget_ms,
                4,
            ),
            (
                "Runtime manager memory actions",
                result.runtime_manager.memory_action_count,
                None,
            ),
            (
                "Runtime control packet commands",
                result.runtime_control_packet.command_count,
                None,
            ),
            (
                "Runtime control packet active commands",
                result.runtime_control_packet.active_command_count,
                None,
            ),
            (
                "Runtime control packet memory commands",
                result.runtime_control_packet.memory_command_count,
                None,
            ),
            (
                "Runtime control state frame budgets",
                result.runtime_control_state.applied_frame_budget_count,
                None,
            ),
            (
                "Runtime control state memory actions",
                result.runtime_control_state.memory_action_count,
                None,
            ),
            ("Runtime gateway tick policy", result.runtime_gateway_tick.tick_policy, None),
            ("Runtime gateway tick steps", result.runtime_gateway_tick.step_count, None),
            (
                "Runtime gateway tick memory active steps",
                result.runtime_gateway_tick.memory_active_step_count,
                None,
            ),
            (
                "Runtime gateway cycle next action",
                result.runtime_gateway_cycle.next_cycle_action,
                None,
            ),
            ("Runtime gateway cycle drift risk", result.runtime_gateway_cycle.drift_risk, None),
            (
                "Runtime gateway cycle memory relief MB",
                result.runtime_gateway_cycle.memory_relief_applied_mb,
                4,
            ),
            (
                "Runtime gateway feedback action",
                result.runtime_gateway_feedback.feedback_action,
                None,
            ),
            (
                "Runtime gateway feedback convergence",
                result.runtime_gateway_feedback.convergence_status,
                None,
            ),
            (
                "Runtime gateway feedback protected gap ms",
                result.runtime_gateway_feedback.protected_gap_ms,
                4,
            ),
            (
                "Runtime policy update action",
                result.runtime_policy_update.policy_action,
                None,
            ),
            (
                "Runtime policy update next profile",
                result.runtime_policy_update.next_profile,
                None,
            ),
            (
                "Runtime policy update next frame budget ms",
                result.runtime_policy_update.next_frame_budget_ms,
                4,
            ),
            (
                "Runtime state accumulator cycles",
                result.runtime_state_accumulator.cycle_count,
                None,
            ),
            (
                "Runtime state accumulator active policies",
                result.runtime_state_accumulator.active_policy_count,
                None,
            ),
            (
                "Runtime state accumulator digest",
                result.runtime_state_accumulator.state_digest,
                None,
            ),
            ("Runtime state transition trend", result.runtime_state_transition.trend, None),
            (
                "Runtime state transition action",
                result.runtime_state_transition.transition_action,
                None,
            ),
            (
                "Runtime state transition pressure delta",
                result.runtime_state_transition.pressure_delta,
                4,
            ),
            (
                "Runtime supervisor directive action",
                result.runtime_supervisor_directive.directive_action,
                None,
            ),
            (
                "Runtime supervisor scheduler posture",
                result.runtime_supervisor_directive.scheduler_posture,
                None,
            ),
            (
                "Runtime supervisor memory posture",
                result.runtime_supervisor_directive.memory_posture,
                None,
            ),
            (
                "Runtime supervisor plan action",
                result.runtime_supervisor_plan.plan_action,
                None,
            ),
            (
                "Runtime supervisor plan commands",
                result.runtime_supervisor_plan.command_count,
                None,
            ),
            (
                "Runtime supervisor plan blocking commands",
                result.runtime_supervisor_plan.blocking_command_count,
                None,
            ),
            (
                "Runtime supervisor execution action",
                result.runtime_supervisor_execution.execution_action,
                None,
            ),
            (
                "Runtime supervisor execution would apply",
                result.runtime_supervisor_execution.would_apply_count,
                None,
            ),
            (
                "Runtime supervisor execution guard",
                result.runtime_supervisor_execution.execution_guard,
                None,
            ),
            ("Live state open frame", result.state_snapshot.open_frame, None),
            (
                "Live state active resources",
                result.state_snapshot.active_resource_count,
                None,
            ),
            (
                "Estimated critical-path reduction ms",
                result.schedule_plan.estimated_latency_reduction_ms,
                4,
            ),
            ("Released resources", len(result.released_resources), None),
            ("Estimated saved ms", snapshot["estimated_saved_ms"], 4),
            (
                "Estimated saved MB moved/allocated",
                snapshot["estimated_saved_mb"],
                4,
            ),
        ]
    )


def print_rows(rows: list[tuple[str, Any, int | None]]) -> None:
    for label, value, precision in rows:
        rendered = f"{value:.{precision}f}" if precision is not None else str(value)
        print(f"{label}: {rendered}")
