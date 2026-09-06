import copy
import json
import tempfile
import unittest
from pathlib import Path

from fluidgateway.application_session import COUNTERS, analyze_application_session, write_application_report
from fluidgateway.cli import main


def session():
    counters = dict.fromkeys(COUNTERS, 0)
    counters.update(devices=1, instances=1, presents=100, buffer_copy_bytes=4096,
                    buffer_copies=1, queue_waits=2)
    return {"schema": "fluidruntime-application-session-v1", "process_id": 42,
            "executable": "demo<script>.exe", "executable_sha256": "a" * 64,
            "layer_sha256": "b" * 64, "observation_requested": True, "layer_verified": True,
            "native_actuation_enabled": False, "performance_claim_allowed": False,
            "process_exited": True, "elapsed_milliseconds": 1000, "failure": None,
            "samples": [{"elapsed_milliseconds": 999, "cpu_milliseconds": 100,
                         "working_set_bytes": 1024, "private_bytes": 1024, "thread_count": 2,
                         "vulkan": counters}], "windows_priority": None}


class ApplicationSessionTests(unittest.TestCase):
    def analyze(self, value):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "session.json"
            source.write_text(json.dumps(value), encoding="utf-8")
            return analyze_application_session(source)

    def test_numeric_evidence_never_promotes_copy_elision(self):
        result = self.analyze(session())
        self.assertFalse(result["native_actuation_allowed"])
        self.assertFalse(result["performance_claim_allowed"])
        self.assertEqual(4096, result["counters"]["buffer_copy_bytes"])
        self.assertTrue(all(finding["evidence"] for finding in result["findings"]))

    def test_rejects_mutated_identity_flags_and_counters(self):
        for key, value in (("schema", "other"), ("process_id", True), ("layer_sha256", "z" * 64),
                           ("native_actuation_enabled", True), ("performance_claim_allowed", True),
                           ("elapsed_milliseconds", float("nan"))):
            with self.subTest(key=key):
                report = session()
                report[key] = value
                with self.assertRaises(ValueError):
                    self.analyze(report)
        for value in (-1, True, 1.5, 2**63):
            report = session()
            report["samples"][0]["vulkan"]["presents"] = value
            with self.assertRaises(ValueError):
                self.analyze(report)

    def test_rejects_missing_counter_and_backwards_sequence(self):
        report = session()
        del report["samples"][0]["vulkan"]["frees"]
        with self.assertRaises(ValueError):
            self.analyze(report)
        report = session()
        report["samples"].append(copy.deepcopy(report["samples"][0]))
        report["samples"][1]["vulkan"]["presents"] = 1
        with self.assertRaises(ValueError):
            self.analyze(report)

    def test_baseline_and_capacity_limits_are_not_successful_optimization(self):
        report = session()
        report["layer_verified"] = False
        report["samples"][0]["vulkan"]["untracked_allocations"] = 1
        result = self.analyze(report)
        self.assertEqual({"incomplete-session", "tracking-capacity", "recorded-transfers", "queue-idle-waits"},
                         {item["id"] for item in result["findings"]})

    def test_priority_identity_mismatch_is_rejected(self):
        report = session()
        report["windows_priority"] = {"process_id": 99}
        with self.assertRaises(ValueError):
            self.analyze(report)

    def test_priority_cannot_claim_restoration_at_another_priority(self):
        report = session()
        report["windows_priority"] = {"process_id": 42, "target_sha256": "a" * 64,
            "before": "Normal", "requested": "AboveNormal", "after": "Normal", "applied": True,
            "restoration": "restored", "requested_seconds": 2, "start_time_utc_ticks": 1234,
            "elapsed_milliseconds": 2001, "authority": "explicit-user-timed-priority-only"}
        self.assertEqual("restored", self.analyze(report)["windows_priority"]["restoration"])
        report["windows_priority"]["after"] = "High"
        with self.assertRaises(ValueError):
            self.analyze(report)

    def test_html_escapes_source_and_cli_writes_both_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "session.json"
            source.write_text(json.dumps(session()), encoding="utf-8")
            output = Path(directory) / "report.html"
            self.assertEqual(0, main(["analyze-app", "--session", str(source), "--out", str(output)]))
            self.assertNotIn("demo<script>", output.read_text(encoding="utf-8"))
            self.assertIn("demo&lt;script&gt;", output.read_text(encoding="utf-8"))
            self.assertTrue(output.with_suffix(".json").is_file())

    def test_output_collision_preserves_original_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "session.json"
            original = json.dumps(session())
            source.write_text(original, encoding="utf-8")
            result = analyze_application_session(source)
            with self.assertRaises(ValueError):
                write_application_report(result, source.with_suffix(".html"))
            self.assertEqual(original, source.read_text(encoding="utf-8"))
            self.assertFalse(source.with_suffix(".html").exists())

    def test_huge_numbers_fail_with_validation_error(self):
        report = session()
        report["elapsed_milliseconds"] = 10 ** 400
        with self.assertRaises(ValueError):
            self.analyze(report)

    def test_size_limit_counts_utf8_bytes_not_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "session.json"
            report = session()
            report["notes"] = "\u00e9" * (8 * 1024 * 1024)
            source.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds 16 MiB"):
                analyze_application_session(source)

    def test_contradictory_priority_outcomes_are_rejected(self):
        for state, applied, after in (("not-applied", True, None),
                                      ("process-exited", False, None),
                                      ("process-exited", True, "AboveNormal"),
                                      ("external-change-preserved", True, "AboveNormal"),
                                      ("external-change-preserved", True, None),
                                      ("restore-failed", False, None)):
            with self.subTest(state=state, applied=applied, after=after):
                report = session()
                report["windows_priority"] = {"process_id": 42, "target_sha256": "a" * 64,
                    "before": "Normal", "requested": "AboveNormal", "after": after, "applied": applied,
                    "restoration": state, "requested_seconds": 2, "start_time_utc_ticks": 1234,
                    "elapsed_milliseconds": 2001, "authority": "explicit-user-timed-priority-only"}
                with self.assertRaises(ValueError):
                    self.analyze(report)
