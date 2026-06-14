from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.client import RuntimeEventClient, summarize_client_responses
from fluidgateway.server import create_runtime_event_server


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeSupervisorExecutionTests(unittest.TestCase):
    def test_runtime_supervisor_execution_records_baseline_dry_run(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        execution = payload["runtime_supervisor_execution"]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(execution["mode"], "runtime-supervisor-execution-v0.45")
        self.assertEqual(
            execution["execution_action"],
            "dry-run-observation-supervisor-commands",
        )
        self.assertTrue(execution["dry_run"])
        self.assertFalse(execution["would_modify_system"])
        self.assertEqual(execution["execution_guard"], "advisory-only")
        self.assertEqual(execution["command_count"], 5)
        self.assertEqual(execution["would_apply_count"], 5)
        self.assertEqual(execution["would_block_count"], 0)
        self.assertEqual(execution["scheduler_execution_count"], 1)
        self.assertEqual(execution["memory_execution_count"], 1)

    def test_runtime_supervisor_execution_relaxes_after_improvement(self):
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        stable = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl",
            previous_state=pressure.runtime_state_accumulator,
        )
        execution = stable.to_dict()["runtime_supervisor_execution"]
        command_by_domain = {
            command["domain"]: command for command in execution["command_executions"]
        }

        self.assertEqual(
            execution["execution_action"],
            "dry-run-relaxed-supervisor-commands",
        )
        self.assertEqual(execution["would_apply_count"], 5)
        self.assertEqual(execution["would_block_count"], 0)
        self.assertEqual(command_by_domain["scheduler"]["dry_run_status"], "would-apply")
        self.assertEqual(
            command_by_domain["scheduler"]["effect"],
            "simulate-scheduler-posture",
        )
        self.assertEqual(command_by_domain["admission"]["simulated_budget_ms"], 1.2)
        self.assertEqual(command_by_domain["memory"]["simulated_target_mb"], 0)

    def test_runtime_supervisor_execution_marks_blocking_after_regression(self):
        stable = replay_adapter_event_stream(FIXTURES / "adapter_state_query_events.jsonl")
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl",
            previous_state=stable.runtime_state_accumulator,
        )
        execution = pressure.to_dict()["runtime_supervisor_execution"]
        blocking_domains = {
            command["domain"]
            for command in execution["command_executions"]
            if command["would_block"]
        }

        self.assertEqual(
            execution["execution_action"],
            "dry-run-tightened-supervisor-commands",
        )
        self.assertEqual(execution["would_apply_count"], 5)
        self.assertEqual(execution["would_block_count"], 3)
        self.assertEqual(blocking_domains, {"scheduler", "admission", "memory"})
        self.assertFalse(execution["would_modify_system"])
        self.assertEqual(execution["execution_guard"], "advisory-only")

    def test_runtime_event_server_reports_baseline_supervisor_execution(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(
                    FIXTURES / "adapter_state_query_events.jsonl"
                )

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        execution = summary["runtime_supervisor_execution"]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(execution["mode"], "runtime-supervisor-execution-v0.45")
        self.assertTrue(execution["dry_run"])
        self.assertFalse(execution["would_modify_system"])
        self.assertEqual(execution["command_count"], 5)
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_run_adapter_cli_reports_relaxed_execution_dry_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            state_path = temp / "runtime-state.json"
            first_out = temp / "first-session.json"
            second_out = temp / "second-session.json"

            first = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-adapter",
                    "--events",
                    str(FIXTURES / "adapter_budget_pressure_events.jsonl"),
                    "--state-out",
                    str(state_path),
                    "--out",
                    str(first_out),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fluidgateway",
                    "runtime",
                    "run-adapter",
                    "--events",
                    str(FIXTURES / "adapter_state_query_events.jsonl"),
                    "--state-in",
                    str(state_path),
                    "--state-out",
                    str(state_path),
                    "--out",
                    str(second_out),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            session = json.loads(second_out.read_text(encoding="utf-8"))

        execution = session["runtime_supervisor_execution"]
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn(
            "Runtime supervisor execution action: dry-run-relaxed-supervisor-commands",
            second.stdout,
        )
        self.assertIn("Runtime supervisor execution guard: advisory-only", second.stdout)
        self.assertEqual(
            execution["execution_action"],
            "dry-run-relaxed-supervisor-commands",
        )
        self.assertEqual(execution["would_apply_count"], 5)


if __name__ == "__main__":
    unittest.main()
