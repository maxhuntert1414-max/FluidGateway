from __future__ import annotations

import math

from .models import FrameSample, MetricSummary


def clean_numbers(values: list[float | None]) -> list[float]:
    return [value for value in values if value is not None and math.isfinite(value)]


def frame_numbers(frames: list[FrameSample], column: str) -> list[float]:
    return clean_numbers([frame.number(column) for frame in frames])


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def summarize(values: list[float]) -> MetricSummary:
    if not values:
        return MetricSummary(count=0)
    return MetricSummary(
        count=len(values),
        average=average(values),
        p50=percentile(values, 0.50),
        p95=percentile(values, 0.95),
        p99=percentile(values, 0.99),
        maximum=max(values),
        stdev=stdev(values),
    )


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f} ms"


def fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}x"


def fmt_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"
