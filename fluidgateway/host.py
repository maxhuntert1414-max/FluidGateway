from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Any


HOST_CAPABILITY_MODE = "host-capability-snapshot-v0.47"
HOST_CAPTURE_GUARD = "observe-only"
BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class HostGpuCapability:
    name: str
    adapter_ram_mb: float | None
    driver_version: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "adapter_ram_mb": round(self.adapter_ram_mb, 4)
            if self.adapter_ram_mb is not None
            else None,
            "driver_version": self.driver_version,
            "source": self.source,
        }


@dataclass(frozen=True)
class HostCapabilitySnapshot:
    mode: str
    dry_run: bool
    would_modify_system: bool
    capture_guard: str
    os_name: str
    os_release: str
    os_version: str
    machine: str
    processor: str
    python_version: str
    cpu_logical_count: int | None
    cpu_class: str
    total_ram_mb: float | None
    available_ram_mb: float | None
    ram_pressure_pct: float | None
    ram_class: str
    ram_pressure_class: str
    gpu_count: int
    total_reported_vram_mb: float | None
    largest_reported_vram_mb: float | None
    gpu_selection_basis: str
    gpu_class: str
    host_profile: str
    manager_hint: str
    telemetry_confidence: str
    capture_errors: list[str]
    gpus: list[HostGpuCapability]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "capture_guard": self.capture_guard,
            "os_name": self.os_name,
            "os_release": self.os_release,
            "os_version": self.os_version,
            "machine": self.machine,
            "processor": self.processor,
            "python_version": self.python_version,
            "cpu_logical_count": self.cpu_logical_count,
            "cpu_class": self.cpu_class,
            "total_ram_mb": round(self.total_ram_mb, 4)
            if self.total_ram_mb is not None
            else None,
            "available_ram_mb": round(self.available_ram_mb, 4)
            if self.available_ram_mb is not None
            else None,
            "ram_pressure_pct": round(self.ram_pressure_pct, 4)
            if self.ram_pressure_pct is not None
            else None,
            "ram_class": self.ram_class,
            "ram_pressure_class": self.ram_pressure_class,
            "gpu_count": self.gpu_count,
            "total_reported_vram_mb": round(self.total_reported_vram_mb, 4)
            if self.total_reported_vram_mb is not None
            else None,
            "largest_reported_vram_mb": round(self.largest_reported_vram_mb, 4)
            if self.largest_reported_vram_mb is not None
            else None,
            "gpu_selection_basis": self.gpu_selection_basis,
            "gpu_class": self.gpu_class,
            "host_profile": self.host_profile,
            "manager_hint": self.manager_hint,
            "telemetry_confidence": self.telemetry_confidence,
            "capture_errors": list(self.capture_errors),
            "gpus": [gpu.to_dict() for gpu in self.gpus],
        }


def collect_host_capability_snapshot() -> HostCapabilitySnapshot:
    errors: list[str] = []
    total_ram_mb, available_ram_mb, memory_error = collect_memory_status()
    if memory_error:
        errors.append(memory_error)
    gpus, gpu_errors = collect_gpu_capabilities()
    errors.extend(gpu_errors)
    return build_host_capability_snapshot(
        os_name=platform.system() or "unknown",
        os_release=platform.release() or "unknown",
        os_version=platform.version() or "unknown",
        machine=platform.machine() or "unknown",
        processor=platform.processor() or "unknown",
        python_version=platform.python_version(),
        cpu_logical_count=os.cpu_count(),
        total_ram_mb=total_ram_mb,
        available_ram_mb=available_ram_mb,
        gpus=gpus,
        capture_errors=errors,
    )


def build_host_capability_snapshot(
    *,
    os_name: str,
    os_release: str,
    os_version: str,
    machine: str,
    processor: str,
    python_version: str,
    cpu_logical_count: int | None,
    total_ram_mb: float | None,
    available_ram_mb: float | None,
    gpus: list[HostGpuCapability] | None = None,
    capture_errors: list[str] | None = None,
) -> HostCapabilitySnapshot:
    gpu_items = list(gpus or [])
    total_vram_mb = sum(
        gpu.adapter_ram_mb or 0.0
        for gpu in gpu_items
        if gpu.adapter_ram_mb is not None
    )
    reported_vram = total_vram_mb if gpu_items else None
    largest_reported_vram = max(
        (gpu.adapter_ram_mb for gpu in gpu_items if gpu.adapter_ram_mb is not None),
        default=None,
    )
    ram_pressure_pct = calculate_ram_pressure_pct(total_ram_mb, available_ram_mb)
    cpu = classify_cpu(cpu_logical_count)
    ram = classify_ram(total_ram_mb)
    ram_pressure = classify_ram_pressure(ram_pressure_pct)
    gpu = classify_gpu(largest_reported_vram, len(gpu_items))
    profile = classify_host_profile(cpu, ram, ram_pressure, gpu)
    hint = manager_hint_for_profile(profile, ram_pressure, gpu)
    errors = list(capture_errors or [])
    return HostCapabilitySnapshot(
        mode=HOST_CAPABILITY_MODE,
        dry_run=True,
        would_modify_system=False,
        capture_guard=HOST_CAPTURE_GUARD,
        os_name=os_name,
        os_release=os_release,
        os_version=os_version,
        machine=machine,
        processor=processor,
        python_version=python_version,
        cpu_logical_count=cpu_logical_count,
        cpu_class=cpu,
        total_ram_mb=total_ram_mb,
        available_ram_mb=available_ram_mb,
        ram_pressure_pct=ram_pressure_pct,
        ram_class=ram,
        ram_pressure_class=ram_pressure,
        gpu_count=len(gpu_items),
        total_reported_vram_mb=reported_vram,
        largest_reported_vram_mb=largest_reported_vram,
        gpu_selection_basis="largest-reported-adapter-not-active-process-binding",
        gpu_class=gpu,
        host_profile=profile,
        manager_hint=hint,
        telemetry_confidence=telemetry_confidence(
            total_ram_mb,
            available_ram_mb,
            gpu_items,
            errors,
        ),
        capture_errors=errors,
        gpus=gpu_items,
    )


def collect_memory_status() -> tuple[float | None, float | None, str | None]:
    if platform.system().lower() == "windows":
        return collect_windows_memory_status()
    return collect_posix_memory_status()


def collect_windows_memory_status() -> tuple[float | None, float | None, str | None]:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError) as exc:
        return None, None, f"windows-memory-probe-failed:{exc}"
    if not ok:
        return None, None, "windows-memory-probe-failed:GlobalMemoryStatusEx"
    return (
        bytes_to_mb(status.ullTotalPhys),
        bytes_to_mb(status.ullAvailPhys),
        None,
    )


def collect_posix_memory_status() -> tuple[float | None, float | None, str | None]:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None, None, "posix-memory-probe-unavailable"
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return None, None, "posix-memory-probe-invalid"
    total = bytes_to_mb(pages * page_size)
    available = None
    return total, available, None


def collect_gpu_capabilities() -> tuple[list[HostGpuCapability], list[str]]:
    if platform.system().lower() != "windows":
        return [], ["gpu-probe-skipped:unsupported-platform"]
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM,DriverVersion | "
            "ConvertTo-Json -Compress"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"gpu-probe-failed:{exc}"]
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return [], [f"gpu-probe-failed:{message or result.returncode}"]
    raw = result.stdout.strip()
    if not raw:
        return [], ["gpu-probe-empty"]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [], [f"gpu-probe-invalid-json:{exc}"]
    items = payload if isinstance(payload, list) else [payload]
    gpus = [gpu_capability_from_cim(item) for item in items if isinstance(item, dict)]
    return gpus, []


def gpu_capability_from_cim(payload: dict[str, Any]) -> HostGpuCapability:
    name = str(payload.get("Name") or "unknown-gpu")
    adapter_ram = parse_adapter_ram_mb(payload.get("AdapterRAM"))
    driver = payload.get("DriverVersion")
    return HostGpuCapability(
        name=name,
        adapter_ram_mb=adapter_ram,
        driver_version=str(driver) if driver is not None else None,
        source="win32-video-controller",
    )


def parse_adapter_ram_mb(value: Any) -> float | None:
    if value is None:
        return None
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return bytes_to_mb(amount)


def calculate_ram_pressure_pct(
    total_ram_mb: float | None,
    available_ram_mb: float | None,
) -> float | None:
    if total_ram_mb is None or available_ram_mb is None or total_ram_mb <= 0:
        return None
    used = max(total_ram_mb - available_ram_mb, 0.0)
    return min((used / total_ram_mb) * 100.0, 100.0)


def classify_cpu(cpu_logical_count: int | None) -> str:
    if cpu_logical_count is None or cpu_logical_count <= 0:
        return "unknown-cpu"
    if cpu_logical_count < 4:
        return "constrained-cpu"
    if cpu_logical_count < 8:
        return "modest-cpu"
    if cpu_logical_count < 16:
        return "balanced-cpu"
    return "high-parallelism-cpu"


def classify_ram(total_ram_mb: float | None) -> str:
    if total_ram_mb is None or total_ram_mb <= 0:
        return "unknown-ram"
    if total_ram_mb < 8192:
        return "constrained-ram"
    if total_ram_mb < 16384:
        return "limited-ram"
    if total_ram_mb < 32768:
        return "balanced-ram"
    return "high-capacity-ram"


def classify_ram_pressure(ram_pressure_pct: float | None) -> str:
    if ram_pressure_pct is None:
        return "unknown-pressure"
    if ram_pressure_pct >= 85.0:
        return "high-pressure"
    if ram_pressure_pct >= 70.0:
        return "medium-pressure"
    return "low-pressure"


def classify_gpu(total_reported_vram_mb: float | None, gpu_count: int) -> str:
    if gpu_count <= 0:
        return "unknown-gpu"
    if total_reported_vram_mb is None or total_reported_vram_mb <= 0:
        return "gpu-present-unknown-vram"
    if total_reported_vram_mb < 3840:
        return "low-vram-gpu"
    if total_reported_vram_mb < 12288:
        return "balanced-vram-gpu"
    return "high-vram-gpu"


def classify_host_profile(
    cpu_class: str,
    ram_class: str,
    ram_pressure_class: str,
    gpu_class: str,
) -> str:
    if ram_pressure_class == "high-pressure":
        return "memory-pressure-host"
    if cpu_class == "constrained-cpu" or ram_class == "constrained-ram":
        return "constrained-host"
    if (
        gpu_class == "high-vram-gpu"
        and ram_class == "high-capacity-ram"
        and cpu_class in {"balanced-cpu", "high-parallelism-cpu"}
    ):
        return "high-capacity-gaming-host"
    if (
        gpu_class in {"balanced-vram-gpu", "high-vram-gpu"}
        and ram_class in {"balanced-ram", "high-capacity-ram"}
    ):
        return "balanced-gaming-host"
    return "observed-host"


def manager_hint_for_profile(
    host_profile: str,
    ram_pressure_class: str,
    gpu_class: str,
) -> str:
    if ram_pressure_class == "high-pressure":
        return "tighten-memory-residency-observation"
    if host_profile == "constrained-host":
        return "prefer-low-residency-and-short-hot-path"
    if gpu_class == "unknown-gpu":
        return "collect-gpu-telemetry-before-gpu-specific-actions"
    if host_profile in {"balanced-gaming-host", "high-capacity-gaming-host"}:
        return "allow-daemon-supervisor-loop"
    return "collect-more-host-telemetry"


def telemetry_confidence(
    total_ram_mb: float | None,
    available_ram_mb: float | None,
    gpus: list[HostGpuCapability],
    capture_errors: list[str],
) -> str:
    memory_known = total_ram_mb is not None and available_ram_mb is not None
    gpu_known = bool(gpus)
    gpu_binding_unambiguous = (
        len(gpus) == 1 and gpus[0].adapter_ram_mb is not None
    )
    if memory_known and gpu_binding_unambiguous and not capture_errors:
        return "high"
    if memory_known and gpu_known:
        return "medium"
    if memory_known:
        return "medium"
    return "low"


def bytes_to_mb(value: int | float) -> float:
    return float(value) / BYTES_PER_MB
