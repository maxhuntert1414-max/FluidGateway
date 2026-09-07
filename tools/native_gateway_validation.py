"""Owned-process validation tools. Python is a test driver, never a native dependency."""

from __future__ import annotations

import argparse
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fluidgateway import fluidlink_v2 as wire


def native_executable() -> Path:
    return Path(
        os.environ.get("FLUIDGATEWAY_NATIVE", ROOT / "native/build/Release/fluidgateway-native.exe")
    )


class Peer:
    def __init__(self, port: int, batch: bool = True, *, receive_buffer_bytes: int | None = None):
        self.socket = socket.socket()
        self.socket.settimeout(5)
        try:
            if receive_buffer_bytes is not None:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_buffer_bytes)
            self.socket.connect(("127.0.0.1", port))
        except BaseException:
            self.socket.close()
            raise
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream = self.socket.makefile("rb")
        self.sequence = 0
        self.session = None
        self.elapsed_us: list[float] = []
        try:
            self.welcome = self.request(
                1,
                wire.encode_hello_payload(
                    client_name="native-validation",
                    client_version="1",
                    contract_digest=wire.FLUIDLINK_V2_BATCH_CONTRACT_DIGEST
                    if batch
                    else wire.FLUIDLINK_V2_CONTRACT_DIGEST,
                    requested_capabilities=wire.FLUIDLINK_V2_BATCH_CAPABILITIES
                    if batch
                    else wire.FLUIDLINK_V2_CAPABILITIES,
                    required_capabilities=wire.FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES
                    if batch
                    else wire.FLUIDLINK_V2_REQUIRED_CAPABILITIES,
                ),
            )
            if self.welcome.opcode != 2:
                raise AssertionError("Handshake rejected")
            self.session = self.welcome.session_id
        except BaseException:
            self.close()
            raise

    def request(self, opcode: int, payload: bytes = b"", subject: int = 0):
        self.sequence += 1
        request = wire.fluidlink_v2_request(
            opcode=opcode,
            sequence=self.sequence,
            payload=payload,
            subject_opcode=subject,
            session_id=self.session,
        )
        started = time.perf_counter_ns()
        self.socket.sendall(wire.encode_fluidlink_v2_frame(request))
        response = wire.read_fluidlink_v2_frame(self.stream)
        self.elapsed_us.append((time.perf_counter_ns() - started) / 1000)
        if (
            response is None
            or response.message_id != request.message_id
            or response.sequence != self.sequence
        ):
            raise AssertionError("Missing/miscorrelated response")
        if self.session and response.session_id != self.session:
            raise AssertionError("Session identity drift")
        return response

    def event(self, subject: int, **event):
        return self.request(10, wire.encode_runtime_event_payload(subject, event), subject)

    def batch(self, count: int = 129, **overrides):
        event = dict(
            batch_id=uuid4().hex,
            operation_count=count,
            operation_type="upload",
            queue="copy",
            source="ram",
            target="vram",
            size_bytes=4194304,
            cost_us=300,
            frame=0,
        )
        event.update(overrides)
        response = self.request(10, wire.encode_operation_batch_event_payload(event), 105)
        return response

    def initialize(self):
        for response in (
            self.event(100, action="begin", id="validation"),
            self.event(101, action="begin", frame=0),
            self.event(
                102, action="register", id="ram", kind="buffer", memory="ram", size_bytes=4194304
            ),
            self.event(
                102, action="register", id="vram", kind="buffer", memory="vram", size_bytes=4194304
            ),
        ):
            if not response.ok or response.opcode != 11:
                raise AssertionError("Setup rejected")

    def finish(self):
        self.event(101, action="end", frame=0)
        self.event(100, action="end", id="")
        self.request(30)

    def close(self):
        self.stream.close()
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@contextlib.contextmanager
def server(backend: str = "Native", executable: Path | None = None):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    executable = executable or native_executable()
    command = (
        [str(executable), "serve-events"]
        if backend == "Native"
        else [sys.executable, "-u", "-m", "fluidgateway", "runtime", "serve-events"]
    )
    process = subprocess.Popen(
        command + ["--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"{backend} server exited: {process.stderr.read()}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("Server startup timed out")
                time.sleep(0.025)
        yield process, port
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)


def process_metrics(pid: int) -> dict:
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
                "private",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        times = [wintypes.FILETIME() for _ in range(4)]
        if not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ) or not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        cpu_ns = sum(((t.dwHighDateTime << 32) | t.dwLowDateTime) * 100 for t in times[2:])
        cycles = ctypes.c_ulonglong()
        if not kernel.QueryProcessCycleTime(handle, ctypes.byref(cycles)):
            raise ctypes.WinError(ctypes.get_last_error())
        return dict(
            private_bytes=counters.private,
            working_set_bytes=counters.working,
            cpu_ns=cpu_ns,
            cpu_cycles=cycles.value,
        )
    finally:
        kernel.CloseHandle(handle)


def distribution(values):
    ordered = sorted(values)

    def percentile(p):
        index = (len(ordered) - 1) * p
        low = int(index)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (index - low)

    return dict(
        count=len(ordered),
        p50=percentile(0.5),
        p95=percentile(0.95),
        p99=percentile(0.99),
        maximum=max(ordered),
        mean=statistics.mean(ordered),
    )


def write_result(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)


def assess_soak(result: dict) -> dict:
    samples = result["samples"]
    stable = [sample["private_bytes"] for sample in samples if sample["elapsed_seconds"] >= 300]
    times = [0.0] + [sample["elapsed_seconds"] for sample in samples] + [result["elapsed_seconds"]]
    gaps = [end - start for start, end in zip(times, times[1:])]
    continuity = bool(samples) and all(0 <= gap <= 90 for gap in gaps)
    memory = bool(stable) and max(stable) <= min(stable) * 1.10 + 1024 * 1024
    return dict(
        post_warmup_private_bytes=distribution(stable) if stable else None,
        memory_plateau_passed=memory,
        maximum_sample_gap_seconds=max(gaps),
        continuous_load_passed=continuity,
        soak_gate_passed=(
            result["complete"]
            and result["elapsed_seconds"] >= result["seconds_required"]
            and result["operations"] >= result["minimum_operations"]
            and continuity
            and memory
        ),
    )


def soak(executable: Path, seconds: float, events: int, out: Path):
    started = time.monotonic()
    count = sessions = 0
    samples = []
    next_sample = 0.0
    result = dict(
        schema="fluidgateway-native-soak-v1",
        complete=False,
        seconds_required=seconds,
        minimum_operations=events,
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
    )
    with server(executable=executable) as (process, port):
        while time.monotonic() - started < seconds or count < events:
            with Peer(port) as peer:
                peer.initialize()
                for index in range(16):
                    response = peer.batch(256)
                    if response.opcode != 11 or not response.ok:
                        raise AssertionError("Soak batch rejected")
                    decisions = wire.decode_operation_batch_decision_payload(response.payload)[
                        "decisions"
                    ]
                    expected = [0] + [2] * 255 if index == 0 else [2] * 256
                    if [item["decision_opcode"] for item in decisions] != expected:
                        raise AssertionError("Soak decision drift")
                    count += 256
                    if count >= events:
                        time.sleep(0.05)
                peer.finish()
            sessions += 1
            elapsed = time.monotonic() - started
            if elapsed >= next_sample:
                samples.append(
                    dict(
                        elapsed_seconds=elapsed,
                        operations=count,
                        sessions=sessions,
                        **process_metrics(process.pid),
                    )
                )
                result.update(
                    elapsed_seconds=elapsed, operations=count, sessions=sessions, samples=samples
                )
                write_result(out, result)
                print(f"Soak {elapsed:.1f}s, {count} operations, {sessions} sessions", flush=True)
                next_sample = elapsed + 60
        result.update(
            complete=True,
            elapsed_seconds=time.monotonic() - started,
            operations=count,
            sessions=sessions,
            final_metrics=process_metrics(process.pid),
        )
    result.update(assess_soak(result))
    write_result(out, result)
    return result


def benchmark(executable: Path, pairs: int, out: Path):
    records = {backend: [] for backend in ("Python", "Native")}
    with (
        server("Python") as (python, python_port),
        server("Native", executable) as (native, native_port),
    ):
        endpoints = {"Python": (python, python_port), "Native": (native, native_port)}
        for index in range(pairs + 5):
            for backend in ("Python", "Native") if index % 2 == 0 else ("Native", "Python"):
                process, port = endpoints[backend]
                before = process_metrics(process.pid)
                started = time.perf_counter_ns()
                with Peer(port) as peer:
                    peer.request(20, wire.encode_nonce_payload("authorization-check"))
                    peer.initialize()
                    response = peer.batch()
                    decisions = wire.decode_operation_batch_decision_payload(response.payload)[
                        "decisions"
                    ]
                    if [entry["decision_opcode"] for entry in decisions] != [0] + [2] * 128:
                        raise AssertionError("Authorization parity failed")
                    peer.finish()
                    elapsed = (time.perf_counter_ns() - started) / 1000
                    roundtrips = peer.elapsed_us
                after = process_metrics(process.pid)
                if index >= 5:
                    records[backend].append(
                        dict(
                            pair=index - 5,
                            authorization_us=elapsed,
                            cpu_ns=after["cpu_ns"] - before["cpu_ns"],
                            private_bytes=after["private_bytes"],
                            cpu_cycles=after["cpu_cycles"] - before["cpu_cycles"],
                            roundtrip_us=roundtrips,
                        )
                    )
    summaries = {}
    for backend, runs in records.items():
        summaries[backend] = dict(
            authorization_us=distribution([r["authorization_us"] for r in runs]),
            roundtrip_us=distribution([v for r in runs for v in r["roundtrip_us"]]),
            cpu_ns_per_operation=sum(r["cpu_ns"] for r in runs) / (129 * pairs),
            cpu_cycles_per_operation=sum(r["cpu_cycles"] for r in runs) / (129 * pairs),
            private_bytes=distribution([r["private_bytes"] for r in runs]),
        )
    baseline, native = summaries["Python"], summaries["Native"]
    passed = (
        pairs >= 30
        and all(
            native["authorization_us"][p] <= baseline["authorization_us"][p] for p in ("p95", "p99")
        )
        and 0 < native["cpu_cycles_per_operation"] < baseline["cpu_cycles_per_operation"]
    )
    result = dict(
        schema="fluidgateway-native-comparison-v1",
        pairs=pairs,
        warmup_pairs=5,
        native_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        summaries=summaries,
        samples=records,
        comparison_gate_passed=passed,
        scope="Gateway authorization only; no GPU/game/FPS claim and no Runtime PID/hash validation in this driver",
    )
    write_result(out, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("soak", "benchmark"))
    parser.add_argument("--native", type=Path, default=native_executable())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=3600)
    parser.add_argument("--events", type=int, default=1_000_000)
    parser.add_argument("--pairs", type=int, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0 or args.events < 1 or args.pairs < 1:
        parser.error("Counts and durations must be positive")
    result = (
        soak(args.native.resolve(), args.seconds, args.events, args.out)
        if args.mode == "soak"
        else benchmark(args.native.resolve(), args.pairs, args.out)
    )
    print(
        json.dumps({k: v for k, v in result.items() if k not in ("samples", "summaries")}, indent=2)
    )
    return 0 if result.get("soak_gate_passed", result.get("comparison_gate_passed", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
