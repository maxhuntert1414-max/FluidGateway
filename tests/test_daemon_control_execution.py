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


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonControlExecutionTests(unittest.TestCase):
    def test_control_execution_runs_readonly_telemetry_dry_run(self):
        execution = build_control_execution(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = execution.to_dict()
        step = payload["steps"][0]

        self.assertEqual(payload["mode"], "runtime-daemon-control-execution-v0.54")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["execution_policy"], "execute-readonly-control")
        self.assertEqual(payload["step_count"], 1)
        self.assertEqual(payload["executed_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["readonly_execution_count"], 1)
        self.assertEqual(payload["telemetry_step_count"], 1)
        self.assertEqual(
            step["execution_status"],
            "executed-readonly-control-dry-run",
        )
        self.assertTrue(step["executed"])
        self.assertFalse(step["blocked"])
        self.assertEqual(step["effect"], "observe-control-surface-signal")

    def test_control_execution_blocks_native_ram_vram_surface(self):
        execution = build_control_execution(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = execution.to_dict()
        by_surface = {step["control_surface"]: step for step in payload["steps"]}

        self.assertEqual(payload["execution_policy"], "hold-native-control-surfaces")
        self.assertEqual(payload["step_count"], 2)
        self.assertEqual(payload["executed_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["native_blocked_execution_count"], 1)
        self.assertEqual(payload["ram_surface_count"], 1)
        self.assertEqual(payload["vram_surface_count"], 1)
        self.assertEqual(
            by_surface["ram-vram"]["execution_status"],
            "blocked-native-control-surface",
        )
        self.assertFalse(by_surface["ram-vram"]["executed"])
        self.assertTrue(by_surface["ram-vram"]["blocked"])
        self.assertIn("native-backend", by_surface["ram-vram"]["blocked_by"])

    def test_control_execution_runs_scheduler_advisory_dry_run(self):
        execution = build_control_execution(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = execution.to_dict()

        self.assertEqual(payload["execution_policy"], "execute-advisory-control")
        self.assertEqual(payload["executed_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["advisory_execution_count"], 1)
        self.assertEqual(payload["scheduler_step_count"], 1)
        self.assertEqual(
            payload["steps"][0]["execution_status"],
            "executed-advisory-control-dry-run",
        )

    def test_control_execution_preserves_safety_hold_dry_run(self):
        execution = build_control_execution(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-tightened-supervisor-commands",
            final_supervisor_action="escalate-supervisor-pressure",
            total_would_block_count=3,
        )
        payload = execution.to_dict()

        self.assertEqual(payload["execution_policy"], "execute-advisory-control")
        self.assertEqual(payload["executed_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["safety_step_count"], 1)
        self.assertEqual(
            payload["steps"][0]["execution_status"],
            "executed-advisory-control-dry-run",
        )


def build_control_execution(
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
    return dry_run_runtime_daemon_control_plan(control_plan)


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
