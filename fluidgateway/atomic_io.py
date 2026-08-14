from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(
    output_path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Replace a file only after its complete contents reach stable storage."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def atomic_write_json(
    output_path: str | Path,
    payload: Any,
    *,
    trailing_newline: bool = False,
) -> Path:
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    if trailing_newline:
        content += "\n"
    return atomic_write_text(output_path, content)
