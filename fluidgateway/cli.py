from __future__ import annotations

import argparse
import sys

from . import __version__
from .analyzer import analyze_trace
from .parser import parse_presentmon_csv
from .report import write_report


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
    return parser


def run_analyze(args: argparse.Namespace) -> int:
    trace = parse_presentmon_csv(args.presentmon)
    report = analyze_trace(trace)
    html_path, json_path = write_report(report, args.out)
    print(f"FluidGateway report written: {html_path}")
    print(f"Structured report written: {json_path}")
    print(f"Findings: {len(report.findings)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"fluidgateway: error: {exc}", file=sys.stderr)
        return 1
