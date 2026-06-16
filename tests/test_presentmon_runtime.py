from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from fluidgateway.adapter import replay_adapter_event_stream
from fluidgateway.analyzer import analyze_trace
from fluidgateway.cli import main
from fluidgateway.daemon import run_runtime_daemon
from fluidgateway.parser import parse_presentmon_csv
from fluidgateway.presentmon_daemon import run_presentmon_daemon
from fluidgateway.presentmon_runtime import (
    build_presentmon_runtime_event_stream,
    write_presentmon_runtime_events,
)
from tests.test_native_backend_probe import build_balanced_host


FIXTURES = Path(__file__).parent / "fixtures"


class PresentMonRuntimeEventTests(unittest.TestCase):
    def test_presentmon_analysis_becomes_runtime_adapter_events(self):
        report = analyze_trace(parse_presentmon_csv(FIXTURES / "gpu_wait.csv"))
        stream = build_presentmon_runtime_event_stream(report)
        payload = stream.to_dict()
        session = payload["events"][0]
        operation_actions = {
            event["management_action_id"]
            for event in payload["events"]
            if event.get("event") == "operation"
        }

        self.assertEqual(payload["mode"], "presentmon-runtime-event-ingest-v0.59")
        self.assertEqual(payload["application"], "BubbleGame.exe")
        self.assertEqual(payload["session_id"], "presentmon-bubblegame-exe")
        self.assertEqual(payload["target_frame_ms"], 16.6)
        self.assertEqual(payload["finding_count"], 1)
        self.assertEqual(payload["management_action_count"], 3)
        self.assertEqual(payload["resource_event_count"], 4)
        self.assertEqual(payload["operation_event_count"], 3)
        self.assertEqual(session["budgets"]["frame_ms"], 16.6)
        self.assertEqual(session["budgets"]["vram_mb"], 48.0)
        self.assertIn("gpu-work-prefetch-budget", operation_actions)
        self.assertIn("early-handoff-scheduler", operation_actions)
        self.assertIn("ram-vram-residency-manager", operation_actions)

    def test_written_presentmon_events_replay_through_adapter_manager(self):
        report = analyze_trace(parse_presentmon_csv(FIXTURES / "gpu_wait.csv"))
        stream = build_presentmon_runtime_event_stream(report)

        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = write_presentmon_runtime_events(
                stream,
                Path(temp_dir) / "presentmon-runtime-events",
            )
            result = replay_adapter_event_stream(events_path)
            payload = result.to_dict()

        self.assertEqual(events_path.suffix, ".jsonl")
        self.assertEqual(payload["events_processed"], 12)
        self.assertEqual(payload["operation_events"], 3)
        self.assertGreater(payload["policy_action_count"], 0)
        self.assertEqual(payload["runtime_manager"]["profile"], "aggressive")
        self.assertGreaterEqual(payload["runtime_manager"]["memory_action_count"], 1)
        self.assertEqual(
            payload["runtime_state_accumulator"]["profile"],
            "aggressive",
        )

    def test_runtime_ingest_presentmon_cli_writes_daemon_consumable_stream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "presentmon-events.jsonl"
            with redirect_stdout(StringIO()) as stdout:
                status = main(
                    [
                        "runtime",
                        "ingest-presentmon",
                        "--presentmon",
                        str(FIXTURES / "gpu_wait.csv"),
                        "--out",
                        str(events_path),
                    ]
                )
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            report = run_runtime_daemon(
                [events_path],
                host_snapshot=build_balanced_host(),
            )
            payload = report.to_dict()

        self.assertEqual(status, 0)
        self.assertIn("PresentMon runtime events written", stdout.getvalue())
        self.assertEqual(events[0]["mode"], "presentmon-runtime-event-ingest-v0.59")
        self.assertEqual(payload["events_processed"], 12)
        self.assertEqual(payload["operation_events"], 3)
        self.assertEqual(payload["final_state"]["profile"], "aggressive")
        self.assertEqual(
            payload["daemon_decision_action"],
            "tighten-daemon-memory-observation",
        )
        self.assertEqual(
            payload["native_backend_gate_policy"],
            "advance-safe-paths-hold-native",
        )
        self.assertEqual(payload["native_backend_gate_advance_count"], 1)
        self.assertEqual(payload["native_backend_gate_blocked_count"], 1)
        self.assertEqual(payload["native_backend_gate_native_blocked_count"], 1)

    def test_presentmon_daemon_runner_preserves_events_and_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "events"
            result = run_presentmon_daemon(
                presentmon_path=FIXTURES / "gpu_wait.csv",
                events_output_path=events_path,
                host_snapshot=build_balanced_host(),
            )
            payload = result.report.to_dict()
            events = [
                json.loads(line)
                for line in result.events_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result.mode, "presentmon-daemon-run-v0.60")
        self.assertEqual(result.events_path.suffix, ".jsonl")
        self.assertEqual(result.event_stream.application, "BubbleGame.exe")
        self.assertEqual(len(events), 12)
        self.assertEqual(events[0]["mode"], "presentmon-runtime-event-ingest-v0.59")
        self.assertEqual(payload["events_processed"], 12)
        self.assertEqual(payload["operation_events"], 3)
        self.assertEqual(payload["final_state"]["profile"], "aggressive")
        self.assertEqual(
            payload["native_backend_gate_policy"],
            "advance-safe-paths-hold-native",
        )
        self.assertFalse(payload["native_backend_gate"]["native_promotion_allowed"])

    def test_runtime_run_presentmon_daemon_cli_writes_all_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            events_path = temp / "events.jsonl"
            state_path = temp / "state.json"
            report_path = temp / "report.json"
            with redirect_stdout(StringIO()) as stdout:
                status = main(
                    [
                        "runtime",
                        "run-presentmon-daemon",
                        "--presentmon",
                        str(FIXTURES / "gpu_wait.csv"),
                        "--events-out",
                        str(events_path),
                        "--state",
                        str(state_path),
                        "--out",
                        str(report_path),
                    ]
                )
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            state = json.loads(state_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertIn("PresentMon application: BubbleGame.exe", stdout.getvalue())
        self.assertIn("Daemon cycles: 1", stdout.getvalue())
        self.assertEqual(events[0]["mode"], "presentmon-runtime-event-ingest-v0.59")
        self.assertEqual(state["profile"], "aggressive")
        self.assertEqual(report["cycle_count"], 1)
        self.assertEqual(report["events_processed"], 12)
        self.assertIn("native_backend_gate", report)

    def test_runtime_run_presentmon_daemon_rejects_output_path_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            same_path = temp / "same"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                status = main(
                    [
                        "runtime",
                        "run-presentmon-daemon",
                        "--presentmon",
                        str(FIXTURES / "gpu_wait.csv"),
                        "--events-out",
                        str(temp / "events.jsonl"),
                        "--state",
                        str(same_path),
                        "--out",
                        str(same_path),
                    ]
                )

        self.assertEqual(status, 1)


if __name__ == "__main__":
    unittest.main()
