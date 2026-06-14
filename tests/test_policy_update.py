from __future__ import annotations

import threading
import unittest
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.calibration import FrameCalibration, RuntimeCalibrationReport
from fluidgateway.client import RuntimeEventClient, summarize_client_responses
from fluidgateway.control_packet import build_runtime_control_packet
from fluidgateway.control_state import apply_runtime_control_packet
from fluidgateway.gateway import build_runtime_gateway_tick
from fluidgateway.gateway_cycle import execute_runtime_gateway_tick
from fluidgateway.gateway_feedback import build_runtime_gateway_feedback
from fluidgateway.manager import (
    FrameManagerDirective,
    MemoryManagerDirective,
    RuntimeManagerDirective,
)
from fluidgateway.policy_update import build_runtime_policy_update
from fluidgateway.server import create_runtime_event_server


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimePolicyUpdateTests(unittest.TestCase):
    def test_runtime_policy_update_continues_pressure_policy(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        update = payload["runtime_policy_update"]
        frame = update["frame_updates"][0]
        memory = update["memory_updates"][0]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.42")
        self.assertEqual(update["mode"], "runtime-policy-update-v0.39")
        self.assertEqual(update["profile"], "aggressive")
        self.assertEqual(update["next_profile"], "aggressive")
        self.assertEqual(
            update["source_feedback_action"],
            "continue-pressure-management",
        )
        self.assertEqual(update["policy_action"], "continue-runtime-pressure-policy")
        self.assertEqual(update["convergence_status"], "diverging")
        self.assertEqual(update["drift_risk"], "high")
        self.assertEqual(update["update_count"], 2)
        self.assertEqual(update["frame_update_count"], 1)
        self.assertEqual(update["memory_update_count"], 1)
        self.assertEqual(update["active_update_count"], 2)
        self.assertEqual(update["next_frame_budget_ms"], 6.0)
        self.assertEqual(update["hot_path_budget_ms"], 6.0)
        self.assertEqual(update["copy_queue_budget_ms"], 0)
        self.assertEqual(update["pre_frame_window_ms"], 4.5)
        self.assertEqual(update["memory_relief_target_mb"], 40)
        self.assertEqual(update["memory_headroom_target_mb"], 0)
        self.assertEqual(frame["action"], "continue-frame-pressure-management")
        self.assertEqual(frame["admission_policy"], "prestage-and-defer-noncritical")
        self.assertEqual(frame["scheduler_policy"], "closed-loop-aggressive")
        self.assertEqual(frame["guardband_ms"], 1.625)
        self.assertEqual(memory["action"], "continue-memory-relief")
        self.assertEqual(memory["residency_policy"], "evict-or-defer-residency")
        self.assertEqual(memory["relief_target_mb"], 40)

    def test_runtime_event_server_reports_runtime_policy_update(self):
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
        update = summary["runtime_policy_update"]
        frame = update["frame_updates"][0]
        memory = update["memory_updates"][0]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.42")
        self.assertEqual(update["mode"], "runtime-policy-update-v0.39")
        self.assertEqual(update["profile"], "stable")
        self.assertEqual(update["next_profile"], "stable")
        self.assertEqual(update["policy_action"], "preserve-runtime-cycle-policy")
        self.assertEqual(update["convergence_status"], "stable")
        self.assertEqual(update["drift_risk"], "low")
        self.assertEqual(update["next_frame_budget_ms"], 8)
        self.assertEqual(update["hot_path_budget_ms"], 8)
        self.assertEqual(update["copy_queue_budget_ms"], 1.2)
        self.assertEqual(update["pre_frame_window_ms"], 4.2)
        self.assertEqual(update["memory_relief_target_mb"], 0)
        self.assertEqual(update["memory_headroom_target_mb"], 0)
        self.assertEqual(frame["action"], "preserve-cycle-shape")
        self.assertEqual(frame["admission_policy"], "preserve-budgeted-hot-path")
        self.assertEqual(frame["scheduler_policy"], "closed-loop-stable")
        self.assertEqual(memory["action"], "hold-memory-residency")
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_policy_update_preserves_memory_headroom(self):
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
        calibration = RuntimeCalibrationReport(
            mode="runtime-calibration-report-v0.32",
            frame_count=1,
            over_budget_observed_count=0,
            over_budget_planned_count=0,
            total_observed_frame_cost_ms=7.0,
            total_planned_current_frame_cost_ms=7.0,
            total_planned_frame_relief_ms=0.0,
            total_pre_frame_cost_ms=0.0,
            total_deferred_cost_ms=0.0,
            total_avoided_cost_ms=0.0,
            total_memory_relief_mb=0.0,
            max_guardband_ms=0.0,
            recommended_next_frame_budget_ms=8.0,
            action_count=0,
            frames=[
                FrameCalibration(
                    frame=0,
                    target_frame_ms=8.0,
                    observed_frame_cost_ms=7.0,
                    planned_current_frame_cost_ms=7.0,
                    planned_pre_frame_cost_ms=0.0,
                    planned_deferred_cost_ms=0.0,
                    planned_avoided_cost_ms=0.0,
                    planned_frame_relief_ms=0.0,
                    guardband_ms=0.0,
                    recommended_next_frame_budget_ms=8.0,
                    observed_pressure_status="within-budget",
                    planned_pressure_status="within-budget",
                    action="monitor",
                    confidence="medium",
                )
            ],
        )

        packet = build_runtime_control_packet(manager)
        state = apply_runtime_control_packet(packet)
        tick = build_runtime_gateway_tick(state)
        cycle = execute_runtime_gateway_tick(tick)
        feedback = build_runtime_gateway_feedback(cycle, calibration)
        update = build_runtime_policy_update(feedback).to_dict()
        memory = update["memory_updates"][0]

        self.assertEqual(update["mode"], "runtime-policy-update-v0.39")
        self.assertEqual(update["policy_action"], "preserve-memory-headroom-policy")
        self.assertEqual(update["next_profile"], "stable")
        self.assertEqual(update["memory_headroom_target_mb"], 15.0)
        self.assertEqual(update["memory_relief_target_mb"], 0)
        self.assertEqual(update["active_update_count"], 1)
        self.assertEqual(memory["action"], "preserve-memory-headroom")
        self.assertEqual(memory["residency_policy"], "reserve-headroom")
        self.assertEqual(memory["headroom_target_mb"], 15.0)


if __name__ == "__main__":
    unittest.main()
