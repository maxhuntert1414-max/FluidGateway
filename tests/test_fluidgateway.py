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
from fluidgateway.events import replay_event_stream, write_event_replay
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.9")
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

                with redirect_stdout(StringIO()):
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
            self.assertEqual(payload["mode"], "runtime-event-client-v0.9")
            self.assertEqual(payload["events_sent"], 12)
            self.assertEqual(payload["decision_count"], 4)
            self.assertEqual(payload["failed_responses"], 0)

    def test_adapter_session_replays_lifecycle_stream(self):
        result = replay_adapter_event_stream(FIXTURES / "adapter_session_events.jsonl")
        payload = result.to_dict()
        frame = payload["frames"][0]
        policies = {
            item["decision"]["policy"]
            for item in payload["results"]
            if item["decision"] is not None
        }

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.9")
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
            with redirect_stdout(StringIO()):
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
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.9")
            self.assertEqual(payload["snapshot"]["estimated_saved_mb"], 40)

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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.9")
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


if __name__ == "__main__":
    unittest.main()
