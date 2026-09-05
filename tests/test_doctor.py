from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fluidgateway.cli import main
from fluidgateway.doctor import (
    OPTIONAL_VULKAN_ASSETS, REQUIRED_NATIVE_ASSETS, collect_doctor_report,
    probe_native_assets,
)
from fluidgateway.host import HostGpuCapability, build_host_capability_snapshot


def test_host_snapshot():
    return build_host_capability_snapshot(
        os_name="Windows",
        os_release="11",
        os_version="test",
        machine="AMD64",
        processor="test-cpu",
        python_version="3.13.0",
        cpu_logical_count=16,
        total_ram_mb=32768,
        available_ram_mb=24576,
        gpus=[HostGpuCapability("Test GPU", 8192, "1", "test")],
    )


def write_test_pe(path: Path) -> None:
    payload = bytearray(132)
    payload[:2] = b"MZ"
    payload[60:64] = (128).to_bytes(4, "little")
    payload[128:132] = b"PE\x00\x00"
    path.write_bytes(payload)


class DoctorTests(unittest.TestCase):
    def test_vulkan_assets_do_not_claim_execution_or_break_existing_native_builds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            for name in REQUIRED_NATIVE_ASSETS:
                write_test_pe(directory / name)
            legacy = probe_native_assets(directory)
            self.assertEqual(legacy.status, "pass")
            self.assertFalse(legacy.evidence["optional_vulkan_assets_present"])
            for name in OPTIONAL_VULKAN_ASSETS:
                write_test_pe(directory / name)
            vulkan = probe_native_assets(directory)
            self.assertEqual(vulkan.status, "pass")
            self.assertTrue(vulkan.evidence["optional_vulkan_assets_present"])
            self.assertFalse(vulkan.evidence["vulkan_device_execution_verified"])
            (directory / OPTIONAL_VULKAN_ASSETS[0]).write_bytes(b"invalid")
            invalid = probe_native_assets(directory)
            self.assertFalse(invalid.evidence["optional_vulkan_assets_present"])
            self.assertEqual(invalid.status, "pass")

    def test_report_is_fail_closed_about_unsupported_actuation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "tool.exe"
            write_test_pe(executable)
            native_directory = Path(temporary_directory) / "native"
            native_directory.mkdir()
            for name in REQUIRED_NATIVE_ASSETS:
                write_test_pe(native_directory / name)
            report = collect_doctor_report(
                state_directory=temporary_directory,
                presentmon_executable=executable,
                fluidruntime_executable=executable,
                native_directory=native_directory,
                host_snapshot=test_host_snapshot(),
            )

        self.assertEqual(report["status"], "ready-with-limitations")
        self.assertTrue(report["readiness"]["offline_trace_diagnostics"])
        self.assertTrue(report["readiness"]["live_presentmon_capture"])
        self.assertTrue(report["readiness"]["owned_native_labs"])
        self.assertFalse(report["readiness"]["external_process_hooking"])
        self.assertFalse(report["readiness"]["system_wide_actuation"])
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["would_modify_system"])

    def test_cli_writes_structured_report_when_optional_tools_are_missing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "doctor.json"
            with patch(
                "fluidgateway.doctor.collect_host_capability_snapshot",
                return_value=test_host_snapshot(),
            ), patch("fluidgateway.doctor.shutil.which", return_value=None), redirect_stdout(StringIO()):
                status = main(["doctor", "--out", str(output)])

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertFalse(payload["readiness"]["live_presentmon_capture"])
        self.assertFalse(payload["readiness"]["owned_native_labs"])

    def test_explicit_invalid_executable_is_a_configuration_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid = Path(temporary_directory) / "not-a-pe.exe"
            invalid.write_bytes(b"MZ")
            report = collect_doctor_report(
                state_directory=temporary_directory,
                fluidruntime_executable=invalid,
                host_snapshot=test_host_snapshot(),
            )

        runtime_check = next(
            check for check in report["checks"] if check["id"] == "fluidruntime"
        )
        self.assertEqual(report["status"], "misconfigured")
        self.assertEqual(runtime_check["status"], "fail")
        self.assertFalse(report["readiness"]["owned_native_labs"])

    def test_keyboard_interrupt_returns_shell_interrupt_status(self):
        stderr = StringIO()
        with patch(
            "fluidgateway.cli.serve_runtime_events",
            side_effect=KeyboardInterrupt,
        ), redirect_stdout(StringIO()), redirect_stderr(stderr):
            status = main(["runtime", "serve-events", "--once"])

        self.assertEqual(status, 130)
        self.assertIn("interrupted", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
