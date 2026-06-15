from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_actions import build_runtime_daemon_action_queue
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonActionQueueTests(unittest.TestCase):
    def test_action_queue_allows_readonly_telemetry_and_blocks_native_memory(self):
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
        queue = build_runtime_daemon_action_queue(decision)
        payload = queue.to_dict()
        by_domain = {action["domain"]: action for action in payload["actions"]}

        self.assertEqual(payload["mode"], "runtime-daemon-action-queue-v0.49")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["queue_policy"], "queue-native-backend-work")
        self.assertEqual(payload["queued_action_count"], 2)
        self.assertEqual(payload["would_apply_count"], 1)
        self.assertEqual(payload["blocked_action_count"], 1)
        self.assertEqual(payload["native_backend_required_count"], 1)
        self.assertEqual(payload["privileged_action_count"], 1)
        self.assertEqual(by_domain["telemetry"]["dry_run_status"], "would-apply-readonly")
        self.assertFalse(by_domain["telemetry"]["requires_native_backend"])
        self.assertEqual(
            by_domain["memory"]["dry_run_status"],
            "blocked-native-backend-required",
        )
        self.assertTrue(by_domain["memory"]["requires_native_backend"])
        self.assertEqual(
            by_domain["memory"]["safety_boundary"],
            "blocked-before-system-mutation",
        )

    def test_action_queue_continues_advisory_supervisor_loop(self):
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
        payload = build_runtime_daemon_action_queue(decision).to_dict()

        self.assertEqual(payload["queue_policy"], "continue-advisory-loop")
        self.assertEqual(payload["scheduler_action_count"], 1)
        self.assertEqual(payload["blocked_action_count"], 0)
        self.assertEqual(payload["actions"][0]["backend"], "advisory-supervisor-loop")
        self.assertEqual(payload["actions"][0]["operation"], "continue-supervisor-loop")
        self.assertEqual(payload["actions"][0]["dry_run_status"], "would-apply-advisory")

    def test_action_queue_holds_native_promotion_for_safety_actions(self):
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
        payload = build_runtime_daemon_action_queue(decision).to_dict()

        self.assertEqual(payload["queue_policy"], "hold-native-promotion")
        self.assertEqual(payload["safety_action_count"], 1)
        self.assertEqual(payload["blocked_action_count"], 0)
        self.assertEqual(payload["actions"][0]["backend"], "safety-gate")
        self.assertEqual(payload["actions"][0]["operation"], "hold-blocking-commands")
        self.assertFalse(payload["actions"][0]["would_modify_system"])


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
