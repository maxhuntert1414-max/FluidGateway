# FluidLink v2

FluidLink v2 is the preferred local advisory transport between FluidRuntime and
FluidGateway. It removes JSON from the wire payload while preserving the fixed
binary envelope introduced by v1.

Canonical files:

- [`fluidlink-v2.contract.json`](../contracts/fluidlink-v2.contract.json)
- [`fluidlink-v2.golden.json`](../contracts/fluidlink-v2.golden.json)

Contract SHA-256:

`0d24d96aec32d74e123f9e198e51adde74ddf190e8c40b0ac18bddf5c4108b2f`

Golden-vector SHA-256:

`3afb2a04373b1a21bd36fe9580c2adc95b38a619d1c4d8864205eaf45bcf6216`

The golden fixture contains 17 complete frames. It covers every message and
runtime-event opcode, both lifecycle endings, register/release, every optional
budget and operation field, execute/deduplicate decision shapes, heartbeat, one
numeric `invalid_payload` error, and goodbye. Other decision/error registry
values remain covered by codec validation rather than one vector each.

## What Changed

| Concern | v1 | v2 |
| --- | --- | --- |
| Header | Fixed 56-byte binary | Same layout, wire version `2` |
| Event vocabulary | Numeric opcodes | Numeric opcodes |
| Payload | Strict bounded JSON object | Opcode-specific positional binary |
| Capabilities | Array of strings | Unsigned 64-bit bitmask |
| Time | Decimal milliseconds in dynamic fields | Unsigned integer microseconds |
| Memory | Decimal MiB in dynamic fields | Unsigned integer bytes |
| Maximum payload | 1 MiB | 65,535 bytes |

Version 2 is additive. The server selects v1 or v2 from byte 5 after the
`FLNK` magic and never mixes versions within a connection. A non-FluidLink
connection can still use the isolated JSONL compatibility endpoint.

## Header

All integers are little-endian.

| Offset | Bytes | Field |
| ---: | ---: | --- |
| `0` | `4` | ASCII magic `FLNK` |
| `4` | `1` | Wire version `2` |
| `5` | `1` | Frame kind: request `1`, response `2` |
| `6` | `1` | Message opcode |
| `7` | `1` | Runtime-event subject opcode or zero |
| `8` | `1` | Decision opcode or zero |
| `9` | `1` | Flags: OK bit `0`, session bit `1` |
| `10` | `2` | Reserved, must be zero |
| `12` | `8` | Nonzero monotonic sequence |
| `20` | `16` | Nonzero message ID |
| `36` | `16` | Session ID, zero when the session flag is absent |
| `52` | `4` | Payload byte count |

Message opcodes remain `Hello=1`, `Welcome=2`, `RuntimeEvent=10`,
`RuntimeDecision=11`, `Ping=20`, `Pong=21`, `Goodbye=30`, and `Error=255`.
Event opcodes remain `Session=100`, `Frame=101`, `Resource=102`,
`Operation=103`, and `State=104`.

## Positional Payloads

Text uses a one- or two-byte unsigned UTF-8 length followed by exactly that many
bytes. Invalid UTF-8, trailing bytes, unknown enum values, unknown mask bits,
and out-of-range lengths are rejected.

| Message | Field order |
| --- | --- |
| Hello | contract hash `32B`, requested capabilities `u64`, required capabilities `u64`, client name `text8`, client version `text8` |
| Welcome | contract hash `32B`, available capabilities `u64`, accepted capabilities `u64`, maximum payload `u32`, server name `text8`, server version `text8` |
| Ping/Pong | nonce `text8` |
| Goodbye | empty |
| Decision | status flags `u8`, saved microseconds `u64`, saved bytes `u64` |
| Error | error code `u16`, message `text16` |

Runtime-event payloads:

| Event | Field order |
| --- | --- |
| Session | action `u8`, presence `u8`, ID `text16`, then present budgets in frame-us/RAM/VRAM/shared/staging/swapchain order |
| Frame | action `u8`, presence `u8`, frame `u64`, optional target-frame-us `u32` |
| Resource | action `u8`, ID `text16`; register then adds kind `u8`, memory `u8`, lifetime `u8`, size `u64`, alias count `u8`, aliases `text16[]` |
| Operation | type `u8`, queue `u8`, presence `u8`, ID `text16`, optional source/target/reason, cost-us `u32`, size `u64`, optional frame `u64`, dependency count `u8`, dependencies `text16[]` |
| State | action `u8`; v2 currently supports only the snapshot request |

The complete enum registry, field masks, bounds, action-specific rules, and
error codes live in the canonical contract rather than in implementation-only
constants.

Malformed positional bytes return numeric `invalid_payload`. A valid event that
the Gateway adapter cannot accept returns `runtime_event_rejected`. Only that
typed rejection is recoverable for the .NET client; sequence, session,
correlation, framing, and other peer errors invalidate local session state and
require a new handshake.

## Fixed-Point Boundary

Time and memory are deterministic on the wire:

- frame budgets, target frame time, and operation cost are integer
  microseconds;
- resource size, memory budgets, and estimated savings are integer bytes;
- legacy Gateway millisecond/MiB values are converted with half-away-from-zero
  rounding before encoding;
- decoding back into the current Gateway adapter may produce its existing
  decimal millisecond/MiB model.

This removes floating-point representation drift between Python and .NET at the
transport boundary. It does not claim that every internal project model has
already migrated to integers.

## Measured Same-Flow Result

The v0.14 probe opens one real v1 session and one real v2 session against the
same Gateway. Each performs Hello, heartbeat, eight runtime events, and
Goodbye. Both produce the same duplicate-upload decision.

| Measurement | v1 | v2 |
| --- | ---: | ---: |
| Request frame bytes | `1,755` | `1,032` |
| Response frame bytes | `1,434` | `848` |
| Total frame bytes | `3,189` | `1,880` |

Version 2 saves `1,309` frame bytes, or `41.05%`, for this exact control flow.
The counters include FluidLink headers and payloads handed to TCP. They exclude
TCP/IP overhead and are not measurements of RAM/VRAM, PCIe, FPS, power, or a
game workload.

## Why Delta And Shared Memory Are Deferred

Delta encoding is useful only when repeated state bodies exist. The current
FluidLink state event is a one-byte snapshot request; the full snapshot remains
inside the Gateway adapter response path and is not transported as a v2 state
body. Adding baseline IDs, resynchronization, retention, and loss recovery now
would save zero bytes in the implemented flow.

A generic shared-memory FluidLink transport is also separate from the existing
native hook ring. Reusing that ring would incorrectly couple the managed
Gateway protocol to the D3D11 hook ABI. A future transport needs an explicit
record layout, producer/consumer atomics, backpressure, process identity and
ACL rules, timeout behavior, peer-crash recovery, and fallback to TCP.

Promotion gates:

- consider delta when real snapshot traffic reaches 60 Hz or 10 KiB/s and an
  exact reconstruction prototype keeps median deltas at or below 50% and p95 at
  or below 75% of full snapshots;
- consider shared memory after a sustained benchmark, then require at least 30%
  p99 latency improvement and 20% combined CPU reduction with zero corruption
  under wraparound, slow-reader, cancellation, and peer-crash tests.

The 11-round-trip functional probe records application RTT for visibility, but
its tiny sample includes handshake and Python scheduling. It is not the
sustained benchmark required for transport promotion.

## Verification

```powershell
# FluidGateway
python -m unittest tests.test_fluidlink tests.test_fluidlink_v2 -v

# FluidRuntime, with both repositories adjacent
dotnet test tests/FluidRuntime.Tests/FluidRuntime.Tests.csproj `
  -c Release --filter FullyQualifiedName~FluidLink
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools/Test-FluidLinkIntegration.ps1 `
  -GatewayPath ..\FluidGateway
```

The integration gate hashes both contract copies and both 17-vector copies,
requires the exact fixed-point decision, checks the same-flow byte budget, and
rejects any v2 report that claims JSON, delta encoding, or shared-memory
transport. Encoder tests also reject implicit identifier coercion and
registration-only fields on resource-release messages.

## Trust Boundary

FluidLink is advisory local user-space IPC without hostile-peer authentication.
It does not authorize a native hook or turn discrete memory into unified memory.
Any actuation still requires owned-target opt-in, provenance, bounded action and
budget, expiration, equivalence, evidence, and rollback in FluidRuntime.
