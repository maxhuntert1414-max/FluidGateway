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


class RuntimeSupervisorPlanTests(unittest.TestCase):
    def test_runtime_supervisor_plan_records_baseline_commands(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        plan = payload["runtime_supervisor_plan"]
        commands = {command["domain"]: command for command in plan["commands"]}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(plan["mode"], "runtime-supervisor-plan-v0.44")
        self.assertEqual(plan["source_directive_action"], "establish-supervisor-baseline")
        self.assertEqual(plan["plan_action"], "observe-next-cycle")
        self.assertEqual(plan["command_count"], 5)
        self.assertEqual(plan["blocking_command_count"], 0)
        self.assertEqual(plan["scheduler_command_count"], 1)
        self.assertEqual(plan["admission_command_count"], 1)
        self.assertEqual(plan["memory_command_count"], 1)
        self.assertEqual(commands["scheduler"]["action"], "observe-runtime-cycle")
        self.assertEqual(commands["admission"]["action"], "observe-admission")
        self.assertEqual(commands["memory"]["action"], "observe-residency")

    def test_runtime_supervisor_plan_relaxes_after_improvement(self):
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        stable = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl",
            previous_state=pressure.runtime_state_accumulator,
        )
        plan = stable.to_dict()["runtime_supervisor_plan"]
        commands = {command["domain"]: command for command in plan["commands"]}

        self.assertEqual(plan["source_directive_action"], "relax-supervisor-pressure")
        self.assertEqual(plan["plan_action"], "apply-relaxed-next-cycle-posture")
        self.assertEqual(plan["command_count"], 5)
        self.assertEqual(plan["blocking_command_count"], 0)
        self.assertEqual(plan["cooldown_cycles"], 2)
        self.assertEqual(commands["scheduler"]["action"], "relax-to-stable-cycle")
        self.assertEqual(commands["scheduler"]["budget_ms"], 4.2)
        self.assertEqual(commands["admission"]["action"], "allow-budgeted-copy-queue")
        self.assertEqual(commands["admission"]["budget_ms"], 1.2)
        self.assertEqual(commands["memory"]["action"], "release-relief-watch")
        self.assertEqual(commands["memory"]["target_mb"], 0)

    def test_runtime_supervisor_plan_blocks_copy_queue_after_regression(self):
        stable = replay_adapter_event_stream(FIXTURES / "adapter_state_query_events.jsonl")
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl",
            previous_state=stable.runtime_state_accumulator,
        )
        plan = pressure.to_dict()["runtime_supervisor_plan"]
        commands = {command["domain"]: command for command in plan["commands"]}

        self.assertEqual(plan["source_directive_action"], "escalate-supervisor-pressure")
        self.assertEqual(plan["plan_action"], "apply-tightened-next-cycle-posture")
        self.assertEqual(plan["blocking_command_count"], 3)
        self.assertEqual(plan["escalation_level"], 2)
        self.assertTrue(commands["scheduler"]["blocking"])
        self.assertTrue(commands["admission"]["blocking"])
        self.assertTrue(commands["memory"]["blocking"])
        self.assertEqual(commands["admission"]["action"], "block-noncritical-copy-queue")
        self.assertEqual(commands["admission"]["budget_ms"], 0)
        self.assertEqual(commands["frame-budget"]["action"], "tighten-hot-path-budget")

    def test_runtime_event_server_reports_baseline_supervisor_plan(self):
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
        plan = summary["runtime_supervisor_plan"]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(plan["mode"], "runtime-supervisor-plan-v0.44")
        self.assertEqual(plan["plan_action"], "observe-next-cycle")
        self.assertEqual(plan["command_count"], 5)
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_run_adapter_cli_reports_relaxed_supervisor_plan(self):
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

        plan = session["runtime_supervisor_plan"]
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn(
            "Runtime supervisor plan action: apply-relaxed-next-cycle-posture",
            second.stdout,
        )
        self.assertIn("Runtime supervisor plan commands: 5", second.stdout)
        self.assertEqual(plan["plan_action"], "apply-relaxed-next-cycle-posture")
        self.assertEqual(plan["blocking_command_count"], 0)


if __name__ == "__main__":
    unittest.main()
