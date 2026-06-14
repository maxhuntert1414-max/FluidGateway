from __future__ import annotations

import threading
import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.client import RuntimeEventClient, summarize_client_responses
from fluidgateway.control_packet import build_runtime_control_packet
from fluidgateway.control_state import apply_runtime_control_packet
from fluidgateway.gateway import build_runtime_gateway_tick
from fluidgateway.manager import (
    FrameManagerDirective,
    MemoryManagerDirective,
    RuntimeManagerDirective,
)
from fluidgateway.server import create_runtime_event_server


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeGatewayTickTests(unittest.TestCase):
    def test_runtime_gateway_tick_builds_pressure_management_lanes(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        tick = payload["runtime_gateway_tick"]
        steps = tick["steps"]
        memory = {step["memory"]: step for step in steps if step["domain"] == "memory"}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.38")
        self.assertEqual(tick["mode"], "runtime-gateway-tick-v0.36")
        self.assertEqual(tick["profile"], "aggressive")
        self.assertEqual(tick["tick_policy"], "closed-loop-pressure-management")
        self.assertEqual(tick["step_count"], 9)
        self.assertEqual(tick["active_step_count"], 9)
        self.assertEqual(tick["frame_count"], 1)
        self.assertEqual(tick["memory_layer_count"], 3)
        self.assertEqual(tick["display_lane_step_count"], 1)
        self.assertEqual(tick["cpu_lane_step_count"], 2)
        self.assertEqual(tick["gpu_lane_step_count"], 1)
        self.assertEqual(tick["copy_queue_step_count"], 1)
        self.assertEqual(tick["scheduler_step_count"], 1)
        self.assertEqual(tick["memory_lane_step_count"], 3)
        self.assertEqual(tick["memory_active_step_count"], 3)
        self.assertEqual(tick["next_frame_budget_ms"], 6.0)
        self.assertEqual(tick["hot_path_budget_ms"], 6.0)
        self.assertEqual(tick["copy_queue_budget_ms"], 0)
        self.assertEqual(tick["pre_frame_window_ms"], 4.5)
        self.assertEqual(tick["memory_relief_target_mb"], 40)
        self.assertEqual(
            [step["sequence"] for step in steps],
            list(range(1, 10)),
        )
        self.assertEqual(
            [step["action"] for step in steps],
            [
                "protect_next_frame_budget",
                "protect_gpu_hot_path",
                "block_late_copy_queue",
                "reserve_pre_frame_window",
                "apply_admission_mode",
                "apply_scheduler_mode",
                "relieve_memory_residency",
                "relieve_memory_residency",
                "relieve_memory_residency",
            ],
        )
        self.assertEqual(steps[0]["lane"], "display-frame")
        self.assertEqual(steps[1]["lane"], "gpu-hot-path")
        self.assertEqual(steps[2]["lane"], "copy-queue")
        self.assertEqual(steps[3]["lane"], "cpu-pre-frame")
        self.assertEqual(steps[4]["lane"], "cpu-admission")
        self.assertEqual(steps[5]["lane"], "scheduler")
        self.assertEqual(memory["ram"]["lane"], "memory:ram")
        self.assertEqual(memory["ram"]["budget_mb"], 16)
        self.assertTrue(memory["ram"]["active"])
        self.assertEqual(memory["vram"]["budget_mb"], 16)
        self.assertTrue(memory["vram"]["active"])
        self.assertEqual(memory["swapchain"]["budget_mb"], 8)
        self.assertTrue(memory["swapchain"]["active"])

    def test_runtime_event_server_reports_runtime_gateway_tick(self):
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
        tick = summary["runtime_gateway_tick"]
        steps = tick["steps"]
        memory = {step["memory"]: step for step in steps if step["domain"] == "memory"}

        self.assertEqual(summary["mode"], "runtime-event-client-v0.38")
        self.assertEqual(tick["mode"], "runtime-gateway-tick-v0.36")
        self.assertEqual(tick["profile"], "stable")
        self.assertEqual(tick["tick_policy"], "stable-budget-guard")
        self.assertEqual(tick["step_count"], 8)
        self.assertEqual(tick["active_step_count"], 6)
        self.assertEqual(tick["memory_layer_count"], 2)
        self.assertEqual(tick["memory_lane_step_count"], 2)
        self.assertEqual(tick["memory_active_step_count"], 0)
        self.assertEqual(tick["copy_queue_budget_ms"], 1.2)
        self.assertEqual(steps[2]["action"], "budget_copy_queue")
        self.assertEqual(steps[4]["setting"], "preserve-budgeted-hot-path")
        self.assertEqual(steps[5]["setting"], "closed-loop-stable")
        self.assertEqual(memory["ram"]["action"], "hold_memory_residency")
        self.assertFalse(memory["ram"]["active"])
        self.assertEqual(memory["vram"]["action"], "hold_memory_residency")
        self.assertFalse(memory["vram"]["active"])
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_gateway_tick_covers_memory_reserve_and_observe(self):
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
        state = apply_runtime_control_packet(packet)
        tick = build_runtime_gateway_tick(state).to_dict()
        memory = {
            step["memory"]: step
            for step in tick["steps"]
            if step["domain"] == "memory"
        }

        self.assertEqual(tick["mode"], "runtime-gateway-tick-v0.36")
        self.assertEqual(tick["tick_policy"], "closed-loop-pressure-management")
        self.assertEqual(tick["step_count"], 8)
        self.assertEqual(tick["active_step_count"], 7)
        self.assertEqual(tick["memory_active_step_count"], 1)
        self.assertEqual(memory["vram"]["action"], "reserve_memory_headroom")
        self.assertEqual(memory["vram"]["budget_mb"], 15.0)
        self.assertTrue(memory["vram"]["active"])
        self.assertEqual(memory["shared"]["action"], "observe_memory_residency")
        self.assertEqual(memory["shared"]["budget_mb"], 0)
        self.assertFalse(memory["shared"]["active"])


if __name__ == "__main__":
    unittest.main()
