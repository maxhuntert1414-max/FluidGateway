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


class RuntimeStateTransitionTests(unittest.TestCase):
    def test_runtime_state_transition_records_baseline_without_previous_state(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        state = payload["runtime_state_accumulator"]
        transition = payload["runtime_state_transition"]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.43")
        self.assertEqual(transition["mode"], "runtime-state-transition-v0.42")
        self.assertFalse(transition["has_previous_state"])
        self.assertIsNone(transition["previous_cycle_count"])
        self.assertEqual(transition["current_cycle_count"], 1)
        self.assertEqual(transition["cycle_delta"], 0)
        self.assertEqual(transition["trend"], "baseline")
        self.assertEqual(
            transition["transition_action"],
            "establish-runtime-baseline",
        )
        self.assertGreater(transition["current_pressure_index"], 0)
        self.assertEqual(transition["pressure_delta"], 0)
        self.assertEqual(transition["previous_state_digest"], None)
        self.assertEqual(transition["current_state_digest"], state["state_digest"])

    def test_runtime_state_transition_detects_improving_pressure(self):
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        stable = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl",
            previous_state=pressure.runtime_state_accumulator,
        )
        transition = stable.to_dict()["runtime_state_transition"]

        self.assertTrue(transition["has_previous_state"])
        self.assertEqual(transition["previous_cycle_count"], 1)
        self.assertEqual(transition["current_cycle_count"], 2)
        self.assertEqual(transition["cycle_delta"], 1)
        self.assertEqual(transition["trend"], "improving")
        self.assertEqual(
            transition["transition_action"],
            "relax-after-pressure-relief",
        )
        self.assertLess(transition["pressure_delta"], 0)
        self.assertEqual(transition["profile_transition"], "aggressive->stable")
        self.assertEqual(transition["memory_relief_delta_mb"], -40)
        self.assertEqual(transition["active_policy_delta"], -1)

    def test_runtime_state_transition_detects_worsening_pressure(self):
        stable = replay_adapter_event_stream(FIXTURES / "adapter_state_query_events.jsonl")
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl",
            previous_state=stable.runtime_state_accumulator,
        )
        transition = pressure.to_dict()["runtime_state_transition"]

        self.assertEqual(transition["trend"], "worsening")
        self.assertEqual(
            transition["transition_action"],
            "tighten-after-pressure-regression",
        )
        self.assertGreater(transition["pressure_delta"], 0)
        self.assertEqual(transition["profile_transition"], "stable->aggressive")
        self.assertEqual(transition["memory_relief_delta_mb"], 40)
        self.assertEqual(transition["active_policy_delta"], 1)

    def test_runtime_event_server_reports_baseline_state_transition(self):
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
        transition = summary["runtime_state_transition"]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.43")
        self.assertEqual(transition["mode"], "runtime-state-transition-v0.42")
        self.assertEqual(transition["trend"], "baseline")
        self.assertEqual(transition["transition_action"], "establish-runtime-baseline")
        self.assertFalse(transition["has_previous_state"])

    def test_runtime_run_adapter_cli_reports_improving_transition(self):
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

        transition = session["runtime_state_transition"]
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Runtime state transition trend: improving", second.stdout)
        self.assertIn(
            "Runtime state transition action: relax-after-pressure-relief",
            second.stdout,
        )
        self.assertEqual(transition["trend"], "improving")
        self.assertLess(transition["pressure_delta"], 0)


if __name__ == "__main__":
    unittest.main()
