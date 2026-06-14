from __future__ import annotations

import threading
import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.client import RuntimeEventClient, summarize_client_responses
from fluidgateway.server import create_runtime_event_server
from fluidgateway.state_accumulator import build_runtime_state_accumulator


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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.40")
        self.assertEqual(state["mode"], "runtime-state-accumulator-v0.40")
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.40")
        self.assertEqual(state["mode"], "runtime-state-accumulator-v0.40")
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


if __name__ == "__main__":
    unittest.main()
