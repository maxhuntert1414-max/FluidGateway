from __future__ import annotations

import unittest

from fluidgateway.native_backend_gate import build_runtime_native_backend_gate
from fluidgateway.native_backend_probe import run_runtime_native_backend_probe
from fluidgateway.native_backend_readiness import (
    assess_runtime_native_backend_readiness,
)
from tests.test_native_backend_probe import (
    FIXTURES,
    build_balanced_host,
    build_manifest,
)


class RuntimeNativeBackendGateTests(unittest.TestCase):
    def test_gate_advances_complete_readonly_observation(self):
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
        gate = build_runtime_native_backend_gate(readiness)
        payload = gate.to_dict()
        decision = payload["decisions"][0]

        self.assertEqual(payload["mode"], "runtime-native-backend-gate-v0.58")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["gate_policy"], "advance-readonly-observation")
        self.assertFalse(payload["native_promotion_allowed"])
        self.assertEqual(payload["advance_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertEqual(decision["gate_status"], "allow-readonly-observation")
        self.assertEqual(decision["gate_action"], "continue-readonly-telemetry")
        self.assertEqual(decision["promotion_scope"], "read-only-observation")
        self.assertTrue(decision["advance_allowed"])
        self.assertFalse(decision["native_promotion_allowed"])

    def test_gate_blocks_missing_host_snapshot_for_evidence(self):
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
        gate = build_runtime_native_backend_gate(readiness)
        payload = gate.to_dict()
        decision = payload["decisions"][0]

        self.assertEqual(
            payload["gate_policy"],
            "collect-evidence-before-promotion",
        )
        self.assertEqual(payload["advance_count"], 0)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["evidence_blocked_count"], 1)
        self.assertEqual(decision["gate_status"], "block-for-evidence")
        self.assertEqual(decision["gate_action"], "collect-required-evidence")
        self.assertEqual(decision["blocked_by"], ["host-snapshot"])
        self.assertTrue(decision["blocked"])

    def test_gate_advances_safe_path_and_blocks_native_ram_vram(self):
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
        gate = build_runtime_native_backend_gate(readiness)
        payload = gate.to_dict()
        by_surface = {
            item["control_surface"]: item for item in payload["decisions"]
        }

        self.assertEqual(
            payload["gate_policy"],
            "advance-safe-paths-hold-native",
        )
        self.assertEqual(payload["advance_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(payload["native_blocked_count"], 1)
        self.assertEqual(payload["high_risk_count"], 1)
        self.assertEqual(
            by_surface["ram-vram"]["gate_status"],
            "block-native-promotion",
        )
        self.assertEqual(
            by_surface["ram-vram"]["gate_action"],
            "hold-native-control",
        )
        self.assertIn(
            "native-promotion-disabled",
            by_surface["ram-vram"]["blocked_by"],
        )
        self.assertEqual(
            by_surface["scheduler"]["gate_status"],
            "allow-advisory-loop",
        )

    def test_gate_advances_advisory_loop_without_native_promotion(self):
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
        gate = build_runtime_native_backend_gate(readiness)
        payload = gate.to_dict()
        decision = payload["decisions"][0]

        self.assertEqual(payload["gate_policy"], "advance-advisory-loop")
        self.assertEqual(payload["advance_count"], 1)
        self.assertEqual(payload["blocked_count"], 0)
        self.assertFalse(payload["native_promotion_allowed"])
        self.assertEqual(decision["gate_status"], "allow-advisory-loop")
        self.assertEqual(decision["gate_action"], "continue-advisory-daemon-loop")
        self.assertEqual(decision["promotion_scope"], "advisory-loop")


if __name__ == "__main__":
    unittest.main()
