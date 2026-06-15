from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonDecisionPlanTests(unittest.TestCase):
    def test_daemon_decision_allows_supervisor_loop_on_balanced_host(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        host = build_balanced_host()

        plan = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=host,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = plan.to_dict()

        self.assertEqual(payload["mode"], "runtime-daemon-decision-plan-v0.48")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(
            payload["decision_action"],
            "continue-host-aware-supervisor-loop",
        )
        self.assertEqual(payload["risk_level"], "medium")
        self.assertEqual(payload["confidence"], "high")
        self.assertEqual(payload["scheduler_action_count"], 1)
        self.assertEqual(payload["memory_action_count"], 0)
        self.assertEqual(payload["telemetry_action_count"], 0)
        self.assertEqual(
            payload["actions"][0]["action"],
            "allow-daemon-supervisor-loop",
        )

    def test_daemon_decision_tightens_memory_observation_under_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )

        plan = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = plan.to_dict()

        self.assertEqual(
            payload["decision_action"],
            "tighten-daemon-memory-observation",
        )
        self.assertEqual(payload["risk_level"], "high")
        self.assertEqual(payload["confidence"], "low")
        self.assertEqual(payload["memory_action_count"], 1)
        self.assertEqual(payload["telemetry_action_count"], 1)
        self.assertEqual(
            {action["action"] for action in payload["actions"]},
            {
                "collect-host-telemetry",
                "tighten-memory-residency-observation",
            },
        )

    def test_daemon_decision_holds_blocking_supervisor_commands(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )

        plan = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-tightened-supervisor-commands",
            final_supervisor_action="escalate-supervisor-pressure",
            total_would_block_count=3,
        )
        payload = plan.to_dict()

        self.assertEqual(
            payload["decision_action"],
            "hold-daemon-supervisor-promotion",
        )
        self.assertEqual(payload["risk_level"], "high")
        self.assertEqual(payload["safety_action_count"], 1)
        self.assertEqual(payload["actions"][-1]["domain"], "safety")
        self.assertEqual(
            payload["actions"][-1]["action"],
            "hold-blocking-supervisor-commands",
        )

    def test_daemon_decision_requests_gpu_telemetry_for_unknown_gpu(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        host = build_host_capability_snapshot(
            os_name="Windows",
            os_release="11",
            os_version="test",
            machine="AMD64",
            processor="test-cpu",
            python_version="3.13.0",
            cpu_logical_count=8,
            total_ram_mb=16000,
            available_ram_mb=12000,
            gpus=[],
        )

        plan = build_runtime_daemon_decision_plan(
            final_state=result.runtime_state_accumulator,
            host_snapshot=host,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = plan.to_dict()

        self.assertEqual(payload["decision_action"], "preserve-daemon-loop")
        self.assertEqual(payload["gpu_action_count"], 1)
        self.assertEqual(
            payload["actions"][0]["action"],
            "collect-gpu-telemetry-before-gpu-specific-actions",
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
