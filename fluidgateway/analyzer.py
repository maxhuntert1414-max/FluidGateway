from __future__ import annotations

from collections import Counter

from .heuristics import run_heuristics
from .management import build_management_plan
from .models import (
    SUMMARY_METRICS,
    AnalysisReport,
    FrameSample,
    TraceData,
    TraceSummary,
)
from .stats import frame_numbers, summarize


DISCLAIMER = (
    "Diagnostico inferido: estes achados apontam desperdicio provavel, "
    "nao prova absoluta de causa interna no jogo, driver ou sistema."
)


def analyze_trace(trace: TraceData) -> AnalysisReport:
    summary = build_summary(trace)
    findings = run_heuristics(trace.frames, summary)
    management_plan = build_management_plan(summary, findings)
    return AnalysisReport(
        summary=summary,
        findings=findings,
        management_plan=management_plan,
        disclaimer=DISCLAIMER,
    )


def build_summary(trace: TraceData) -> TraceSummary:
    for column in ("Application", "ProcessID", "SwapChainAddress"):
        identities = {value.casefold() for value in unique_texts(trace.frames, column)}
        if len(identities) > 1:
            raise ValueError(
                f"Trace contains multiple {column} values; filter the CSV to "
                "one application/process/swapchain before analyzing frame timing."
            )
    metrics = {
        metric: summarize(frame_numbers(trace.frames, metric))
        for metric in SUMMARY_METRICS
    }
    duration_ms = estimate_duration_ms(trace.frames)
    approx_fps = None
    if duration_ms and duration_ms > 0:
        approx_fps = len(trace.frames) / (duration_ms / 1000)

    return TraceSummary(
        source=trace.source,
        application=most_common_text(trace.frames, "Application") or "Unknown",
        runtimes=sorted(unique_texts(trace.frames, "PresentRuntime")),
        present_modes=sorted(unique_texts(trace.frames, "PresentMode")),
        frame_count=len(trace.frames),
        duration_ms=duration_ms,
        approx_fps=approx_fps,
        missing_columns=trace.missing_columns,
        metrics=metrics,
    )


def estimate_duration_ms(frames: list[FrameSample]) -> float | None:
    between = frame_numbers(frames, "MsBetweenPresents")
    if between:
        return sum(value for value in between if value >= 0)

    displayed = frame_numbers(frames, "DisplayedTime")
    if displayed:
        return sum(value for value in displayed if value >= 0)

    return None


def unique_texts(frames: list[FrameSample], column: str) -> set[str]:
    return {
        value
        for value in (frame.text(column) for frame in frames)
        if value
    }


def most_common_text(frames: list[FrameSample], column: str) -> str | None:
    values = [frame.text(column) for frame in frames if frame.text(column)]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]
