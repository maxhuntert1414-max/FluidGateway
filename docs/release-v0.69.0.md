# v0.69.0: Optional In-Process Gateway

This release adds `FluidGatewayNative.dll` without replacing the server. Both
backends execute the same C++20 core and unchanged FluidLink v2/base+batch contracts.
The C ABI is versioned independently as `0x00010000`; Runtime integration is opt-in.

## Measured A/B

One Windows machine, .NET 10, five warmup pairs, 30 alternating AB/BA pairs.
Each backend completed 1,920 batches of 128 operations and 960 complete
authorizations of 128 candidates. DLL loading/hash cost is excluded from the
steady-state measurements. The server is a separate owned process; no GPU calls
are made in this benchmark.

| Workload / metric | Server | In-process |
| --- | ---: | ---: |
| Batch p50 / p95 / p99, microseconds | 332.50 / 578.21 / 808.71 | 185.65 / 360.26 / 637.29 |
| Authorization p50 / p95 / p99, microseconds | 5,530.75 / 6,723.22 / 8,229.58 | 407.10 / 694.82 / 1,037.72 |
| Batch CPU cycles / operation | 12,439 | 5,376 |
| Authorization CPU cycles / candidate | 178,567 | 12,305 |
| Batch managed allocated bytes / operation | 218.56 | 186.29 |
| Authorization managed allocated bytes / candidate | 1,018.51 | 565.21 |
| Batches / second | 2,723 | 4,662 |
| Complete authorizations / second | 175.67 | 2,124.75 |

Raw samples, CPU time, private memory, per-batch counters and all measured binary
hashes: [backend-ab.json](evidence/inprocess-v0.69.0/backend-ab.json).
Package identities: [native-manifest.json](evidence/inprocess-v0.69.0/native-manifest.json).

**Limits:** Windows CPU-time counters are too coarse for short phases: batch CPU
time did not improve in this run even though cycles and latency did. Do not hide
that result or substitute cycles for elapsed CPU time. Managed allocation is
bytes, not object count. PMR counters measure only retained native state; native
CRT totals and OS/kernel copy counts are unmeasured. Private process memory was
roughly 43-45 MiB in the host, not eliminated by embedding the Gateway. This machine
has third-party Windhawk modules; no system settings were changed for the test.

The DLL recorded 151,488 explicit wire-payload copy bytes across each 64-batch
sample, so this implementation is explicitly **not zero-copy**. A sample retained
3,605,096 bytes with 8,192 operation IDs, below the unchanged 8 MiB limit.

## Validation

- Full Gateway suite: 330 tests passed.
- Full managed Runtime suite with the packaged DLL: 257 tests passed, none skipped.
- CTest Release, Debug and ASAN: core, C ABI consumer, and C++ ABI consumer passed.
- Live server/DLL differential corpus and state limits passed in Release, Debug
  and ASAN. Existing codec golden vectors and Python/C++ comparisons are retained.
- Ten repeated Release native suites included 80,000 concurrent session renewals.
- D3D11, D3D12 and Vulkan owned workloads completed with both backends. Packaged
  in-process runs also completed with PATH restricted to Windows directories,
  without Python or a Gateway server. Exact content and rollback gates passed.
- DLL exports only five C entry points; Release imports only `bcrypt.dll` and
  `KERNEL32.dll`, not Python, ASAN or the dynamic MSVC redistributable.

Testing found and fixed a slot-allocation race: probing a live session's lock could
spuriously return BUSY to an unrelated exchange. A separate atomic slot reservation
now avoids that contention; the failure remained fail-closed throughout testing.
Buffer pooling also removed per-session response-buffer allocation in the Runtime.

The graphics checks were two-pair correctness checks, not performance qualification.
D3D11/D3D12 used WARP; Vulkan used hardware. This release does not establish game
FPS, input-delay, power, RAM/VRAM residency or physical transfer improvements.
The prior v0.68 60-minute server soak is historical evidence, not a DLL soak claim.

See [ABI, lifecycle, trust limits and next typed-call stage](inprocess-gateway.md).
The isolated server remains the default and no automatic fallback grants authority.
