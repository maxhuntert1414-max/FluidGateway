from __future__ import annotations

import csv
from pathlib import Path

from .models import NUMERIC_COLUMNS, FrameSample, TraceData


NA_VALUES = {"", "na", "n/a", "nan", "null", "none", "-"}


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

        columns = [column.strip() for column in reader.fieldnames if column]
        frames: list[FrameSample] = []

        for row in reader:
            normalized = {
                (key or "").strip(): (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            values = {
                column: parse_number(normalized.get(column))
                for column in NUMERIC_COLUMNS
                if column in normalized
            }
            frames.append(FrameSample(raw=normalized, values=values))

    if not frames:
        raise ValueError(f"{csv_path} has headers but no frame rows.")

    return TraceData(source=str(csv_path), columns=columns, frames=frames)
