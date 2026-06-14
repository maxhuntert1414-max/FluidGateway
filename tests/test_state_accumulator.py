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
from fluidgateway.state_accumulator import (
    build_runtime_state_accumulator,
    load_runtime_state_accumulator,
    runtime_state_accumulator_from_dict,
    write_runtime_state_accumulator,
)


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeStateAccumulatorTests(unittest.TestCase):
    def test_runtime_state_accumulator_records_pressure_policy_state(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        state = payload["runtime_state_accumulator"]
        frame = state["frames"][0]
        memory = state["memory"][0]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.43")
        self.assertEqual(state["mode"], "runtime-state-accumulator-v0.41")
        self.assertEqual(state["profile"], "aggressive")
        self.assertEqual(state["policy_action"], "continue-runtime-pressure-policy")
        self.assertEqual(state["convergence_status"], "diverging")
        self.assertEqual(state["drift_risk"], "high")
        self.assertEqual(state["cycle_count"], 1)
        self.assertEqual(state["frame_state_count"], 1)
        self.assertEqual(state["memory_state_count"], 1)
        self.assertEqual(state["active_policy_count"], 2)
        self.assertEqual(state["next_frame_budget_ms"], 6.0)
        self.assertEqual(state["hot_path_budget_ms"], 6.0)
        self.assertEqual(state["copy_queue_budget_ms"], 0)
        self.assertEqual(state["pre_frame_window_ms"], 4.5)
        self.assertEqual(state["memory_relief_target_mb"], 40)
        self.assertEqual(state["memory_headroom_target_mb"], 0)
        self.assertEqual(
            state["state_digest"],
            "profile:aggressive|policy:continue-runtime-pressure-policy|"
            "frames:1|memory:40.0000:0.0000|cycle:1",
        )
        self.assertEqual(frame["action"], "continue-frame-pressure-management")
        self.assertEqual(frame["admission_policy"], "prestage-and-defer-noncritical")
        self.assertEqual(frame["scheduler_policy"], "closed-loop-aggressive")
        self.assertEqual(frame["cycle_count"], 1)
        self.assertEqual(memory["action"], "continue-memory-relief")
        self.assertEqual(memory["residency_policy"], "evict-or-defer-residency")
        self.assertTrue(memory["active"])
        self.assertEqual(memory["cycle_count"], 1)

    def test_runtime_event_server_reports_runtime_state_accumulator(self):
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
        state = summary["runtime_state_accumulator"]
        memory = state["memory"][0]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.43")
        self.assertEqual(state["mode"], "runtime-state-accumulator-v0.41")
        self.assertEqual(state["profile"], "stable")
        self.assertEqual(state["policy_action"], "preserve-runtime-cycle-policy")
        self.assertEqual(state["cycle_count"], 1)
        self.assertEqual(state["active_policy_count"], 1)
        self.assertEqual(state["copy_queue_budget_ms"], 1.2)
        self.assertEqual(state["pre_frame_window_ms"], 4.2)
        self.assertEqual(memory["action"], "hold-memory-residency")
        self.assertEqual(memory["residency_policy"], "hold-residency")
        self.assertFalse(memory["active"])
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_state_accumulator_applies_sequential_updates(self):
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        stable = replay_adapter_event_stream(FIXTURES / "adapter_state_query_events.jsonl")

        first_state = build_runtime_state_accumulator(pressure.runtime_policy_update)
        second_state = build_runtime_state_accumulator(
            stable.runtime_policy_update,
            previous=first_state,
        )

        self.assertEqual(first_state.cycle_count, 1)
        self.assertEqual(second_state.cycle_count, 2)
        self.assertEqual(second_state.profile, "stable")
        self.assertEqual(second_state.policy_action, "preserve-runtime-cycle-policy")
        self.assertEqual(second_state.frames[0].cycle_count, 2)
        self.assertEqual(second_state.memory[0].cycle_count, 2)
        self.assertEqual(second_state.memory[0].action, "hold-memory-residency")
        self.assertEqual(second_state.memory[0].relief_target_mb, 0)
        self.assertIn("cycle:2", second_state.state_digest)

    def test_runtime_state_accumulator_roundtrips_through_json_file(self):
        pressure = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        stable = replay_adapter_event_stream(FIXTURES / "adapter_state_query_events.jsonl")

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "runtime-state.json"
            written = write_runtime_state_accumulator(
                pressure.runtime_state_accumulator,
                state_path,
            )
            previous = load_runtime_state_accumulator(written)
            self.assertIsNotNone(previous)

            resumed = replay_adapter_event_stream(
                FIXTURES / "adapter_state_query_events.jsonl",
                previous_state=previous,
            )

        assert previous is not None
        self.assertEqual(previous.cycle_count, 1)
        self.assertEqual(resumed.runtime_state_accumulator.cycle_count, 2)
        self.assertEqual(
            resumed.runtime_state_accumulator.profile,
            stable.runtime_state_accumulator.profile,
        )
        self.assertEqual(resumed.runtime_state_accumulator.memory[0].cycle_count, 2)

    def test_runtime_run_adapter_cli_loads_and_writes_state_file(self):
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
            self.assertTrue(state_path.exists())

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
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Runtime previous state cycles: 1", second.stdout)
        self.assertEqual(session["runtime_state_accumulator"]["cycle_count"], 2)
        self.assertEqual(state["cycle_count"], 2)
        self.assertEqual(state["memory"][0]["cycle_count"], 2)

    def test_runtime_state_loader_treats_missing_file_as_fresh_cycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "missing-runtime-state.json"
            self.assertIsNone(load_runtime_state_accumulator(state_path))

    def test_runtime_state_loader_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "bad-runtime-state.json"
            state_path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                load_runtime_state_accumulator(state_path)

    def test_runtime_state_loader_accepts_v040_payloads(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.runtime_state_accumulator.to_dict()
        payload["mode"] = "runtime-state-accumulator-v0.40"

        loaded = runtime_state_accumulator_from_dict(payload)

        self.assertEqual(loaded.mode, "runtime-state-accumulator-v0.40")
        self.assertEqual(loaded.cycle_count, 1)
        self.assertEqual(loaded.memory[0].action, "continue-memory-relief")


if __name__ == "__main__":
    unittest.main()
