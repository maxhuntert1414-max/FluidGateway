import unittest

from fluidgateway.analyzer import analyze_trace
from fluidgateway.models import FrameSample, TraceData


class HeuristicConfidenceTests(unittest.TestCase):
    def test_missing_and_na_supporting_metrics_reduce_confidence(self):
        cases = (
            ("cpu-present-wait", "MsInPresentAPI", "MsCPUWait"),
            ("gpu-bubbles", "MsGPUWait", "MsGPUTime"),
        )
        for finding_id, observed, supporting in cases:
            for value, expected in ((None, "medium"), (0.0, "high"), (5.0, "high")):
                with self.subTest(finding=finding_id, supporting=value):
                    frame = FrameSample({}, {"MsBetweenPresents": 16.0, observed: 12.0, supporting: value})
                    report = analyze_trace(TraceData("test", list(frame.values), [frame] * 10))
                    finding = next(item for item in report.findings if item.id == finding_id)
                    self.assertEqual(expected, finding.confidence)
