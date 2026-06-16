from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_actions import build_runtime_daemon_action_queue
from fluidgateway.daemon_arbitration import build_runtime_daemon_arbitration_plan
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.daemon_execution import dry_run_runtime_daemon_action_queue
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot
from fluidgateway.native_backend import build_runtime_native_backend_preflight


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonArbitrationTests(unittest.TestCase):
    def test_arbitration_holds_native_memory_and_prioritizes_telemetry(self):
        plan = build_arbitration(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = plan.to_dict()
        by_domain = {lane["domain"]: lane for lane in payload["lanes"]}

        self.assertEqual(
            payload["mode"],
            "runtime-daemon-arbitration-plan-v0.52",
        )
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(
            payload["arbitration_policy"],
            "hold-native-and-prioritize-telemetry",
        )
        self.assertGreater(payload["pressure_score"], 0)
        self.assertEqual(payload["lane_count"], 2)
        self.assertEqual(payload["executable_lane_count"], 1)
        self.assertEqual(payload["blocked_lane_count"], 1)
        self.assertEqual(payload["native_promotable_lane_count"], 0)
        self.assertEqual(payload["telemetry_lane_count"], 1)
        self.assertEqual(payload["memory_lane_count"], 1)
        self.assertEqual(payload["lanes"][0]["domain"], "telemetry")
        self.assertEqual(
            by_domain["memory"]["arbitration_action"],
            "hold-native-backend",
        )
        self.assertEqual(
            by_domain["memory"]["arbitration_status"],
            "blocked-by-native-preflight",
        )
        self.assertIn("native-backend", by_domain["memory"]["blocked_by"])

    def test_arbitration_continues_scheduler_advisory_loop(self):
        plan = build_arbitration(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = plan.to_dict()

        self.assertEqual(
            payload["arbitration_policy"],
            "continue-supervisor-loop",
        )
        self.assertEqual(payload["scheduler_lane_count"], 1)
        self.assertEqual(payload["blocked_lane_count"], 0)
        self.assertEqual(payload["native_promotable_lane_count"], 0)
        self.assertEqual(
            payload["lanes"][0]["arbitration_action"],
            "continue-advisory-supervisor-loop",
        )
        self.assertEqual(payload["lanes"][0]["arbitration_status"], "advisory-ready")

    def test_arbitration_uses_safety_first_policy(self):
        plan = build_arbitration(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-tightened-supervisor-commands",
            final_supervisor_action="escalate-supervisor-pressure",
            total_would_block_count=3,
        )
        payload = plan.to_dict()

        self.assertEqual(payload["arbitration_policy"], "safety-first")
        self.assertEqual(payload["safety_lane_count"], 1)
        self.assertEqual(payload["blocked_lane_count"], 0)
        self.assertEqual(payload["lanes"][0]["domain"], "safety")
        self.assertEqual(
            payload["lanes"][0]["arbitration_action"],
            "hold-supervisor-promotion",
        )


def build_arbitration(
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
    execution = dry_run_runtime_daemon_action_queue(queue)
    preflight = build_runtime_native_backend_preflight(queue, execution)
    return build_runtime_daemon_arbitration_plan(
        final_state=result.runtime_state_accumulator,
        decision_plan=decision,
        action_execution=execution,
        native_backend_preflight=preflight,
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
