from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analyzer import analyze_trace
from .daemon import RuntimeDaemonReport, run_runtime_daemon
from .host import HostCapabilitySnapshot
from .parser import parse_presentmon_csv
from .presentmon_ledger import (
    PresentMonOperationalLedger,
    build_presentmon_operational_ledger,
)
from .presentmon_runtime import (
    PresentMonRuntimeEventStream,
    build_presentmon_runtime_event_stream,
    write_presentmon_runtime_events,
)
from .state_accumulator import RuntimeStateAccumulator


PRESENTMON_DAEMON_RUN_MODE = "presentmon-daemon-run-v0.61"


@dataclass(frozen=True)
class PresentMonDaemonRun:
    mode: str
    presentmon_path: str
    events_path: Path
    report: RuntimeDaemonReport
    event_stream: PresentMonRuntimeEventStream
    operational_ledger: PresentMonOperationalLedger


def run_presentmon_daemon(
    *,
    presentmon_path: str | Path,
    events_output_path: str | Path,
    initial_state: RuntimeStateAccumulator | None = None,
    host_snapshot: HostCapabilitySnapshot | None = None,
) -> PresentMonDaemonRun:
    trace = parse_presentmon_csv(presentmon_path)
    analysis = analyze_trace(trace)
    event_stream = build_presentmon_runtime_event_stream(analysis)
    events_path = write_presentmon_runtime_events(
        event_stream,
        events_output_path,
    )
    report = run_runtime_daemon(
        [events_path],
        initial_state=initial_state,
        host_snapshot=host_snapshot,
    )
    operational_ledger = build_presentmon_operational_ledger(
        presentmon_path=presentmon_path,
        events_path=events_path,
        event_stream=event_stream,
        daemon_report=report,
    )
    return PresentMonDaemonRun(
        mode=PRESENTMON_DAEMON_RUN_MODE,
        presentmon_path=str(presentmon_path),
        events_path=events_path,
        report=report,
        event_stream=event_stream,
        operational_ledger=operational_ledger,
    )
