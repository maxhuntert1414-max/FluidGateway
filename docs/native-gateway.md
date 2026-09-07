# Native Online Gateway

FluidGateway's C++20 executable handles live FluidLink decisions without loading
Python. Python remains the offline diagnostic/reporting tool and reference test
implementation; FluidRuntime remains the separate C# coordinator and C++ actuator.
This is not a new graphics driver, system scheduler, or expansion of hook authority.

## Run

Extract the Windows x64 native release package and run:

```powershell
.\fluidgateway-native.exe serve-events --host 127.0.0.1 --port 8765
```

Only the exact IPv4 loopback address is accepted. An occupied port is an error,
not a reason to replace another listener. Ctrl+C requests shutdown; reads and
writes check shutdown at intervals of at most 250 ms. No service, scheduled task,
autorun, Python interpreter or global Vulkan layer is installed. Runtime needs
its own .NET prerequisites; the Gateway executable does not.

The native endpoint accepts FluidLink v2 base and batch profiles. Existing header,
positional payload, opcode, SHA256 handshake and golden-vector contracts remain
unchanged. JSONL/v1 are deliberately rejected, not forwarded to Python. The
reference endpoint is still available explicitly:

```powershell
python -m fluidgateway runtime serve-events --host 127.0.0.1 --port 8766
```

## Decision Boundary

The online core tracks declared resources, aliases, write invalidation,
dependency replacements and allocation reuse. It produces the compact decisions
already exposed by FluidLink v2. It does not run the offline report/simulation
pipeline, nor serialize then discard those large structures on every request.
Session/frame budgets retain their wire validation; they do not become new native
actuation authority. Rich advisory snapshots remain an offline/reference feature.

Aliases and operation declarations are advisory inputs, not proof of exact bytes
in an arbitrary application. FluidRuntime must still bind the expected server PID
and executable hash, check request context/backend/topology, and enforce native
content guards, bounded budgets, expiry and rollback. No per-GPU-call Python or
TCP round trip is introduced. Native control is still authorized per bounded run.

## Bounds and Renewal

| Bound | Behavior |
| --- | --- |
| 8 simultaneous connections / backlog 16 | Excess accepted connections are closed |
| Initial prefix 1 s / complete frame 2 s / idle 30 s | Deadline closes that connection |
| Response writes 2 s | A stalled receiver cannot retain a worker indefinitely |
| Payload 65,535 bytes / batch 256 operations | Strict existing contract validation |
| 4,096 active resources / 16,384 operation IDs | Reject and close when another entry exceeds the limit |
| 8 MiB retained allocation requests per connection | Enforced by the PMR allocator; reject and close on exhaustion |

Eight persistent worker threads serve connections. Each connection still owns a
new protocol session and fresh decision state; reusing a worker never reuses an
authorization. This avoids repeated thread creation during session renewal.

The 8 MiB limit covers retained container/string allocations, not total process
RSS, Windows thread stacks, allocator bookkeeping or bounded temporary packet
buffers. The implementation stores no complete frame history. Operation IDs and
dependencies are never evicted to keep authorizing work. A new connection starts
with no resources or provenance and must register its own inputs again. Current
Runtime authorizations already use separate short connections; this does not add
transparent infinite-session rotation for other clients.

Batch failure returns an error and closes the session without a decision vector,
even when preceding items had updated its now-retired advisory state. An existing
Runtime native lease expires under its original TTL; disconnect is not a promise
of instantaneous revocation of previously published control.

## Integer Precision

Bytes remain uint64 and operation time remains uint32 microseconds through the
decision path. Unlike the Python reference's float adaptation, the native core
distinguishes adjacent byte counts above 2^53 and can return UINT64_MAX exactly.
Those boundary tests follow the wire contract, deliberately not Python rounding.
For normal exactly representable inputs, differential tests compare decisions,
acceptance, saved units and error codes. Generated session UUIDs and descriptive
error wording are not required to match.

## Build and Verify

Use Visual Studio C++ Build Tools, Windows SDK and CMake 3.25+:

```powershell
cmake -S native -B native/build -A x64
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
python -m unittest
python tools/profile_gateway_core.py --out tmp/native-core-profile.json
python tools/native_gateway_validation.py benchmark --pairs 30 --out tmp/native-transport.json
python tools/native_gateway_validation.py soak --seconds 3600 --events 1000000 --out tmp/native-soak.json
```

`FLUIDGATEWAY_NATIVE` selects a built executable for Python integration tests;
its sibling `fluidgateway-native-tests.exe` is also required. Those tests skip
when no native build exists, and run in the native CI job. Use Debug and a separate
`-DFLUIDGATEWAY_ENABLE_ASAN=ON` Release build for development validation. ASAN's DLL
must be available only in the test process environment. Never distribute that build.

The development benchmark and test executables are not part of the release ZIP.
Release uses the static MSVC CRT. The package includes the server, MIT license,
this guide and a SHA256 manifest. The shipped executable is checked with a restricted
PATH and its imported DLLs inspected for Python, ASAN or developer-CRT dependencies.
`tools/Test-NativePackage.ps1 -PackagePath <directory>` exercises 11 real protocol
exchanges using PowerShell/.NET only and checks loaded modules and the manifest.

## Runtime Integration

Runtime validation scripts accept `-GatewayBackend Native -GatewayExecutable <exe>`
or the explicit `Python` reference backend. Fault peers may still use Python as
test machinery; successful native operation never silently launches Python.
The comparison-oriented `link-probe` can use `--v1-baseline-port` for a separate,
explicit v1 reference server. Its report records both endpoints.

Build Runtime's `tools/GatewayComparison/GatewayComparison.csproj` and run
`python tools/compare_runtime_gateway.py --out tmp/native-real-authorizer.json`
to compare 30 AB/BA pairs with five warmup pairs using the actual Runtime
authorizer. This includes PID/hash/context validation but publishes no GPU policy.
The default Runtime native build is `native/build-vulkan`; select another with
`--runtime-native-build native/build`. Build paths refer to the Runtime checkout.
CPU cycles come from Windows QueryProcessCycleTime and are not converted into
nanoseconds. Short process-time samples can round to zero; they are not evidence
of zero CPU cost.

Promotion requires functional/contract parity, Release/Debug/ASAN validation,
bounded memory through an uninterrupted 60-minute soak, and lower CPU cycles per
operation with no p95/p99 regression across 30 paired authorizations. Local
measurements are workload-specific and do not authorize FPS, input-latency,
energy, physical PCIe or RAM/VRAM-saving claims.

Soak samples are taken at least once per minute under load. Any sampling gap over
90 seconds fails the continuity check, including a final unsampled pause. The
memory criterion is unchanged: after 300 seconds, maximum sampled private bytes
must stay within 110% of the minimum plus 1 MiB. Short diagnostic runs are not
substitutes for the 3600-second release gate. Retain failed and interrupted results.
