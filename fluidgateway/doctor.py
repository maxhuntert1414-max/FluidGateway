from __future__ import annotations

import platform
import shutil
import struct
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .atomic_io import atomic_write_json, atomic_write_text
from .host import HostCapabilitySnapshot, collect_host_capability_snapshot
from .server import create_runtime_event_server


DOCTOR_MODE = "fluidgateway-doctor-v0.67.1"
REQUIRED_NATIVE_ASSETS = (
    "fluidruntime-native-probe.exe",
    "fluidruntime-d3d12-observation.exe",
    "fluidruntime-d3d12-hook.dll",
    "fluidruntime-d3d12-hook-target.exe",
    "fluidruntime-d3d12-transfer-hook.dll",
    "fluidruntime-d3d12-transfer-target.exe",
    "fluidruntime-present-hook.dll",
    "fluidruntime-hook-target.exe",
)


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    status: str
    summary: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "summary": self.summary,
            "evidence": self.evidence,
        }


def collect_doctor_report(
    *,
    state_directory: str | Path,
    presentmon_executable: str | Path | None = None,
    fluidruntime_executable: str | Path | None = None,
    native_directory: str | Path | None = None,
    host_snapshot: HostCapabilitySnapshot | None = None,
) -> dict[str, Any]:
    state_check = probe_atomic_state_directory(state_directory)
    endpoint_check = probe_loopback_endpoint()
    presentmon_check = probe_executable(
        "presentmon",
        presentmon_executable,
        "PresentMon",
    )
    runtime_check = probe_executable(
        "fluidruntime",
        fluidruntime_executable,
        "fluidruntime",
    )
    native_check = probe_native_assets(native_directory)
    host = host_snapshot or collect_host_capability_snapshot()
    host_status = "pass" if host.telemetry_confidence == "high" else "warn"
    host_check = DoctorCheck(
        id="host-telemetry",
        status=host_status,
        summary=(
            "Host telemetry captured."
            if host_status == "pass"
            else "Host telemetry is partial; decisions must keep reduced confidence."
        ),
        evidence={
            "telemetry_confidence": host.telemetry_confidence,
            "capture_errors": list(host.capture_errors),
            "gpu_count": host.gpu_count,
            "gpu_selection_basis": host.gpu_selection_basis,
        },
    )
    python_supported = sys.version_info >= (3, 10)
    pointer_bits = struct.calcsize("P") * 8
    platform_check = DoctorCheck(
        id="runtime-platform",
        status="pass" if python_supported and pointer_bits == 64 else "fail",
        summary=(
            "Python and process architecture satisfy the supported local baseline."
            if python_supported and pointer_bits == 64
            else "Python 3.10+ and a 64-bit process are required."
        ),
        evidence={
            "python_version": platform.python_version(),
            "pointer_bits": pointer_bits,
            "os": platform.system() or "unknown",
            "machine": platform.machine() or "unknown",
        },
    )
    checks = [
        platform_check,
        state_check,
        endpoint_check,
        host_check,
        presentmon_check,
        runtime_check,
        native_check,
    ]
    diagnostic_ready = all(
        check.status == "pass"
        for check in (platform_check, state_check)
    )
    decision_server_ready = diagnostic_ready and endpoint_check.status == "pass"
    live_capture_ready = diagnostic_ready and presentmon_check.status == "pass"
    owned_native_labs_ready = (
        platform.system().lower() == "windows"
        and runtime_check.status == "pass"
        and native_check.status == "pass"
    )
    readiness = {
        "offline_trace_diagnostics": diagnostic_ready,
        "fluidlink_decision_server": decision_server_ready,
        "live_presentmon_capture": live_capture_ready,
        "owned_native_labs": owned_native_labs_ready,
        "external_process_hooking": False,
        "system_wide_actuation": False,
    }
    blockers = [
        "External-process injection and general game hooking are not supported.",
        "System-wide CPU/GPU/RAM/VRAM scheduling is not supported.",
        "Native actuation remains restricted to owned, cooperative lab targets.",
    ]
    if not live_capture_ready:
        blockers.append("Live capture needs an explicit, available PresentMon executable.")
    if not owned_native_labs_ready:
        blockers.append(
            "Owned native labs need FluidRuntime plus the complete Windows native asset set."
        )
    configuration_failed = any(check.status == "fail" for check in checks)
    if not diagnostic_ready:
        status = "blocked"
    elif configuration_failed:
        status = "misconfigured"
    else:
        status = "ready-with-limitations"
    return {
        "mode": DOCTOR_MODE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fluidgateway_version": __version__,
        "dry_run": True,
        "would_modify_system": False,
        "status": status,
        "readiness": readiness,
        "checks": [check.to_dict() for check in checks],
        "host": host.to_dict(),
        "hard_boundaries": blockers,
    }


def write_doctor_report(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    return atomic_write_json(path, report, trailing_newline=True)


def probe_atomic_state_directory(state_directory: str | Path) -> DoctorCheck:
    raw_directory = Path(state_directory).expanduser()
    try:
        directory = raw_directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="doctor-", dir=directory) as temporary:
            probe_path = Path(temporary) / "atomic-write.probe"
            atomic_write_text(probe_path, "fluidgateway-doctor")
            verified = probe_path.read_text(encoding="utf-8") == "fluidgateway-doctor"
        if not verified:
            raise OSError("atomic write verification returned unexpected content")
    except (OSError, RuntimeError) as exc:
        return DoctorCheck(
            id="state-directory",
            status="fail",
            summary="Local state directory is not safely writable.",
            evidence={"path": str(raw_directory), "error": str(exc)},
        )
    return DoctorCheck(
        id="state-directory",
        status="pass",
        summary="Atomic local state writes succeeded.",
        evidence={"path": str(directory)},
    )


def probe_loopback_endpoint() -> DoctorCheck:
    try:
        with create_runtime_event_server("127.0.0.1", 0) as server:
            address = f"{server.server_address[0]}:{server.server_address[1]}"
    except OSError as exc:
        return DoctorCheck(
            id="loopback-endpoint",
            status="fail",
            summary="FluidLink could not reserve a loopback endpoint.",
            evidence={"error": str(exc)},
        )
    return DoctorCheck(
        id="loopback-endpoint",
        status="pass",
        summary="FluidLink can reserve an isolated loopback endpoint.",
        evidence={
            "probe_address": address,
            "windows_exclusive_bind": platform.system().lower() == "windows",
        },
    )


def probe_executable(
    check_id: str,
    explicit_path: str | Path | None,
    command_name: str,
) -> DoctorCheck:
    if explicit_path is not None:
        source = "explicit"
        try:
            candidate = Path(explicit_path).expanduser().resolve()
            found = str(candidate) if candidate.is_file() else None
        except (OSError, RuntimeError) as exc:
            return DoctorCheck(
                id=check_id,
                status="fail",
                summary=f"{command_name} path could not be resolved.",
                evidence={"source": source, "path": str(explicit_path), "error": str(exc)},
            )
    else:
        found = shutil.which(command_name)
        source = "path"
    if found is None:
        return DoctorCheck(
            id=check_id,
            status="fail" if explicit_path is not None else "warn",
            summary=f"{command_name} was not found; its dependent capability is disabled.",
            evidence={"source": source, "path": None},
        )
    candidate = Path(found).resolve()
    if platform.system().lower() == "windows" and not is_portable_executable(candidate):
        return DoctorCheck(
            id=check_id,
            status="fail",
            summary=f"{command_name} exists but is not a Windows PE executable.",
            evidence={"source": source, "path": str(candidate)},
        )
    return DoctorCheck(
        id=check_id,
        status="pass",
        summary=f"{command_name} executable is available.",
        evidence={"source": source, "path": str(candidate)},
    )


def probe_native_assets(native_directory: str | Path | None) -> DoctorCheck:
    if native_directory is None:
        return DoctorCheck(
            id="native-assets",
            status="warn",
            summary="Native asset directory was not supplied; owned labs are disabled.",
            evidence={"path": None, "missing": list(REQUIRED_NATIVE_ASSETS)},
        )
    try:
        directory = Path(native_directory).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return DoctorCheck(
            id="native-assets",
            status="fail",
            summary="Native asset directory could not be resolved.",
            evidence={"path": str(native_directory), "error": str(exc)},
        )
    missing = [
        name
        for name in REQUIRED_NATIVE_ASSETS
        if not is_portable_executable(directory / name)
    ]
    if missing:
        return DoctorCheck(
            id="native-assets",
            status="fail",
            summary="Native asset set is incomplete or contains invalid PE files.",
            evidence={"path": str(directory), "missing": missing},
        )
    return DoctorCheck(
        id="native-assets",
        status="pass",
        summary="Complete owned-lab native asset set is available.",
        evidence={"path": str(directory), "missing": []},
    )


def is_portable_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            dos_header = handle.read(64)
            if len(dos_header) != 64 or dos_header[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(dos_header[60:64], "little")
            if pe_offset < 64 or pe_offset > 64 * 1024 * 1024:
                return False
            handle.seek(pe_offset)
            return handle.read(4) == b"PE\x00\x00"
    except (OSError, ValueError):
        return False
