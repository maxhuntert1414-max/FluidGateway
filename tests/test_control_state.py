from __future__ import annotations

import threading
import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.client import RuntimeEventClient, summarize_client_responses
from fluidgateway.control_packet import build_runtime_control_packet
from fluidgateway.control_state import apply_runtime_control_packet
from fluidgateway.manager import (
    FrameManagerDirective,
    MemoryManagerDirective,
    RuntimeManagerDirective,
)
from fluidgateway.server import create_runtime_event_server


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeControlStateTests(unittest.TestCase):
    def test_runtime_control_state_dry_run_applies_pressure_packet(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        state = payload["runtime_control_state"]
        frame = state["frames"][0]
        memory = {layer["memory"]: layer for layer in state["memory_layers"]}

        self.assertEqual(state["mode"], "runtime-control-state-v0.35")
        self.assertEqual(state["profile"], "aggressive")
        self.assertEqual(state["dispatch_action"], "activate-dispatch-profile")
        self.assertEqual(state["command_count"], 9)
        self.assertEqual(state["active_command_count"], 9)
        self.assertEqual(state["frame_count"], 1)
        self.assertEqual(state["memory_layer_count"], 3)
        self.assertEqual(state["applied_frame_budget_count"], 2)
        self.assertEqual(state["applied_queue_budget_count"], 2)
        self.assertEqual(state["applied_scheduler_mode_count"], 2)
        self.assertEqual(state["memory_action_count"], 3)
        self.assertEqual(state["next_frame_budget_ms"], 6.0)
        self.assertEqual(state["hot_path_budget_ms"], 6.0)
        self.assertEqual(state["copy_queue_budget_ms"], 0)
        self.assertEqual(state["pre_frame_window_ms"], 4.5)
        self.assertEqual(state["total_expected_memory_relief_mb"], 40)
        self.assertEqual(frame["next_frame_budget_ms"], 6.0)
        self.assertEqual(frame["hot_path_budget_ms"], 6.0)
        self.assertEqual(frame["copy_queue_budget_ms"], 0)
        self.assertEqual(frame["pre_frame_window_ms"], 4.5)
        self.assertEqual(frame["admission_mode"], "prestage-and-defer-noncritical")
        self.assertEqual(frame["scheduler_mode"], "closed-loop-aggressive")
        self.assertEqual(frame["priority"], "high")
        self.assertEqual(frame["command_count"], 6)
        self.assertEqual(frame["active_command_count"], 6)
        self.assertTrue(memory["ram"]["active"])
        self.assertEqual(memory["ram"]["command"], "evict_or_defer_residency")
        self.assertEqual(memory["ram"]["expected_relief_mb"], 16)
        self.assertTrue(memory["vram"]["active"])
        self.assertEqual(memory["vram"]["expected_relief_mb"], 16)
        self.assertTrue(memory["swapchain"]["active"])
        self.assertEqual(memory["swapchain"]["expected_relief_mb"], 8)

    def test_runtime_event_server_reports_runtime_control_state(self):
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
        state = summary["runtime_control_state"]
        frame = state["frames"][0]
        memory = {layer["memory"]: layer for layer in state["memory_layers"]}

        self.assertEqual(summary["mode"], "runtime-event-client-v0.40")
        self.assertEqual(state["mode"], "runtime-control-state-v0.35")
        self.assertEqual(state["profile"], "stable")
        self.assertEqual(state["dispatch_action"], "preserve-dispatch-profile")
        self.assertEqual(state["command_count"], 8)
        self.assertEqual(state["active_command_count"], 6)
        self.assertEqual(state["frame_count"], 1)
        self.assertEqual(state["memory_layer_count"], 2)
        self.assertEqual(state["applied_frame_budget_count"], 2)
        self.assertEqual(state["applied_queue_budget_count"], 2)
        self.assertEqual(state["applied_scheduler_mode_count"], 2)
        self.assertEqual(state["memory_action_count"], 0)
        self.assertEqual(frame["next_frame_budget_ms"], 8)
        self.assertEqual(frame["hot_path_budget_ms"], 8)
        self.assertEqual(frame["copy_queue_budget_ms"], 1.2)
        self.assertEqual(frame["pre_frame_window_ms"], 4.2)
        self.assertEqual(frame["admission_mode"], "preserve-budgeted-hot-path")
        self.assertEqual(frame["scheduler_mode"], "closed-loop-stable")
        self.assertFalse(memory["ram"]["active"])
        self.assertEqual(memory["ram"]["command"], "hold_residency")
        self.assertFalse(memory["vram"]["active"])
        self.assertEqual(memory["vram"]["command"], "hold_residency")
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_control_state_covers_memory_reserve_and_observe(self):
        manager = RuntimeManagerDirective(
            mode="runtime-manager-directive-v0.33",
            profile="stable",
            next_frame_policy="tighten-memory-admission",
            dispatch_action="monitor-runtime",
            frame_count=1,
            memory_layer_count=2,
            memory_action_count=1,
            control_action_count=1,
            next_frame_budget_ms=8.0,
            hot_path_budget_ms=8.0,
            copy_queue_budget_ms=1.2,
            pre_frame_window_ms=4.2,
            total_expected_memory_relief_mb=0.0,
            frames=[
                FrameManagerDirective(
                    frame=0,
                    target_frame_ms=8.0,
                    observed_frame_cost_ms=7.0,
                    planned_current_frame_cost_ms=7.0,
                    expected_frame_relief_ms=0.0,
                    next_frame_budget_ms=8.0,
                    hot_path_budget_ms=8.0,
                    copy_queue_budget_ms=1.2,
                    pre_frame_window_ms=4.2,
                    guardband_ms=0.0,
                    admission_mode="observe-admission",
                    scheduler_mode="observe",
                    queue_policy="budget-copy-queue",
                    calibration_action="monitor",
                    reason="Synthetic direct branch coverage.",
                )
            ],
            memory_directives=[
                MemoryManagerDirective(
                    memory="vram",
                    active_mb=85.0,
                    budget_mb=100.0,
                    pressure_mb=0.0,
                    status="near-budget",
                    action="reserve-headroom",
                    expected_relief_mb=0.0,
                    reserve_headroom_mb=15.0,
                    reason="Synthetic near-budget layer.",
                ),
                MemoryManagerDirective(
                    memory="shared",
                    active_mb=32.0,
                    budget_mb=None,
                    pressure_mb=0.0,
                    status="unbounded",
                    action="observe-residency",
                    expected_relief_mb=0.0,
                    reserve_headroom_mb=0.0,
                    reason="Synthetic unbounded layer.",
                ),
            ],
        )

        packet = build_runtime_control_packet(manager)
        state = apply_runtime_control_packet(packet).to_dict()
        memory = {layer["memory"]: layer for layer in state["memory_layers"]}

        self.assertEqual(state["mode"], "runtime-control-state-v0.35")
        self.assertEqual(state["command_count"], 8)
        self.assertEqual(state["active_command_count"], 7)
        self.assertEqual(state["memory_action_count"], 1)
        self.assertEqual(state["memory_layer_count"], 2)
        self.assertEqual(state["applied_frame_budget_count"], 2)
        self.assertEqual(state["applied_queue_budget_count"], 2)
        self.assertEqual(state["applied_scheduler_mode_count"], 2)
        self.assertTrue(memory["vram"]["active"])
        self.assertEqual(memory["vram"]["command"], "reserve_memory_headroom")
        self.assertEqual(memory["vram"]["reserve_headroom_mb"], 15.0)
        self.assertEqual(memory["vram"]["expected_relief_mb"], 0)
        self.assertFalse(memory["shared"]["active"])
        self.assertEqual(memory["shared"]["command"], "observe_residency")


if __name__ == "__main__":
    unittest.main()
