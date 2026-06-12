from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EXPECTED_COLUMNS = (
    "Application",
    "PresentRuntime",
    "PresentMode",
    "SyncInterval",
    "AllowsTearing",
    "MsCPUBusy",
    "MsCPUWait",
    "MsGPULatency",
    "MsGPUTime",
    "MsGPUBusy",
    "MsGPUWait",
    "DisplayLatency",
    "DisplayedTime",
    "MsAnimationError",
    "MsBetweenPresents",
    "MsInPresentAPI",
    "MsUntilDisplayed",
    "MsRenderPresentLatency",
)

NUMERIC_COLUMNS = (
    "SyncInterval",
    "AllowsTearing",
    "MsCPUBusy",
    "MsCPUWait",
    "MsGPULatency",
    "MsGPUTime",
    "MsGPUBusy",
    "MsGPUWait",
    "DisplayLatency",
    "DisplayedTime",
    "MsAnimationError",
    "MsBetweenPresents",
    "MsInPresentAPI",
    "MsUntilDisplayed",
    "MsRenderPresentLatency",
)

SUMMARY_METRICS = (
    "MsBetweenPresents",
    "DisplayedTime",
    "DisplayLatency",
    "MsUntilDisplayed",
    "MsRenderPresentLatency",
    "MsInPresentAPI",
    "MsCPUBusy",
    "MsCPUWait",
    "MsGPUTime",
    "MsGPUBusy",
    "MsGPUWait",
    "MsGPULatency",
    "MsAnimationError",
)


@dataclass(frozen=True)
class FrameSample:
    raw: dict[str, str]
    values: dict[str, float | None]

    def text(self, column: str) -> str:
        return (self.raw.get(column) or "").strip()

    def number(self, column: str) -> float | None:
        return self.values.get(column)

    @property
    def present_mode(self) -> str:
        return self.text("PresentMode")

    @property
    def present_runtime(self) -> str:
        return self.text("PresentRuntime")

    @property
    def application(self) -> str:
        return self.text("Application")

    @property
    def displayed_missing(self) -> bool:
        raw = self.text("DisplayedTime").lower()
        return raw in {"", "na", "n/a", "nan", "null", "none"}


@dataclass(frozen=True)
class TraceData:
    source: str
    columns: list[str]
    frames: list[FrameSample]

    @property
    def missing_columns(self) -> list[str]:
        return [column for column in EXPECTED_COLUMNS if column not in self.columns]


@dataclass(frozen=True)
class MetricSummary:
    count: int
    average: float | None = None
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    maximum: float | None = None
    stdev: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "average": self.average,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "maximum": self.maximum,
            "stdev": self.stdev,
        }


@dataclass(frozen=True)
class Evidence:
    label: str
    value: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "value": self.value, "detail": self.detail}


@dataclass(frozen=True)
class Finding:
    id: str
    title: str
    hypothesis: str
    severity: str
    confidence: str
    score: int
    evidence: list[Evidence]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "severity": self.severity,
            "confidence": self.confidence,
            "score": self.score,
            "evidence": [item.to_dict() for item in self.evidence],
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class ManagementAction:
    id: str
    title: str
    layer: str
    objective: str
    policy: str
    trigger: str
    expected_effect: str
    risk: str
    priority: int
    confidence: str
    source_findings: list[str]
    evidence: list[Evidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "layer": self.layer,
            "objective": self.objective,
            "policy": self.policy,
            "trigger": self.trigger,
            "expected_effect": self.expected_effect,
            "risk": self.risk,
            "priority": self.priority,
            "confidence": self.confidence,
            "source_findings": self.source_findings,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class ManagementPlan:
    mode: str
    target: str
    summary: str
    actions: list[ManagementAction]
    constraints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "target": self.target,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions],
            "constraints": self.constraints,
        }


@dataclass(frozen=True)
class TraceSummary:
    source: str
    application: str
    runtimes: list[str]
    present_modes: list[str]
    frame_count: int
    duration_ms: float | None
    approx_fps: float | None
    missing_columns: list[str]
    metrics: dict[str, MetricSummary] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "application": self.application,
            "runtimes": self.runtimes,
            "present_modes": self.present_modes,
            "frame_count": self.frame_count,
            "duration_ms": self.duration_ms,
            "approx_fps": self.approx_fps,
            "missing_columns": self.missing_columns,
            "metrics": {
                name: summary.to_dict() for name, summary in self.metrics.items()
            },
        }


@dataclass(frozen=True)
class AnalysisReport:
    summary: TraceSummary
    findings: list[Finding]
    management_plan: ManagementPlan
    disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "management_plan": self.management_plan.to_dict(),
            "disclaimer": self.disclaimer,
        }
