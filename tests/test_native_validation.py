from copy import deepcopy
import unittest

from tools.native_gateway_validation import assess_soak


class NativeValidationTests(unittest.TestCase):
    def setUp(self):
        self.report = dict(
            complete=True,
            seconds_required=3600,
            minimum_operations=1000000,
            elapsed_seconds=3601,
            operations=18000000,
            samples=[
                dict(elapsed_seconds=second, private_bytes=8 * 1024 * 1024)
                for second in range(60, 3601, 60)
            ],
        )

    def test_complete_continuous_stable_soak_passes(self):
        original = deepcopy(self.report)
        checks = assess_soak(self.report)
        self.assertTrue(checks["soak_gate_passed"])
        self.assertTrue(checks["continuous_load_passed"])
        self.assertEqual(checks["maximum_sample_gap_seconds"], 60)
        self.assertEqual(self.report, original)

    def test_suspend_gap_is_not_counted_as_continuous_load(self):
        self.report["samples"] = self.report["samples"][:10] + self.report["samples"][30:]
        checks = assess_soak(self.report)
        self.assertTrue(checks["memory_plateau_passed"])
        self.assertFalse(checks["continuous_load_passed"])
        self.assertFalse(checks["soak_gate_passed"])

    def test_final_unsampled_pause_fails(self):
        self.report["elapsed_seconds"] += 120
        self.assertFalse(assess_soak(self.report)["soak_gate_passed"])

    def test_memory_failure_is_not_overridden_by_elapsed_time(self):
        self.report["samples"][-1]["private_bytes"] *= 2
        checks = assess_soak(self.report)
        self.assertTrue(checks["continuous_load_passed"])
        self.assertFalse(checks["memory_plateau_passed"])
        self.assertFalse(checks["soak_gate_passed"])

    def test_incomplete_or_short_run_fails(self):
        for key, value in (("complete", False), ("seconds_required", 7200), ("operations", 10)):
            with self.subTest(key=key):
                report = deepcopy(self.report)
                report[key] = value
                self.assertFalse(assess_soak(report)["soak_gate_passed"])

    def test_missing_warmup_samples_fails(self):
        self.report["samples"] = []
        self.assertFalse(assess_soak(self.report)["soak_gate_passed"])

    def test_regressing_sample_clock_fails(self):
        self.report["samples"][20]["elapsed_seconds"] = 0
        self.assertFalse(assess_soak(self.report)["soak_gate_passed"])
