# FluidGateway v0.68.0: Native Online Core

Live FluidLink v2 decisions now run in C++20 without Python. Python remains the
offline analysis/reporting tool and reference implementation. The separate
FluidRuntime retains C# coordination, native execution and all authority gates.

[Download the Windows x64 package](https://github.com/maxhuntert1414-max/FluidGateway/releases/tag/v0.68.0)
and follow the [native guide](native-gateway.md). Nothing is installed globally.

## What Changed

- Strict v2 base/batch transport preserves opcodes, contracts and golden vectors.
- Incremental state replaces repeated scans of completed frame history.
- Aliases, write invalidation, dependencies and reuse remain part of decisions.
- Eight persistent workers create fresh state for every connection. Each session
  is bounded by 8 MiB of retained allocations, 4,096 resources and 16,384 IDs.
- Overflow, malformed input, capacity exhaustion and deadlines reject requests
  without partial batch decisions or silent Python fallback.
- Contributor guides, pinned formatters and scoped CI checks cover the new core.

## Measured Authorization Cost

The actual Runtime authorizer ran five warmup pairs and **30 measured AB/BA pairs**,
with 128 candidates per authorization. PID/hash/context guards passed; the
benchmark published no native GPU policy. The unchanged promotion criteria passed.

| Metric | Python reference | C++ native |
| --- | ---: | ---: |
| Authorization p50 | 27.38 ms | 5.56 ms |
| Authorization p95 | 30.92 ms | 7.38 ms |
| Authorization p99 | 31.21 ms | 7.58 ms |
| Server CPU cycles / logical operation | 509,501 | 28,094 |

That is **94.5% fewer server CPU cycles per operation** and **75.7% lower p99**
on this fixture and machine. [All authorization samples](evidence/native-v0.68.0/authorization.json)
are included, not only the summary. Short process-time samples rounded to zero
for Native; cycle counts, not a claim of zero CPU, determine the CPU gate.

Separate [decoded-core](evidence/native-v0.68.0/core.json) and
[transport](evidence/native-v0.68.0/transport.json) profiles keep those costs apart.
The decoded core processed 32,768 operations at about 8,070 ops/s in Python and
1,012,111 ops/s in C++; this excludes codec, TCP and GPU work. Native peak PMR
allocation and Python process-private memory have different scopes and must not
be compared as a memory-saving ratio.

Environment: Xeon E5-2650 v2, Windows 11, 16 GiB installed RAM, MSVC 19.51,
Python 3.14.5 and .NET 10.0.300. Existing global Windhawk injection was observed
and left unchanged. Results are not from an isolated benchmark OS.
[Environment and source identities](evidence/native-v0.68.0/environment.json).

## Soak and Correctness

The **same shipped executable** completed **3,600.49 seconds, 18,186,240 operations
and 4,440 successive sessions**. The maximum sample gap was 60.86 seconds.
Post-warmup sampled private bytes peaked at 6,848,512 (6.53 MiB), passing the
unchanged memory-plateau and uninterrupted-load gates.
[Full soak samples](evidence/native-v0.68.0/soak.json).

An earlier candidate failed the memory gate after 60 minutes. That
[failed result remains published](evidence/native-v0.68.0/previous-failed-soak.json).
Replacing per-connection thread creation with persistent workers removed the
observed growth in the final run. This is measured stability, not proof that
every possible allocator or OS workload has been exhausted.

- Gateway: 325 local tests, including 24 native integration tests; native core
  and integration suites also passed Debug and ASAN. All six CI jobs passed.
- Runtime: 251 managed tests and 32 native CTests in each of Release/Debug/ASAN.
- Real C# interop: 11 round trips, unchanged contract hashes, 1,880 v2 bytes
  against 3,189 v1 reference bytes for this flow.
- Owned D3D11 and D3D12: two pairs each, 128 redundant API calls omitted per
  optimized run, exact content and rollback verified on WARP.
- Cooperative Vulkan: two pairs on Radeon RX 580 2048SP, 128 omissions per run,
  exact readback, mutation/invalidation guards and rollback verified.
- Malformed, stalled and slow peers: all three APIs retained original execution,
  with zero skipped calls and verified content/rollback.
- Packaged Gateway plus actual Runtime and owned D3D11 execution passed with
  Python absent from the child PATH. No Python, ASAN or developer CRT was loaded
  by the Gateway. No system or user environment was changed.

[Selected interop, actuation and standalone evidence](evidence/native-v0.68.0/labs.json)
omits local paths and PIDs and retains source-report hashes. D3D12's combined
native/performance gate remains blocked by WARP and insufficient performance
pairs; its correctness checks passed. None of these GPU runs permits a
performance claim.

## Artifact Identity

The Release server uses a static MSVC CRT; the ZIP contains only the server,
MIT license, guide and SHA256 manifest. Test, benchmark and ASAN executables are
not distributed. The release also provides a ZIP checksum.

```text
fluidgateway-native.exe
SHA256 33f6ca5033039d474a37915dc07a1fcb159b1458fc4bb217abe8719a276ea654
```

The environment file identifies the validated source commit. Subsequent release
documentation does not change the native source or this binary. The real-authorizer
tool is hash-bound too; its exit status now fails on a failed performance gate.

## Limits

This release reduces the cost of FluidGateway itself. It does **not** establish
higher game FPS, lower input delay, reduced energy, physical PCIe savings or an
equivalent to unified memory. Existing content, identity, expiry, budget and
rollback protections remain mandatory; third-party GPU calls are not elided.
