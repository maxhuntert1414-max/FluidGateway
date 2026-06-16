from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_actions import build_runtime_daemon_action_queue
from fluidgateway.daemon_arbitration import build_runtime_daemon_arbitration_plan
from fluidgateway.daemon_control import build_runtime_daemon_control_plan
from fluidgateway.daemon_control_execution import dry_run_runtime_daemon_control_plan
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.daemon_execution import dry_run_runtime_daemon_action_queue
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot
from fluidgateway.native_backend import build_runtime_native_backend_preflight
from fluidgateway.native_backend_manifest import (
    build_runtime_native_backend_manifest,
)
from fluidgateway.native_backend_probe import run_runtime_native_backend_probe


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeNativeBackendProbeTests(unittest.TestCase):
    def test_probe_executes_readonly_host_snapshot_signals(self):
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        probe = run_runtime_native_backend_probe(
            manifest=manifest,
            host_snapshot=build_balanced_host(),
        )
        payload = probe.to_dict()
        step = payload["steps"][0]

        self.assertEqual(payload["mode"], "runtime-native-backend-probe-v0.56")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "read-only-observe")
        self.assertEqual(payload["probe_policy"], "readonly-probe-executed")
        self.assertEqual(payload["probed_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["readonly_probe_count"], 1)
        self.assertGreaterEqual(payload["host_signal_count"], 10)
        self.assertEqual(payload["memory_signal_count"], 4)
        self.assertEqual(payload["gpu_signal_count"], 3)
        self.assertEqual(
            step["probe_status"],
            "executed-readonly-host-snapshot-probe",
        )
        self.assertEqual(step["probe_action"], "bind-host-snapshot-signals")
        self.assertEqual(step["signals"]["cpu_logical_count"], 16)
        self.assertEqual(step["signals"]["total_ram_mb"], 32768)
        self.assertEqual(step["signals"]["total_reported_vram_mb"], 8192)

    def test_probe_blocks_readonly_without_host_snapshot(self):
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        probe = run_runtime_native_backend_probe(
            manifest=manifest,
            host_snapshot=None,
        )
        payload = probe.to_dict()
        step = payload["steps"][0]

        self.assertEqual(
            payload["probe_policy"],
            "hold-readonly-probe-for-host-snapshot",
        )
        self.assertEqual(payload["probed_count"], 0)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["missing_host_snapshot_count"], 1)
        self.assertEqual(step["probe_status"], "blocked-missing-host-snapshot")
        self.assertEqual(step["blocked_by"], ["host-snapshot"])
        self.assertFalse(step["probed"])
        self.assertTrue(step["blocked"])

    def test_probe_holds_native_ram_vram_backend(self):
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        probe = run_runtime_native_backend_probe(
            manifest=manifest,
            host_snapshot=build_balanced_host(),
        )
        payload = probe.to_dict()
        by_surface = {step["control_surface"]: step for step in payload["steps"]}
        memory_step = by_surface["ram-vram"]

        self.assertEqual(payload["probe_policy"], "probe-safe-and-hold-native")
        self.assertEqual(payload["step_count"], 2)
        self.assertEqual(payload["probed_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["native_blocked_probe_count"], 1)
        self.assertEqual(
            memory_step["probe_status"],
            "blocked-native-backend-probe",
        )
        self.assertEqual(memory_step["probe_action"], "hold-native-backend-probe")
        self.assertIn("native-backend", memory_step["blocked_by"])
        self.assertFalse(memory_step["would_modify_system"])

    def test_probe_executes_scheduler_advisory_contract(self):
        host = build_balanced_host()
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=host,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        probe = run_runtime_native_backend_probe(
            manifest=manifest,
            host_snapshot=host,
        )
        payload = probe.to_dict()
        step = payload["steps"][0]

        self.assertEqual(payload["probe_policy"], "advisory-probe-executed")
        self.assertEqual(payload["probed_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["advisory_probe_count"], 1)
        self.assertEqual(step["probe_scope"], "daemon-contract")
        self.assertEqual(step["probe_status"], "executed-advisory-contract-probe")
        self.assertEqual(step["signals"]["manifest_policy"], "advisory-backend-ready")
        self.assertEqual(step["signals"]["host_profile"], "balanced-gaming-host")


def build_manifest(
    events_path: Path,
    host_snapshot,
    final_execution_action: str,
    final_supervisor_action: str,
    total_would_block_count: int,
):
    result = replay_adapter_event_stream(events_path)
    decision = build_runtime_daemon_decision_plan(
        final_state=result.runtime_state_accumulator,
        host_snapshot=host_snapshot,
        final_execution_action=final_execution_action,
        final_supervisor_action=final_supervisor_action,
        total_would_block_count=total_would_block_count,
    )
    queue = build_runtime_daemon_action_queue(decision)
    action_execution = dry_run_runtime_daemon_action_queue(queue)
    preflight = build_runtime_native_backend_preflight(queue, action_execution)
    arbitration = build_runtime_daemon_arbitration_plan(
        final_state=result.runtime_state_accumulator,
        decision_plan=decision,
        action_execution=action_execution,
        native_backend_preflight=preflight,
    )
    control_plan = build_runtime_daemon_control_plan(
        final_state=result.runtime_state_accumulator,
        arbitration_plan=arbitration,
        native_backend_preflight=preflight,
    )
    control_execution = dry_run_runtime_daemon_control_plan(control_plan)
    return build_runtime_native_backend_manifest(
        control_execution=control_execution,
        native_backend_preflight=preflight,
        host_snapshot=host_snapshot,
    )


def build_balanced_host():
    return build_host_capability_snapshot(
        os_name="Windows",
        os_release="11",
        os_version="test",
        machine="AMD64",
        processor="test-cpu",
        python_version="3.13.0",
        cpu_logical_count=16,
        total_ram_mb=32768,
        available_ram_mb=24576,
        gpus=[
            HostGpuCapability(
                name="Test GPU",
                adapter_ram_mb=8192,
                driver_version="1.2.3",
                source="test",
            )
        ],
    )


if __name__ == "__main__":
    unittest.main()
