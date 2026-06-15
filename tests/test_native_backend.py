from __future__ import annotations

import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.daemon_actions import build_runtime_daemon_action_queue
from fluidgateway.daemon_decision import build_runtime_daemon_decision_plan
from fluidgateway.daemon_execution import dry_run_runtime_daemon_action_queue
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot
from fluidgateway.native_backend import build_runtime_native_backend_preflight


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeNativeBackendPreflightTests(unittest.TestCase):
    def test_preflight_passes_readonly_telemetry_without_native_promotion(self):
        preflight = build_preflight(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = preflight.to_dict()

        self.assertEqual(
            payload["mode"],
            "runtime-native-backend-preflight-v0.51",
        )
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertFalse(payload["native_promotion_allowed"])
        self.assertEqual(payload["backend_policy"], "advisory-preflight-passed")
        self.assertEqual(payload["requirement_count"], 1)
        self.assertEqual(payload["advisory_safe_count"], 1)
        self.assertEqual(payload["blocked_requirement_count"], 0)
        self.assertEqual(payload["missing_native_backend_count"], 0)
        self.assertEqual(
            payload["capabilities"][0]["capability_status"],
            "available-readonly-dry-run",
        )
        self.assertEqual(
            payload["requirements"][0]["preflight_status"],
            "passed-readonly-dry-run",
        )
        self.assertFalse(payload["requirements"][0]["can_promote_to_native"])

    def test_preflight_blocks_native_memory_backend_requirements(self):
        preflight = build_preflight(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=None,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        payload = preflight.to_dict()
        by_domain = {
            requirement["domain"]: requirement
            for requirement in payload["requirements"]
        }

        self.assertEqual(
            payload["backend_policy"],
            "hold-native-backend-promotion",
        )
        self.assertFalse(payload["native_promotion_allowed"])
        self.assertEqual(payload["requirement_count"], 2)
        self.assertEqual(payload["advisory_safe_count"], 1)
        self.assertEqual(payload["blocked_requirement_count"], 1)
        self.assertEqual(payload["missing_native_backend_count"], 1)
        self.assertEqual(payload["privilege_required_count"], 1)
        self.assertEqual(payload["safety_review_required_count"], 1)
        self.assertEqual(payload["memory_requirement_count"], 1)
        self.assertEqual(
            by_domain["memory"]["preflight_status"],
            "blocked-privileged-native-backend-required",
        )
        self.assertEqual(
            by_domain["memory"]["blocked_by"],
            ["action-queue", "native-backend", "privilege", "safety-review"],
        )
        self.assertFalse(by_domain["memory"]["can_execute_now"])
        self.assertFalse(by_domain["memory"]["can_promote_to_native"])

    def test_preflight_passes_scheduler_advisory_loop(self):
        preflight = build_preflight(
            events_path=FIXTURES / "adapter_state_query_events.jsonl",
            host_snapshot=build_balanced_host(),
            final_execution_action="dry-run-relaxed-supervisor-commands",
            final_supervisor_action="relax-supervisor-pressure",
            total_would_block_count=0,
        )
        payload = preflight.to_dict()

        self.assertEqual(payload["backend_policy"], "advisory-preflight-passed")
        self.assertEqual(payload["scheduler_requirement_count"], 1)
        self.assertEqual(payload["advisory_safe_count"], 1)
        self.assertEqual(payload["blocked_requirement_count"], 0)
        self.assertEqual(
            payload["requirements"][0]["preflight_status"],
            "passed-advisory-dry-run",
        )
        self.assertEqual(
            payload["capabilities"][0]["required_interface"],
            "daemon-advisory-loop",
        )


def build_preflight(
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
    return build_runtime_native_backend_preflight(queue, execution)


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
