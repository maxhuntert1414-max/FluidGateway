import unittest

from fluidgateway.analyzer import analyze_trace
from fluidgateway.models import FrameSample, TraceData


class TraceScopeTests(unittest.TestCase):
    def test_distinct_present_streams_cannot_be_misattributed_to_one_app(self):
        for column in ("Application", "ProcessID", "SwapChainAddress"):
            with self.subTest(column=column):
                frames = [FrameSample({"Application": "app.exe", column: value},
                                      {"MsBetweenPresents": timing})
                          for value, timing in (("a", 10), ("b", 30))]
                with self.assertRaisesRegex(ValueError, "one application/process/swapchain"):
                    analyze_trace(TraceData("mixed.csv", [column, "MsBetweenPresents"], frames))

    def test_case_variations_and_missing_optional_identity_do_not_break_single_stream(self):
        frames = [FrameSample({"Application": name}, {"MsBetweenPresents": 10})
                  for name in ("app.exe", "APP.EXE")]
        report = analyze_trace(TraceData("one.csv", ["Application", "MsBetweenPresents"], frames))
        self.assertEqual(100, report.summary.approx_fps)
