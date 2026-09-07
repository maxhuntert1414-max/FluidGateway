"""Compare decoded-operation processing without TCP or GPU execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from native_gateway_validation import (
    ROOT,
    distribution,
    native_executable,
    process_metrics,
    write_result,
)
from fluidgateway.adapter import RuntimeAdapterSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, default=native_executable())
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    latencies = []
    before = {}
    started = 0
    for session_index in range(69):
        if session_index == 5:
            before = process_metrics(os.getpid())
            started = time.perf_counter()
        session = RuntimeAdapterSession()
        session.process_event(dict(event="resource", id="ram", memory="ram"))
        session.process_event(dict(event="resource", id="vram", memory="vram"))
        for index in range(512):
            event = dict(
                event="operation",
                id=str(index),
                frame=0,
                source="ram",
                target="ram" if index % 64 == 0 else "vram",
                queue="copy",
                cost_ms=0.3,
                size_mb=4,
                operation_type="compute" if index % 64 == 0 else "upload",
            )
            start = time.perf_counter_ns()
            response = session.process_event(event)
            elapsed = (time.perf_counter_ns() - start) / 1000
            if response["result"]["executed"] != (index % 64 < 2):
                raise AssertionError("Reference decision drift")
            if session_index >= 5:
                latencies.append(elapsed)
    duration = time.perf_counter() - started
    after = process_metrics(os.getpid())
    native = subprocess.run(
        [str(args.native.with_name("fluidgateway-native-benchmark.exe"))],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    write_result(
        args.out,
        dict(
            schema="fluidgateway-decoded-core-profile-v1",
            native_sha256=hashlib.sha256(args.native.read_bytes()).hexdigest(),
            benchmark_sha256=hashlib.sha256(
                args.native.with_name("fluidgateway-native-benchmark.exe").read_bytes()
            ).hexdigest(),
            warmup_sessions=5,
            operations=32768,
            operations_per_session=512,
            writes_every=64,
            python=dict(
                event_us=distribution(latencies),
                operations_per_second=len(latencies) / duration,
                cpu_cycles_per_operation=(after["cpu_cycles"] - before["cpu_cycles"])
                / len(latencies),
                process_private_bytes=after["private_bytes"],
            ),
            native=json.loads(native.stdout),
            scope="Decoded-operation handling: Python online adapter versus native state; no decode/encode/TCP/GPU. "
            "Throughput and CPU include session setup. Native PMR peak is not process private memory.",
        ),
    )
    print(f"Decoded-core profile: {args.out}")


if __name__ == "__main__":
    main()
