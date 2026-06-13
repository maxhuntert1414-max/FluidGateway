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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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
            self.assertEqual(payload["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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
            self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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
        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
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

        self.assertEqual(payload["mode"], "runtime-adapter-session-v0.18")
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

        self.assertEqual(summary["mode"], "runtime-event-client-v0.18")
        self.assertEqual(summary["admission_decision_count"], 2)
        self.assertEqual(summary["admission_plan"]["prefetch_count"], 1)
        self.assertEqual(summary["admission_plan"]["estimated_hot_path_cost_ms"], 3.2)
        self.assertEqual(summary["failed_responses"], 0)


if __name__ == "__main__":
    unittest.main()
