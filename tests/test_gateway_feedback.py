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
from fluidgateway.server import create_runtime_event_server


FIXTURES = Path(__file__).parent / "fixtures"


class RuntimeGatewayFeedbackTests(unittest.TestCase):
    def test_runtime_gateway_feedback_reports_pressure_delta(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        feedback = payload["runtime_gateway_feedback"]
        frame = feedback["frame_feedbacks"][0]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.44")
        self.assertEqual(feedback["mode"], "runtime-gateway-feedback-delta-v0.38")
        self.assertEqual(feedback["profile"], "aggressive")
        self.assertEqual(feedback["feedback_action"], "continue-pressure-management")
        self.assertEqual(feedback["convergence_status"], "diverging")
        self.assertEqual(feedback["drift_risk"], "high")
        self.assertEqual(feedback["confidence"], "medium")
        self.assertEqual(feedback["frame_count"], 1)
        self.assertEqual(feedback["memory_layer_count"], 3)
        self.assertEqual(feedback["pressure_frame_count"], 1)
        self.assertEqual(feedback["protected_gap_frame_count"], 1)
        self.assertEqual(feedback["observed_frame_cost_ms"], 12.5)
        self.assertEqual(feedback["target_frame_budget_ms"], 8.0)
        self.assertEqual(feedback["planned_current_frame_cost_ms"], 0)
        self.assertEqual(feedback["next_frame_budget_ms"], 6.0)
        self.assertEqual(feedback["hot_path_budget_ms"], 6.0)
        self.assertEqual(feedback["observed_over_budget_ms"], 4.5)
        self.assertEqual(feedback["planned_over_budget_ms"], 0)
        self.assertEqual(feedback["protected_gap_ms"], 6.5)
        self.assertEqual(feedback["planned_frame_relief_ms"], 12.5)
        self.assertEqual(feedback["memory_relief_expected_mb"], 40)
        self.assertEqual(feedback["memory_relief_applied_mb"], 40)
        self.assertEqual(feedback["memory_headroom_reserved_mb"], 0)
        self.assertEqual(feedback["memory_delta_mb"], 0)
        self.assertEqual(frame["feedback_action"], "continue-pressure-management")
        self.assertEqual(frame["protected_gap_ms"], 6.5)

    def test_runtime_event_server_reports_runtime_gateway_feedback(self):
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
        feedback = summary["runtime_gateway_feedback"]
        frame = feedback["frame_feedbacks"][0]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.44")
        self.assertEqual(feedback["mode"], "runtime-gateway-feedback-delta-v0.38")
        self.assertEqual(feedback["profile"], "stable")
        self.assertEqual(feedback["feedback_action"], "preserve-cycle-shape")
        self.assertEqual(feedback["convergence_status"], "stable")
        self.assertEqual(feedback["drift_risk"], "low")
        self.assertEqual(feedback["pressure_frame_count"], 0)
        self.assertEqual(feedback["protected_gap_frame_count"], 0)
        self.assertEqual(feedback["observed_frame_cost_ms"], 7.4)
        self.assertEqual(feedback["planned_current_frame_cost_ms"], 3.2)
        self.assertEqual(feedback["next_frame_budget_ms"], 8)
        self.assertEqual(feedback["observed_over_budget_ms"], 0)
        self.assertEqual(feedback["planned_over_budget_ms"], 0)
        self.assertEqual(feedback["protected_gap_ms"], 0)
        self.assertEqual(feedback["memory_delta_mb"], 0)
        self.assertEqual(frame["feedback_action"], "preserve-cycle-shape")
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_gateway_feedback_covers_memory_headroom(self):
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
        feedback = build_runtime_gateway_feedback(cycle, calibration).to_dict()

        self.assertEqual(feedback["mode"], "runtime-gateway-feedback-delta-v0.38")
        self.assertEqual(feedback["feedback_action"], "monitor-headroom")
        self.assertEqual(feedback["convergence_status"], "watching-headroom")
        self.assertEqual(feedback["drift_risk"], "medium")
        self.assertEqual(feedback["memory_headroom_reserved_mb"], 15.0)
        self.assertEqual(feedback["memory_relief_expected_mb"], 0)
        self.assertEqual(feedback["memory_relief_applied_mb"], 0)
        self.assertEqual(feedback["protected_gap_ms"], 0)
        self.assertEqual(
            feedback["frame_feedbacks"][0]["feedback_action"],
            "monitor-cycle",
        )


if __name__ == "__main__":
    unittest.main()
