from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .adapter import replay_adapter_event_stream, write_adapter_session
from .analyzer import analyze_trace
from .client import (
    RuntimeEventClient,
    summarize_client_responses,
    write_client_responses,
)
from .control import FluidGatewayController
from .daemon import run_runtime_daemon, write_runtime_daemon_report
from .daemon_cli import print_runtime_daemon_summary
from .events import replay_event_stream, write_event_replay
from .host import collect_host_capability_snapshot
from .parser import parse_presentmon_csv
from .presentmon_runtime import (
    build_presentmon_runtime_event_stream,
    write_presentmon_runtime_events,
)
from .presentmon_daemon import run_presentmon_daemon
from .report import write_report
from .report import write_management_plan
from .runtime import RuntimeManifest, load_manifest, optimize_manifest, write_runtime_plan
from .server import serve_runtime_events
from .state_accumulator import (
    load_runtime_state_accumulator,
    write_runtime_state_accumulator,
)
from .tracker import DEFAULT_REGISTRY, summarize_registry, track_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fluidgateway",
        description="Diagnose probable waste in PresentMon frame traces.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze a PresentMon 2.x CSV and write HTML/JSON reports.",
    )
    analyze.add_argument(
        "--presentmon",
        required=True,
        help="Path to a PresentMon 2.x CSV trace.",
    )
    analyze.add_argument(
        "--out",
        required=True,
        help="Path to the HTML report. A JSON report is written next to it.",
    )
    analyze.set_defaults(func=run_analyze)

    manage = subparsers.add_parser(
        "manage",
        help="Generate an advisory management plan from a PresentMon 2.x CSV.",
    )
    manage.add_argument(
        "--presentmon",
        required=True,
        help="Path to a PresentMon 2.x CSV trace.",
    )
    manage.add_argument(
        "--out",
        required=True,
        help="Path to the management JSON plan.",
    )
    manage.set_defaults(func=run_manage)

    track = subparsers.add_parser(
        "track",
        help="Analyze a trace and append it to the local FluidGateway registry.",
    )
    track.add_argument(
        "--presentmon",
        required=True,
        help="Path to a PresentMon 2.x CSV trace.",
    )
    track.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Path to the trace registry JSON.",
    )
    track.add_argument(
        "--label",
        help="Human-readable trace label. Defaults to the detected application.",
    )
    track.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Tag to attach to the trace record. Can be repeated.",
    )
    track.add_argument(
        "--notes",
        default="",
        help="Free-form notes for this trace.",
    )
    track.set_defaults(func=run_track)

    history = subparsers.add_parser(
        "history",
        help="List traces stored in the local FluidGateway registry.",
    )
    history.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Path to the trace registry JSON.",
    )
    history.set_defaults(func=run_history)

    runtime = subparsers.add_parser(
        "runtime",
        help="Optimize an explicit CPU/GPU/RAM/VRAM pipeline manifest.",
    )
    runtime_subparsers = runtime.add_subparsers(dest="runtime_command", required=True)
    optimize = runtime_subparsers.add_parser(
        "optimize",
        help="Generate an optimized runtime plan from a pipeline manifest.",
    )
    optimize.add_argument(
        "--manifest",
        required=True,
        help="Path to a FluidGateway runtime manifest JSON.",
    )
    optimize.add_argument(
        "--out",
        required=True,
        help="Path to the runtime optimization JSON plan.",
    )
    optimize.set_defaults(func=run_runtime_optimize)
    simulate = runtime_subparsers.add_parser(
        "simulate-control",
        help="Run a manifest through the incremental FluidGateway control plane.",
    )
    simulate.add_argument(
        "--manifest",
        required=True,
        help="Path to a FluidGateway runtime manifest JSON.",
    )
    simulate.add_argument(
        "--out",
        required=True,
        help="Path to the control-plane snapshot JSON.",
    )
    simulate.set_defaults(func=run_runtime_simulate_control)
    replay = runtime_subparsers.add_parser(
        "replay-events",
        help="Replay a JSONL runtime event stream through the control plane.",
    )
    replay.add_argument(
        "--events",
        required=True,
        help="Path to a FluidGateway runtime JSONL event stream.",
    )
    replay.add_argument(
        "--out",
        required=True,
        help="Path to the event replay JSON output.",
    )
    replay.set_defaults(func=run_runtime_replay_events)
    ingest = runtime_subparsers.add_parser(
        "ingest-presentmon",
        help="Convert a PresentMon CSV analysis into runtime adapter JSONL events.",
    )
    ingest.add_argument(
        "--presentmon",
        required=True,
        help="Path to a PresentMon 2.x CSV trace.",
    )
    ingest.add_argument(
        "--out",
        required=True,
        help="Path to the generated FluidGateway adapter JSONL stream.",
    )
    ingest.set_defaults(func=run_runtime_ingest_presentmon)
    presentmon_daemon = runtime_subparsers.add_parser(
        "run-presentmon-daemon",
        help="Analyze a PresentMon CSV and feed it directly into the runtime daemon.",
    )
    presentmon_daemon.add_argument(
        "--presentmon",
        required=True,
        help="Path to a PresentMon 2.x CSV trace.",
    )
    presentmon_daemon.add_argument(
        "--events-out",
        required=True,
        help="Path to write the generated adapter JSONL event stream.",
    )
    presentmon_daemon.add_argument(
        "--state",
        required=True,
        help=(
            "runtime_state_accumulator JSON path to load before the daemon "
            "loop and overwrite with the final daemon state."
        ),
    )
    presentmon_daemon.add_argument(
        "--out",
        required=True,
        help="Path to the runtime daemon dry-run JSON report.",
    )
    presentmon_daemon.set_defaults(func=run_runtime_run_presentmon_daemon)
    send = runtime_subparsers.add_parser(
        "send-events",
        help="Send a JSONL runtime event stream to a running decision server.",
    )
    send.add_argument(
        "--events",
        required=True,
        help="Path to a FluidGateway runtime JSONL event stream.",
    )
    send.add_argument(
        "--host",
        default="127.0.0.1",
        help="Runtime server host. Defaults to 127.0.0.1.",
    )
    send.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Runtime server TCP port. Defaults to 8765.",
    )
    send.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Socket timeout in seconds. Defaults to 5.",
    )
    send.add_argument(
        "--out",
        required=True,
        help="Path to the server response JSON output.",
    )
    send.set_defaults(func=run_runtime_send_events)
    adapter = runtime_subparsers.add_parser(
        "run-adapter",
        help="Run a lifecycle-aware adapter JSONL session locally.",
    )
    adapter.add_argument(
        "--events",
        required=True,
        help="Path to a FluidGateway adapter lifecycle JSONL stream.",
    )
    adapter.add_argument(
        "--out",
        required=True,
        help="Path to the adapter session JSON output.",
    )
    adapter.add_argument(
        "--state-in",
        help=(
            "Optional previous runtime_state_accumulator JSON. Missing files "
            "start a fresh cycle."
        ),
    )
    adapter.add_argument(
        "--state-out",
        help="Optional path to write the next runtime_state_accumulator JSON.",
    )
    adapter.set_defaults(func=run_runtime_run_adapter)
    daemon = runtime_subparsers.add_parser(
        "run-daemon",
        help="Run a persistent advisory runtime daemon loop locally.",
    )
    daemon.add_argument(
        "--events",
        action="append",
        required=True,
        help=(
            "Path to a FluidGateway adapter lifecycle JSONL stream. Can be "
            "repeated to replay different streams across daemon cycles."
        ),
    )
    daemon.add_argument(
        "--iterations",
        type=int,
        default=1,
        help=(
            "Minimum number of daemon cycles to run. If more --events streams "
            "are supplied, all streams are consumed; the last stream repeats "
            "when iterations is larger. Defaults to 1."
        ),
    )
    daemon.add_argument(
        "--state",
        required=True,
        help=(
            "runtime_state_accumulator JSON path to load before the "
            "loop and overwrite with the final daemon state."
        ),
    )
    daemon.add_argument(
        "--out",
        required=True,
        help="Path to the runtime daemon dry-run JSON report.",
    )
    daemon.set_defaults(func=run_runtime_run_daemon)
    serve = runtime_subparsers.add_parser(
        "serve-events",
        help="Serve a local TCP JSONL runtime decision endpoint.",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind. Defaults to 127.0.0.1.",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8765,
        help="TCP port to bind. Defaults to 8765.",
    )
    serve.add_argument(
        "--once",
        action="store_true",
        help="Accept one connection and exit. Useful for tests and scripted runs.",
    )
    serve.set_defaults(func=run_runtime_serve_events)
    return parser


def run_analyze(args: argparse.Namespace) -> int:
    trace = parse_presentmon_csv(args.presentmon)
    report = analyze_trace(trace)
    html_path, json_path = write_report(report, args.out)
    print(f"FluidGateway report written: {html_path}")
    print(f"Structured report written: {json_path}")
    print(f"Findings: {len(report.findings)}")
    print(f"Management actions: {len(report.management_plan.actions)}")
    return 0


def run_manage(args: argparse.Namespace) -> int:
    trace = parse_presentmon_csv(args.presentmon)
    report = analyze_trace(trace)
    output_path = write_management_plan(report.management_plan, args.out)
    print(f"FluidGateway management plan written: {output_path}")
    print(f"Management actions: {len(report.management_plan.actions)}")
    return 0


def run_track(args: argparse.Namespace) -> int:
    trace = parse_presentmon_csv(args.presentmon)
    result = track_trace(
        trace=trace,
        registry_path=args.registry,
        label=args.label,
        tags=args.tag,
        notes=args.notes,
    )
    print(f"FluidGateway trace tracked: {result.record.id}")
    print(f"Registry: {result.registry_path}")
    print(f"Label: {result.record.label}")
    print(f"Findings: {len(result.record.finding_ids)}")
    print(f"Management actions: {len(result.record.management_action_ids)}")
    if result.duplicate:
        print("Duplicate source hash detected: this trace was already present.")
    return 0


def run_history(args: argparse.Namespace) -> int:
    rows = summarize_registry(args.registry)
    if not rows:
        print("No FluidGateway traces tracked yet.")
        return 0
    print("ID           Added At                  App                    Frames  FPS     Findings  Actions  Label")
    print("-" * 104)
    for row in rows:
        fps = "n/a" if row["fps"] is None else f"{row['fps']:.1f}"
        print(
            f"{row['id']:<12} "
            f"{row['added_at'][:19]:<25} "
            f"{row['application'][:22]:<22} "
            f"{row['frames']:<7} "
            f"{fps:<7} "
            f"{row['findings']:<9} "
            f"{row['actions']:<8} "
            f"{row['label']}"
        )
    return 0


def run_runtime_optimize(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    plan = optimize_manifest(manifest)
    output_path = write_runtime_plan(plan, args.out)
    print(f"FluidGateway runtime plan written: {output_path}")
    print(f"Original operations: {plan.original_operations}")
    print(f"Optimized operations: {plan.optimized_operations}")
    print(f"Decisions: {len(plan.decisions)}")
    print(f"Estimated saved ms: {plan.estimated_saved_ms:.4f}")
    print(f"Estimated saved MB moved/allocated: {plan.estimated_saved_mb:.4f}")
    return 0


def run_runtime_simulate_control(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    controller = controller_from_manifest(manifest)
    output_path = controller.write_snapshot(args.out)
    snapshot = controller.snapshot()
    print(f"FluidGateway control snapshot written: {output_path}")
    print(f"Executed operations: {len(snapshot['executed_operations'])}")
    print(f"Decisions: {len(snapshot['decisions'])}")
    print(f"Estimated saved ms: {snapshot['estimated_saved_ms']:.4f}")
    print(f"Estimated saved MB moved/allocated: {snapshot['estimated_saved_mb']:.4f}")
    return 0


def run_runtime_replay_events(args: argparse.Namespace) -> int:
    result = replay_event_stream(args.events)
    output_path = write_event_replay(result, args.out)
    snapshot = result.snapshot
    print(f"FluidGateway event replay written: {output_path}")
    print(f"Events processed: {result.events_processed}")
    print(f"Operation events: {result.operation_events}")
    print(f"Decisions: {len(snapshot['decisions'])}")
    print(f"Estimated saved ms: {snapshot['estimated_saved_ms']:.4f}")
    print(f"Estimated saved MB moved/allocated: {snapshot['estimated_saved_mb']:.4f}")
    return 0


def run_runtime_ingest_presentmon(args: argparse.Namespace) -> int:
    trace = parse_presentmon_csv(args.presentmon)
    report = analyze_trace(trace)
    stream = build_presentmon_runtime_event_stream(report)
    output_path = write_presentmon_runtime_events(stream, args.out)
    print(f"FluidGateway PresentMon runtime events written: {output_path}")
    print(f"Application: {stream.application}")
    print(f"Findings: {stream.finding_count}")
    print(f"Management actions: {stream.management_action_count}")
    print(f"Adapter events: {stream.event_count}")
    print(f"Runtime operations: {stream.operation_event_count}")
    print(f"Target frame budget ms: {stream.target_frame_ms:.4f}")
    return 0


def run_runtime_run_presentmon_daemon(args: argparse.Namespace) -> int:
    state_path = normalized_json_path(args.state)
    report_path = normalized_json_path(args.out)
    events_path = normalized_jsonl_path(args.events_out)
    if state_path == report_path:
        raise ValueError(
            "PresentMon daemon --state and --out must be different paths."
        )
    if events_path in {state_path, report_path}:
        raise ValueError(
            "PresentMon daemon --events-out must be different from --state and --out."
        )
    initial_state = load_runtime_state_accumulator(state_path)
    host_snapshot = collect_host_capability_snapshot()
    result = run_presentmon_daemon(
        presentmon_path=args.presentmon,
        events_output_path=events_path,
        initial_state=initial_state,
        host_snapshot=host_snapshot,
    )
    output_path = write_runtime_daemon_report(result.report, report_path)
    state_output_path = write_runtime_state_accumulator(
        result.report.final_state,
        state_path,
    )

    print(f"FluidGateway PresentMon runtime events written: {result.events_path}")
    print(f"PresentMon application: {result.event_stream.application}")
    print(f"PresentMon findings: {result.event_stream.finding_count}")
    print(f"PresentMon management actions: {result.event_stream.management_action_count}")
    print(f"PresentMon adapter events: {result.event_stream.event_count}")
    print_runtime_daemon_summary(
        report=result.report,
        output_path=output_path,
        state_output_path=state_output_path,
        initial_state=initial_state,
    )
    return 0


def run_runtime_send_events(args: argparse.Namespace) -> int:
    with RuntimeEventClient(args.host, args.port, args.timeout) as client:
        responses = client.send_jsonl(args.events)
    output_path = write_client_responses(responses, args.out)
    summary = summarize_client_responses(responses)
    operation_responses = [
        response for response in responses if response.get("event") == "operation"
    ]
    decision_count = sum(
        1
        for response in operation_responses
        if response.get("result", {}).get("decision") is not None
    )
    state_response_count = sum(
        1 for response in responses if response.get("event") == "state"
    )
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
    failed_responses = sum(1 for response in responses if not response.get("ok"))
    print(f"FluidGateway server responses written: {output_path}")
    print(f"Events sent: {len(responses)}")
    print(f"Operation responses: {len(operation_responses)}")
    print(f"State responses: {state_response_count}")
    print(f"State snapshots: {state_snapshot_count}")
    print(f"Policy loop directives: {policy_loop_directive_count}")
    print(f"Execution gates: {execution_gate_count}")
    print(f"Admission decisions: {admission_decision_count}")
    print(f"Efficiency impacts: {efficiency_impact_count}")
    print(f"Actuation commands: {summary['actuation_plan']['command_count']}")
    print(f"Memory transit hops: {summary['memory_transit_map']['hop_count']}")
    print(f"Memory route directives: {summary['memory_route_plan']['directive_count']}")
    print(f"Frame window slots: {summary['frame_window_plan']['slot_count']}")
    print(f"Execution packet commands: {summary['execution_packet']['command_count']}")
    print(
        "Execution simulated hot-path after ms: "
        f"{summary['execution_simulation']['hot_path_after_ms']:.4f}"
    )
    print(f"Adaptive executor profile: {summary['adaptive_executor_loop']['profile']}")
    print(f"Budget envelope policy: {summary['budget_envelope']['next_frame_policy']}")
    print(
        "Budget envelope constrained memory layers: "
        f"{summary['budget_envelope']['constrained_memory_count']}"
    )
    print(
        "Budget arbitration deferred commands: "
        f"{summary['budget_arbitration']['deferred_count']}"
    )
    print(
        "Budget arbitration memory actions: "
        f"{summary['budget_arbitration']['memory_action_count']}"
    )
    print(f"Dispatch commands: {summary['dispatch_plan']['command_count']}")
    print(
        "Dispatch pre-frame commands: "
        f"{summary['dispatch_plan']['pre_frame_count']}"
    )
    print(
        "Dispatch hot-path commands: "
        f"{summary['dispatch_plan']['hot_path_count']}"
    )
    print(
        "Dispatch next-frame commands: "
        f"{summary['dispatch_plan']['next_frame_count']}"
    )
    print(
        "Dispatch execution current-frame ms: "
        f"{summary['dispatch_execution']['current_frame_cost_ms']:.4f}"
    )
    print(
        "Dispatch execution pre-frame ms: "
        f"{summary['dispatch_execution']['pre_frame_cost_ms']:.4f}"
    )
    print(
        "Dispatch execution deferred ms: "
        f"{summary['dispatch_execution']['deferred_cost_ms']:.4f}"
    )
    print(
        "Dispatch execution memory relief MB: "
        f"{summary['dispatch_execution']['memory_relief_mb']:.4f}"
    )
    print(
        "Runtime calibration observed frame ms: "
        f"{summary['runtime_calibration']['total_observed_frame_cost_ms']:.4f}"
    )
    print(
        "Runtime calibration planned current-frame ms: "
        f"{summary['runtime_calibration']['total_planned_current_frame_cost_ms']:.4f}"
    )
    print(
        "Runtime calibration relief ms: "
        f"{summary['runtime_calibration']['total_planned_frame_relief_ms']:.4f}"
    )
    print(
        "Runtime calibration max guardband ms: "
        f"{summary['runtime_calibration']['max_guardband_ms']:.4f}"
    )
    print(f"Runtime manager profile: {summary['runtime_manager']['profile']}")
    print(
        "Runtime manager next frame budget ms: "
        f"{summary['runtime_manager']['next_frame_budget_ms']:.4f}"
    )
    print(
        "Runtime manager memory actions: "
        f"{summary['runtime_manager']['memory_action_count']}"
    )
    print(
        "Runtime control packet commands: "
        f"{summary['runtime_control_packet']['command_count']}"
    )
    print(
        "Runtime control packet active commands: "
        f"{summary['runtime_control_packet']['active_command_count']}"
    )
    print(
        "Runtime control packet memory commands: "
        f"{summary['runtime_control_packet']['memory_command_count']}"
    )
    print(
        "Runtime control state frame budgets: "
        f"{summary['runtime_control_state']['applied_frame_budget_count']}"
    )
    print(
        "Runtime control state memory actions: "
        f"{summary['runtime_control_state']['memory_action_count']}"
    )
    print(
        "Runtime gateway tick policy: "
        f"{summary['runtime_gateway_tick']['tick_policy']}"
    )
    print(
        "Runtime gateway tick steps: "
        f"{summary['runtime_gateway_tick']['step_count']}"
    )
    print(
        "Runtime gateway tick memory active steps: "
        f"{summary['runtime_gateway_tick']['memory_active_step_count']}"
    )
    print(
        "Runtime gateway cycle next action: "
        f"{summary['runtime_gateway_cycle']['next_cycle_action']}"
    )
    print(
        "Runtime gateway cycle drift risk: "
        f"{summary['runtime_gateway_cycle']['drift_risk']}"
    )
    print(
        "Runtime gateway cycle memory relief MB: "
        f"{summary['runtime_gateway_cycle']['memory_relief_applied_mb']:.4f}"
    )
    print(
        "Runtime gateway feedback action: "
        f"{summary['runtime_gateway_feedback']['feedback_action']}"
    )
    print(
        "Runtime gateway feedback convergence: "
        f"{summary['runtime_gateway_feedback']['convergence_status']}"
    )
    print(
        "Runtime gateway feedback protected gap ms: "
        f"{summary['runtime_gateway_feedback']['protected_gap_ms']:.4f}"
    )
    print(
        "Runtime policy update action: "
        f"{summary['runtime_policy_update']['policy_action']}"
    )
    print(
        "Runtime policy update next profile: "
        f"{summary['runtime_policy_update']['next_profile']}"
    )
    print(
        "Runtime policy update next frame budget ms: "
        f"{summary['runtime_policy_update']['next_frame_budget_ms']:.4f}"
    )
    print(
        "Runtime state accumulator cycles: "
        f"{summary['runtime_state_accumulator']['cycle_count']}"
    )
    print(
        "Runtime state accumulator active policies: "
        f"{summary['runtime_state_accumulator']['active_policy_count']}"
    )
    print(
        "Runtime state accumulator digest: "
        f"{summary['runtime_state_accumulator']['state_digest']}"
    )
    print(
        "Runtime state transition trend: "
        f"{summary['runtime_state_transition']['trend']}"
    )
    print(
        "Runtime state transition action: "
        f"{summary['runtime_state_transition']['transition_action']}"
    )
    print(
        "Runtime state transition pressure delta: "
        f"{summary['runtime_state_transition']['pressure_delta']:.4f}"
    )
    print(
        "Runtime supervisor directive action: "
        f"{summary['runtime_supervisor_directive']['directive_action']}"
    )
    print(
        "Runtime supervisor scheduler posture: "
        f"{summary['runtime_supervisor_directive']['scheduler_posture']}"
    )
    print(
        "Runtime supervisor memory posture: "
        f"{summary['runtime_supervisor_directive']['memory_posture']}"
    )
    print(
        "Runtime supervisor plan action: "
        f"{summary['runtime_supervisor_plan']['plan_action']}"
    )
    print(
        "Runtime supervisor plan commands: "
        f"{summary['runtime_supervisor_plan']['command_count']}"
    )
    print(
        "Runtime supervisor plan blocking commands: "
        f"{summary['runtime_supervisor_plan']['blocking_command_count']}"
    )
    print(
        "Runtime supervisor execution action: "
        f"{summary['runtime_supervisor_execution']['execution_action']}"
    )
    print(
        "Runtime supervisor execution would apply: "
        f"{summary['runtime_supervisor_execution']['would_apply_count']}"
    )
    print(
        "Runtime supervisor execution guard: "
        f"{summary['runtime_supervisor_execution']['execution_guard']}"
    )
    print(f"Decisions: {decision_count}")
    print(f"Failed responses: {failed_responses}")
    return 1 if failed_responses else 0


def run_runtime_run_adapter(args: argparse.Namespace) -> int:
    previous_state = (
        load_runtime_state_accumulator(args.state_in) if args.state_in else None
    )
    result = replay_adapter_event_stream(args.events, previous_state=previous_state)
    output_path = write_adapter_session(result, args.out)
    state_output_path = None
    if args.state_out:
        state_output_path = write_runtime_state_accumulator(
            result.runtime_state_accumulator,
            args.state_out,
        )
    snapshot = result.snapshot
    print(f"FluidGateway adapter session written: {output_path}")
    if previous_state is not None:
        print(f"Runtime previous state cycles: {previous_state.cycle_count}")
    if state_output_path is not None:
        print(f"Runtime state accumulator written: {state_output_path}")
    print(f"Events processed: {result.events_processed}")
    print(f"Frames observed: {len(result.frames)}")
    print(f"Operation events: {result.operation_events}")
    print(f"Decisions: {len(snapshot['decisions'])}")
    print(f"Policy actions: {len(result.policy_actions)}")
    print(f"Lifetime plan actions: {result.lifetime_plan.plan_action_count}")
    print(f"Scheduled steps: {result.schedule_plan.scheduled_step_count}")
    print(f"Enforcement commands: {result.enforcement_plan.command_count}")
    print(f"Live commands: {len(result.live_commands)}")
    print(f"Policy loop directives: {len(result.policy_loop_directives)}")
    print(f"Execution gates: {len(result.execution_gates)}")
    print(f"Admission operations: {result.admission_plan.operation_count}")
    print(
        "Admission hot-path cost ms: "
        f"{result.admission_plan.estimated_hot_path_cost_ms:.4f}"
    )
    print(
        "Admission avoided cost ms: "
        f"{result.admission_plan.estimated_avoided_cost_ms:.4f}"
    )
    print(
        "Efficiency relief cost ms: "
        f"{result.efficiency_ledger.relief_cost_ms:.4f}"
    )
    print(
        "Efficiency transfer relief MB: "
        f"{result.efficiency_ledger.transfer_relief_mb:.4f}"
    )
    print(f"Feedback actions: {result.feedback_plan.action_count}")
    if result.feedback_plan.frames:
        print(
            "Feedback next copy budget ms: "
            f"{result.feedback_plan.frames[0].suggested_copy_budget_ms:.4f}"
        )
    print(f"Actuation commands: {result.actuation_plan.command_count}")
    print(
        "Actuation copy budget ms: "
        f"{result.actuation_plan.total_copy_budget_ms:.4f}"
    )
    print(f"Memory transit hops: {result.memory_transit_map.hop_count}")
    print(
        "Memory avoided transfer MB: "
        f"{result.memory_transit_map.avoided_transfer_mb:.4f}"
    )
    print(f"Memory route directives: {result.memory_route_plan.directive_count}")
    print(
        "Memory route saved MB: "
        f"{result.memory_route_plan.estimated_saved_mb:.4f}"
    )
    print(f"Frame window slots: {result.frame_window_plan.slot_count}")
    print(f"Frame pre-frame slots: {result.frame_window_plan.pre_frame_count}")
    print(f"Execution packet commands: {result.execution_packet.command_count}")
    print(
        "Execution packet saved MB: "
        f"{result.execution_packet.estimated_saved_mb:.4f}"
    )
    print(
        "Execution simulated hot-path before ms: "
        f"{result.execution_simulation.hot_path_before_ms:.4f}"
    )
    print(
        "Execution simulated hot-path after ms: "
        f"{result.execution_simulation.hot_path_after_ms:.4f}"
    )
    print(f"Adaptive executor profile: {result.adaptive_executor_loop.profile}")
    print(
        "Adaptive executor over-budget frames: "
        f"{result.adaptive_executor_loop.over_budget_count}"
    )
    print(f"Budget envelope policy: {result.budget_envelope.next_frame_policy}")
    print(
        "Budget envelope constrained memory layers: "
        f"{result.budget_envelope.constrained_memory_count}"
    )
    print(
        "Budget arbitration deferred commands: "
        f"{result.budget_arbitration.deferred_count}"
    )
    print(
        "Budget arbitration memory actions: "
        f"{result.budget_arbitration.memory_action_count}"
    )
    print(f"Dispatch commands: {result.dispatch_plan.command_count}")
    print(f"Dispatch pre-frame commands: {result.dispatch_plan.pre_frame_count}")
    print(f"Dispatch hot-path commands: {result.dispatch_plan.hot_path_count}")
    print(
        "Dispatch next-frame commands: "
        f"{result.dispatch_plan.next_frame_count}"
    )
    print(
        "Dispatch execution current-frame ms: "
        f"{result.dispatch_execution.current_frame_cost_ms:.4f}"
    )
    print(
        "Dispatch execution pre-frame ms: "
        f"{result.dispatch_execution.pre_frame_cost_ms:.4f}"
    )
    print(
        "Dispatch execution deferred ms: "
        f"{result.dispatch_execution.deferred_cost_ms:.4f}"
    )
    print(
        "Dispatch execution memory relief MB: "
        f"{result.dispatch_execution.memory_relief_mb:.4f}"
    )
    print(
        "Runtime calibration observed frame ms: "
        f"{result.runtime_calibration.total_observed_frame_cost_ms:.4f}"
    )
    print(
        "Runtime calibration planned current-frame ms: "
        f"{result.runtime_calibration.total_planned_current_frame_cost_ms:.4f}"
    )
    print(
        "Runtime calibration relief ms: "
        f"{result.runtime_calibration.total_planned_frame_relief_ms:.4f}"
    )
    print(
        "Runtime calibration max guardband ms: "
        f"{result.runtime_calibration.max_guardband_ms:.4f}"
    )
    print(f"Runtime manager profile: {result.runtime_manager.profile}")
    print(
        "Runtime manager next frame budget ms: "
        f"{result.runtime_manager.next_frame_budget_ms:.4f}"
    )
    print(
        "Runtime manager memory actions: "
        f"{result.runtime_manager.memory_action_count}"
    )
    print(
        "Runtime control packet commands: "
        f"{result.runtime_control_packet.command_count}"
    )
    print(
        "Runtime control packet active commands: "
        f"{result.runtime_control_packet.active_command_count}"
    )
    print(
        "Runtime control packet memory commands: "
        f"{result.runtime_control_packet.memory_command_count}"
    )
    print(
        "Runtime control state frame budgets: "
        f"{result.runtime_control_state.applied_frame_budget_count}"
    )
    print(
        "Runtime control state memory actions: "
        f"{result.runtime_control_state.memory_action_count}"
    )
    print(
        "Runtime gateway tick policy: "
        f"{result.runtime_gateway_tick.tick_policy}"
    )
    print(
        "Runtime gateway tick steps: "
        f"{result.runtime_gateway_tick.step_count}"
    )
    print(
        "Runtime gateway tick memory active steps: "
        f"{result.runtime_gateway_tick.memory_active_step_count}"
    )
    print(
        "Runtime gateway cycle next action: "
        f"{result.runtime_gateway_cycle.next_cycle_action}"
    )
    print(
        "Runtime gateway cycle drift risk: "
        f"{result.runtime_gateway_cycle.drift_risk}"
    )
    print(
        "Runtime gateway cycle memory relief MB: "
        f"{result.runtime_gateway_cycle.memory_relief_applied_mb:.4f}"
    )
    print(
        "Runtime gateway feedback action: "
        f"{result.runtime_gateway_feedback.feedback_action}"
    )
    print(
        "Runtime gateway feedback convergence: "
        f"{result.runtime_gateway_feedback.convergence_status}"
    )
    print(
        "Runtime gateway feedback protected gap ms: "
        f"{result.runtime_gateway_feedback.protected_gap_ms:.4f}"
    )
    print(
        "Runtime policy update action: "
        f"{result.runtime_policy_update.policy_action}"
    )
    print(
        "Runtime policy update next profile: "
        f"{result.runtime_policy_update.next_profile}"
    )
    print(
        "Runtime policy update next frame budget ms: "
        f"{result.runtime_policy_update.next_frame_budget_ms:.4f}"
    )
    print(
        "Runtime state accumulator cycles: "
        f"{result.runtime_state_accumulator.cycle_count}"
    )
    print(
        "Runtime state accumulator active policies: "
        f"{result.runtime_state_accumulator.active_policy_count}"
    )
    print(
        "Runtime state accumulator digest: "
        f"{result.runtime_state_accumulator.state_digest}"
    )
    print(f"Runtime state transition trend: {result.runtime_state_transition.trend}")
    print(
        "Runtime state transition action: "
        f"{result.runtime_state_transition.transition_action}"
    )
    print(
        "Runtime state transition pressure delta: "
        f"{result.runtime_state_transition.pressure_delta:.4f}"
    )
    print(
        "Runtime supervisor directive action: "
        f"{result.runtime_supervisor_directive.directive_action}"
    )
    print(
        "Runtime supervisor scheduler posture: "
        f"{result.runtime_supervisor_directive.scheduler_posture}"
    )
    print(
        "Runtime supervisor memory posture: "
        f"{result.runtime_supervisor_directive.memory_posture}"
    )
    print(f"Runtime supervisor plan action: {result.runtime_supervisor_plan.plan_action}")
    print(
        "Runtime supervisor plan commands: "
        f"{result.runtime_supervisor_plan.command_count}"
    )
    print(
        "Runtime supervisor plan blocking commands: "
        f"{result.runtime_supervisor_plan.blocking_command_count}"
    )
    print(
        "Runtime supervisor execution action: "
        f"{result.runtime_supervisor_execution.execution_action}"
    )
    print(
        "Runtime supervisor execution would apply: "
        f"{result.runtime_supervisor_execution.would_apply_count}"
    )
    print(
        "Runtime supervisor execution guard: "
        f"{result.runtime_supervisor_execution.execution_guard}"
    )
    print(f"Live state open frame: {result.state_snapshot.open_frame}")
    print(f"Live state active resources: {result.state_snapshot.active_resource_count}")
    print(
        "Estimated critical-path reduction ms: "
        f"{result.schedule_plan.estimated_latency_reduction_ms:.4f}"
    )
    print(f"Released resources: {len(result.released_resources)}")
    print(f"Estimated saved ms: {snapshot['estimated_saved_ms']:.4f}")
    print(f"Estimated saved MB moved/allocated: {snapshot['estimated_saved_mb']:.4f}")
    return 0


def run_runtime_run_daemon(args: argparse.Namespace) -> int:
    state_path = normalized_json_path(args.state)
    output_path_arg = normalized_json_path(args.out)
    if state_path == output_path_arg:
        raise ValueError("Runtime daemon --state and --out must be different paths.")
    initial_state = load_runtime_state_accumulator(state_path)
    host_snapshot = collect_host_capability_snapshot()
    report = run_runtime_daemon(
        args.events,
        iterations=args.iterations,
        initial_state=initial_state,
        host_snapshot=host_snapshot,
    )
    output_path = write_runtime_daemon_report(report, args.out)
    state_output_path = write_runtime_state_accumulator(
        report.final_state,
        state_path,
    )

    print_runtime_daemon_summary(
        report=report,
        output_path=output_path,
        state_output_path=state_output_path,
        initial_state=initial_state,
    )
    return 0


def normalized_json_path(value: str) -> Path:
    path = Path(value)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    return path.resolve()


def normalized_jsonl_path(value: str) -> Path:
    path = Path(value)
    if path.suffix.lower() != ".jsonl":
        path = path.with_suffix(".jsonl")
    return path.resolve()


def run_runtime_serve_events(args: argparse.Namespace) -> int:
    print(f"FluidGateway runtime event server listening on {args.host}:{args.port}")
    if args.once:
        print("Mode: one connection then exit")
    serve_runtime_events(args.host, args.port, once=args.once)
    return 0


def controller_from_manifest(manifest: RuntimeManifest) -> FluidGatewayController:
    controller = FluidGatewayController()
    for resource in manifest.resources.values():
        controller.register_resource(
            resource_id=resource.id,
            kind=resource.kind,
            memory=resource.memory,
            size_mb=resource.size_mb,
            lifetime=resource.lifetime,
            aliases=resource.aliases,
        )
    for operation in manifest.operations:
        controller.submit_operation(
            operation_id=operation.id,
            operation_type=operation.type,
            source=operation.source,
            target=operation.target,
            queue=operation.queue,
            reason=operation.reason,
            cost_ms=operation.cost_ms,
            size_mb=operation.size_mb,
            frame=operation.frame,
            depends_on=operation.depends_on,
        )
    return controller


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"fluidgateway: error: {exc}", file=sys.stderr)
        return 1
