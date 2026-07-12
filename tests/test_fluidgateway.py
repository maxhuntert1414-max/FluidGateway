from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from fluidgateway.cli import main
from fluidgateway.analyzer import analyze_trace
from fluidgateway.adapter import RuntimeAdapterSession, replay_adapter_event_stream
from fluidgateway.client import RuntimeEventClient, summarize_client_responses
from fluidgateway.control import FluidGatewayController
from fluidgateway.control_packet import build_runtime_control_packet
from fluidgateway.events import replay_event_stream, write_event_replay
from fluidgateway.manager import (
    FrameManagerDirective,
    MemoryManagerDirective,
    RuntimeManagerDirective,
)
from fluidgateway.parser import parse_number, parse_presentmon_csv
from fluidgateway.report import write_report
from fluidgateway.runtime import load_manifest, optimize_manifest, write_runtime_plan
from fluidgateway.server import create_runtime_event_server
from fluidgateway.tracker import summarize_registry, track_trace


FIXTURES = Path(__file__).parent / "fixtures"


class FluidGatewayTests(unittest.TestCase):
    def analyze_fixture(self, name: str):
        trace = parse_presentmon_csv(FIXTURES / name)
        return analyze_trace(trace)

    def assert_has_finding(self, report, finding_id: str):
        ids = {finding.id for finding in report.findings}
        self.assertIn(finding_id, ids)

    def test_parse_number_accepts_na_ms_and_decimal_comma(self):
        self.assertIsNone(parse_number("NA"))
        self.assertEqual(parse_number("12.5 ms"), 12.5)
        self.assertEqual(parse_number("12,5"), 12.5)

    def test_legacy_presentmon_columns_are_canonicalized(self):
        trace = parse_presentmon_csv(FIXTURES / "legacy_presentmon.csv")
        report = analyze_trace(trace)

        self.assertEqual(trace.frames[0].present_runtime, "DXGI")
        self.assertEqual(trace.frames[0].number("MsBetweenPresents"), 16.4)
        self.assertIsNone(trace.frames[1].number("DisplayedTime"))
        self.assertNotIn("PresentRuntime", report.summary.missing_columns)
        self.assertNotIn("MsBetweenPresents", report.summary.missing_columns)
        self.assertNotIn("MsInPresentAPI", report.summary.missing_columns)
        self.assertNotIn("MsUntilDisplayed", report.summary.missing_columns)
        self.assertNotIn("MsRenderPresentLatency", report.summary.missing_columns)
        self.assertNotIn("DisplayedTime", report.summary.missing_columns)
        self.assertIsNotNone(report.summary.duration_ms)
        self.assertIsNotNone(report.summary.approx_fps)
        self.assert_has_finding(report, "undisplayed-frames")

    def test_clean_trace_has_no_medium_or_worse_findings(self):
        report = self.analyze_fixture("clean.csv")
        severe = [finding for finding in report.findings if finding.score >= 45]
        self.assertEqual(severe, [])

    def test_copy_present_mode_triggers_copy_path_finding(self):
        report = self.analyze_fixture("copy_present.csv")
        self.assert_has_finding(report, "presentation-copy-path")

    def test_high_present_wait_triggers_cpu_wait_finding(self):
        report = self.analyze_fixture("high_present_wait.csv")
        self.assert_has_finding(report, "cpu-present-wait")

    def test_gpu_wait_triggers_gpu_bubbles_finding(self):
        report = self.analyze_fixture("gpu_wait.csv")
        self.assert_has_finding(report, "gpu-bubbles")

    def test_gpu_wait_triggers_ram_vram_management_action(self):
        report = self.analyze_fixture("gpu_wait.csv")
        action_ids = {action.id for action in report.management_plan.actions}
        self.assertIn("ram-vram-residency-manager", action_ids)

    def test_irregular_pacing_triggers_pacing_finding(self):
        report = self.analyze_fixture("irregular_pacing.csv")
        self.assert_has_finding(report, "unstable-frame-pacing")

    def test_missing_columns_do_not_break_analysis(self):
        trace = parse_presentmon_csv(FIXTURES / "missing_columns.csv")
        report = analyze_trace(trace)
        self.assertGreater(len(report.summary.missing_columns), 0)
        self.assertEqual(report.summary.frame_count, 3)

    def test_na_displayed_time_triggers_undisplayed_finding(self):
        report = self.analyze_fixture("na_values.csv")
        self.assert_has_finding(report, "undisplayed-frames")

    def test_report_writer_creates_html_and_json(self):
        report = self.analyze_fixture("copy_present.csv")
        with tempfile.TemporaryDirectory() as tmp:
            html_path, json_path = write_report(report, Path(tmp) / "report.html")
            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("findings", payload)
            self.assertIn("management_plan", payload)
            self.assertGreater(len(payload["management_plan"]["actions"]), 0)
            self.assertIn("diagnostico inferido", payload["disclaimer"].lower())

    def test_manage_command_writes_management_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "management.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "manage",
                        "--presentmon",
                        str(FIXTURES / "gpu_wait.csv"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "advisory-management-v0.2")
            self.assertIn(
                "ram-vram-residency-manager",
                {action["id"] for action in payload["actions"]},
            )

    def test_track_trace_writes_registry_record(self):
        trace = parse_presentmon_csv(FIXTURES / "gpu_wait.csv")
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "traces.json"
            result = track_trace(
                trace,
                registry_path=registry,
                label="gpu wait baseline",
                tags=["baseline", "gpu"],
                notes="first tracked trace",
            )
            self.assertTrue(registry.exists())
            self.assertFalse(result.duplicate)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(len(payload["records"]), 1)
            record = payload["records"][0]
            self.assertEqual(record["label"], "gpu wait baseline")
            self.assertEqual(record["tags"], ["baseline", "gpu"])
            self.assertIn("gpu-bubbles", record["finding_ids"])
            self.assertIn(
                "ram-vram-residency-manager",
                record["management_action_ids"],
            )
            self.assertEqual(len(record["sha256"]), 64)

    def test_track_trace_marks_duplicate_hash(self):
        trace = parse_presentmon_csv(FIXTURES / "gpu_wait.csv")
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "traces.json"
            first = track_trace(trace, registry_path=registry)
            second = track_trace(trace, registry_path=registry)
            self.assertFalse(first.duplicate)
            self.assertTrue(second.duplicate)
            self.assertEqual(len(summarize_registry(registry)), 2)

    def test_track_and_history_commands_use_registry_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "traces.json"
            with redirect_stdout(StringIO()):
                track_status = main(
                    [
                        "track",
                        "--presentmon",
                        str(FIXTURES / "copy_present.csv"),
                        "--registry",
                        str(registry),
                        "--label",
                        "copy path trace",
                        "--tag",
                        "presentation",
                    ]
                )
            self.assertEqual(track_status, 0)

            output = StringIO()
            with redirect_stdout(output):
                history_status = main(["history", "--registry", str(registry)])
            self.assertEqual(history_status, 0)
            history_text = output.getvalue()
            self.assertIn("CopyGame.exe", history_text)
            self.assertIn("copy path trace", history_text)

    def test_runtime_optimizer_removes_redundant_pipeline_work(self):
        manifest = load_manifest(FIXTURES / "runtime_waste_manifest.json")
        plan = optimize_manifest(manifest)
        policies = {decision.policy for decision in plan.decisions}
        self.assertEqual(plan.mode, "runtime-optimizer-v0.4-manifest")
        self.assertLess(plan.optimized_operations, plan.original_operations)
        self.assertGreater(plan.estimated_saved_ms, 0)
        self.assertGreater(plan.estimated_saved_mb, 0)
        self.assertIn("deduplicate-identical-transfer", policies)
        self.assertIn("collapse-aliased-resource-copy", policies)
        self.assertIn("remove-orphan-sync", policies)
        self.assertIn("reuse-transient-buffer", policies)

    def test_runtime_optimize_command_writes_plan_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "runtime-plan.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "optimize",
                        "--manifest",
                        str(FIXTURES / "runtime_waste_manifest.json"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["manifest_name"], "runtime-waste-demo")
            self.assertLess(payload["optimized_operations"], payload["original_operations"])
            self.assertTrue(payload["decisions"])

    def test_write_runtime_plan_creates_json(self):
        manifest = load_manifest(FIXTURES / "runtime_waste_manifest.json")
        plan = optimize_manifest(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            output = write_runtime_plan(plan, Path(tmp) / "plan")
            self.assertEqual(output.suffix, ".json")
            self.assertTrue(output.exists())

    def test_control_plane_decides_before_redundant_operation_executes(self):
        controller = FluidGatewayController()
        controller.register_resource(
            "ram_texture",
            kind="texture",
            memory="ram",
            size_mb=32,
            aliases=["tex"],
        )
        controller.register_resource(
            "vram_texture",
            kind="texture",
            memory="vram",
            size_mb=32,
            aliases=["tex_gpu"],
        )

        first = controller.submit_operation(
            "upload_1",
            "upload",
            source="ram_texture",
            target="vram_texture",
            queue="copy",
            reason="initial upload",
            cost_ms=0.5,
            size_mb=32,
        )
        duplicate = controller.submit_operation(
            "upload_2",
            "upload",
            source="ram_texture",
            target="vram_texture",
            queue="copy",
            reason="duplicate upload",
            cost_ms=0.5,
            size_mb=32,
        )

        self.assertTrue(first.executed)
        self.assertFalse(duplicate.executed)
        self.assertEqual(duplicate.decision.policy, "deduplicate-identical-transfer")
        snapshot = controller.snapshot()
        self.assertEqual(snapshot["mode"], "runtime-control-plane-v0.5")
        self.assertEqual(len(snapshot["executed_operations"]), 1)
        self.assertEqual(len(snapshot["decisions"]), 1)
        self.assertEqual(snapshot["estimated_saved_mb"], 32)

    def test_runtime_simulate_control_command_writes_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "control-snapshot.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "simulate-control",
                        "--manifest",
                        str(FIXTURES / "runtime_waste_manifest.json"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-control-plane-v0.5")
            self.assertEqual(len(payload["executed_operations"]), 4)
            self.assertEqual(len(payload["decisions"]), 4)
            self.assertGreater(payload["estimated_saved_ms"], 0)

    def test_runtime_event_stream_replays_incremental_decisions(self):
        result = replay_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        policies = {
            item["decision"]["policy"]
            for item in payload["results"]
            if item["decision"] is not None
        }
        self.assertEqual(payload["mode"], "runtime-event-stream-v0.6")
        self.assertEqual(payload["resource_events"], 5)
        self.assertEqual(payload["operation_events"], 7)
        self.assertEqual(len(payload["snapshot"]["executed_operations"]), 3)
        self.assertEqual(len(payload["snapshot"]["decisions"]), 4)
        self.assertIn("reuse-transient-buffer", policies)
        self.assertIn("deduplicate-identical-transfer", policies)
        self.assertIn("collapse-aliased-resource-copy", policies)
        self.assertIn("remove-orphan-sync", policies)

    def test_runtime_replay_events_command_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "event-replay.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "replay-events",
                        "--events",
                        str(FIXTURES / "runtime_events.jsonl"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-event-stream-v0.6")
            self.assertEqual(payload["operation_events"], 7)
            self.assertGreater(payload["snapshot"]["estimated_saved_mb"], 0)

    def test_write_event_replay_creates_json(self):
        result = replay_event_stream(FIXTURES / "runtime_events.jsonl")
        with tempfile.TemporaryDirectory() as tmp:
            output = write_event_replay(result, Path(tmp) / "events")
            self.assertEqual(output.suffix, ".json")
            self.assertTrue(output.exists())

    def test_runtime_event_server_returns_decisions_over_tcp(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            lines = (FIXTURES / "runtime_events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            payload = ("\n".join(lines) + "\n").encode("utf-8")
            with socket.create_connection((host, port), timeout=5) as client:
                client.sendall(payload)
                client.shutdown(socket.SHUT_WR)
                received = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    received += chunk

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        responses = [
            json.loads(line)
            for line in received.decode("utf-8").splitlines()
            if line.strip()
        ]
        policies = {
            response["result"]["decision"]["policy"]
            for response in responses
            if response.get("event") == "operation"
            and response["result"]["decision"] is not None
        }
        self.assertEqual(len(responses), 12)
        self.assertTrue(all(response["ok"] for response in responses))
        self.assertIn("deduplicate-identical-transfer", policies)
        self.assertIn("remove-orphan-sync", policies)

    def test_runtime_event_client_sends_jsonl_to_server(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(FIXTURES / "runtime_events.jsonl")

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        policies = {
            response["result"]["decision"]["policy"]
            for response in responses
            if response.get("event") == "operation"
            and response["result"]["decision"] is not None
        }
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["events_sent"], 12)
        self.assertEqual(summary["resource_responses"], 5)
        self.assertEqual(summary["operation_responses"], 7)
        self.assertEqual(summary["decision_count"], 4)
        self.assertEqual(summary["failed_responses"], 0)
        self.assertIn("deduplicate-identical-transfer", policies)
        self.assertIn("remove-orphan-sync", policies)

    def test_runtime_send_events_command_writes_server_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "server-responses.json"
            with create_runtime_event_server("127.0.0.1", 0) as server:
                server.timeout = 5
                host, port = server.server_address
                thread = threading.Thread(target=server.handle_request)
                thread.start()

                stdout = StringIO()
                with redirect_stdout(stdout):
                    status = main(
                        [
                            "runtime",
                            "send-events",
                            "--events",
                            str(FIXTURES / "runtime_events.jsonl"),
                            "--host",
                            host,
                            "--port",
                            str(port),
                            "--out",
                            str(output),
                        ]
                    )

                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-event-client-v0.45")
            self.assertEqual(payload["events_sent"], 12)
            self.assertEqual(payload["decision_count"], 4)
            self.assertEqual(payload["failed_responses"], 0)
            self.assertIn("Events sent: 12", stdout.getvalue())
            self.assertIn("Decisions: 4", stdout.getvalue())
            self.assertIn("Failed responses: 0", stdout.getvalue())

    def test_adapter_session_replays_lifecycle_stream(self):
        result = replay_adapter_event_stream(FIXTURES / "adapter_session_events.jsonl")
        payload = result.to_dict()
        frame = payload["frames"][0]
        policies = {
            item["decision"]["policy"]
            for item in payload["results"]
            if item["decision"] is not None
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(payload["session_id"], "demo-adapter")
        self.assertEqual(payload["events_processed"], 12)
        self.assertEqual(payload["lifecycle_events"], 4)
        self.assertEqual(payload["resource_events"], 4)
        self.assertEqual(payload["operation_events"], 4)
        self.assertEqual(payload["released_resources"], ["scratch"])
        self.assertEqual(frame["frame"], 0)
        self.assertEqual(frame["operation_count"], 4)
        self.assertEqual(frame["decision_count"], 2)
        self.assertEqual(frame["end_event_index"], 11)
        self.assertIn("reuse-transient-buffer", policies)
        self.assertIn("deduplicate-identical-transfer", policies)
        self.assertTrue(
            all(item["operation"]["frame"] == 0 for item in payload["results"])
        )

    def test_runtime_run_adapter_command_writes_session_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "adapter-session.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "runtime",
                        "run-adapter",
                        "--events",
                        str(FIXTURES / "adapter_session_events.jsonl"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
            self.assertEqual(payload["snapshot"]["estimated_saved_mb"], 40)
            self.assertIn("Events processed: 12", stdout.getvalue())
            self.assertIn("Runtime manager profile:", stdout.getvalue())
            self.assertIn("Estimated saved MB moved/allocated: 40.0000", stdout.getvalue())

    def test_runtime_event_server_accepts_adapter_lifecycle_events(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(FIXTURES / "adapter_session_events.jsonl")

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        policies = {
            response["result"]["decision"]["policy"]
            for response in responses
            if response.get("event") == "operation"
            and response["result"]["decision"] is not None
        }
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["session_responses"], 2)
        self.assertEqual(summary["frame_responses"], 2)
        self.assertEqual(summary["decision_count"], 2)
        self.assertEqual(summary["failed_responses"], 0)
        self.assertIn("reuse-transient-buffer", policies)
        self.assertIn("deduplicate-identical-transfer", policies)

    def test_adapter_session_rejects_mismatched_frame_end(self):
        session = RuntimeAdapterSession()
        session.process_event({"event": "frame", "action": "begin", "frame": 1})
        with self.assertRaises(ValueError):
            session.process_event({"event": "frame", "action": "end", "frame": 2})

    def test_adapter_policy_engine_flags_frame_and_memory_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_policy_pressure_events.jsonl"
        )
        payload = result.to_dict()
        frame = payload["frames"][0]
        action_ids = {action["id"] for action in payload["policy_actions"]}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(payload["session_id"], "policy-pressure")
        self.assertEqual(payload["policy_action_count"], 3)
        self.assertEqual(frame["frame"], 0)
        self.assertEqual(frame["target_frame_ms"], 8)
        self.assertEqual(frame["estimated_total_cost_ms"], 10.9)
        self.assertEqual(frame["transfer_mb"], 64)
        self.assertEqual(frame["policy_action_count"], 3)
        self.assertIn("late-upload-pressure", action_ids)
        self.assertIn("vram-budget-pressure", action_ids)
        self.assertIn("frame-budget-pressure", action_ids)

    def test_runtime_run_adapter_command_writes_policy_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "adapter-policy-session.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "run-adapter",
                        "--events",
                        str(FIXTURES / "adapter_policy_pressure_events.jsonl"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
            self.assertEqual(payload["policy_action_count"], 3)

    def test_runtime_event_server_reports_policy_actions(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(
                    FIXTURES / "adapter_policy_pressure_events.jsonl"
                )

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["policy_action_count"], 3)
        self.assertEqual(summary["failed_responses"], 0)

    def test_adapter_lifetime_planner_outputs_resource_plan(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_lifetime_plan_events.jsonl"
        )
        payload = result.to_dict()
        plan = payload["lifetime_plan"]
        actions = {item["action"]: item for item in plan["actions"]}
        resource_actions = {
            (item["resource_id"], item["action"]) for item in plan["actions"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(plan["mode"], "resource-lifetime-plan-v0.11")
        self.assertEqual(plan["plan_action_count"], 4)
        self.assertEqual(plan["estimated_reduced_transfer_mb"], 64)
        self.assertEqual(plan["estimated_release_mb"], 32)
        self.assertIn(("vram_texture", "keep-resident"), resource_actions)
        self.assertIn(("scratch_upload", "release-after-frame"), resource_actions)
        self.assertIn(("upload_hero", "prefetch-before-frame"), resource_actions)
        self.assertIn(("upload_hero", "defer-upload"), resource_actions)
        self.assertEqual(actions["prefetch-before-frame"]["target_frame"], 0)

    def test_runtime_run_adapter_command_writes_lifetime_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "adapter-lifetime-session.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "run-adapter",
                        "--events",
                        str(FIXTURES / "adapter_lifetime_plan_events.jsonl"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
            self.assertEqual(payload["lifetime_plan"]["plan_action_count"], 4)

    def test_runtime_event_server_reports_lifetime_plan_delta(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(
                    FIXTURES / "adapter_lifetime_plan_events.jsonl"
                )

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["lifetime_plan_action_count"], 4)
        self.assertEqual(summary["failed_responses"], 0)

    def test_scheduler_simulator_moves_prefetch_out_of_critical_path(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_lifetime_plan_events.jsonl"
        )
        payload = result.to_dict()
        schedule = payload["schedule_plan"]
        frame = schedule["frames"][0]
        steps = schedule["steps"]

        self.assertEqual(schedule["mode"], "frame-scheduler-simulation-v0.12")
        self.assertEqual(schedule["scheduled_step_count"], 3)
        self.assertEqual(schedule["estimated_critical_path_before_ms"], 7.4)
        self.assertEqual(schedule["estimated_critical_path_after_ms"], 3.2)
        self.assertEqual(schedule["estimated_latency_reduction_ms"], 4.2)
        self.assertEqual(schedule["estimated_moved_transfer_mb"], 64)
        self.assertEqual(frame["budget_status_after"], "within-budget")
        self.assertEqual(steps[0]["phase"], "prefetch")
        self.assertEqual(steps[0]["operation_id"], "upload_hero")
        self.assertEqual(steps[-1]["phase"], "cleanup")
        self.assertEqual(steps[-1]["resource_id"], "scratch_upload")

    def test_runtime_run_adapter_command_writes_schedule_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "adapter-schedule-session.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "run-adapter",
                        "--events",
                        str(FIXTURES / "adapter_lifetime_plan_events.jsonl"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
            self.assertEqual(
                payload["schedule_plan"]["estimated_latency_reduction_ms"],
                4.2,
            )

    def test_runtime_event_server_reports_schedule_steps(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(
                    FIXTURES / "adapter_lifetime_plan_events.jsonl"
                )

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["schedule_step_count"], 3)
        self.assertEqual(summary["failed_responses"], 0)

    def test_enforcement_contract_converts_schedule_to_adapter_commands(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_lifetime_plan_events.jsonl"
        )
        payload = result.to_dict()
        enforcement = payload["enforcement_plan"]
        commands = enforcement["commands"]

        self.assertEqual(enforcement["mode"], "adapter-enforcement-contract-v0.13")
        self.assertEqual(enforcement["command_count"], 3)
        self.assertEqual(enforcement["commands_by_action"]["prefetch_now"], 1)
        self.assertEqual(enforcement["commands_by_action"]["execute_now"], 1)
        self.assertEqual(enforcement["commands_by_action"]["release_after_frame"], 1)
        self.assertEqual(commands[0]["action"], "prefetch_now")
        self.assertEqual(commands[0]["operation_id"], "upload_hero")
        self.assertEqual(commands[1]["action"], "execute_now")
        self.assertEqual(commands[1]["operation_id"], "draw_hero")
        self.assertEqual(commands[2]["action"], "release_after_frame")
        self.assertEqual(commands[2]["resource_id"], "scratch_upload")

    def test_runtime_run_adapter_command_writes_enforcement_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "adapter-enforcement-session.json"
            with redirect_stdout(StringIO()):
                status = main(
                    [
                        "runtime",
                        "run-adapter",
                        "--events",
                        str(FIXTURES / "adapter_lifetime_plan_events.jsonl"),
                        "--out",
                        str(output),
                    ]
                )
            self.assertEqual(status, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
            self.assertEqual(payload["enforcement_plan"]["command_count"], 3)

    def test_runtime_event_server_reports_enforcement_commands(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(
                    FIXTURES / "adapter_lifetime_plan_events.jsonl"
                )

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["enforcement_command_count"], 3)
        self.assertEqual(summary["failed_responses"], 0)

    def test_live_commands_are_returned_for_streamed_operations(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_lifetime_plan_events.jsonl"
        )
        payload = result.to_dict()
        live_by_operation = {
            item["operation"]["id"]: item["live_command"]["action"]
            for item in payload["results"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(payload["live_command_count"], 2)
        self.assertEqual(live_by_operation["upload_hero"], "prefetch_now")
        self.assertEqual(live_by_operation["draw_hero"], "execute_now")

    def test_live_commands_map_removed_work_to_reuse_or_defer(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        live_by_operation = {
            item["operation"]["id"]: item["live_command"]["action"]
            for item in payload["results"]
        }

        self.assertEqual(live_by_operation["alloc_scratch_2"], "reuse")
        self.assertEqual(live_by_operation["upload_texture_a_duplicate"], "defer")

    def test_runtime_event_server_reports_live_commands(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with RuntimeEventClient(host, port, timeout=5) as client:
                responses = client.send_jsonl(
                    FIXTURES / "adapter_lifetime_plan_events.jsonl"
                )

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        summary = summarize_client_responses(responses)
        operation_responses = [
            response for response in responses if response.get("event") == "operation"
        ]
        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["live_command_count"], 2)
        self.assertEqual(
            [response["live_command"]["action"] for response in operation_responses],
            ["prefetch_now", "execute_now"],
        )
        self.assertEqual(summary["failed_responses"], 0)

    def test_adapter_state_snapshot_is_queryable_during_frame(self):
        session = RuntimeAdapterSession()
        session.process_event(
            {
                "event": "session",
                "action": "begin",
                "id": "state-demo",
                "budgets": {"frame_ms": 8, "ram_mb": 96, "vram_mb": 96},
            }
        )
        session.process_event({"event": "frame", "action": "begin", "frame": 0})
        session.process_event(
            {
                "event": "resource",
                "id": "ram_texture",
                "kind": "texture",
                "memory": "ram",
                "size_mb": 64,
            }
        )
        session.process_event(
            {
                "event": "resource",
                "id": "vram_texture",
                "kind": "texture",
                "memory": "vram",
                "size_mb": 64,
            }
        )
        operation_response = session.process_event(
            {
                "event": "operation",
                "id": "upload_hero",
                "operation_type": "upload",
                "source": "ram_texture",
                "target": "vram_texture",
                "queue": "copy",
                "cost_ms": 4.2,
                "size_mb": 64,
            }
        )
        state_response = session.process_event({"event": "state", "action": "snapshot"})
        snapshot = state_response["state_snapshot"]

        self.assertEqual(operation_response["state_snapshot"]["live_command_count"], 1)
        self.assertEqual(state_response["event"], "state")
        self.assertEqual(snapshot["mode"], "live-state-snapshot-v0.15")
        self.assertEqual(snapshot["session_id"], "state-demo")
        self.assertEqual(snapshot["current_frame"], 0)
        self.assertTrue(snapshot["open_frame"])
        self.assertEqual(snapshot["frames_observed"], 1)
        self.assertEqual(snapshot["memory_totals_mb"]["ram"], 64)
        self.assertEqual(snapshot["memory_totals_mb"]["vram"], 64)
        self.assertEqual(snapshot["queue_costs_ms"]["copy"], 4.2)
        self.assertEqual(snapshot["estimated_total_cost_ms_current_frame"], 4.2)
        self.assertEqual(snapshot["transfer_mb_current_frame"], 64)
        self.assertEqual(snapshot["live_command_count"], 1)

    def test_adapter_final_result_includes_live_state_snapshot(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        snapshot = payload["state_snapshot"]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(snapshot["mode"], "live-state-snapshot-v0.15")
        self.assertIsNone(snapshot["current_frame"])
        self.assertFalse(snapshot["open_frame"])
        self.assertEqual(snapshot["frames_observed"], 1)
        self.assertEqual(snapshot["events_processed"], 9)
        self.assertEqual(snapshot["operation_events"], 2)
        self.assertEqual(snapshot["live_command_count"], 2)

    def test_runtime_event_server_reports_live_state_snapshot(self):
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
        state_responses = [
            response for response in responses if response.get("event") == "state"
        ]
        operation_responses = [
            response for response in responses if response.get("event") == "operation"
        ]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["state_response_count"], 1)
        self.assertEqual(summary["state_snapshot_count"], len(responses))
        self.assertEqual(
            state_responses[0]["state_snapshot"]["queue_costs_ms"]["copy"], 4.2
        )
        self.assertEqual(
            operation_responses[0]["state_snapshot"]["live_command_count"], 1
        )
        self.assertEqual(summary["live_command_count"], 2)
        self.assertEqual(summary["failed_responses"], 0)

    def test_live_policy_loop_emits_incremental_directives(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        directives = payload["policy_loop_directives"]
        actions = {directive["action"] for directive in directives}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(payload["policy_loop_directive_count"], 3)
        self.assertIn("prefetch-before-critical-path", actions)
        self.assertIn("drain-copy-queue-before-draw", actions)
        self.assertIn("protect-frame-budget", actions)
        self.assertTrue(
            all(directive["mode"] == "live-policy-loop-v0.16" for directive in directives)
        )

    def test_operation_response_carries_new_policy_loop_directives(self):
        session = RuntimeAdapterSession()
        session.process_event(
            {
                "event": "session",
                "action": "begin",
                "id": "governor-demo",
                "budgets": {"frame_ms": 8, "ram_mb": 96, "vram_mb": 96},
            }
        )
        session.process_event({"event": "frame", "action": "begin", "frame": 0})
        session.process_event(
            {
                "event": "resource",
                "id": "ram_texture",
                "kind": "texture",
                "memory": "ram",
                "size_mb": 64,
            }
        )
        session.process_event(
            {
                "event": "resource",
                "id": "vram_texture",
                "kind": "texture",
                "memory": "vram",
                "size_mb": 64,
            }
        )
        response = session.process_event(
            {
                "event": "operation",
                "id": "upload_hero",
                "operation_type": "upload",
                "source": "ram_texture",
                "target": "vram_texture",
                "queue": "copy",
                "cost_ms": 4.2,
                "size_mb": 64,
            }
        )
        actions = {item["action"] for item in response["policy_loop_directives"]}

        self.assertEqual(response["state_snapshot"]["live_command_count"], 1)
        self.assertEqual(len(response["policy_loop_directives"]), 2)
        self.assertIn("prefetch-before-critical-path", actions)
        self.assertIn("drain-copy-queue-before-draw", actions)

    def test_live_policy_loop_includes_ram_vram_residency_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_policy_pressure_events.jsonl"
        )
        payload = result.to_dict()
        memory_directives = [
            directive
            for directive in payload["policy_loop_directives"]
            if directive["action"] == "reduce-memory-residency"
        ]

        self.assertEqual(memory_directives[0]["resource_id"], "vram")
        self.assertEqual(memory_directives[0]["queue"], "memory")
        self.assertEqual(memory_directives[0]["frame"], 0)

    def test_runtime_event_server_reports_policy_loop_directives(self):
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["policy_loop_directive_count"], 3)
        self.assertEqual(summary["failed_responses"], 0)

    def test_execution_gate_prestages_heavy_uploads_before_draw(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        gates = {
            item["operation"]["id"]: item["execution_gate"]
            for item in payload["results"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(payload["execution_gate_count"], 2)
        self.assertEqual(gates["upload_hero"]["mode"], "adaptive-execution-gate-v0.17")
        self.assertEqual(gates["upload_hero"]["action"], "prestage_before_draw")
        self.assertEqual(gates["upload_hero"]["preferred_phase"], "prefetch")
        self.assertTrue(gates["upload_hero"]["should_execute"])
        self.assertEqual(gates["draw_hero"]["action"], "execute_now")
        self.assertEqual(gates["draw_hero"]["preferred_phase"], "critical")

    def test_execution_gate_maps_reuse_and_defer_decisions(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        gates = {
            item["operation"]["id"]: item["execution_gate"]
            for item in payload["results"]
        }

        self.assertEqual(gates["alloc_scratch_2"]["action"], "reuse_existing_resource")
        self.assertFalse(gates["alloc_scratch_2"]["should_execute"])
        self.assertEqual(
            gates["upload_texture_a_duplicate"]["action"],
            "defer_redundant_work",
        )
        self.assertFalse(gates["upload_texture_a_duplicate"]["should_execute"])

    def test_execution_gate_holds_noncritical_work_when_frame_is_hot(self):
        session = RuntimeAdapterSession()
        session.process_event(
            {
                "event": "session",
                "action": "begin",
                "id": "gate-hot-frame",
                "budgets": {"frame_ms": 8, "ram_mb": 128, "vram_mb": 128},
            }
        )
        session.process_event({"event": "frame", "action": "begin", "frame": 0})
        session.process_event(
            {
                "event": "operation",
                "id": "draw_heavy",
                "operation_type": "draw",
                "queue": "graphics",
                "reason": "critical scene draw",
                "cost_ms": 7.4,
            }
        )
        session.process_event(
            {
                "event": "resource",
                "id": "ram_cosmetic",
                "kind": "texture",
                "memory": "ram",
                "size_mb": 1,
            }
        )
        session.process_event(
            {
                "event": "resource",
                "id": "vram_cosmetic",
                "kind": "texture",
                "memory": "vram",
                "size_mb": 1,
            }
        )
        response = session.process_event(
            {
                "event": "operation",
                "id": "late_tiny_upload",
                "operation_type": "upload",
                "source": "ram_cosmetic",
                "target": "vram_cosmetic",
                "queue": "copy",
                "reason": "tiny late cosmetic upload",
                "cost_ms": 0.1,
                "size_mb": 1,
            }
        )
        gate = response["execution_gate"]

        self.assertEqual(gate["action"], "hold_noncritical_work")
        self.assertEqual(gate["preferred_phase"], "next-frame")
        self.assertFalse(gate["should_execute"])

    def test_runtime_event_server_reports_execution_gates(self):
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
        operation_responses = [
            response for response in responses if response.get("event") == "operation"
        ]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["execution_gate_count"], 2)
        self.assertEqual(
            operation_responses[0]["execution_gate"]["action"],
            "prestage_before_draw",
        )
        self.assertEqual(summary["failed_responses"], 0)

    def test_admission_plan_aggregates_hot_path_and_prestaged_work(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        admission = payload["admission_plan"]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(admission["mode"], "adaptive-admission-controller-v0.18")
        self.assertEqual(admission["operation_count"], 2)
        self.assertEqual(admission["immediate_count"], 1)
        self.assertEqual(admission["prefetch_count"], 1)
        self.assertEqual(admission["estimated_hot_path_cost_ms"], 3.2)
        self.assertEqual(admission["estimated_prestaged_cost_ms"], 4.2)
        self.assertEqual(admission["estimated_prestaged_transfer_mb"], 64)

    def test_operation_response_carries_admission_decision(self):
        session = RuntimeAdapterSession()
        session.process_event(
            {
                "event": "session",
                "action": "begin",
                "id": "admission-demo",
                "budgets": {"frame_ms": 8, "ram_mb": 96, "vram_mb": 96},
            }
        )
        session.process_event({"event": "frame", "action": "begin", "frame": 0})
        session.process_event(
            {
                "event": "resource",
                "id": "ram_texture",
                "kind": "texture",
                "memory": "ram",
                "size_mb": 64,
            }
        )
        session.process_event(
            {
                "event": "resource",
                "id": "vram_texture",
                "kind": "texture",
                "memory": "vram",
                "size_mb": 64,
            }
        )
        response = session.process_event(
            {
                "event": "operation",
                "id": "upload_hero",
                "operation_type": "upload",
                "source": "ram_texture",
                "target": "vram_texture",
                "queue": "copy",
                "cost_ms": 4.2,
                "size_mb": 64,
            }
        )
        admission = response["admission_decision"]

        self.assertEqual(admission["mode"], "adaptive-admission-controller-v0.18")
        self.assertEqual(admission["operation_id"], "upload_hero")
        self.assertEqual(admission["action"], "admit-prefetch")
        self.assertEqual(admission["phase"], "prefetch")
        self.assertEqual(admission["contribution"], "prestaged")
        self.assertEqual(admission["cost_ms"], 4.2)
        self.assertEqual(admission["size_mb"], 64)

    def test_admission_plan_counts_reuse_and_deferred_waste(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        admission = result.to_dict()["admission_plan"]

        self.assertEqual(admission["operation_count"], 7)
        self.assertEqual(admission["reused_count"], 1)
        self.assertEqual(admission["deferred_count"], 3)
        self.assertEqual(admission["estimated_avoided_cost_ms"], 1.53)
        self.assertEqual(admission["estimated_avoided_transfer_mb"], 144)

    def test_runtime_event_server_reports_admission_decisions(self):
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["admission_decision_count"], 2)
        self.assertEqual(summary["admission_plan"]["prefetch_count"], 1)
        self.assertEqual(summary["admission_plan"]["estimated_hot_path_cost_ms"], 3.2)
        self.assertEqual(summary["failed_responses"], 0)

    def test_efficiency_ledger_quantifies_shifted_hot_path_work(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        ledger = payload["efficiency_ledger"]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(ledger["mode"], "frame-efficiency-ledger-v0.19")
        self.assertEqual(ledger["operation_count"], 2)
        self.assertEqual(ledger["hot_path_cost_ms"], 3.2)
        self.assertEqual(ledger["shifted_cost_ms"], 4.2)
        self.assertEqual(ledger["avoided_cost_ms"], 0)
        self.assertEqual(ledger["transfer_relief_mb"], 64)
        self.assertEqual(ledger["efficiency_score"], 56.7568)

    def test_efficiency_ledger_quantifies_avoided_waste(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        ledger = result.to_dict()["efficiency_ledger"]

        self.assertEqual(ledger["operation_count"], 7)
        self.assertEqual(ledger["hot_path_cost_ms"], 6.28)
        self.assertEqual(ledger["shifted_cost_ms"], 0.9)
        self.assertEqual(ledger["avoided_cost_ms"], 1.53)
        self.assertEqual(ledger["transfer_relief_mb"], 208)
        self.assertEqual(ledger["frames"][0]["frame"], 0)

    def test_operation_response_carries_efficiency_impact(self):
        session = RuntimeAdapterSession()
        session.process_event(
            {
                "event": "session",
                "action": "begin",
                "id": "efficiency-demo",
                "budgets": {"frame_ms": 8, "ram_mb": 96, "vram_mb": 96},
            }
        )
        session.process_event({"event": "frame", "action": "begin", "frame": 0})
        session.process_event(
            {
                "event": "resource",
                "id": "ram_texture",
                "kind": "texture",
                "memory": "ram",
                "size_mb": 64,
            }
        )
        session.process_event(
            {
                "event": "resource",
                "id": "vram_texture",
                "kind": "texture",
                "memory": "vram",
                "size_mb": 64,
            }
        )
        response = session.process_event(
            {
                "event": "operation",
                "id": "upload_hero",
                "operation_type": "upload",
                "source": "ram_texture",
                "target": "vram_texture",
                "queue": "copy",
                "cost_ms": 4.2,
                "size_mb": 64,
            }
        )
        impact = response["efficiency_impact"]

        self.assertEqual(impact["mode"], "frame-efficiency-ledger-v0.19")
        self.assertEqual(impact["operation_id"], "upload_hero")
        self.assertEqual(impact["impact"], "shifted-off-hot-path")
        self.assertEqual(impact["relief_cost_ms"], 4.2)
        self.assertEqual(impact["relief_transfer_mb"], 64)

    def test_runtime_event_server_reports_efficiency_ledger(self):
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["efficiency_impact_count"], 2)
        self.assertEqual(summary["efficiency_ledger"]["shifted_cost_ms"], 4.2)
        self.assertEqual(summary["efficiency_ledger"]["transfer_relief_mb"], 64)
        self.assertEqual(summary["failed_responses"], 0)

    def test_feedback_plan_recommends_next_frame_budgets(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        feedback = payload["feedback_plan"]
        frame = feedback["frames"][0]
        actions = {action["action"] for action in feedback["actions"]}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(feedback["mode"], "adaptive-feedback-controller-v0.20")
        self.assertEqual(feedback["frame_count"], 1)
        self.assertEqual(feedback["action_count"], 2)
        self.assertEqual(frame["target_frame_ms"], 8)
        self.assertEqual(frame["hot_path_headroom_ms"], 4.8)
        self.assertEqual(frame["suggested_copy_budget_ms"], 1.2)
        self.assertEqual(frame["suggested_prefetch_window_ms"], 4.2)
        self.assertIn("preserve-prefetch-window", actions)
        self.assertIn("cap-copy-queue", actions)

    def test_feedback_plan_reinforces_reuse_and_dedupe(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        feedback = result.to_dict()["feedback_plan"]
        frame = feedback["frames"][0]
        actions = {action["action"] for action in feedback["actions"]}

        self.assertEqual(frame["target_frame_ms"], 16.67)
        self.assertEqual(frame["suggested_copy_budget_ms"], 2.5005)
        self.assertEqual(frame["suggested_prefetch_window_ms"], 3.334)
        self.assertIn("maintain-reuse-dedupe", actions)
        self.assertIn("cap-copy-queue", actions)

    def test_runtime_event_server_reports_feedback_plan(self):
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["feedback_plan"]["action_count"], 2)
        self.assertEqual(
            summary["feedback_plan"]["frames"][0]["suggested_copy_budget_ms"],
            1.2,
        )
        self.assertEqual(summary["failed_responses"], 0)

    def test_actuation_plan_translates_feedback_to_commands(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_state_query_events.jsonl"
        )
        payload = result.to_dict()
        actuation = payload["actuation_plan"]
        commands = {command["command"]: command for command in actuation["commands"]}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(actuation["mode"], "runtime-actuation-plan-v0.21")
        self.assertEqual(actuation["command_count"], 2)
        self.assertEqual(commands["reserve_prefetch_window"]["value"], 4.2)
        self.assertEqual(commands["reserve_prefetch_window"]["unit"], "ms")
        self.assertEqual(commands["set_copy_queue_budget"]["value"], 1.2)
        self.assertEqual(commands["set_copy_queue_budget"]["target"], "copy")

    def test_actuation_plan_enables_reuse_dedupe_from_runtime_waste(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        actuation = result.to_dict()["actuation_plan"]
        commands = {command["command"]: command for command in actuation["commands"]}

        self.assertEqual(actuation["command_count"], 3)
        self.assertEqual(commands["reserve_prefetch_window"]["value"], 3.334)
        self.assertEqual(commands["set_copy_queue_budget"]["value"], 2.5005)
        self.assertEqual(commands["enable_reuse_dedupe"]["target"], "control-plane")

    def test_runtime_event_server_reports_actuation_plan(self):
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
        commands = {
            command["command"]: command
            for command in summary["actuation_plan"]["commands"]
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(summary["actuation_plan"]["command_count"], 2)
        self.assertEqual(commands["reserve_prefetch_window"]["value"], 4.2)
        self.assertEqual(summary["failed_responses"], 0)

    def test_memory_transit_map_tracks_ram_vram_swapchain_paths(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        transit = payload["memory_transit_map"]
        paths = {path["path"]: path for path in transit["paths"]}
        hops = {hop["operation_id"]: hop for hop in transit["hops"]}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(transit["mode"], "memory-transit-map-v0.22")
        self.assertEqual(transit["hop_count"], 7)
        self.assertEqual(transit["executed_hop_count"], 3)
        self.assertEqual(transit["avoided_hop_count"], 4)
        self.assertEqual(transit["attempted_transfer_mb"], 256)
        self.assertEqual(transit["executed_transfer_mb"], 112)
        self.assertEqual(transit["avoided_transfer_mb"], 144)
        self.assertEqual(transit["estimated_avoidable_cost_ms"], 1.53)
        self.assertEqual(paths["ram->vram"]["attempted_mb"], 128)
        self.assertEqual(paths["ram->vram"]["avoided_mb"], 64)
        self.assertEqual(paths["vram->swapchain"]["executed_mb"], 32)
        self.assertEqual(
            hops["upload_texture_a_duplicate"]["classification"],
            "duplicate-transfer",
        )
        self.assertEqual(
            hops["copy_alias_texture"]["classification"],
            "same-layer-aliased-copy",
        )
        self.assertEqual(hops["sync_duplicate_upload"]["classification"], "orphan-sync")

    def test_runtime_event_server_reports_memory_transit_map(self):
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
        transit = summary["memory_transit_map"]
        paths = {path["path"]: path for path in transit["paths"]}

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(transit["mode"], "memory-transit-map-v0.22")
        self.assertEqual(transit["hop_count"], 2)
        self.assertEqual(transit["executed_hop_count"], 2)
        self.assertEqual(paths["ram->vram"]["executed_mb"], 64)
        self.assertEqual(summary["failed_responses"], 0)

    def test_memory_route_plan_turns_transit_map_into_directives(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        route = payload["memory_route_plan"]
        directives = {
            directive["operation_id"]: directive for directive in route["directives"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(route["mode"], "memory-route-plan-v0.23")
        self.assertEqual(route["directive_count"], 7)
        self.assertEqual(route["suppress_count"], 3)
        self.assertEqual(route["prefetch_count"], 1)
        self.assertEqual(route["residency_count"], 1)
        self.assertEqual(route["sync_count"], 1)
        self.assertEqual(route["estimated_saved_mb"], 144)
        self.assertEqual(route["estimated_saved_ms"], 1.53)
        self.assertEqual(
            directives["upload_texture_a"]["directive"],
            "prestage_cross_memory_transfer",
        )
        self.assertEqual(
            directives["upload_texture_a_duplicate"]["directive"],
            "suppress_redundant_hop",
        )
        self.assertEqual(
            directives["copy_alias_texture"]["directive"],
            "suppress_redundant_hop",
        )
        self.assertEqual(
            directives["sync_duplicate_upload"]["directive"],
            "remove_sync_wait",
        )
        self.assertEqual(
            directives["draw_scene"]["directive"],
            "protect_presentation_route",
        )

    def test_runtime_event_server_reports_memory_route_plan(self):
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
        route = summary["memory_route_plan"]
        directives = {
            directive["operation_id"]: directive for directive in route["directives"]
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(route["mode"], "memory-route-plan-v0.23")
        self.assertEqual(route["directive_count"], 2)
        self.assertEqual(route["prefetch_count"], 1)
        self.assertEqual(
            directives["upload_hero"]["directive"],
            "prestage_cross_memory_transfer",
        )
        self.assertEqual(summary["failed_responses"], 0)

    def test_frame_window_plan_schedules_route_directives(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        plan = payload["frame_window_plan"]
        slots = {slot["operation_id"]: slot for slot in plan["slots"]}
        frame = plan["frames"][0]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(plan["mode"], "frame-window-plan-v0.24")
        self.assertEqual(plan["slot_count"], 7)
        self.assertEqual(plan["frame_count"], 1)
        self.assertEqual(plan["never_count"], 4)
        self.assertEqual(plan["pre_frame_count"], 1)
        self.assertEqual(plan["setup_count"], 1)
        self.assertEqual(plan["hot_path_count"], 1)
        self.assertEqual(plan["post_present_count"], 0)
        self.assertEqual(plan["estimated_hot_path_relief_ms"], 1.53)
        self.assertEqual(plan["estimated_saved_mb"], 144)
        self.assertEqual(frame["slot_count"], 7)
        self.assertEqual(frame["never_count"], 4)
        self.assertEqual(slots["upload_texture_a"]["window"], "pre-frame")
        self.assertEqual(slots["upload_texture_a"]["phase"], "prefetch")
        self.assertEqual(slots["alloc_scratch_1"]["window"], "setup")
        self.assertEqual(slots["upload_texture_a_duplicate"]["window"], "never")
        self.assertEqual(slots["sync_duplicate_upload"]["phase"], "remove-sync")
        self.assertEqual(slots["draw_scene"]["window"], "hot-path")

    def test_runtime_event_server_reports_frame_window_plan(self):
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
        plan = summary["frame_window_plan"]
        slots = {slot["operation_id"]: slot for slot in plan["slots"]}

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(plan["mode"], "frame-window-plan-v0.24")
        self.assertEqual(plan["slot_count"], 2)
        self.assertEqual(plan["pre_frame_count"], 1)
        self.assertEqual(plan["hot_path_count"], 1)
        self.assertEqual(slots["upload_hero"]["window"], "pre-frame")
        self.assertEqual(summary["failed_responses"], 0)

    def test_execution_packet_orders_window_slots_into_commands(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        packet = payload["execution_packet"]
        commands = {
            command["operation_id"]: command for command in packet["commands"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(packet["mode"], "runtime-execution-packet-v0.25")
        self.assertEqual(packet["command_count"], 7)
        self.assertEqual(packet["frame_count"], 1)
        self.assertEqual(packet["skip_count"], 4)
        self.assertEqual(packet["pre_frame_count"], 1)
        self.assertEqual(packet["setup_count"], 1)
        self.assertEqual(packet["hot_path_count"], 1)
        self.assertEqual(packet["estimated_saved_mb"], 144)
        self.assertEqual(packet["estimated_hot_path_relief_ms"], 1.53)
        self.assertEqual(packet["commands"][0]["window"], "never")
        self.assertEqual(packet["commands"][0]["action"], "reuse_allocation")
        self.assertEqual(
            commands["upload_texture_a"]["action"],
            "prestage_transfer",
        )
        self.assertEqual(commands["upload_texture_a"]["window"], "pre-frame")
        self.assertEqual(
            commands["upload_texture_a_duplicate"]["action"],
            "skip_transfer",
        )
        self.assertEqual(commands["sync_duplicate_upload"]["action"], "drop_sync_wait")
        self.assertEqual(commands["draw_scene"]["action"], "execute_protected")
        self.assertEqual(packet["frames"][0]["command_count"], 7)

    def test_runtime_event_server_reports_execution_packet(self):
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
        packet = summary["execution_packet"]
        commands = {
            command["operation_id"]: command for command in packet["commands"]
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(packet["mode"], "runtime-execution-packet-v0.25")
        self.assertEqual(packet["command_count"], 2)
        self.assertEqual(packet["pre_frame_count"], 1)
        self.assertEqual(packet["hot_path_count"], 1)
        self.assertEqual(commands["upload_hero"]["action"], "prestage_transfer")
        self.assertEqual(commands["upload_hero"]["window"], "pre-frame")
        self.assertEqual(summary["failed_responses"], 0)

    def test_execution_simulation_reports_before_after_frame_cost(self):
        result = replay_adapter_event_stream(FIXTURES / "runtime_events.jsonl")
        payload = result.to_dict()
        simulation = payload["execution_simulation"]
        frame = simulation["frames"][0]
        command_results = {
            result["operation_id"]: result for result in simulation["command_results"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(simulation["mode"], "runtime-execution-simulation-v0.26")
        self.assertEqual(simulation["command_count"], 7)
        self.assertEqual(simulation["applied_count"], 7)
        self.assertEqual(simulation["ignored_count"], 0)
        self.assertEqual(simulation["removed_cost_ms"], 1.53)
        self.assertEqual(simulation["prestaged_cost_ms"], 0.9)
        self.assertEqual(simulation["setup_cost_ms"], 0.08)
        self.assertEqual(simulation["protected_hot_path_cost_ms"], 6.2)
        self.assertEqual(simulation["hot_path_before_ms"], 8.71)
        self.assertEqual(simulation["hot_path_after_ms"], 6.2)
        self.assertEqual(simulation["hot_path_relief_ms"], 2.51)
        self.assertEqual(simulation["estimated_saved_mb"], 144)
        self.assertEqual(frame["frame"], 0)
        self.assertEqual(frame["command_count"], 7)
        self.assertEqual(frame["hot_path_after_ms"], 6.2)
        self.assertEqual(command_results["upload_texture_a"]["status"], "applied")
        self.assertEqual(command_results["upload_texture_a"]["effect"], "prestaged")
        self.assertEqual(command_results["sync_duplicate_upload"]["effect"], "removed")

    def test_runtime_event_server_reports_execution_simulation(self):
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
        simulation = summary["execution_simulation"]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(simulation["mode"], "runtime-execution-simulation-v0.26")
        self.assertEqual(simulation["command_count"], 2)
        self.assertEqual(simulation["prestaged_cost_ms"], 4.2)
        self.assertEqual(simulation["hot_path_before_ms"], 7.4)
        self.assertEqual(simulation["hot_path_after_ms"], 3.2)
        self.assertEqual(simulation["hot_path_relief_ms"], 4.2)
        self.assertEqual(summary["failed_responses"], 0)

    def test_adaptive_executor_loop_flags_over_budget_frame(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_over_budget_executor_events.jsonl"
        )
        payload = result.to_dict()
        loop = payload["adaptive_executor_loop"]
        frame = loop["frames"][0]
        actions = {directive["action"] for directive in loop["directives"]}

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(loop["mode"], "adaptive-executor-loop-v0.27")
        self.assertEqual(loop["frame_count"], 1)
        self.assertEqual(loop["over_budget_count"], 1)
        self.assertEqual(loop["within_budget_count"], 0)
        self.assertEqual(loop["max_over_budget_ms"], 1.5)
        self.assertEqual(loop["profile"], "aggressive")
        self.assertEqual(frame["frame"], 0)
        self.assertEqual(frame["target_frame_ms"], 8)
        self.assertEqual(frame["hot_path_after_ms"], 9.5)
        self.assertEqual(frame["budget_delta_ms"], -1.5)
        self.assertEqual(frame["pressure_status"], "over-budget")
        self.assertIn("tighten-hot-path-admission", actions)
        self.assertIn("expand-pre-frame-window", actions)

    def test_runtime_event_server_reports_adaptive_executor_loop(self):
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
        loop = summary["adaptive_executor_loop"]
        frame = loop["frames"][0]
        actions = {directive["action"] for directive in loop["directives"]}

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(loop["mode"], "adaptive-executor-loop-v0.27")
        self.assertEqual(loop["frame_count"], 1)
        self.assertEqual(loop["within_budget_count"], 1)
        self.assertEqual(loop["over_budget_count"], 0)
        self.assertEqual(loop["profile"], "stable")
        self.assertEqual(frame["target_frame_ms"], 8)
        self.assertEqual(frame["hot_path_after_ms"], 3.2)
        self.assertEqual(frame["budget_delta_ms"], 4.8)
        self.assertEqual(frame["pressure_status"], "within-budget")
        self.assertIn("preserve-pre-frame-window", actions)
        self.assertEqual(summary["failed_responses"], 0)

    def test_budget_envelope_combines_frame_and_memory_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        envelope = payload["budget_envelope"]
        frame = envelope["frames"][0]
        memory = {
            layer["memory"]: layer for layer in envelope["memory_layers"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(envelope["mode"], "runtime-budget-envelope-v0.28")
        self.assertEqual(envelope["profile"], "aggressive")
        self.assertEqual(
            envelope["next_frame_policy"],
            "tighten-frame-and-memory-admission",
        )
        self.assertEqual(envelope["over_budget_frame_count"], 1)
        self.assertEqual(envelope["constrained_memory_count"], 3)
        self.assertEqual(envelope["total_memory_pressure_mb"], 40)
        self.assertEqual(frame["frame"], 0)
        self.assertEqual(frame["pressure_status"], "over-budget")
        self.assertEqual(frame["copy_queue_budget_ms"], 0)
        self.assertEqual(frame["pre_frame_window_ms"], 4.5)
        self.assertEqual(frame["admission_policy"], "block-noncritical-hot-path")
        self.assertEqual(frame["memory_policy"], "evict-or-defer-residency")
        self.assertEqual(memory["ram"]["status"], "over-budget")
        self.assertEqual(memory["ram"]["pressure_mb"], 16)
        self.assertEqual(memory["vram"]["status"], "over-budget")
        self.assertEqual(memory["vram"]["pressure_mb"], 16)
        self.assertEqual(memory["swapchain"]["status"], "over-budget")
        self.assertEqual(memory["swapchain"]["pressure_mb"], 8)

    def test_runtime_event_server_reports_budget_envelope(self):
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
        envelope = summary["budget_envelope"]
        frame = envelope["frames"][0]
        memory = {
            layer["memory"]: layer for layer in envelope["memory_layers"]
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(envelope["mode"], "runtime-budget-envelope-v0.28")
        self.assertEqual(envelope["profile"], "stable")
        self.assertEqual(envelope["next_frame_policy"], "maintain-current-envelope")
        self.assertEqual(envelope["constrained_memory_count"], 0)
        self.assertEqual(frame["copy_queue_budget_ms"], 1.2)
        self.assertEqual(frame["pre_frame_window_ms"], 4.2)
        self.assertEqual(frame["admission_policy"], "allow-budgeted-hot-path")
        self.assertEqual(memory["ram"]["status"], "within-budget")
        self.assertEqual(memory["vram"]["status"], "within-budget")
        self.assertEqual(summary["failed_responses"], 0)

    def test_budget_arbiter_defers_hot_path_and_memory_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        arbitration = payload["budget_arbitration"]
        commands = {
            command["operation_id"]: command
            for command in arbitration["commands"]
        }
        memory_actions = {
            action["memory"]: action for action in arbitration["memory_actions"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(arbitration["mode"], "runtime-budget-arbiter-v0.29")
        self.assertEqual(arbitration["command_count"], 3)
        self.assertEqual(arbitration["prestaged_count"], 1)
        self.assertEqual(arbitration["dropped_count"], 1)
        self.assertEqual(arbitration["deferred_count"], 1)
        self.assertEqual(arbitration["admitted_count"], 0)
        self.assertEqual(arbitration["memory_action_count"], 3)
        self.assertEqual(arbitration["deferred_hot_path_cost_ms"], 9.5)
        self.assertEqual(arbitration["prestaged_cost_ms"], 3.0)
        self.assertEqual(arbitration["dropped_cost_ms"], 1.0)
        self.assertEqual(commands["upload_boss_texture"]["decision"], "prestage-before-frame")
        self.assertEqual(commands["upload_boss_texture"]["status"], "prestaged")
        self.assertEqual(
            commands["upload_boss_texture_duplicate"]["decision"],
            "drop-waste",
        )
        self.assertEqual(commands["draw_boss"]["decision"], "split-or-defer-hot-path")
        self.assertEqual(commands["draw_boss"]["status"], "deferred")
        self.assertEqual(memory_actions["ram"]["decision"], "evict-or-defer-residency")
        self.assertEqual(memory_actions["vram"]["decision"], "evict-or-defer-residency")
        self.assertEqual(
            memory_actions["swapchain"]["decision"],
            "evict-or-defer-residency",
        )

    def test_runtime_event_server_reports_budget_arbitration(self):
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
        arbitration = summary["budget_arbitration"]
        commands = {
            command["operation_id"]: command
            for command in arbitration["commands"]
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(arbitration["mode"], "runtime-budget-arbiter-v0.29")
        self.assertEqual(arbitration["command_count"], 2)
        self.assertEqual(arbitration["prestaged_count"], 1)
        self.assertEqual(arbitration["admitted_count"], 1)
        self.assertEqual(arbitration["deferred_count"], 0)
        self.assertEqual(arbitration["dropped_count"], 0)
        self.assertEqual(arbitration["memory_action_count"], 0)
        self.assertEqual(commands["upload_hero"]["decision"], "prestage-before-frame")
        self.assertEqual(commands["draw_hero"]["decision"], "admit-hot-path")
        self.assertEqual(commands["draw_hero"]["status"], "admitted")
        self.assertEqual(summary["failed_responses"], 0)

    def test_dispatch_plan_orders_runtime_commands(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        dispatch = payload["dispatch_plan"]
        commands = dispatch["commands"]
        by_operation = {
            command["operation_id"]: command
            for command in commands
            if command["operation_id"] is not None
        }
        by_memory = {
            command["memory"]: command
            for command in commands
            if command["memory"] is not None
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(dispatch["mode"], "runtime-dispatch-plan-v0.30")
        self.assertEqual(dispatch["command_count"], 6)
        self.assertEqual(dispatch["control_count"], 1)
        self.assertEqual(dispatch["memory_count"], 3)
        self.assertEqual(dispatch["pre_frame_count"], 1)
        self.assertEqual(dispatch["hot_path_count"], 0)
        self.assertEqual(dispatch["next_frame_count"], 1)
        self.assertEqual(dispatch["dropped_count"], 1)
        self.assertEqual(dispatch["deferred_count"], 1)
        self.assertEqual(dispatch["total_memory_pressure_mb"], 40)
        self.assertEqual(
            [command["phase"] for command in commands],
            ["control", "memory", "memory", "memory", "pre-frame", "next-frame"],
        )
        self.assertEqual(
            by_operation["upload_boss_texture_duplicate"]["command"],
            "drop_operation",
        )
        self.assertEqual(
            by_operation["upload_boss_texture"]["command"],
            "prestage_operation",
        )
        self.assertEqual(
            by_operation["draw_boss"]["command"],
            "defer_or_split_operation",
        )
        self.assertEqual(by_memory["ram"]["command"], "evict_or_defer_residency")
        self.assertEqual(by_memory["vram"]["command"], "evict_or_defer_residency")
        self.assertEqual(
            by_memory["swapchain"]["command"],
            "evict_or_defer_residency",
        )

    def test_runtime_event_server_reports_dispatch_plan(self):
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
        dispatch = summary["dispatch_plan"]
        commands = {
            command["operation_id"]: command
            for command in dispatch["commands"]
            if command["operation_id"] is not None
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(dispatch["mode"], "runtime-dispatch-plan-v0.30")
        self.assertEqual(dispatch["command_count"], 2)
        self.assertEqual(dispatch["pre_frame_count"], 1)
        self.assertEqual(dispatch["hot_path_count"], 1)
        self.assertEqual(dispatch["next_frame_count"], 0)
        self.assertEqual(dispatch["memory_count"], 0)
        self.assertEqual(commands["upload_hero"]["command"], "prestage_operation")
        self.assertEqual(commands["draw_hero"]["command"], "execute_operation")
        self.assertEqual(commands["draw_hero"]["phase"], "hot-path")
        self.assertEqual(summary["failed_responses"], 0)

    def test_dispatch_execution_reports_applied_runtime_effects(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        execution = payload["dispatch_execution"]
        steps = {
            step["operation_id"] or step["memory"]: step
            for step in execution["steps"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(execution["mode"], "runtime-dispatch-execution-v0.31")
        self.assertEqual(execution["step_count"], 6)
        self.assertEqual(execution["applied_count"], 1)
        self.assertEqual(execution["scheduled_count"], 4)
        self.assertEqual(execution["deferred_count"], 1)
        self.assertEqual(execution["removed_count"], 1)
        self.assertEqual(execution["memory_action_count"], 3)
        self.assertEqual(execution["current_frame_cost_ms"], 0)
        self.assertEqual(execution["pre_frame_cost_ms"], 3.0)
        self.assertEqual(execution["avoided_cost_ms"], 1.0)
        self.assertEqual(execution["deferred_cost_ms"], 9.5)
        self.assertEqual(execution["memory_relief_mb"], 40)
        self.assertEqual(steps["upload_boss_texture"]["outcome"], "scheduled")
        self.assertEqual(steps["upload_boss_texture"]["pre_frame_cost_ms"], 3.0)
        self.assertEqual(
            steps["upload_boss_texture_duplicate"]["outcome"],
            "applied",
        )
        self.assertEqual(
            steps["upload_boss_texture_duplicate"]["avoided_cost_ms"],
            1.0,
        )
        self.assertEqual(steps["draw_boss"]["outcome"], "deferred")
        self.assertEqual(steps["draw_boss"]["deferred_cost_ms"], 9.5)
        self.assertEqual(steps["ram"]["memory_relief_mb"], 16)
        self.assertEqual(steps["vram"]["memory_relief_mb"], 16)
        self.assertEqual(steps["swapchain"]["memory_relief_mb"], 8)

    def test_runtime_event_server_reports_dispatch_execution(self):
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
        execution = summary["dispatch_execution"]
        steps = {
            step["operation_id"]: step
            for step in execution["steps"]
            if step["operation_id"] is not None
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(execution["mode"], "runtime-dispatch-execution-v0.31")
        self.assertEqual(execution["step_count"], 2)
        self.assertEqual(execution["applied_count"], 1)
        self.assertEqual(execution["scheduled_count"], 1)
        self.assertEqual(execution["deferred_count"], 0)
        self.assertEqual(execution["current_frame_cost_ms"], 3.2)
        self.assertEqual(execution["pre_frame_cost_ms"], 4.2)
        self.assertEqual(execution["memory_relief_mb"], 0)
        self.assertEqual(steps["upload_hero"]["outcome"], "scheduled")
        self.assertEqual(steps["draw_hero"]["outcome"], "applied")
        self.assertEqual(steps["draw_hero"]["current_frame_cost_ms"], 3.2)
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_calibration_reports_observed_vs_planned_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        calibration = payload["runtime_calibration"]
        frame = calibration["frames"][0]

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(calibration["mode"], "runtime-calibration-report-v0.32")
        self.assertEqual(calibration["frame_count"], 1)
        self.assertEqual(calibration["over_budget_observed_count"], 1)
        self.assertEqual(calibration["over_budget_planned_count"], 0)
        self.assertEqual(calibration["total_observed_frame_cost_ms"], 12.5)
        self.assertEqual(calibration["total_planned_current_frame_cost_ms"], 0)
        self.assertEqual(calibration["total_planned_frame_relief_ms"], 12.5)
        self.assertEqual(calibration["total_pre_frame_cost_ms"], 3.0)
        self.assertEqual(calibration["total_deferred_cost_ms"], 9.5)
        self.assertEqual(calibration["total_avoided_cost_ms"], 1.0)
        self.assertEqual(calibration["total_memory_relief_mb"], 40)
        self.assertEqual(calibration["max_guardband_ms"], 2.0)
        self.assertEqual(calibration["recommended_next_frame_budget_ms"], 6.0)
        self.assertEqual(frame["observed_frame_cost_ms"], 12.5)
        self.assertEqual(frame["target_frame_ms"], 8)
        self.assertEqual(frame["planned_current_frame_cost_ms"], 0)
        self.assertEqual(frame["planned_frame_relief_ms"], 12.5)
        self.assertEqual(frame["action"], "apply-dispatch-before-next-frame")
        self.assertEqual(frame["confidence"], "medium")

    def test_runtime_event_server_reports_runtime_calibration(self):
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
        calibration = summary["runtime_calibration"]
        frame = calibration["frames"][0]

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(calibration["mode"], "runtime-calibration-report-v0.32")
        self.assertEqual(calibration["frame_count"], 1)
        self.assertEqual(calibration["over_budget_observed_count"], 0)
        self.assertEqual(calibration["over_budget_planned_count"], 0)
        self.assertEqual(calibration["total_observed_frame_cost_ms"], 7.4)
        self.assertEqual(calibration["total_planned_current_frame_cost_ms"], 3.2)
        self.assertEqual(calibration["total_planned_frame_relief_ms"], 4.2)
        self.assertEqual(calibration["max_guardband_ms"], 0)
        self.assertEqual(calibration["recommended_next_frame_budget_ms"], 8)
        self.assertEqual(frame["action"], "preserve-dispatch-shape")
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_manager_directive_controls_frame_and_memory_pressure(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        manager = payload["runtime_manager"]
        frame = manager["frames"][0]
        memory = {
            directive["memory"]: directive
            for directive in manager["memory_directives"]
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(manager["mode"], "runtime-manager-directive-v0.33")
        self.assertEqual(manager["profile"], "aggressive")
        self.assertEqual(
            manager["next_frame_policy"],
            "tighten-frame-and-memory-admission",
        )
        self.assertEqual(manager["dispatch_action"], "activate-dispatch-profile")
        self.assertEqual(manager["frame_count"], 1)
        self.assertEqual(manager["memory_layer_count"], 3)
        self.assertEqual(manager["memory_action_count"], 3)
        self.assertEqual(manager["control_action_count"], 4)
        self.assertEqual(manager["next_frame_budget_ms"], 6.0)
        self.assertEqual(manager["hot_path_budget_ms"], 6.0)
        self.assertEqual(manager["copy_queue_budget_ms"], 0)
        self.assertEqual(manager["pre_frame_window_ms"], 4.5)
        self.assertEqual(manager["total_expected_memory_relief_mb"], 40)
        self.assertEqual(frame["scheduler_mode"], "closed-loop-aggressive")
        self.assertEqual(frame["admission_mode"], "prestage-and-defer-noncritical")
        self.assertEqual(frame["queue_policy"], "block-late-copy-queue")
        self.assertEqual(frame["calibration_action"], "apply-dispatch-before-next-frame")
        self.assertEqual(frame["next_frame_budget_ms"], 6.0)
        self.assertEqual(frame["hot_path_budget_ms"], 6.0)
        self.assertEqual(memory["ram"]["action"], "evict-or-defer-residency")
        self.assertEqual(memory["ram"]["expected_relief_mb"], 16)
        self.assertEqual(memory["vram"]["action"], "evict-or-defer-residency")
        self.assertEqual(memory["vram"]["expected_relief_mb"], 16)
        self.assertEqual(memory["swapchain"]["action"], "evict-or-defer-residency")
        self.assertEqual(memory["swapchain"]["expected_relief_mb"], 8)

    def test_runtime_event_server_reports_runtime_manager_directive(self):
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
        manager = summary["runtime_manager"]
        frame = manager["frames"][0]
        memory = {
            directive["memory"]: directive
            for directive in manager["memory_directives"]
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(manager["mode"], "runtime-manager-directive-v0.33")
        self.assertEqual(manager["profile"], "stable")
        self.assertEqual(manager["next_frame_policy"], "maintain-current-envelope")
        self.assertEqual(manager["dispatch_action"], "preserve-dispatch-profile")
        self.assertEqual(manager["memory_action_count"], 0)
        self.assertEqual(manager["control_action_count"], 1)
        self.assertEqual(manager["next_frame_budget_ms"], 8)
        self.assertEqual(manager["hot_path_budget_ms"], 8)
        self.assertEqual(manager["copy_queue_budget_ms"], 1.2)
        self.assertEqual(manager["pre_frame_window_ms"], 4.2)
        self.assertEqual(manager["total_expected_memory_relief_mb"], 0)
        self.assertEqual(frame["scheduler_mode"], "closed-loop-stable")
        self.assertEqual(frame["admission_mode"], "preserve-budgeted-hot-path")
        self.assertEqual(frame["queue_policy"], "budget-copy-queue")
        self.assertEqual(frame["calibration_action"], "preserve-dispatch-shape")
        self.assertEqual(memory["ram"]["action"], "hold-residency")
        self.assertEqual(memory["vram"]["action"], "hold-residency")
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_control_packet_serializes_pressure_directives(self):
        result = replay_adapter_event_stream(
            FIXTURES / "adapter_budget_pressure_events.jsonl"
        )
        payload = result.to_dict()
        packet = payload["runtime_control_packet"]
        commands = {
            command["command"]: command
            for command in packet["commands"]
            if command["domain"] != "memory"
        }
        memory = {
            command["memory"]: command
            for command in packet["commands"]
            if command["domain"] == "memory"
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.45")
        self.assertEqual(packet["mode"], "runtime-control-packet-v0.34")
        self.assertEqual(packet["profile"], "aggressive")
        self.assertEqual(packet["dispatch_action"], "activate-dispatch-profile")
        self.assertEqual(packet["command_count"], 9)
        self.assertEqual(packet["active_command_count"], 9)
        self.assertEqual(packet["frame_command_count"], 2)
        self.assertEqual(packet["queue_command_count"], 2)
        self.assertEqual(packet["scheduler_command_count"], 2)
        self.assertEqual(packet["memory_command_count"], 3)
        self.assertEqual(packet["next_frame_budget_ms"], 6.0)
        self.assertEqual(packet["hot_path_budget_ms"], 6.0)
        self.assertEqual(packet["copy_queue_budget_ms"], 0)
        self.assertEqual(packet["pre_frame_window_ms"], 4.5)
        self.assertEqual(packet["total_expected_memory_relief_mb"], 40)
        self.assertEqual(
            [command["sequence"] for command in packet["commands"]],
            list(range(1, 10)),
        )
        self.assertEqual(
            [command["domain"] for command in packet["commands"]],
            [
                "frame",
                "frame",
                "queue",
                "queue",
                "scheduler",
                "scheduler",
                "memory",
                "memory",
                "memory",
            ],
        )
        self.assertEqual(
            [command["command"] for command in packet["commands"]],
            [
                "set_next_frame_budget",
                "set_hot_path_budget",
                "set_copy_queue_budget",
                "reserve_pre_frame_window",
                "set_admission_mode",
                "set_scheduler_mode",
                "evict_or_defer_residency",
                "evict_or_defer_residency",
                "evict_or_defer_residency",
            ],
        )
        self.assertEqual(commands["set_next_frame_budget"]["value_ms"], 6.0)
        self.assertEqual(commands["set_hot_path_budget"]["value_ms"], 6.0)
        self.assertEqual(commands["set_copy_queue_budget"]["value_ms"], 0)
        self.assertEqual(commands["reserve_pre_frame_window"]["value_ms"], 4.5)
        self.assertEqual(
            commands["set_admission_mode"]["setting"],
            "prestage-and-defer-noncritical",
        )
        self.assertEqual(
            commands["set_scheduler_mode"]["setting"],
            "closed-loop-aggressive",
        )
        self.assertEqual(memory["ram"]["command"], "evict_or_defer_residency")
        self.assertEqual(memory["ram"]["value_mb"], 16)
        self.assertEqual(memory["vram"]["command"], "evict_or_defer_residency")
        self.assertEqual(memory["vram"]["value_mb"], 16)
        self.assertEqual(memory["swapchain"]["command"], "evict_or_defer_residency")
        self.assertEqual(memory["swapchain"]["value_mb"], 8)

    def test_runtime_event_server_reports_runtime_control_packet(self):
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
        packet = summary["runtime_control_packet"]
        commands = {
            command["command"]: command
            for command in packet["commands"]
            if command["domain"] != "memory"
        }
        memory = {
            command["memory"]: command
            for command in packet["commands"]
            if command["domain"] == "memory"
        }

        self.assertEqual(summary["mode"], "runtime-event-client-v0.45")
        self.assertEqual(packet["mode"], "runtime-control-packet-v0.34")
        self.assertEqual(packet["profile"], "stable")
        self.assertEqual(packet["dispatch_action"], "preserve-dispatch-profile")
        self.assertEqual(packet["command_count"], 8)
        self.assertEqual(packet["active_command_count"], 6)
        self.assertEqual(packet["frame_command_count"], 2)
        self.assertEqual(packet["queue_command_count"], 2)
        self.assertEqual(packet["scheduler_command_count"], 2)
        self.assertEqual(packet["memory_command_count"], 2)
        self.assertEqual(packet["next_frame_budget_ms"], 8)
        self.assertEqual(packet["hot_path_budget_ms"], 8)
        self.assertEqual(packet["copy_queue_budget_ms"], 1.2)
        self.assertEqual(packet["pre_frame_window_ms"], 4.2)
        self.assertEqual(
            [command["sequence"] for command in packet["commands"]],
            list(range(1, 9)),
        )
        self.assertEqual(
            [command["domain"] for command in packet["commands"]],
            [
                "frame",
                "frame",
                "queue",
                "queue",
                "scheduler",
                "scheduler",
                "memory",
                "memory",
            ],
        )
        self.assertEqual(
            [command["command"] for command in packet["commands"]],
            [
                "set_next_frame_budget",
                "set_hot_path_budget",
                "set_copy_queue_budget",
                "reserve_pre_frame_window",
                "set_admission_mode",
                "set_scheduler_mode",
                "hold_residency",
                "hold_residency",
            ],
        )
        self.assertEqual(commands["set_copy_queue_budget"]["value_ms"], 1.2)
        self.assertEqual(
            commands["set_admission_mode"]["setting"],
            "preserve-budgeted-hot-path",
        )
        self.assertEqual(
            commands["set_scheduler_mode"]["setting"],
            "closed-loop-stable",
        )
        self.assertEqual(memory["ram"]["command"], "hold_residency")
        self.assertEqual(memory["vram"]["command"], "hold_residency")
        self.assertEqual(summary["failed_responses"], 0)

    def test_runtime_control_packet_covers_memory_reserve_and_observe(self):
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

        packet = build_runtime_control_packet(manager).to_dict()
        memory = {
            command["memory"]: command
            for command in packet["commands"]
            if command["domain"] == "memory"
        }

        self.assertEqual(packet["mode"], "runtime-control-packet-v0.34")
        self.assertEqual(packet["command_count"], 8)
        self.assertEqual(packet["active_command_count"], 7)
        self.assertEqual(packet["memory_command_count"], 2)
        self.assertEqual(
            [command["sequence"] for command in packet["commands"]],
            list(range(1, 9)),
        )
        self.assertEqual(
            [command["command"] for command in packet["commands"]],
            [
                "set_next_frame_budget",
                "set_hot_path_budget",
                "set_copy_queue_budget",
                "reserve_pre_frame_window",
                "set_admission_mode",
                "set_scheduler_mode",
                "reserve_memory_headroom",
                "observe_residency",
            ],
        )
        self.assertEqual(memory["vram"]["command"], "reserve_memory_headroom")
        self.assertEqual(memory["vram"]["setting"], "reserve-headroom")
        self.assertEqual(memory["vram"]["value_mb"], 15.0)
        self.assertEqual(memory["shared"]["command"], "observe_residency")
        self.assertEqual(memory["shared"]["setting"], "observe-residency")
        self.assertEqual(memory["shared"]["priority"], "low")


if __name__ == "__main__":
    unittest.main()
