from __future__ import annotations

import csv
from pathlib import Path

from .models import EXPECTED_COLUMNS, NUMERIC_COLUMNS, FrameSample, TraceData


NA_VALUES = {"", "na", "n/a", "nan", "null", "none", "-"}

COLUMN_ALIASES = {column.casefold(): column for column in EXPECTED_COLUMNS}
COLUMN_ALIASES.update(
    {
        "runtime": "PresentRuntime",
        "msbetweendisplaychange": "DisplayedTime",
        "msuntilrendercomplete": "MsRenderPresentLatency",
    }
)


def canonical_column_name(column: str) -> str:
    stripped = column.strip()
    return COLUMN_ALIASES.get(stripped.casefold(), stripped)


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in NA_VALUES:
        return None
    if text.lower().endswith("ms"):
        text = text[:-2].strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_presentmon_csv(path: str | Path) -> TraceData:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path} does not look like a CSV with headers.")

        columns = list(
            dict.fromkeys(
                canonical_column_name(column)
                for column in reader.fieldnames
                if column and column.strip()
            )
        )
        frames: list[FrameSample] = []

        for row in reader:
            source = {
                (key or "").strip(): (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            normalized = dict(source)
            for key, value in source.items():
                normalized.setdefault(canonical_column_name(key), value)

            has_native_displayed_time = any(
                key.casefold() == "displayedtime" for key in source
            )
            dropped = parse_number(source.get("Dropped"))
            if not has_native_displayed_time and dropped not in (None, 0):
                normalized["DisplayedTime"] = "NA"

            values = {
                column: parse_number(normalized.get(column))
                for column in NUMERIC_COLUMNS
                if column in normalized
            }
            frames.append(FrameSample(raw=normalized, values=values))

    if not frames:
        raise ValueError(f"{csv_path} has headers but no frame rows.")

    return TraceData(source=str(csv_path), columns=columns, frames=frames)
