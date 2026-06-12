from __future__ import annotations

import argparse
import sys

from . import __version__
from .analyzer import analyze_trace
from .control import FluidGatewayController
from .events import replay_event_stream, write_event_replay
from .parser import parse_presentmon_csv
from .report import write_report
from .report import write_management_plan
from .runtime import RuntimeManifest, load_manifest, optimize_manifest, write_runtime_plan
from .server import serve_runtime_events
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
