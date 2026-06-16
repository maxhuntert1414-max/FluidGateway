from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fluidgateway.daemon import run_runtime_daemon, write_runtime_daemon_report
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeDaemonTests(unittest.TestCase):
    def test_runtime_daemon_chains_event_streams_through_persisted_state(self):
        report = run_runtime_daemon(
            [
                FIXTURES / "adapter_budget_pressure_events.jsonl",
                FIXTURES / "adapter_state_query_events.jsonl",
            ]
        )
        payload = report.to_dict()
        first = payload["cycles"][0]
        second = payload["cycles"][1]

        self.assertEqual(payload["mode"], "runtime-daemon-dry-run-v0.55")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["execution_guard"], "advisory-only")
        self.assertEqual(payload["configured_iterations"], 1)
        self.assertEqual(payload["cycle_count"], 2)
        self.assertEqual(payload["events_stream_count"], 2)
        self.assertEqual(payload["events_processed"], 19)
        self.assertEqual(payload["operation_events"], 5)
        self.assertFalse(payload["initial_state_loaded"])
        self.assertIsNone(payload["initial_state_digest"])
        self.assertFalse(payload["host_snapshot_loaded"])
        self.assertIsNone(payload["host_profile"])
        self.assertIsNone(payload["host_manager_hint"])
        self.assertIsNone(payload["host_snapshot"])
        self.assertEqual(payload["daemon_decision_action"], "expand-daemon-telemetry")
        self.assertEqual(payload["daemon_decision_risk_level"], "high")
        self.assertEqual(
            payload["daemon_action_queue_policy"],
            "run-readonly-telemetry-before-native-work",
        )
        self.assertEqual(payload["daemon_action_blocked_count"], 0)
        self.assertEqual(
            payload["daemon_action_execution_policy"],
            "execute-readonly-telemetry",
        )
        self.assertEqual(payload["daemon_action_execution_blocked_count"], 0)
        self.assertEqual(payload["native_backend_policy"], "advisory-preflight-passed")
        self.assertEqual(payload["native_backend_blocked_count"], 0)
        self.assertFalse(payload["native_promotion_allowed"])
        self.assertEqual(payload["daemon_arbitration_policy"], "telemetry-first")
        self.assertEqual(payload["daemon_arbitration_blocked_count"], 0)
        self.assertGreaterEqual(payload["daemon_arbitration_pressure_score"], 0)
        self.assertEqual(
            payload["daemon_control_policy"],
            "collect-evidence-before-control",
        )
        self.assertEqual(payload["daemon_control_blocked_count"], 0)
        self.assertEqual(payload["daemon_control_ready_count"], 1)
        self.assertEqual(
            payload["daemon_control_execution_policy"],
            "execute-readonly-control",
        )
        self.assertEqual(payload["daemon_control_execution_blocked_count"], 0)
        self.assertEqual(payload["daemon_control_execution_executed_count"], 1)
        self.assertEqual(
            payload["native_backend_manifest_policy"],
            "readonly-probe-ready",
        )
        self.assertEqual(payload["native_backend_manifest_ready_count"], 1)
        self.assertEqual(payload["native_backend_manifest_blocked_count"], 0)
        self.assertEqual(payload["final_cycle_count"], 2)
        self.assertEqual(payload["total_would_apply_count"], 10)
        self.assertEqual(payload["total_would_block_count"], 0)
        self.assertEqual(
            payload["final_execution_action"],
            "dry-run-relaxed-supervisor-commands",
        )
        self.assertEqual(first["previous_cycle_count"], None)
        self.assertIsNone(first["previous_state_digest"])
        self.assertEqual(first["current_cycle_count"], 1)
        self.assertEqual(first["events_processed"], 10)
        self.assertEqual(first["operation_events"], 3)
        self.assertEqual(first["transition_trend"], "baseline")
        self.assertEqual(
            first["execution_action"],
            "dry-run-observation-supervisor-commands",
        )
        self.assertEqual(second["previous_cycle_count"], 1)
        self.assertIn("cycle:1", second["previous_state_digest"])
        self.assertEqual(second["current_cycle_count"], 2)
        self.assertEqual(second["events_processed"], 9)
        self.assertEqual(second["operation_events"], 2)
        self.assertEqual(second["transition_trend"], "improving")
        self.assertEqual(
            second["execution_action"],
            "dry-run-relaxed-supervisor-commands",
        )
        self.assertEqual(payload["final_state"]["cycle_count"], 2)
        self.assertEqual(payload["final_state"]["profile"], "stable")
        self.assertIn("cycle:2", payload["final_state_digest"])
        self.assertEqual(
            payload["daemon_decision_plan"]["mode"],
            "runtime-daemon-decision-plan-v0.48",
        )
        self.assertEqual(
            payload["daemon_decision_plan"]["actions"][0]["action"],
            "collect-host-telemetry",
        )
        self.assertEqual(
            payload["daemon_action_queue"]["mode"],
            "runtime-daemon-action-queue-v0.49",
        )
        self.assertEqual(
            payload["daemon_action_queue"]["queue_policy"],
            "run-readonly-telemetry-before-native-work",
        )
        self.assertEqual(
            payload["daemon_action_execution"]["mode"],
            "runtime-daemon-action-execution-v0.50",
        )
        self.assertEqual(
            payload["daemon_action_execution"]["execution_policy"],
            "execute-readonly-telemetry",
        )
        self.assertEqual(
            payload["native_backend_preflight"]["mode"],
            "runtime-native-backend-preflight-v0.51",
        )
        self.assertEqual(
            payload["native_backend_preflight"]["backend_policy"],
            "advisory-preflight-passed",
        )
        self.assertEqual(
            payload["daemon_arbitration_plan"]["mode"],
            "runtime-daemon-arbitration-plan-v0.52",
        )
        self.assertEqual(
            payload["daemon_arbitration_plan"]["arbitration_policy"],
            "telemetry-first",
        )
        self.assertEqual(
            payload["daemon_control_plan"]["mode"],
            "runtime-daemon-control-plan-v0.53",
        )
        self.assertEqual(
            payload["daemon_control_plan"]["control_policy"],
            "collect-evidence-before-control",
        )
        self.assertEqual(
            payload["daemon_control_execution"]["mode"],
            "runtime-daemon-control-execution-v0.54",
        )
        self.assertEqual(
            payload["daemon_control_execution"]["execution_policy"],
            "execute-readonly-control",
        )
        self.assertEqual(
            payload["native_backend_manifest"]["mode"],
            "runtime-native-backend-manifest-v0.55",
        )
        self.assertEqual(
            payload["native_backend_manifest"]["manifest_policy"],
            "readonly-probe-ready",
        )

    def test_runtime_daemon_can_attach_host_capability_snapshot(self):
        host = build_host_capability_snapshot(
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
        report = run_runtime_daemon(
            [FIXTURES / "adapter_state_query_events.jsonl"],
            host_snapshot=host,
        )
        payload = report.to_dict()

        self.assertTrue(payload["host_snapshot_loaded"])
        self.assertEqual(payload["host_profile"], "balanced-gaming-host")
        self.assertEqual(
            payload["host_manager_hint"],
            "allow-daemon-supervisor-loop",
        )
        self.assertEqual(
            payload["host_snapshot"]["mode"],
            "host-capability-snapshot-v0.47",
        )
        self.assertEqual(
            payload["daemon_decision_action"],
            "continue-host-aware-supervisor-loop",
        )
        self.assertEqual(payload["daemon_decision_risk_level"], "medium")
        self.assertEqual(payload["daemon_action_queue_policy"], "continue-advisory-loop")
        self.assertEqual(payload["daemon_action_blocked_count"], 0)
        self.assertEqual(
            payload["daemon_action_execution_policy"],
            "execute-advisory-loop",
        )
        self.assertEqual(payload["daemon_action_execution_blocked_count"], 0)
        self.assertEqual(payload["native_backend_policy"], "advisory-preflight-passed")
        self.assertEqual(payload["native_backend_blocked_count"], 0)
        self.assertEqual(
            payload["daemon_arbitration_policy"],
            "continue-supervisor-loop",
        )
        self.assertEqual(payload["daemon_arbitration_blocked_count"], 0)
        self.assertEqual(
            payload["daemon_control_policy"],
            "maintain-advisory-control-loop",
        )
        self.assertEqual(payload["daemon_control_blocked_count"], 0)
        self.assertEqual(
            payload["daemon_control_execution_policy"],
            "execute-advisory-control",
        )
        self.assertEqual(payload["daemon_control_execution_blocked_count"], 0)
        self.assertEqual(
            payload["native_backend_manifest_policy"],
            "advisory-backend-ready",
        )
        self.assertEqual(payload["native_backend_manifest_ready_count"], 1)
        self.assertEqual(payload["native_backend_manifest_blocked_count"], 0)

    def test_runtime_daemon_repeats_last_events_stream_for_iterations(self):
        report = run_runtime_daemon(
            [FIXTURES / "adapter_budget_pressure_events.jsonl"],
            iterations=2,
        )
        payload = report.to_dict()
        first, second = payload["cycles"]

        self.assertEqual(payload["cycle_count"], 2)
        self.assertEqual(payload["configured_iterations"], 2)
        self.assertEqual(payload["events_stream_count"], 1)
        self.assertEqual(payload["final_cycle_count"], 2)
        self.assertEqual(first["events_path"], second["events_path"])
        self.assertEqual(second["previous_cycle_count"], 1)
        self.assertEqual(second["current_cycle_count"], 2)
        self.assertEqual(payload["final_state"]["cycle_count"], 2)

    def test_runtime_daemon_rejects_empty_or_invalid_loop(self):
        with self.assertRaisesRegex(ValueError, "at least one events path"):
            run_runtime_daemon([])

        with self.assertRaisesRegex(ValueError, "iterations must be at least 1"):
            run_runtime_daemon(
                [FIXTURES / "adapter_budget_pressure_events.jsonl"],
                iterations=0,
            )

    def test_runtime_daemon_report_writer_adds_json_suffix(self):
        report = run_runtime_daemon(
            [FIXTURES / "adapter_state_query_events.jsonl"]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "daemon-report"
            written = write_runtime_daemon_report(report, output)
            payload = json.loads(written.read_text(encoding="utf-8"))

        self.assertEqual(written.suffix, ".json")
        self.assertEqual(payload["mode"], "runtime-daemon-dry-run-v0.55")
        self.assertEqual(payload["cycle_count"], 1)

    def test_runtime_run_daemon_cli_writes_report_and_final_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            state_path = temp / "runtime-state.json"
            report_path = temp / "daemon-report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-daemon",
                    "--events",
                    str(FIXTURES / "adapter_budget_pressure_events.jsonl"),
                    "--events",
                    str(FIXTURES / "adapter_state_query_events.jsonl"),
                    "--state",
                    str(state_path),
                    "--out",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Daemon cycles: 2", result.stdout)
        self.assertIn("Daemon guard: advisory-only", result.stdout)
        self.assertEqual(report["mode"], "runtime-daemon-dry-run-v0.55")
        self.assertEqual(report["cycle_count"], 2)
        self.assertEqual(report["final_cycle_count"], 2)
        self.assertTrue(report["host_snapshot_loaded"])
        self.assertIsNotNone(report["host_snapshot"])
        self.assertIn("daemon_decision_plan", report)
        self.assertIn("daemon_action_queue", report)
        self.assertIn("daemon_action_execution", report)
        self.assertIn("native_backend_preflight", report)
        self.assertIn("daemon_arbitration_plan", report)
        self.assertIn("daemon_control_plan", report)
        self.assertIn("daemon_control_execution", report)
        self.assertIn("native_backend_manifest", report)
        self.assertIn("Daemon action queue policy:", result.stdout)
        self.assertIn("Daemon action blocked commands:", result.stdout)
        self.assertIn("Daemon action execution policy:", result.stdout)
        self.assertIn("Daemon action execution blocked:", result.stdout)
        self.assertIn("Native backend policy:", result.stdout)
        self.assertIn("Native backend blocked requirements:", result.stdout)
        self.assertIn("Native promotion allowed:", result.stdout)
        self.assertIn("Daemon arbitration policy:", result.stdout)
        self.assertIn("Daemon arbitration blocked lanes:", result.stdout)
        self.assertIn("Daemon arbitration pressure score:", result.stdout)
        self.assertIn("Daemon control policy:", result.stdout)
        self.assertIn("Daemon control ready intents:", result.stdout)
        self.assertIn("Daemon control blocked intents:", result.stdout)
        self.assertIn("Daemon control execution policy:", result.stdout)
        self.assertIn("Daemon control execution executed:", result.stdout)
        self.assertIn("Daemon control execution blocked:", result.stdout)
        self.assertIn("Native backend manifest policy:", result.stdout)
        self.assertIn("Native backend manifest ready:", result.stdout)
        self.assertIn("Native backend manifest blocked:", result.stdout)
        self.assertIn("Daemon decision action:", result.stdout)
        self.assertIn("Daemon decision risk:", result.stdout)
        self.assertIn("Daemon host profile:", result.stdout)
        self.assertIn("Daemon host manager hint:", result.stdout)
        self.assertEqual(state["cycle_count"], 2)
        self.assertEqual(state["profile"], "stable")

    def test_runtime_run_daemon_cli_loads_normalized_state_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            state_arg = temp / "runtime-state"
            state_path = state_arg.with_suffix(".json")
            first_report = temp / "first-report.json"
            second_report = temp / "second-report.json"

            first = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-daemon",
                    "--events",
                    str(FIXTURES / "adapter_budget_pressure_events.jsonl"),
                    "--state",
                    str(state_arg),
                    "--out",
                    str(first_report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            second = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-daemon",
                    "--events",
                    str(FIXTURES / "adapter_state_query_events.jsonl"),
                    "--state",
                    str(state_arg),
                    "--out",
                    str(second_report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            report = json.loads(second_report.read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Runtime daemon previous state cycles: 1", second.stdout)
        self.assertTrue(report["initial_state_loaded"])
        self.assertEqual(report["cycles"][0]["previous_cycle_count"], 1)
        self.assertEqual(report["final_cycle_count"], 2)
        self.assertEqual(state["cycle_count"], 2)

    def test_runtime_run_daemon_cli_rejects_invalid_normalized_state_before_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            state_arg = temp / "runtime-state"
            state_path = state_arg.with_suffix(".json")
            report_path = temp / "daemon-report.json"
            state_path.write_text("{", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-daemon",
                    "--events",
                    str(FIXTURES / "adapter_budget_pressure_events.jsonl"),
                    "--state",
                    str(state_arg),
                    "--out",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(state_path.read_text(encoding="utf-8"), "{")
            self.assertFalse(report_path.exists())

        self.assertEqual(result.returncode, 1)
        self.assertIn("not valid JSON", result.stderr)

    def test_runtime_run_daemon_cli_requires_state_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "daemon-report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-daemon",
                    "--events",
                    str(FIXTURES / "adapter_budget_pressure_events.jsonl"),
                    "--out",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--state", result.stderr)

    def test_runtime_run_daemon_cli_rejects_state_and_report_same_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            same_path = Path(temp_dir) / "daemon-output"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-daemon",
                    "--events",
                    str(FIXTURES / "adapter_budget_pressure_events.jsonl"),
                    "--state",
                    str(same_path),
                    "--out",
                    str(same_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            written_path = same_path.with_suffix(".json")
            self.assertFalse(written_path.exists())

        self.assertEqual(result.returncode, 1)
        self.assertIn("must be different paths", result.stderr)


if __name__ == "__main__":
    unittest.main()
