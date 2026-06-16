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


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeNativeBackendManifestTests(unittest.TestCase):
    def test_manifest_marks_readonly_telemetry_backend_ready(self):
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = manifest.to_dict()
        entry = payload["entries"][0]

        self.assertEqual(payload["mode"], "runtime-native-backend-manifest-v0.55")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["manifest_policy"], "readonly-probe-ready")
        self.assertEqual(payload["entry_count"], 1)
        self.assertEqual(payload["ready_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["readonly_ready_count"], 1)
        self.assertEqual(entry["backend_id"], "python-stdlib-readonly-probe")
        self.assertEqual(entry["load_status"], "loaded-python-stdlib-readonly")
        self.assertEqual(
            entry["capability_status"],
            "available-readonly-control-dry-run",
        )
        self.assertFalse(entry["promotion_allowed"])

    def test_manifest_blocks_ram_vram_native_backend_load(self):
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = manifest.to_dict()
        by_surface = {entry["control_surface"]: entry for entry in payload["entries"]}
        memory_entry = by_surface["ram-vram"]

        self.assertEqual(payload["manifest_policy"], "hold-native-backend-load")
        self.assertEqual(payload["entry_count"], 2)
        self.assertEqual(payload["ready_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["native_blocked_count"], 1)
        self.assertEqual(payload["privileged_blocked_count"], 1)
        self.assertEqual(payload["ram_surface_count"], 1)
        self.assertEqual(payload["vram_surface_count"], 1)
        self.assertEqual(memory_entry["backend_id"], "native-host-control-backend")
        self.assertEqual(
            memory_entry["capability_status"],
            "blocked-privileged-native-backend-required",
        )
        self.assertEqual(
            memory_entry["load_status"],
            "not-loaded-native-backend-missing",
        )
        self.assertTrue(memory_entry["requires_native_backend"])
        self.assertTrue(memory_entry["requires_privilege"])
        self.assertTrue(memory_entry["requires_safety_review"])
        self.assertFalse(memory_entry["promotion_allowed"])
        self.assertIn("native-backend", memory_entry["blocked_by"])

    def test_manifest_marks_scheduler_advisory_backend_ready(self):
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = manifest.to_dict()
        entry = payload["entries"][0]

        self.assertEqual(payload["manifest_policy"], "advisory-backend-ready")
        self.assertTrue(payload["host_snapshot_loaded"])
        self.assertEqual(payload["host_profile"], "balanced-gaming-host")
        self.assertEqual(payload["ready_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["advisory_ready_count"], 1)
        self.assertEqual(payload["scheduler_surface_count"], 1)
        self.assertEqual(entry["backend_id"], "daemon-advisory-loop")
        self.assertEqual(entry["load_status"], "loaded-daemon-advisory-loop")
        self.assertEqual(
            entry["capability_status"],
            "available-advisory-control-dry-run",
        )


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
