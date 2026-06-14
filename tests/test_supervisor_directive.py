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


class RuntimeSupervisorDirectiveTests(unittest.TestCase):
    def test_runtime_supervisor_directive_records_baseline_posture(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        directive = payload["runtime_supervisor_directive"]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(directive["mode"], "runtime-supervisor-directive-v0.43")
        self.assertEqual(directive["source_trend"], "baseline")
        self.assertEqual(
            directive["directive_action"],
            "establish-supervisor-baseline",
        )
        self.assertEqual(directive["scheduler_posture"], "observe-runtime-cycle")
        self.assertEqual(directive["admission_posture"], "observe-admission")
        self.assertEqual(directive["memory_posture"], "observe-residency")
        self.assertEqual(directive["escalation_level"], 0)
        self.assertEqual(directive["cooldown_cycles"], 1)
        self.assertEqual(directive["next_frame_budget_ms"], 6.0)
        self.assertEqual(directive["copy_queue_budget_ms"], 0)

    def test_runtime_supervisor_directive_relaxes_after_improvement(self):
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        stable = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl",
            previous_state=pressure.runtime_state_accumulator,
        )
        directive = stable.to_dict()["runtime_supervisor_directive"]

        self.assertEqual(directive["source_trend"], "improving")
        self.assertEqual(directive["directive_action"], "relax-supervisor-pressure")
        self.assertEqual(directive["scheduler_posture"], "relax-to-stable-cycle")
        self.assertEqual(directive["admission_posture"], "allow-budgeted-copy-queue")
        self.assertEqual(directive["memory_posture"], "release-relief-watch")
        self.assertEqual(directive["frame_budget_posture"], "restore-stable-budget")
        self.assertEqual(directive["guardband_posture"], "decay-guardband")
        self.assertEqual(directive["escalation_level"], 0)
        self.assertEqual(directive["cooldown_cycles"], 2)
        self.assertEqual(directive["copy_queue_budget_ms"], 1.2)
        self.assertEqual(directive["memory_relief_target_mb"], 0)
        self.assertLess(directive["pressure_delta"], 0)

    def test_runtime_supervisor_directive_escalates_after_regression(self):
        stable = replay_adapter_event_stream(FIXTURES / "adapter_state_query_events.jsonl")
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl",
            previous_state=stable.runtime_state_accumulator,
        )
        directive = pressure.to_dict()["runtime_supervisor_directive"]

        self.assertEqual(directive["source_trend"], "worsening")
        self.assertEqual(
            directive["directive_action"],
            "escalate-supervisor-pressure",
        )
        self.assertEqual(directive["scheduler_posture"], "tighten-preframe-dispatch")
        self.assertEqual(directive["admission_posture"], "block-noncritical-copy-queue")
        self.assertEqual(directive["memory_posture"], "protect-residency-and-relief")
        self.assertEqual(directive["frame_budget_posture"], "tighten-hot-path-budget")
        self.assertEqual(directive["guardband_posture"], "increase-guardband")
        self.assertEqual(directive["escalation_level"], 2)
        self.assertEqual(directive["cooldown_cycles"], 0)
        self.assertEqual(directive["copy_queue_budget_ms"], 0)
        self.assertGreater(directive["pressure_delta"], 0)

    def test_runtime_event_server_reports_baseline_supervisor_directive(self):
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
        directive = summary["runtime_supervisor_directive"]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(directive["mode"], "runtime-supervisor-directive-v0.43")
        self.assertEqual(directive["source_trend"], "baseline")
        self.assertEqual(directive["directive_action"], "establish-supervisor-baseline")
        self.assertEqual(directive["scheduler_posture"], "observe-runtime-cycle")

    def test_runtime_run_adapter_cli_reports_relaxed_supervisor_directive(self):
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

        directive = session["runtime_supervisor_directive"]
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn(
            "Runtime supervisor directive action: relax-supervisor-pressure",
            second.stdout,
        )
        self.assertIn(
            "Runtime supervisor scheduler posture: relax-to-stable-cycle",
            second.stdout,
        )
        self.assertEqual(directive["directive_action"], "relax-supervisor-pressure")
        self.assertEqual(directive["memory_posture"], "release-relief-watch")


if __name__ == "__main__":
    unittest.main()
