from __future__ import annotations

from pathlib import Path

from .daemon import RuntimeDaemonReport
from .state_accumulator import RuntimeStateAccumulator


def print_runtime_daemon_summary(
    *,
    report: RuntimeDaemonReport,
    output_path: Path,
    state_output_path: Path,
    initial_state: RuntimeStateAccumulator | None,
) -> None:
    print(f"FluidGateway runtime daemon dry-run written: {output_path}")
    if initial_state is not None:
        print(f"Runtime daemon previous state cycles: {initial_state.cycle_count}")
    print(f"Runtime daemon state written: {state_output_path}")
    for label, attr in daemon_summary_fields():
        print(f"{label}: {getattr(report, attr)}")


def daemon_summary_fields() -> tuple[tuple[str, str], ...]:
    return (
        ("Daemon cycles", "cycle_count"),
        ("Daemon event streams", "events_stream_count"),
        ("Daemon final cycle count", "final_cycle_count"),
        ("Daemon final execution action", "final_execution_action"),
        ("Daemon final supervisor action", "final_supervisor_action"),
        ("Daemon host profile", "host_profile"),
        ("Daemon host manager hint", "host_manager_hint"),
        ("Daemon decision action", "daemon_decision_action"),
        ("Daemon decision risk", "daemon_decision_risk_level"),
        ("Daemon action queue policy", "daemon_action_queue_policy"),
        ("Daemon action blocked commands", "daemon_action_blocked_count"),
        ("Daemon action execution policy", "daemon_action_execution_policy"),
        ("Daemon action execution blocked", "daemon_action_execution_blocked_count"),
        ("Native backend policy", "native_backend_policy"),
        ("Native backend blocked requirements", "native_backend_blocked_count"),
        ("Native promotion allowed", "native_promotion_allowed"),
        ("Daemon arbitration policy", "daemon_arbitration_policy"),
        ("Daemon arbitration blocked lanes", "daemon_arbitration_blocked_count"),
        ("Daemon arbitration pressure score", "daemon_arbitration_pressure_score"),
        ("Daemon control policy", "daemon_control_policy"),
        ("Daemon control ready intents", "daemon_control_ready_count"),
        ("Daemon control blocked intents", "daemon_control_blocked_count"),
        ("Daemon control execution policy", "daemon_control_execution_policy"),
        (
            "Daemon control execution executed",
            "daemon_control_execution_executed_count",
        ),
        ("Daemon control execution blocked", "daemon_control_execution_blocked_count"),
        ("Native backend manifest policy", "native_backend_manifest_policy"),
        ("Native backend manifest ready", "native_backend_manifest_ready_count"),
        ("Native backend manifest blocked", "native_backend_manifest_blocked_count"),
        ("Native backend probe policy", "native_backend_probe_policy"),
        ("Native backend probe probed", "native_backend_probe_probed_count"),
        ("Native backend probe blocked", "native_backend_probe_blocked_count"),
        ("Daemon would apply commands", "total_would_apply_count"),
        ("Daemon would block commands", "total_would_block_count"),
        ("Daemon guard", "execution_guard"),
    )
