from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .host import HostCapabilitySnapshot
from .native_backend_manifest import (
    RuntimeNativeBackendManifest,
    RuntimeNativeBackendManifestEntry,
)


NATIVE_BACKEND_PROBE_MODE = "runtime-native-backend-probe-v0.56"
NATIVE_BACKEND_PROBE_GUARD = "read-only-observe"
MEMORY_SIGNAL_KEYS = {
    "total_ram_mb",
    "available_ram_mb",
    "ram_pressure_pct",
    "ram_pressure_class",
}
GPU_SIGNAL_KEYS = {
    "gpu_count",
    "gpu_class",
    "total_reported_vram_mb",
}


@dataclass(frozen=True)
class RuntimeNativeBackendProbeStep:
    step_id: str
    source_entry_id: str
    backend_id: str
    control_surface: str
    probe_scope: str
    probe_action: str
    probe_status: str
    dry_run: bool
    would_modify_system: bool
    probed: bool
    blocked: bool
    blocked_by: list[str]
    signal_count: int
    signals: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "source_entry_id": self.source_entry_id,
            "backend_id": self.backend_id,
            "control_surface": self.control_surface,
            "probe_scope": self.probe_scope,
            "probe_action": self.probe_action,
            "probe_status": self.probe_status,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "probed": self.probed,
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "signal_count": self.signal_count,
            "signals": self.signals,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeNativeBackendProbeReport:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_manifest_policy: str
    host_snapshot_loaded: bool
    host_profile: str | None
    probe_policy: str
    step_count: int
    probed_count: int
    blocked_count: int
    readonly_probe_count: int
    advisory_probe_count: int
    native_blocked_probe_count: int
    missing_host_snapshot_count: int
    host_signal_count: int
    memory_signal_count: int
    gpu_signal_count: int
    steps: list[RuntimeNativeBackendProbeStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_manifest_policy": self.source_manifest_policy,
            "host_snapshot_loaded": self.host_snapshot_loaded,
            "host_profile": self.host_profile,
            "probe_policy": self.probe_policy,
            "step_count": self.step_count,
            "probed_count": self.probed_count,
            "blocked_count": self.blocked_count,
            "readonly_probe_count": self.readonly_probe_count,
            "advisory_probe_count": self.advisory_probe_count,
            "native_blocked_probe_count": self.native_blocked_probe_count,
            "missing_host_snapshot_count": self.missing_host_snapshot_count,
            "host_signal_count": self.host_signal_count,
            "memory_signal_count": self.memory_signal_count,
            "gpu_signal_count": self.gpu_signal_count,
            "steps": [step.to_dict() for step in self.steps],
        }


def run_runtime_native_backend_probe(
    *,
    manifest: RuntimeNativeBackendManifest,
    host_snapshot: HostCapabilitySnapshot | None,
) -> RuntimeNativeBackendProbeReport:
    steps = [
        probe_step(index + 1, entry, manifest, host_snapshot)
        for index, entry in enumerate(manifest.entries)
    ]
    return RuntimeNativeBackendProbeReport(
        mode=NATIVE_BACKEND_PROBE_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=NATIVE_BACKEND_PROBE_GUARD,
        source_manifest_policy=manifest.manifest_policy,
        host_snapshot_loaded=host_snapshot is not None,
        host_profile=host_snapshot.host_profile if host_snapshot else None,
        probe_policy=probe_policy(steps),
        step_count=len(steps),
        probed_count=sum(1 for step in steps if step.probed),
        blocked_count=sum(1 for step in steps if step.blocked),
        readonly_probe_count=count_status(
            steps,
            "executed-readonly-host-snapshot-probe",
        ),
        advisory_probe_count=count_status(
            steps,
            "executed-advisory-contract-probe",
        ),
        native_blocked_probe_count=count_status(
            steps,
            "blocked-native-backend-probe",
        ),
        missing_host_snapshot_count=count_status(
            steps,
            "blocked-missing-host-snapshot",
        ),
        host_signal_count=count_signal_scope(steps, "host"),
        memory_signal_count=count_signal_scope(steps, "memory"),
        gpu_signal_count=count_signal_scope(steps, "gpu"),
        steps=steps,
    )


def probe_step(
    index: int,
    entry: RuntimeNativeBackendManifestEntry,
    manifest: RuntimeNativeBackendManifest,
    host_snapshot: HostCapabilitySnapshot | None,
) -> RuntimeNativeBackendProbeStep:
    if entry.requires_native_backend or entry.backend_id == "native-host-control-backend":
        return blocked_native_step(index, entry)
    if entry.blocked:
        return blocked_advisory_step(index, entry)
    if entry.backend_id == "python-stdlib-readonly-probe":
        return readonly_host_step(index, entry, host_snapshot)
    return advisory_contract_step(index, entry, manifest, host_snapshot)


def readonly_host_step(
    index: int,
    entry: RuntimeNativeBackendManifestEntry,
    host_snapshot: HostCapabilitySnapshot | None,
) -> RuntimeNativeBackendProbeStep:
    if host_snapshot is None:
        return RuntimeNativeBackendProbeStep(
            step_id=f"native.probe.{index:03d}",
            source_entry_id=entry.entry_id,
            backend_id=entry.backend_id,
            control_surface=entry.control_surface,
            probe_scope="host",
            probe_action="collect-host-snapshot-before-readonly-probe",
            probe_status="blocked-missing-host-snapshot",
            dry_run=True,
            would_modify_system=False,
            probed=False,
            blocked=True,
            blocked_by=["host-snapshot"],
            signal_count=0,
            signals={},
            reason=(
                "Read-only probe needs a host snapshot before it can bind "
                "CPU/RAM/GPU/VRAM evidence."
            ),
        )
    signals = host_probe_signals(host_snapshot)
    return RuntimeNativeBackendProbeStep(
        step_id=f"native.probe.{index:03d}",
        source_entry_id=entry.entry_id,
        backend_id=entry.backend_id,
        control_surface=entry.control_surface,
        probe_scope="host",
        probe_action="bind-host-snapshot-signals",
        probe_status="executed-readonly-host-snapshot-probe",
        dry_run=True,
        would_modify_system=False,
        probed=True,
        blocked=False,
        blocked_by=[],
        signal_count=count_known_signals(signals),
        signals=signals,
        reason="Read-only backend bound existing host capability evidence.",
    )


def advisory_contract_step(
    index: int,
    entry: RuntimeNativeBackendManifestEntry,
    manifest: RuntimeNativeBackendManifest,
    host_snapshot: HostCapabilitySnapshot | None,
) -> RuntimeNativeBackendProbeStep:
    signals = advisory_probe_signals(entry, manifest, host_snapshot)
    return RuntimeNativeBackendProbeStep(
        step_id=f"native.probe.{index:03d}",
        source_entry_id=entry.entry_id,
        backend_id=entry.backend_id,
        control_surface=entry.control_surface,
        probe_scope="daemon-contract",
        probe_action="bind-daemon-contract-signals",
        probe_status="executed-advisory-contract-probe",
        dry_run=True,
        would_modify_system=False,
        probed=True,
        blocked=False,
        blocked_by=[],
        signal_count=count_known_signals(signals),
        signals=signals,
        reason="Advisory backend bound daemon contract evidence without host mutation.",
    )


def blocked_native_step(
    index: int,
    entry: RuntimeNativeBackendManifestEntry,
) -> RuntimeNativeBackendProbeStep:
    return RuntimeNativeBackendProbeStep(
        step_id=f"native.probe.{index:03d}",
        source_entry_id=entry.entry_id,
        backend_id=entry.backend_id,
        control_surface=entry.control_surface,
        probe_scope="native-host",
        probe_action="hold-native-backend-probe",
        probe_status="blocked-native-backend-probe",
        dry_run=True,
        would_modify_system=False,
        probed=False,
        blocked=True,
        blocked_by=list(entry.blocked_by),
        signal_count=0,
        signals={},
        reason=(
            "Native backend probe is held until backend, privilege, and "
            "safety-review requirements exist."
        ),
    )


def blocked_advisory_step(
    index: int,
    entry: RuntimeNativeBackendManifestEntry,
) -> RuntimeNativeBackendProbeStep:
    return RuntimeNativeBackendProbeStep(
        step_id=f"native.probe.{index:03d}",
        source_entry_id=entry.entry_id,
        backend_id=entry.backend_id,
        control_surface=entry.control_surface,
        probe_scope="daemon-contract",
        probe_action="hold-advisory-backend-probe",
        probe_status="blocked-advisory-probe",
        dry_run=True,
        would_modify_system=False,
        probed=False,
        blocked=True,
        blocked_by=list(entry.blocked_by),
        signal_count=0,
        signals={},
        reason="Advisory backend probe is held by the manifest blockers.",
    )


def host_probe_signals(host_snapshot: HostCapabilitySnapshot) -> dict[str, Any]:
    return {
        "host_profile": host_snapshot.host_profile,
        "manager_hint": host_snapshot.manager_hint,
        "telemetry_confidence": host_snapshot.telemetry_confidence,
        "cpu_logical_count": host_snapshot.cpu_logical_count,
        "cpu_class": host_snapshot.cpu_class,
        "total_ram_mb": host_snapshot.total_ram_mb,
        "available_ram_mb": host_snapshot.available_ram_mb,
        "ram_pressure_pct": host_snapshot.ram_pressure_pct,
        "ram_pressure_class": host_snapshot.ram_pressure_class,
        "gpu_count": host_snapshot.gpu_count,
        "gpu_class": host_snapshot.gpu_class,
        "total_reported_vram_mb": host_snapshot.total_reported_vram_mb,
        "capture_error_count": len(host_snapshot.capture_errors),
    }


def advisory_probe_signals(
    entry: RuntimeNativeBackendManifestEntry,
    manifest: RuntimeNativeBackendManifest,
    host_snapshot: HostCapabilitySnapshot | None,
) -> dict[str, Any]:
    return {
        "manifest_policy": manifest.manifest_policy,
        "host_profile": host_snapshot.host_profile if host_snapshot else None,
        "source_manifest_ready_count": manifest.ready_count,
        "source_manifest_blocked_count": manifest.blocked_count,
        "control_surface": entry.control_surface,
        "observed_signal": entry.observed_signal,
        "backend_load_status": entry.load_status,
    }


def count_known_signals(signals: dict[str, Any]) -> int:
    return sum(1 for value in signals.values() if value is not None)


def probe_policy(steps: list[RuntimeNativeBackendProbeStep]) -> str:
    native_blocked = any(
        step.probe_status == "blocked-native-backend-probe" for step in steps
    )
    missing_host = any(
        step.probe_status == "blocked-missing-host-snapshot" for step in steps
    )
    probed = any(step.probed for step in steps)
    if native_blocked and probed:
        return "probe-safe-and-hold-native"
    if native_blocked:
        return "hold-native-backend-probes"
    if missing_host:
        return "hold-readonly-probe-for-host-snapshot"
    if any(
        step.probe_status == "executed-readonly-host-snapshot-probe"
        for step in steps
    ):
        return "readonly-probe-executed"
    if any(
        step.probe_status == "executed-advisory-contract-probe"
        for step in steps
    ):
        return "advisory-probe-executed"
    return "observe"


def count_status(
    steps: list[RuntimeNativeBackendProbeStep],
    status: str,
) -> int:
    return sum(1 for step in steps if step.probe_status == status)


def count_signal_scope(
    steps: list[RuntimeNativeBackendProbeStep],
    scope: str,
) -> int:
    if scope == "host":
        return sum(step.signal_count for step in steps if step.probe_scope == "host")
    if scope == "memory":
        return count_signal_keys(steps, MEMORY_SIGNAL_KEYS)
    if scope == "gpu":
        return count_signal_keys(steps, GPU_SIGNAL_KEYS)
    return 0


def count_signal_keys(
    steps: list[RuntimeNativeBackendProbeStep],
    keys: set[str],
) -> int:
    return sum(
        1
        for step in steps
        for key in keys
        if step.signals.get(key) is not None
    )
