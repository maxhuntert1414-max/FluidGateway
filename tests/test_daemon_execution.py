from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_actions import build_runtime_daemon_action_queue
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.daemon_execution import dry_run_runtime_daemon_action_queue
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonActionExecutionTests(unittest.TestCase):
    def test_action_execution_runs_readonly_telemetry_in_dry_run(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        decision = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        execution = dry_run_runtime_daemon_action_queue(
            build_runtime_daemon_action_queue(decision)
        )
        payload = execution.to_dict()

        self.assertEqual(
            payload["mode"],
            "runtime-daemon-action-execution-v0.50",
        )
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["execution_policy"], "execute-readonly-telemetry")
        self.assertEqual(payload["action_count"], 1)
        self.assertEqual(payload["executed_readonly_count"], 1)
        self.assertEqual(payload["executed_advisory_count"], 0)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(payload["telemetry_execution_count"], 1)
        self.assertEqual(
            payload["results"][0]["execution_status"],
            "executed-readonly-dry-run",
        )
        self.assertEqual(
            payload["results"][0]["observed_signal"],
            "updated-host-snapshot",
        )

    def test_action_execution_blocks_native_memory_before_system_mutation(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        decision = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = dry_run_runtime_daemon_action_queue(
            build_runtime_daemon_action_queue(decision)
        ).to_dict()
        by_domain = {result["domain"]: result for result in payload["results"]}

        self.assertEqual(payload["execution_policy"], "hold-native-backend-actions")
        self.assertEqual(payload["executed_readonly_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["blocked_native_count"], 1)
        self.assertEqual(payload["blocked_privileged_count"], 1)
        self.assertEqual(payload["memory_execution_count"], 0)
        self.assertEqual(
            by_domain["memory"]["execution_status"],
            "blocked-privileged-native-backend-required",
        )
        self.assertTrue(by_domain["memory"]["blocked"])
        self.assertFalse(by_domain["memory"]["would_modify_system"])
        self.assertEqual(
            by_domain["memory"]["safety_boundary"],
            "blocked-before-system-mutation",
        )

    def test_action_execution_runs_scheduler_advisory_loop(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        decision = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = dry_run_runtime_daemon_action_queue(
            build_runtime_daemon_action_queue(decision)
        ).to_dict()

        self.assertEqual(payload["execution_policy"], "execute-advisory-loop")
        self.assertEqual(payload["executed_advisory_count"], 1)
        self.assertEqual(payload["scheduler_execution_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(
            payload["results"][0]["execution_status"],
            "executed-advisory-dry-run",
        )

    def test_action_execution_runs_safety_hold_as_advisory_result(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        decision = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-tightened-supervisor-commands",
            final_supervisor_action="escalate-supervisor-pressure",
            total_would_block_count=3,
        )
        payload = dry_run_runtime_daemon_action_queue(
            build_runtime_daemon_action_queue(decision)
        ).to_dict()

        self.assertEqual(payload["execution_policy"], "execute-advisory-loop")
        self.assertEqual(payload["executed_advisory_count"], 1)
        self.assertEqual(payload["safety_execution_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(
            payload["results"][0]["execution_status"],
            "executed-advisory-dry-run",
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
