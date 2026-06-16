from __future__ import annotations

import unittest

from fluidgateway.native_backend_probe import run_runtime_native_backend_probe
from fluidgateway.native_backend_readiness import (
    assess_runtime_native_backend_readiness,
)
from tests.test_native_backend_probe import (
    FIXTURES,
    build_balanced_host,
    build_manifest,
)


class RuntimeNativeBackendReadinessTests(unittest.TestCase):
    def test_readiness_accepts_complete_readonly_observation(self):
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
        readiness = assess_runtime_native_backend_readiness(probe)
        payload = readiness.to_dict()
        assessment = payload["assessments"][0]

        self.assertEqual(payload["mode"], "runtime-native-backend-readiness-v0.57")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["readiness_policy"], "readonly-evidence-ready")
        self.assertFalse(payload["native_action_allowed"])
        self.assertEqual(payload["ready_observation_count"], 1)
        self.assertEqual(payload["needs_evidence_count"], 0)
        self.assertEqual(payload["native_blocked_count"], 0)
        self.assertTrue(payload["cpu_signal_ready"])
        self.assertTrue(payload["memory_signal_ready"])
        self.assertTrue(payload["gpu_signal_ready"])
        self.assertEqual(assessment["readiness_status"], "ready-readonly-observation")
        self.assertEqual(assessment["readiness_score"], 80)
        self.assertEqual(assessment["risk_level"], "low")
        self.assertEqual(assessment["recommended_next_step"], "continue-readonly-telemetry-loop")

    def test_readiness_requires_host_snapshot_before_readonly_probe(self):
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
        readiness = assess_runtime_native_backend_readiness(probe)
        payload = readiness.to_dict()
        assessment = payload["assessments"][0]

        self.assertEqual(payload["readiness_policy"], "collect-readonly-evidence")
        self.assertEqual(payload["ready_observation_count"], 0)
        self.assertEqual(payload["needs_evidence_count"], 1)
        self.assertEqual(payload["native_blocked_count"], 0)
        self.assertFalse(payload["cpu_signal_ready"])
        self.assertFalse(payload["memory_signal_ready"])
        self.assertFalse(payload["gpu_signal_ready"])
        self.assertEqual(assessment["readiness_status"], "needs-host-snapshot")
        self.assertEqual(assessment["blockers"], ["host-snapshot"])
        self.assertEqual(assessment["required_next_evidence"], ["host-capability-snapshot"])
        self.assertEqual(assessment["recommended_next_step"], "collect-host-snapshot-before-control")

    def test_readiness_holds_native_ram_vram_but_keeps_safe_observation(self):
        host = build_balanced_host()
        manifest = build_manifest(
            events_path=FIXTURES / "adapter_budget_pressure_events.jsonl",
            host_snapshot=host,
            final_execution_action="dry-run-observation-supervisor-commands",
            final_supervisor_action="establish-supervisor-baseline",
            total_would_block_count=0,
        )
        probe = run_runtime_native_backend_probe(
            manifest=manifest,
            host_snapshot=host,
        )
        readiness = assess_runtime_native_backend_readiness(probe)
        payload = readiness.to_dict()
        by_surface = {
            item["control_surface"]: item for item in payload["assessments"]
        }

        self.assertEqual(
            payload["readiness_policy"],
            "continue-safe-observation-hold-native",
        )
        self.assertEqual(payload["advisory_ready_count"], 1)
        self.assertEqual(payload["native_blocked_count"], 1)
        self.assertEqual(payload["high_risk_count"], 1)
        self.assertEqual(
            by_surface["ram-vram"]["readiness_status"],
            "blocked-native-safety-boundary",
        )
        self.assertEqual(by_surface["ram-vram"]["readiness_score"], 0)
        self.assertEqual(by_surface["ram-vram"]["risk_level"], "high")
        self.assertIn(
            "safety-review",
            by_surface["ram-vram"]["required_next_evidence"],
        )

    def test_readiness_accepts_advisory_loop_without_native_promotion(self):
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
        readiness = assess_runtime_native_backend_readiness(probe)
        payload = readiness.to_dict()
        assessment = payload["assessments"][0]

        self.assertEqual(payload["readiness_policy"], "advisory-loop-ready")
        self.assertEqual(payload["advisory_ready_count"], 1)
        self.assertEqual(payload["native_blocked_count"], 0)
        self.assertFalse(payload["native_action_allowed"])
        self.assertEqual(assessment["readiness_status"], "ready-advisory-loop")
        self.assertEqual(assessment["readiness_score"], 70)
        self.assertEqual(assessment["recommended_next_step"], "continue-advisory-daemon-loop")


if __name__ == "__main__":
    unittest.main()
