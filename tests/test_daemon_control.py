from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_actions import build_runtime_daemon_action_queue
from fluidgateway.daemon_arbitration import build_runtime_daemon_arbitration_plan
from fluidgateway.daemon_control import build_runtime_daemon_control_plan
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.daemon_execution import dry_run_runtime_daemon_action_queue
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot
from fluidgateway.native_backend import build_runtime_native_backend_preflight


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonControlTests(unittest.TestCase):
    def test_control_plan_collects_readonly_telemetry_before_control(self):
        plan = build_control_plan(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = plan.to_dict()
        intent = payload["intents"][0]

        self.assertEqual(payload["mode"], "runtime-daemon-control-plan-v0.53")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["control_policy"], "collect-evidence-before-control")
        self.assertEqual(payload["intent_count"], 1)
        self.assertEqual(payload["ready_intent_count"], 1)
        self.assertEqual(payload["blocked_intent_count"], 0)
        self.assertEqual(payload["readonly_intent_count"], 1)
        self.assertEqual(payload["telemetry_surface_count"], 1)
        self.assertEqual(intent["control_surface"], "telemetry")
        self.assertEqual(intent["backend_requirement"], "python-stdlib-readonly-probe")
        self.assertEqual(intent["control_status"], "ready-readonly")
        self.assertEqual(intent["control_action"], "collect-control-surface-evidence")

    def test_control_plan_blocks_ram_vram_native_surface(self):
        plan = build_control_plan(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = plan.to_dict()
        by_domain = {intent["domain"]: intent for intent in payload["intents"]}

        self.assertEqual(payload["control_policy"], "hold-native-control-surfaces")
        self.assertEqual(payload["intent_count"], 2)
        self.assertEqual(payload["ready_intent_count"], 1)
        self.assertEqual(payload["blocked_intent_count"], 1)
        self.assertEqual(payload["native_blocked_intent_count"], 1)
        self.assertEqual(payload["ram_surface_count"], 1)
        self.assertEqual(payload["vram_surface_count"], 1)
        self.assertEqual(by_domain["memory"]["control_surface"], "ram-vram")
        self.assertEqual(
            by_domain["memory"]["backend_requirement"],
            "native-host-control-backend",
        )
        self.assertEqual(
            by_domain["memory"]["control_status"],
            "blocked-native-preflight",
        )
        self.assertEqual(by_domain["memory"]["control_action"], "hold-control-surface")
        self.assertIn("native-backend", by_domain["memory"]["blocked_by"])

    def test_control_plan_maintains_scheduler_advisory_loop(self):
        plan = build_control_plan(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = plan.to_dict()
        intent = payload["intents"][0]

        self.assertEqual(payload["control_policy"], "maintain-advisory-control-loop")
        self.assertEqual(payload["scheduler_surface_count"], 1)
        self.assertEqual(payload["advisory_intent_count"], 1)
        self.assertEqual(payload["blocked_intent_count"], 0)
        self.assertEqual(intent["control_surface"], "scheduler")
        self.assertEqual(intent["control_status"], "ready-advisory")
        self.assertEqual(intent["control_action"], "maintain-advisory-scheduler-loop")

    def test_control_plan_preserves_safety_hold(self):
        plan = build_control_plan(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-tightened-supervisor-commands",
            final_supervisor_action="escalate-supervisor-pressure",
            total_would_block_count=3,
        )
        payload = plan.to_dict()
        intent = payload["intents"][0]

        self.assertEqual(payload["control_policy"], "safety-control-hold")
        self.assertEqual(payload["safety_surface_count"], 1)
        self.assertEqual(payload["ready_intent_count"], 1)
        self.assertEqual(payload["blocked_intent_count"], 0)
        self.assertEqual(intent["control_surface"], "safety")
        self.assertEqual(intent["control_status"], "ready-advisory")
        self.assertEqual(intent["control_action"], "preserve-safety-hold")


def build_control_plan(
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
    arbitration = build_runtime_daemon_arbitration_plan(
        final_state=result.runtime_state_accumulator,
        decision_plan=decision,
        action_execution=execution,
        native_backend_preflight=preflight,
    )
    return build_runtime_daemon_control_plan(
        final_state=result.runtime_state_accumulator,
        arbitration_plan=arbitration,
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
