from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .daemon_control_execution import (
    RuntimeDaemonControlExecution,
    RuntimeDaemonControlExecutionStep,
)
from .host import HostCapabilitySnapshot
from .native_backend import RuntimeNativeBackendPreflight


NATIVE_BACKEND_MANIFEST_MODE = "runtime-native-backend-manifest-v0.55"
NATIVE_BACKEND_MANIFEST_GUARD = "advisory-only"


@dataclass(frozen=True)
class RuntimeNativeBackendManifestEntry:
    entry_id: str
    source_intent_id: str
    source_lane_id: str
    domain: str
    control_surface: str
    backend_id: str
    required_interface: str
    capability_status: str
    load_status: str
    ready: bool
    blocked: bool
    blocked_by: list[str]
    requires_native_backend: bool
    requires_privilege: bool
    requires_safety_review: bool
    promotion_allowed: bool
    dry_run: bool
    would_modify_system: bool
    observed_signal: str
    host_requirement: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "source_intent_id": self.source_intent_id,
            "source_lane_id": self.source_lane_id,
            "domain": self.domain,
            "control_surface": self.control_surface,
            "backend_id": self.backend_id,
            "required_interface": self.required_interface,
            "capability_status": self.capability_status,
            "load_status": self.load_status,
            "ready": self.ready,
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "requires_native_backend": self.requires_native_backend,
            "requires_privilege": self.requires_privilege,
            "requires_safety_review": self.requires_safety_review,
            "promotion_allowed": self.promotion_allowed,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "observed_signal": self.observed_signal,
            "host_requirement": self.host_requirement,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeNativeBackendManifest:
    mode: str
    dry_run: bool
    would_modify_system: bool
    execution_guard: str
    source_execution_policy: str
    source_backend_policy: str
    host_snapshot_loaded: bool
    host_profile: str | None
    manifest_policy: str
    entry_count: int
    ready_count: int
    blocked_count: int
    readonly_ready_count: int
    advisory_ready_count: int
    native_blocked_count: int
    privileged_blocked_count: int
    telemetry_surface_count: int
    scheduler_surface_count: int
    ram_surface_count: int
    vram_surface_count: int
    gpu_surface_count: int
    safety_surface_count: int
    entries: list[RuntimeNativeBackendManifestEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dry_run": self.dry_run,
            "would_modify_system": self.would_modify_system,
            "execution_guard": self.execution_guard,
            "source_execution_policy": self.source_execution_policy,
            "source_backend_policy": self.source_backend_policy,
            "host_snapshot_loaded": self.host_snapshot_loaded,
            "host_profile": self.host_profile,
            "manifest_policy": self.manifest_policy,
            "entry_count": self.entry_count,
            "ready_count": self.ready_count,
            "blocked_count": self.blocked_count,
            "readonly_ready_count": self.readonly_ready_count,
            "advisory_ready_count": self.advisory_ready_count,
            "native_blocked_count": self.native_blocked_count,
            "privileged_blocked_count": self.privileged_blocked_count,
            "telemetry_surface_count": self.telemetry_surface_count,
            "scheduler_surface_count": self.scheduler_surface_count,
            "ram_surface_count": self.ram_surface_count,
            "vram_surface_count": self.vram_surface_count,
            "gpu_surface_count": self.gpu_surface_count,
            "safety_surface_count": self.safety_surface_count,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def build_runtime_native_backend_manifest(
    *,
    control_execution: RuntimeDaemonControlExecution,
    native_backend_preflight: RuntimeNativeBackendPreflight,
    host_snapshot: HostCapabilitySnapshot | None,
) -> RuntimeNativeBackendManifest:
    entries = [
        manifest_entry(index + 1, step, host_snapshot)
        for index, step in enumerate(control_execution.steps)
    ]
    return RuntimeNativeBackendManifest(
        mode=NATIVE_BACKEND_MANIFEST_MODE,
        dry_run=True,
        would_modify_system=False,
        execution_guard=NATIVE_BACKEND_MANIFEST_GUARD,
        source_execution_policy=control_execution.execution_policy,
        source_backend_policy=native_backend_preflight.backend_policy,
        host_snapshot_loaded=host_snapshot is not None,
        host_profile=host_snapshot.host_profile if host_snapshot else None,
        manifest_policy=manifest_policy(entries),
        entry_count=len(entries),
        ready_count=sum(1 for entry in entries if entry.ready),
        blocked_count=sum(1 for entry in entries if entry.blocked),
        readonly_ready_count=count_ready_backend(
            entries,
            "python-stdlib-readonly-probe",
        ),
        advisory_ready_count=count_ready_backend(entries, "daemon-advisory-loop"),
        native_blocked_count=sum(
            1 for entry in entries if entry.requires_native_backend
        ),
        privileged_blocked_count=sum(
            1 for entry in entries if entry.requires_privilege
        ),
        telemetry_surface_count=count_surface(entries, "telemetry"),
        scheduler_surface_count=count_surface(entries, "scheduler"),
        ram_surface_count=count_surface(entries, "ram"),
        vram_surface_count=count_surface(entries, "vram"),
        gpu_surface_count=count_surface(entries, "gpu"),
        safety_surface_count=count_surface(entries, "safety"),
        entries=entries,
    )


def manifest_entry(
    index: int,
    step: RuntimeDaemonControlExecutionStep,
    host_snapshot: HostCapabilitySnapshot | None,
) -> RuntimeNativeBackendManifestEntry:
    blocked_by = list(step.blocked_by)
    requires_native_backend = (
        step.backend_requirement == "native-host-control-backend"
        or "native-backend" in blocked_by
    )
    requires_privilege = "privilege" in blocked_by
    requires_safety_review = (
        requires_native_backend
        or requires_privilege
        or "safety-review" in blocked_by
    )
    backend_id = backend_id_for_step(step)
    return RuntimeNativeBackendManifestEntry(
        entry_id=f"native.backend.{index:03d}",
        source_intent_id=step.intent_id,
        source_lane_id=step.source_lane_id,
        domain=step.domain,
        control_surface=step.control_surface,
        backend_id=backend_id,
        required_interface=step.backend_requirement,
        capability_status=capability_status(
            step,
            requires_native_backend,
            requires_privilege,
        ),
        load_status=load_status(step, backend_id, requires_native_backend),
        ready=step.executed and not step.blocked,
        blocked=step.blocked,
        blocked_by=blocked_by,
        requires_native_backend=requires_native_backend,
        requires_privilege=requires_privilege,
        requires_safety_review=requires_safety_review,
        promotion_allowed=False,
        dry_run=True,
        would_modify_system=False,
        observed_signal=step.observed_signal,
        host_requirement=host_requirement(
            step,
            requires_native_backend,
            host_snapshot,
        ),
        reason=manifest_reason(step, requires_native_backend),
    )


def backend_id_for_step(step: RuntimeDaemonControlExecutionStep) -> str:
    if step.backend_requirement == "python-stdlib-readonly-probe":
        return "python-stdlib-readonly-probe"
    if step.backend_requirement == "native-host-control-backend":
        return "native-host-control-backend"
    if step.backend_requirement == "missing-preflight":
        return "missing-preflight"
    return "daemon-advisory-loop"


def capability_status(
    step: RuntimeDaemonControlExecutionStep,
    requires_native_backend: bool,
    requires_privilege: bool,
) -> str:
    if step.blocked:
        if requires_native_backend and requires_privilege:
            return "blocked-privileged-native-backend-required"
        if requires_native_backend:
            return "blocked-native-backend-required"
        return "blocked-advisory-guard"
    if step.execution_status == "executed-readonly-control-dry-run":
        return "available-readonly-control-dry-run"
    return "available-advisory-control-dry-run"


def load_status(
    step: RuntimeDaemonControlExecutionStep,
    backend_id: str,
    requires_native_backend: bool,
) -> str:
    if step.blocked and requires_native_backend:
        return "not-loaded-native-backend-missing"
    if step.blocked:
        return "not-loaded-advisory-guard"
    if backend_id == "python-stdlib-readonly-probe":
        return "loaded-python-stdlib-readonly"
    if backend_id == "daemon-advisory-loop":
        return "loaded-daemon-advisory-loop"
    return "not-loaded"


def host_requirement(
    step: RuntimeDaemonControlExecutionStep,
    requires_native_backend: bool,
    host_snapshot: HostCapabilitySnapshot | None,
) -> str:
    if requires_native_backend:
        if host_snapshot is None:
            return "host-snapshot-and-native-safety-review-required"
        return f"{host_snapshot.host_profile}:native-safety-review-required"
    if step.domain == "telemetry":
        return "host-snapshot-optional-readonly-probe"
    return "daemon-state-contract"


def manifest_reason(
    step: RuntimeDaemonControlExecutionStep,
    requires_native_backend: bool,
) -> str:
    if requires_native_backend:
        return (
            "Native backend load is denied in v0.55; "
            f"{step.reason}"
        )
    return f"Backend contract is dry-run only; {step.reason}"


def manifest_policy(entries: list[RuntimeNativeBackendManifestEntry]) -> str:
    if any(entry.requires_native_backend for entry in entries):
        return "hold-native-backend-load"
    if any(entry.backend_id == "python-stdlib-readonly-probe" for entry in entries):
        return "readonly-probe-ready"
    if any(entry.backend_id == "daemon-advisory-loop" for entry in entries):
        return "advisory-backend-ready"
    return "observe"


def count_ready_backend(
    entries: list[RuntimeNativeBackendManifestEntry],
    backend_id: str,
) -> int:
    return sum(
        1 for entry in entries if entry.ready and entry.backend_id == backend_id
    )


def count_surface(
    entries: list[RuntimeNativeBackendManifestEntry],
    surface: str,
) -> int:
    return sum(
        1
        for entry in entries
        if entry.control_surface == surface
        or (
            surface in {"ram", "vram"}
            and entry.control_surface == "ram-vram"
        )
    )
