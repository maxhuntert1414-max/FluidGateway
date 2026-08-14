from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fluidgateway.atomic_io import atomic_write_json, atomic_write_text


class AtomicIoTests(unittest.TestCase):
    def test_atomic_write_replaces_complete_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "state.json"

            atomic_write_json(path, {"generation": 1})
            atomic_write_json(path, {"generation": 2})

            self.assertEqual(
                {"generation": 2},
                json.loads(path.read_text(encoding="utf-8")),
            )
            self.assertEqual([], list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_failed_replace_preserves_previous_file_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.json"
            path.write_text("stable", encoding="utf-8")

            with patch(
                "fluidgateway.atomic_io.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated replace failure"):
                    atomic_write_text(path, "partial")

            self.assertEqual("stable", path.read_text(encoding="utf-8"))
            self.assertEqual([], list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_cleanup_failure_does_not_mask_original_write_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "state.json"
            path.write_text("stable", encoding="utf-8")

            with patch(
                "fluidgateway.atomic_io.os.replace",
                side_effect=OSError("replace failed"),
            ), patch(
                "fluidgateway.atomic_io.Path.unlink",
                side_effect=OSError("cleanup failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_text(path, "partial")

            self.assertEqual("stable", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
