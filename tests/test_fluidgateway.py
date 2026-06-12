from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from fluidgateway.cli import main
from fluidgateway.analyzer import analyze_trace
from fluidgateway.parser import parse_number, parse_presentmon_csv
from fluidgateway.report import write_report


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


if __name__ == "__main__":
    unittest.main()
