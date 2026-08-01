# FluidGateway Technical Reference

> This document preserves the complete v0.64 protocol and feature history from
> the original long-form README. Start with the
> [project overview](../README.md) for the current capability map, evidence, and
> roadmap.

FluidGateway is an open source project for finding and, over time, reducing
unnecessary friction between CPU, GPU, RAM, VRAM, frame buffers, textures, and
presentation.

The long-term goal is an intelligent software gateway/scheduler that shortens
the practical distance between processing stages as much as normal PC software
can. The inspiration is not to clone DLSS, FSR, or Lossless Scaling, but to
borrow the efficiency philosophy of tightly integrated systems such as Apple
Silicon: less redundant movement, fewer late sync points, more useful work per
watt.

FluidGateway itself does not inject code, hook games, or change drivers. It
ingests PresentMon 2.x CSV data, produces a ranked report of likely waste
patterns with evidence, and includes user-space runtime prototypes for modeling
early CPU/GPU/RAM/VRAM decisions. One exact owned-lab authorization path is now
consumed by FluidRuntime v0.15; it is not a general optimization authority.

> The initial promise is to find probable waste in the frame path, not to
> automatically increase FPS.

The native live-observation and future actuation work now lives in
[FluidRuntime](https://github.com/maxhuntert1414-max/FluidRuntime). FluidGateway
remains the diagnostic, evidence, policy-modeling, and operational-ledger half
of the project; FluidRuntime consumes that evidence alongside live Windows,
memory, GPU, and D3D11 telemetry.

FluidRuntime v0.5 also contains a first controlled actuation experiment: it can
skip one redundant D3D11 resource copy only inside its owned deterministic lab,
then compare buffer/texture bytes exactly, publish hashes, and verify rollback
against a separate baseline. It does not enable optimization or injection in
games.

FluidRuntime v0.6 turns that experiment into a paired trace: alternating
baseline/optimized order, excluded warmups, CPU and disjoint-guarded GPU timing,
p50/p95 distributions, raw runs, and explicit blockers when evidence is too
weak for a performance claim. The published
[v0.6 evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.6-copy-elision.md)
keeps the owned-lab scope explicit and includes the raw traces.

FluidRuntime v0.7 adds the next safety layer: cooperative resource retirement,
monotonic resource IDs, bounded pointer-reuse detection, and managed
active/retired-state reconstruction. Its
[lifecycle evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.7-resource-lifecycle.md)
remains limited to the owned D3D11 target; automatic COM destruction and
external-process actuation are not claimed.

FluidRuntime v0.7.1 adds opt-in automatic destruction observation for returned
D3D11 Buffer/Texture2D interfaces, 64-cycle churn validation, dynamic Release
slot rollback, and a zero-hook cooperative fallback. The published
[automatic-destruction evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.7.1-automatic-destruction.md)
also records an inconclusive AMD performance result and blocks the positive
claim instead of generalizing a favorable median.

FluidRuntime v0.7.2 adds ABI-v4 subresource indices, per-mip generations, and
exact `CopySubresourceRegion` identity. Its owned workload observes eight
regional copies and classifies three exact unchanged repeats while forwarding
all eight. The published
[subresource-provenance evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.7.2-subresource-provenance.md)
includes WARP, fallback, concurrent-detach, and RX 580 traces. The hardware run
supports only a narrow GPU-workload improvement; its CPU timing regressed, so it
does not establish better frame time, FPS, or game-wide efficiency.

FluidRuntime v0.7.3 adds ABI-v5 events for exact Texture2D mip writes observed
through `ClearRenderTargetView` and `ClearUnorderedAccessViewFloat`. The owned
workload proves that an RTV clear on mip 0 preserves mip-1 provenance while a
UAV clear on mip 1 invalidates the next mip-1 repeat. Its
[GPU-view write evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.7.3-gpu-view-writes.md)
contains WARP, fallback, concurrent-detach, and 22 RX 580 runs. All correctness
gates passed, but the positive performance claim was blocked because GPU p95
regressed; this release advances trustworthy observation, not an FPS promise.

FluidRuntime v0.8.0 adds the first managed-to-native actuation path. Its .NET
`manager-lab` publishes one short-lived shared-memory policy epoch to an owned
D3D11 target; the native hook validates and acknowledges it, then may spend a
one-action budget on the already-proven redundant `CopyResource`. The published
[managed control-plane evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.8.0-managed-control-plane.md)
records successful WARP and RX 580 correctness runs. The RX 580 timing regressed,
so the performance gate blocked the claim. CPU scheduling, RAM/VRAM residency,
presentation changes, external attach, and game support remain disabled.

FluidRuntime v0.9.0 turns the one-copy experiment into a bounded sustained
intervention. A managed policy can spend up to 128 actions on proven unchanged
repeats in a 4 MiB owned D3D11 buffer workload. The default optimized run skips
128 copies, avoids 512 MiB of logical GPU copy traffic, preserves exact readback
hashes, and restores original dispatch. The published
[sustained copy-elision evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.9.0-sustained-copy-elision.md)
includes a deterministic 320-process negative policy matrix plus WARP and RX
580 paired traces. The RX 580 GPU-workload gate passed, while CPU timing showed
a small regression; this is not an FPS, frame-time, external-game, RAM/VRAM, or
general efficiency claim.

FluidRuntime v0.10.0 separates the API-visible readback direction from generic
GPU copies. A dedicated action can skip only proven unchanged
`D3D11_USAGE_DEFAULT -> D3D11_USAGE_STAGING + D3D11_CPU_ACCESS_READ` repeats in
the owned target. Baselines forward all 65 readback copies; optimized runs
forward one, skip 64, and still map and compare all 4 MiB 65 times. The
[readback-elision evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.10.0-readback-elision.md)
contains WARP, a 320-process negative matrix, and 22 RX 580 runs. The scoped
CPU/GPU interval gate passed with 10/10 paired wins. This does not prove physical
VRAM placement, PCIe byte reduction, residency control, or external-game
support.

FluidRuntime v0.11.0 proves the opposite API-visible upload direction. A third
action bit can skip only trusted unchanged
`D3D11_USAGE_STAGING + D3D11_CPU_ACCESS_WRITE -> D3D11_USAGE_DEFAULT` repeats
in the owned target. Baselines forward all 65 uploads; optimized runs forward
one and skip 64 after one successful 4 MiB write map/unmap. The
[upload-elision evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.11.0-upload-elision.md)
contains ring ABI 8/snapshot ABI 11 accounting, a 320-process negative matrix,
WARP evidence, and 22 RX 580 runs. GPU won all 10 measured pairs while all CPU
submission pairs stayed inside the declared +1 ms / +10% overhead envelope.
This is not physical RAM-to-VRAM, PCIe, residency, FPS, or CPU-acceleration
evidence.

FluidRuntime v0.12.0 adds a fourth isolated action for a direct CPU-memory
upload path: full-buffer `UpdateSubresource` into one owned 4 MiB default
buffer. Attach-options ABI 3 bounds exact retained content to one resource;
ring ABI 9 and snapshot ABI 12 expose content-comparison, candidate, forwarded,
skipped, and cache evidence. Baselines forward all 67 direct updates. Optimized
runs forward three required writes and skip 64 byte-identical repeats.

The workload is adversarial rather than pointer-based: content B differs from A
by one bit, then an external `CopyResource` writes distinct content C before B
is uploaded again. Both B transitions must be forwarded. Exact `memcmp` proves
equality; FNV-1a hashes only identify evidence. The
[v0.12 evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/v0.12.0/docs/evidence/v0.12.0-update-upload-elision.md)
contains a 320-process negative matrix, WARP traces, and 22 RX 580 raw runs.
CPU and guarded GPU intervals improved in 10/10 measured pairs, but the claim
remains limited to the owned full-buffer workload. It does not establish
physical RAM/VRAM or PCIe traffic, texture/partial uploads, external-game
safety, FPS, or a general cache.

FluidRuntime v0.15.0 closes the first deliberately narrow live control loop.
Before an optimized owned run starts, FluidGateway must return one executed
seed decision and exactly 64 accepted `deduplicate-identical-transfer`
decisions over FluidLink v2. Runtime maps that authorization to the existing
native action bit 8 with budget 64. The hook still requires matching resource
generation and exact 4 MiB content equality before each skip.

Each optimized authorization currently costs 74 serial loopback round trips
under one configurable total deadline; the published positive harness uses
five seconds. Runtime OS-verifies the exact tuple against the expected Gateway
PID/executable, freezes target/hook hashes, and binds all authorization inputs
in a unique context SHA-256. Advertised server identity is metadata, and this
process binding is not cryptographic authentication. The adversarial controls
use 500 ms: a malformed response, a peer that accepts TCP and never responds,
or a valid peer whose cumulative delay exceeds the deadline launches a fresh
baseline with 70 forwarded calls, zero skips, and no policy publication.
The published
[v0.15 evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/v0.15.0/docs/evidence/v0.15.0-gateway-managed-update-upload.md)
records all three WARP controls and 22 RX 580 runs. Gateway authorization remains outside
the native workload interval, so the closed-loop report explicitly blocks an
end-to-end performance claim.

## Intelligent Management Layer

FluidGateway's management layer treats the diagnostic report as the sensor
input for a future runtime controller. The goal is to eventually coordinate:

- CPU/GPU work handoff;
- RAM/VRAM/resource residency;
- texture and buffer upload timing;
- staging buffer reuse;
- present queue depth;
- frame pacing stability;
- zero-copy or lower-copy presentation routes.

FluidGateway-side management remains advisory by default. The tool generates a
plan that says which policies a future gateway/scheduler should apply and why.
The v0.15 exception translates one exact owned-lab decision set into a bounded
Runtime action; it does not generalize to other resources or processes. Direct
RAM/VRAM control requires additional telemetry beyond PresentMon.

The v0.2 management plan can activate policies such as:

- adaptive frame queue depth;
- early CPU/GPU handoff scheduling;
- GPU work prefetch budgeting;
- frame pacing stability control;
- RAM/VRAM residency management;
- zero-copy presentation route preference.

## Quick Start

```powershell
python -m fluidgateway analyze --presentmon trace.csv --out report.html
python -m fluidgateway manage --presentmon trace.csv --out management.json
python -m fluidgateway track --presentmon trace.csv --label "baseline"
python -m fluidgateway history
python -m fluidgateway runtime optimize --manifest pipeline.json --out runtime-plan.json
python -m fluidgateway runtime simulate-control --manifest pipeline.json --out control-snapshot.json
python -m fluidgateway runtime replay-events --events runtime-events.jsonl --out event-replay.json
python -m fluidgateway runtime ingest-presentmon --presentmon trace.csv --out presentmon-events.jsonl
python -m fluidgateway runtime run-presentmon-daemon --presentmon trace.csv --events-out presentmon-events.jsonl --state runtime-state.json --out runtime-daemon.json
python -m fluidgateway runtime serve-events --host 127.0.0.1 --port 8765
python -m fluidgateway runtime send-events --events runtime-events.jsonl --host 127.0.0.1 --port 8765 --out server-responses.json
python -m fluidgateway runtime run-adapter --events adapter-events.jsonl --out adapter-session.json
python -m fluidgateway runtime run-daemon --events adapter-events.jsonl --state runtime-state.json --out runtime-daemon.json
```

The command writes:

- `report.html`: human-readable diagnostic report.
- `report.json`: structured report data next to the HTML file.
- `management.json`: advisory management plan when using `manage`.
- `presentmon-events.jsonl`: synthetic runtime adapter events when using
  `runtime ingest-presentmon`.
- `.fluidgateway/traces.json`: local trace registry when using `track`.

## Trace Tracking

The `track` command turns each analyzed trace into a historical record:

- file SHA-256 fingerprint;
- application/runtime/frame summary;
- finding IDs and max finding score;
- management action IDs and max priority;
- labels, tags, and notes.

This registry is the first dataset layer for the future intelligent gateway. It
lets FluidGateway compare repeated runs, identify recurring waste patterns, and
prepare for deeper telemetry sources such as RAM/VRAM residency, texture upload
timing, staging buffer reuse, and API-level synchronization events.

## PresentMon Runtime Ingest

The v0.59 `runtime ingest-presentmon` command converts a PresentMon analysis
into a FluidGateway adapter JSONL stream:

```powershell
python -m fluidgateway runtime ingest-presentmon `
  --presentmon trace.csv `
  --out presentmon-events.jsonl

python -m fluidgateway runtime run-daemon `
  --events presentmon-events.jsonl `
  --state runtime-state.json `
  --out runtime-daemon.json
```

The v0.60 `runtime run-presentmon-daemon` command does the same bridge and the
daemon pass in one step while still preserving the generated JSONL as evidence:

```powershell
python -m fluidgateway runtime run-presentmon-daemon `
  --presentmon trace.csv `
  --events-out presentmon-events.jsonl `
  --state runtime-state.json `
  --out runtime-daemon.json
```

In v0.61 the same command also writes an operational ledger next to the daemon
report by default, for example `runtime-daemon.ledger.json`. Use `--ledger-out`
to choose a different path. The ledger condenses the run into manager profile,
waste pressure score, safe progress score, blocked native surfaces, and the next
recommended step.

This is the first bridge from measured frame-path symptoms into the persistent
runtime manager loop. It maps advisory management actions to synthetic adapter
events with frame budgets, resource pressure, queue pressure, and evidence
metadata. The generated stream is still inferred from PresentMon: it does not
prove internal engine cause, inspect real textures/buffers, or mutate RAM, VRAM,
GPU queues, drivers, games, or OS scheduling.

## Runtime Optimizer Prototype

The `runtime optimize` command is the first prototype of the actual gateway
behavior. Instead of only reporting symptoms from a trace, it accepts an
explicit pipeline manifest and emits an optimized runtime plan.

The manifest models:

- resources in `ram`, `vram`, `shared`, `staging`, `swapchain`, and `display`;
- `buffer`, `texture`, and `framebuffer` resources;
- `copy`, `upload`, `sync`, `allocate`, `draw`, `compute`, and `present`
  operations;
- operation cost, size, queue, frame, and dependency information.

The v0.4 optimizer can:

- remove self-copies;
- collapse copies between aliased resources in the same memory layer;
- deduplicate repeated uploads/copies into the same target;
- remove syncs that only wait on removed work;
- reuse transient staging/scratch buffers.

This is not driver interception yet. It is the first executable model of the
target runtime: reduce redundant transport and late synchronization before
moving toward API hooks, engine SDKs, or deeper OS/GPU telemetry.

## Runtime Control Plane

The v0.5 control plane exposes the optimizer as an incremental SDK prototype.
An app or engine can register resources, submit operations before executing
them, and receive a decision:

- execute the operation;
- remove redundant work;
- reuse an existing transient resource.

The CLI command `runtime simulate-control` runs this loop against a manifest and
emits a control snapshot. This is the first shape of the real runtime contract:
observe operation intent, decide early, then prevent useless movement or waiting
before it happens.

## Runtime Event Stream

The v0.6 event stream is the first integration-facing protocol. Instead of
requiring a whole manifest up front, an engine, SDK, hook, or telemetry adapter
can emit JSONL events as work is discovered:

```jsonl
{"event":"resource","id":"vram_texture","kind":"texture","memory":"vram","size_mb":64}
{"event":"operation","id":"upload_1","operation_type":"upload","source":"ram_texture","target":"vram_texture","cost_ms":0.9,"size_mb":64}
```

`runtime replay-events` replays the stream through the same control plane and
records per-operation decisions. This is the bridge from offline analysis toward
a runtime that can reject redundant copies, syncs, and transient allocations
before they execute.

## Local Runtime Decision Server

The v0.7 server exposes the event protocol over a local TCP JSONL endpoint:

```powershell
python -m fluidgateway runtime serve-events --host 127.0.0.1 --port 8765
```

Each client connection owns an independent control-plane session. A client sends
one JSON event per line and receives one JSON response per line. Resource events
return an acknowledgement; operation events return whether the operation should
execute or whether FluidGateway removed/reused it.

This is still a user-space prototype, not a driver or graphics API hook. It is,
however, a concrete integration surface for an engine plugin, telemetry adapter,
or future interceptor to ask for decisions before performing CPU/GPU/RAM/VRAM
movement or synchronization.

### FluidLink Binary Modes

Version 0.63 added FluidLink v1 without removing the original JSONL surface. A TCP
connection beginning with ASCII `FLNK` uses a fixed 56-byte little-endian
header; any other valid event connection stays in legacy JSONL mode. The modes
never mix within one connection.

FluidLink places message, event, and decision vocabulary in one-byte numeric
opcodes. Dynamic event fields remain a strict UTF-8 JSON object bounded to 1 MiB
and 64 levels. Handshake, sequence, message/session correlation, exact contract
fingerprint, capability set, flags, reserved bits, and payload length are all
validated before a decision is accepted. The .NET client is loopback-only and
serializes concurrent round trips.

The machine-readable layout is
[`contracts/fluidlink-v1.contract.json`](../contracts/fluidlink-v1.contract.json),
with protocol details and measured framing evidence in
[`docs/fluidlink-v1.md`](fluidlink-v1.md). V1 decisions remain advisory and do
not grant native hook authority.

Version 0.64 adds wire version 2 without changing v1. Byte 5 selects the
connection protocol. V2 removes JSON from FluidLink payloads: each opcode has a
positional binary schema, optional fields use presence masks, capabilities use
one `u64`, time uses integer microseconds, and memory uses integer bytes. The
payload cap is 65,535 bytes and every text field remains strict bounded UTF-8.

The v0.14 cross-process probe executes the same 11 request/response semantics
through a real v1 session and a real v2 session. It measured 3,189 v1 frame
bytes and 1,880 v2 frame bytes, a 41.05% reduction. These are control-protocol
frame bytes, not RAM/VRAM or PCIe traffic. The canonical layout and golden
vectors are [`contracts/fluidlink-v2.contract.json`](../contracts/fluidlink-v2.contract.json)
and [`contracts/fluidlink-v2.golden.json`](../contracts/fluidlink-v2.golden.json).
See [`docs/fluidlink-v2.md`](fluidlink-v2.md) for action rules, fixed-point
boundaries, compatibility, and the explicit delta/shared-memory deferral.
V2 also has one v0.15 owned-lab consumer for the exact direct-update sequence;
all other decisions remain advisory, and native equality checks remain final.

## Runtime Client SDK

The runtime client SDK is the first client-side integration surface for the
local decision server. Python adapters can connect to the server, register
resources, submit operations, and receive one decision per event:

```python
from fluidgateway.client import RuntimeEventClient

with RuntimeEventClient("127.0.0.1", 8765) as client:
    client.register_resource("ram_texture", kind="texture", memory="ram", size_mb=64)
    client.register_resource("vram_texture", kind="texture", memory="vram", size_mb=64)
    response = client.submit_operation(
        "upload_texture",
        "upload",
        source="ram_texture",
        target="vram_texture",
        queue="copy",
        cost_ms=0.9,
        size_mb=64,
    )
```

The CLI command `runtime send-events` uses the same SDK to send a JSONL stream
to a running server and writes every server response to JSON. This keeps replay
and live local-server testing separate: `replay-events` is offline, while
`send-events` exercises the TCP protocol another process would use.

## Runtime Adapter Session

The v0.9 adapter session adds lifecycle structure around the decision loop. An
engine plugin, telemetry collector, or future interceptor can describe a
session, frame boundaries, resources, operations, and resource releases:

```jsonl
{"event":"session","action":"begin","id":"demo-adapter"}
{"event":"frame","action":"begin","frame":0}
{"event":"resource","id":"ram_texture","kind":"texture","memory":"ram","size_mb":32}
{"event":"resource","id":"vram_texture","kind":"texture","memory":"vram","size_mb":32}
{"event":"operation","id":"upload_tex","operation_type":"upload","source":"ram_texture","target":"vram_texture","queue":"copy","cost_ms":0.4,"size_mb":32}
{"event":"frame","action":"end","frame":0}
{"event":"session","action":"end"}
```

`runtime run-adapter` runs this lifecycle stream locally and writes a session
report with per-frame operation counts, per-frame decisions, released resources,
and the underlying control-plane snapshot. The local TCP server also accepts the
same lifecycle events, so the same JSONL shape can be tested offline or over the
runtime socket.

## Frame Policy Engine

The v0.10 policy engine starts turning the adapter stream into management
decisions at frame scope. A session can declare a target frame budget and
RAM/VRAM budgets:

```jsonl
{"event":"session","action":"begin","id":"policy-demo","budgets":{"frame_ms":8,"ram_mb":64,"vram_mb":72}}
{"event":"frame","action":"begin","frame":0}
```

While the frame runs, FluidGateway tracks active resource residency, transfer
volume, queue cost, and estimated frame work. It can emit policy actions such
as:

- `late-upload-pressure`: a copy/upload consumes too much of the active frame budget;
- `vram-budget-pressure` or `ram-budget-pressure`: active residency exceeds the declared budget;
- `frame-budget-pressure`: submitted work exceeds the target frame budget;
- `queue-imbalance-pressure`: one queue dominates frame time while other queues also carry work.

These actions are advisory in v0.10, but they are the first runtime-management
layer above individual copy/sync/buffer decisions. This is the path toward a
software scheduler that reduces late work, redundant memory traffic, and wasted
CPU/GPU/RAM/VRAM movement before it becomes stutter.

## Resource Lifetime Planner

The v0.11 lifetime planner converts adapter activity into an advisory
RAM/VRAM residency plan. It observes registered resources, copy/upload
operations, frame use, and release events, then emits concrete plan actions:

- `keep-resident`: keep frame-critical VRAM textures/buffers resident instead of re-uploading them late;
- `release-after-frame`: release transient staging/scratch buffers after their last observed frame use;
- `prefetch-before-frame`: schedule large uploads before frame-critical draw/compute work;
- `defer-upload`: delay transfers that are not proven necessary for the active frame.

The plan reports estimated transfer volume that could move out of the critical
frame path and memory that can be released earlier. In v0.11 this is still an
advisory planner, not a driver-level allocator. Its purpose is to turn detected
pressure into a concrete set of residency, release, and prefetch intents that a
future engine plugin, API hook, or scheduler can enforce.

## Scheduler Simulator

The v0.12 scheduler simulator turns the lifetime plan into an ordered frame
schedule. It groups work into phases:

- `prefetch`: large uploads/copies moved before frame-critical work;
- `prepare`: frame-local setup that still has to happen before rendering;
- `critical`: draw, compute, and present work on the active frame path;
- `cleanup`: release-after-frame memory actions.

The simulator reports critical-path cost before and after scheduling, moved
transfer volume, budget status per frame, and the ordered steps. This does not
execute graphics API calls yet, but it lets FluidGateway test whether a planned
RAM/VRAM residency and prefetch strategy would shorten the frame's hot path
before building a real scheduler or engine adapter.

## Enforcement Contract

The v0.13 enforcement contract translates the simulated schedule into adapter
commands:

- `prefetch_now`: execute this transfer before frame-critical work;
- `execute_now`: keep this operation on the active frame path;
- `release_after_frame`: release transient memory after the frame consumes it.

This is still advisory user-space output, but it is shaped like the contract a
real engine plugin or API adapter would consume. The scheduler decides the
better order; the enforcement contract says what an integration should do next.

## Live Command Endpoint

The v0.14 live command contract adds an immediate command to each streamed
operation response. Instead of waiting for `session end`, an adapter can submit
an operation intent and receive one of:

- `execute_now`: run the operation on the current frame path;
- `prefetch_now`: move a large copy/upload before frame-critical work;
- `defer`: do not execute redundant or removed work now;
- `reuse`: reuse an existing transient/buffer result.

This is the first runtime-facing command loop in FluidGateway. It still runs in
safe user space, but the protocol now answers the question a real integration
needs to ask at operation time: "what should I do with this CPU/GPU/RAM/VRAM
work right now?"

## Live State Snapshot

The v0.15 live state snapshot lets an adapter inspect the active session while
events are still streaming. Every successful lifecycle/resource/operation
response includes a `state_snapshot`, and an integration can explicitly ask for
one with:

```jsonl
{"event":"state","action":"snapshot"}
```

The snapshot reports the open frame, frames observed, active RAM/VRAM residency,
queue costs, current-frame transfer volume, decisions, policy actions, and live
commands emitted so far. This makes the local runtime endpoint closer to the
future gateway: an engine adapter can ask not only "what should I do with this
operation?", but also "what does FluidGateway currently believe about the frame,
memory pressure, and queued work?"

## Live Policy Loop

The v0.16 live policy loop turns the state snapshot into immediate management
directives. While events are streaming, FluidGateway can now emit
`policy_loop_directives` such as:

- `prefetch-before-critical-path`: move a large transfer before draw-critical work;
- `drain-copy-queue-before-draw`: stop copy queue pressure from landing late in the frame;
- `protect-frame-budget`: defer non-critical work when the frame is close to budget;
- `reduce-memory-residency`: release or avoid duplicate RAM/VRAM residency when a budget is exceeded.

This still does not hook drivers or games. It is the next user-space contract
for the future scheduler: live telemetry in, actionable CPU/GPU/RAM/VRAM
management intent out.

## Adaptive Execution Gate

The v0.17 adaptive execution gate turns live commands and policy-loop
directives into an operation-level decision. Each operation response now
includes an `execution_gate` with an action, preferred phase, and whether the
adapter should execute the work now:

- `execute_now`: keep required critical work moving;
- `prestage_before_draw`: run predictable transfers before draw-critical work;
- `defer_redundant_work`: skip work the control plane already proved redundant;
- `reuse_existing_resource`: reuse an existing transient allocation or resource;
- `hold_noncritical_work`: keep late non-critical work out of a hot frame.

This is still a safe prototype contract, not a game hook. Its purpose is to
make the future scheduler's shape concrete: operation intent comes in, current
frame/memory/queue state is considered, and a gate decision comes out before an
engine integration commits the work.

## Adaptive Admission Controller

The v0.18 admission controller aggregates execution gates into an applied queue
view. Each operation response includes an `admission_decision`, and the final
adapter/session output includes an `admission_plan` that summarizes:

- hot-path work admitted into the current frame;
- transfer work prestaged before draw-critical work;
- redundant work rejected before execution;
- transient/resource reuse;
- non-critical work held for a later frame;
- estimated cost and MB shifted or avoided.

This is the first controller-shaped layer above individual operation gates. It
does not just say what one operation should do; it reports how the runtime queue
would be reshaped to reduce CPU/GPU/RAM/VRAM traffic on the hot frame path.

## Frame Efficiency Ledger

The v0.19 efficiency ledger turns the admission plan into a measured efficiency
view. Each operation response includes an `efficiency_impact`, and the final
session/client output includes an `efficiency_ledger` with:

- hot-path cost that still has to execute;
- transfer or setup cost shifted out of the hot path;
- redundant or reusable work avoided;
- non-critical work held for a later frame;
- total MB of transfer or allocation relief;
- an efficiency score based on managed work shifted or avoided.

This makes the prototype measurable: FluidGateway can now say not only what it
would do, but how much frame-path pressure and memory traffic it believes the
management loop removed or moved earlier.

## Adaptive Feedback Controller

The v0.20 feedback controller closes the loop from measurement back into the
next frame. It reads the `efficiency_ledger`, frame targets, and managed
transfer pressure, then emits a `feedback_plan` with:

- suggested copy-queue budget for the next frame;
- suggested prefetch window size;
- hot-path headroom;
- actions such as `preserve-prefetch-window`, `maintain-reuse-dedupe`, and
  `cap-copy-queue`.

This gives the future scheduler a practical feedback signal: after FluidGateway
measures how much work was shifted or avoided, it can recommend how to shape the
next frame's CPU/GPU/RAM/VRAM work before the same waste appears again.

## Adaptive Actuation Plan

The v0.21 actuation plan turns that feedback into a small command packet for a
future runtime adapter. It does not hook a game or driver yet; it translates the
`feedback_plan` into explicit `actuation_plan` commands such as:

- `reserve_prefetch_window`;
- `set_copy_queue_budget`;
- `enable_reuse_dedupe`;
- `protect_hot_path_headroom`.

This is the first place where the project stops saying only "what looks wasteful"
and starts expressing what a scheduler could actually apply on the next frame.
The current commands are still advisory and serialized as JSON so they can be
tested safely before any lower-level integration exists.

## Memory Transit Map

The v0.22 memory transit map makes RAM/VRAM/display movement explicit. Adapter
and client summaries now include a `memory_transit_map` that turns operation
results into per-hop paths such as `ram->vram`, `vram->swapchain`, and
`sync->graphics`.

For each hop, FluidGateway records:

- source and target memory layer;
- operation type, queue, frame, size, and cost;
- whether the hop executed or was avoided by a runtime decision;
- classification such as `cross-memory-transfer`, `duplicate-transfer`,
  `same-layer-aliased-copy`, or `orphan-sync`.

The map also aggregates attempted, executed, and avoided MB per path. This gives
the project a concrete vocabulary for the core mission: find the useless
transport between CPU, GPU, RAM, VRAM, staging buffers, swapchain, and display
before a future scheduler tries to remove it.

## Memory Route Plan

The v0.23 memory route plan turns the transit map into routing directives. A
`memory_route_plan` now appears in adapter and client summaries with actions
such as:

- `suppress_redundant_hop` for duplicate transfers, aliased same-layer copies,
  and self-transfers;
- `remove_sync_wait` for synchronization that no longer gates useful work;
- `prestage_cross_memory_transfer` for large RAM/VRAM movement that should move
  before draw-critical work;
- `pool_transient_allocation` for reusable allocation shapes;
- `protect_presentation_route` for final frame paths that should stay
  predictable.

This is still an advisory software contract, but it is closer to the intended
gateway: telemetry becomes a map, the map becomes route decisions, and those
decisions become something a scheduler or engine adapter can apply.

## Frame Window Plan

The v0.24 frame window plan places route directives into execution windows. The
`frame_window_plan` answers the next scheduler question: when should each route
decision happen relative to the frame?

Current windows are:

- `never`: suppress redundant transfers, reuse duplicate allocations, or remove
  useless sync waits;
- `pre-frame`: prestage large cross-memory movement before draw-critical work;
- `setup`: prepare reusable pools before the hot path;
- `hot-path`: protect final presentation-facing operations;
- `post-present`: reserved for cleanup after the frame is presented.

This is the first explicit timing contract in the runtime prototype. It does not
execute work yet, but it gives an engine adapter a stable schedule-shaped packet
instead of loose recommendations.

## Execution Packet

The v0.25 execution packet turns frame windows into ordered adapter commands.
Adapter and client summaries now include an `execution_packet` with command
actions such as:

- `skip_transfer`;
- `reuse_allocation`;
- `drop_sync_wait`;
- `prestage_transfer`;
- `pool_allocation`;
- `execute_protected`.

This packet is still advisory, but it is the closest v0 shape to a real runtime
contract: a consuming engine adapter can read ordered commands, apply the
`never` and `pre-frame` choices first, then let protected hot-path work proceed.

## Execution Simulation

The v0.26 execution simulation consumes the `execution_packet` and estimates the
frame effect of applying it. The `execution_simulation` reports:

- commands applied versus ignored;
- removed cost from skipped transfers, reused allocations, and dropped sync waits;
- prestaged cost moved before the frame;
- setup cost moved out of the hot path;
- protected hot-path cost that still has to run;
- hot-path before/after estimates per frame.

This does not execute game or driver work yet. It is a deterministic software
simulation that proves the runtime packet can be evaluated as a scheduler would:
what disappeared, what moved earlier, what stayed hot, and how much useful work
remains on the frame path.

## Adaptive Executor Loop

The v0.27 adaptive executor loop compares `execution_simulation` results against
the frame target. It emits an `adaptive_executor_loop` that reports whether each
frame is within budget or over budget, then recommends how aggressive the next
packet should be.

When the simulated hot path is still too expensive, the loop can emit directives
such as:

- `tighten-hot-path-admission`;
- `expand-pre-frame-window`;
- `split-protected-hot-path`;
- `keep-suppression-active`.

When the frame is within budget, it can preserve the current packet shape with
directives such as `preserve-pre-frame-window`, `maintain-suppression-cache`, and
`hold-current-packet`.

## Runtime Budget Envelope

The v0.28 runtime budget envelope turns the adaptive loop into explicit next
cycle constraints. Adapter and client summaries now include a `budget_envelope`
with:

- next-frame policy;
- per-frame hot-path, copy-queue, and pre-frame budgets;
- admission policy for protected work;
- memory policy for RAM, VRAM, shared memory, staging, and swapchain layers;
- active residency, configured budget, headroom, and pressure per memory layer.

This is still a software-side contract, not a driver hook. Its purpose is to
make the runtime behave more like a small governor: it can decide when to
tighten hot-path admission, when to stop late copies, and when RAM/VRAM
residency pressure should force eviction or deferral.

## Runtime Budget Arbiter

The v0.29 runtime budget arbiter consumes the `execution_packet` and
`budget_envelope` and produces `budget_arbitration`: a command-by-command
decision plan for the next runtime cycle.

It can:

- prestage predictable transfers before the frame;
- drop work already classified as redundant waste;
- admit protected hot-path work while it fits the envelope;
- split or defer hot-path work that exceeds the frame budget;
- request memory actions when RAM, VRAM, staging, shared, or swapchain residency
  is near or over budget.

This is the first v0 layer that behaves like a scheduler/manager instead of only
describing pressure. It still emits a JSON contract, but the contract now says
which operations should move, stop, enter the hot path, or be pushed out.

## Runtime Dispatch Plan

The v0.30 runtime dispatch plan turns `budget_arbitration` into an ordered
runtime-facing queue. Adapter and client summaries now include `dispatch_plan`
commands grouped by phase:

- `control`: drop redundant work before it reaches the runtime path;
- `memory`: evict, reserve, or defer residency when RAM/VRAM/swapchain pressure
  is too high;
- `pre-frame`: run predictable transfers before draw-critical work;
- `hot-path`: execute protected work that fits the budget envelope;
- `next-frame`: defer or split work that would overrun the current frame.

This is still a contract, not a kernel scheduler. But it is now shaped like an
adapter execution queue: a future native layer can consume it phase by phase
instead of reinterpreting diagnostics.

## Dispatch Execution Dry Run

The v0.31 dispatch execution dry run consumes `dispatch_plan` and emits
`dispatch_execution`: a phase-by-phase report of what the runtime would apply,
schedule, defer, or remove.

It reports:

- cost that remains on the current frame;
- cost moved to pre-frame work;
- redundant cost removed before execution;
- hot-path cost deferred or split into a later frame;
- RAM/VRAM/swapchain residency pressure that memory commands are expected to
  relieve.

This is still dry-run execution, but it closes the loop from detection to an
ordered queue and then to an applied effect model. It is the clearest v0 bridge
between a diagnostic tool and a future runtime manager.

## Runtime Calibration Report

The v0.32 runtime calibration report consumes `dispatch_execution` plus observed
frame stats and emits `runtime_calibration`: a next-cycle feedback report.

It compares:

- observed frame cost before runtime intervention;
- planned current-frame cost after dispatch execution;
- cost moved to pre-frame work;
- cost deferred or split out of the current frame;
- redundant cost removed before execution;
- RAM/VRAM/swapchain pressure expected to be relieved.

The report then proposes a guardband and an action such as
`apply-dispatch-before-next-frame`, `tighten-dispatch-guardband`,
`preserve-dispatch-shape`, or `monitor`.

This still does not hook drivers or games. It gives the future manager a
measured control loop: observe the frame, simulate dispatch, calibrate the next
budget, and keep evidence attached to every decision.

## Runtime Manager Directive

The v0.33 runtime manager directive consumes `runtime_calibration` and
`budget_envelope` and emits `runtime_manager`: the first closed-loop control
contract for the next runtime cycle.

It turns evidence into manager-facing directives:

- next-frame budget after guardband;
- hot-path budget for protected draw/present work;
- copy-queue budget for late transfers;
- pre-frame window for predictable RAM/VRAM traffic;
- admission mode for current-frame work;
- scheduler mode for aggressive or stable control;
- per-layer memory actions for RAM, VRAM, shared, staging, and swapchain
  residency.

This is still not a driver hook or OS scheduler. It is the software-side shape
of the manager FluidGateway is growing toward: measure waste, decide what should
move, calibrate the result, and emit a concrete next-cycle control directive.

## Runtime Control Packet

The v0.34 runtime control packet consumes `runtime_manager` and emits
`runtime_control_packet`: an ordered command packet for a future native runtime
or engine adapter.

It serializes manager decisions into explicit control commands:

- set the next-frame budget;
- set the protected hot-path budget;
- set the copy-queue budget;
- reserve the pre-frame work window;
- set the admission mode;
- set the scheduler mode;
- hold, observe, reserve, evict, or defer memory residency per RAM/VRAM/shared/
  staging/swapchain layer.

The packet is still advisory. It does not mutate a process, hook a game, or call
a driver. Its value is that the manager output is now shaped like a concrete
runtime command stream rather than prose or loose recommendations.

## Runtime Control State Dry Run

The v0.35 runtime control state consumes `runtime_control_packet` and emits
`runtime_control_state`: a dry-run view of what the next runtime state would look
like if those packet commands were applied by an engine adapter or native
runtime.

It consolidates the command stream into:

- per-frame next-frame, hot-path, copy-queue, and pre-frame budgets;
- per-frame admission and scheduler modes;
- active versus observational memory commands for RAM, VRAM, shared, staging,
  and swapchain layers;
- expected memory relief and reserved headroom by layer;
- counts for applied frame budgets, queue budgets, scheduler modes, and memory
  actions.

This is still advisory and non-mutating. It is the first bridge from "ordered
commands" to "manager state": the shape a future scheduler, game plugin, or
native service could use to reduce friction between CPU, GPU, RAM, VRAM, queues,
buffers, and frame presentation.

## Runtime Gateway Tick

The v0.36 runtime gateway tick consumes `runtime_control_state` and emits
`runtime_gateway_tick`: a simulated management cycle organized by runtime lanes.

It turns consolidated control state into lane-level work:

- display-frame budget protection;
- GPU hot-path budget protection;
- copy-queue gating or budgeting;
- CPU pre-frame window reservation;
- CPU admission mode application;
- scheduler mode application;
- RAM/VRAM/shared/staging/swapchain memory residency actions.

This is still a dry run. It does not schedule OS threads, mutate game memory, or
call a graphics driver. Its purpose is to make the future manager loop explicit:
one tick receives evidence-backed state, protects the hot path, budgets copy
traffic, gates late work, and plans memory pressure relief before the next frame.

## Runtime Gateway Cycle Report

The v0.37 runtime gateway cycle consumes `runtime_gateway_tick` and emits
`runtime_gateway_cycle`: a dry-run execution report for the simulated manager
cycle.

It records what the gateway cycle would have applied or observed:

- protected display-frame and GPU hot-path budget;
- reserved CPU pre-frame window;
- copy-queue budget or late-copy blocking;
- admission and scheduler mode application;
- memory residency relief, headroom reservation, or observation;
- lane-level drift risk and a next-cycle action.

This still does not mutate processes, drivers, graphics APIs, or OS scheduling.
Its job is to close the loop one step further: turn a planned tick into an
auditable cycle result that can be compared with the next observed frame.

## Runtime Gateway Feedback Delta

The v0.38 runtime gateway feedback delta consumes `runtime_gateway_cycle` and
`runtime_calibration`, then emits `runtime_gateway_feedback`: the first closed
feedback signal between a simulated gateway cycle and observed frame evidence.

It compares:

- observed frame cost against the target frame budget;
- planned current-frame cost after dispatch execution;
- next-frame and GPU hot-path budgets protected by the gateway;
- protected budget gaps that still need pressure management;
- expected memory relief against relief applied by the cycle;
- headroom reservations and observed-only memory lanes.

The output proposes a next feedback action such as
`continue-pressure-management`, `tighten-cycle-guardband`,
`preserve-cycle-shape`, `monitor-headroom`, or `maintain-cycle`.

This still does not control OS scheduling or GPU drivers. It makes the control
loop auditable: observe, plan, simulate a gateway cycle, compare against frame
evidence, and choose the next pressure-management posture.

## Runtime Policy Update

The v0.39 runtime policy update consumes `runtime_gateway_feedback` and emits
`runtime_policy_update`: an advisory policy proposal for the next gateway cycle.

It turns feedback into concrete next-cycle knobs:

- next-frame and GPU hot-path budgets;
- copy-queue budget or blocking posture;
- pre-frame window size;
- admission and scheduler policy;
- memory relief targets or headroom reservation;
- next profile, such as `aggressive` or `stable`.

This still does not rewrite OS scheduling, driver state, or game memory. It is
the first explicit updater in the loop: evidence becomes feedback, feedback
becomes policy, and policy becomes the next manager input shape.

## Runtime State Accumulator

The v0.40 runtime state accumulator consumes `runtime_policy_update` and emits
`runtime_state_accumulator`: a deterministic operational memory for the next
gateway cycle.

It carries forward:

- current runtime profile and policy action;
- accumulated cycle count;
- frame budget, hot-path, copy-queue, and pre-frame window state;
- frame admission and scheduler policy;
- memory residency action, relief target, and headroom target;
- active policy count and a stable state digest for automation.

This still does not hook games, rewrite GPU queues, or change RAM/VRAM
residency. It creates the stateful contract needed before a future runtime
manager can compare the previous cycle against the next one and decide what to
preserve, tighten, defer, or release.

## Runtime State Persistence

The v0.41 runtime state persistence path lets `runtime run-adapter` load a
previous `runtime_state_accumulator` JSON and write the next one:

```powershell
python -m fluidgateway runtime run-adapter `
  --events tests/fixtures/adapter_budget_pressure_events.jsonl `
  --state-in tmp/runtime-state.json `
  --state-out tmp/runtime-state.json `
  --out tmp/adapter-session.json
```

If `--state-in` points to a missing file, FluidGateway starts a fresh cycle. If
the file exists but is not a supported accumulator JSON, the command fails
instead of silently corrupting the runtime memory.

This is still an offline advisory loop. It is the first persisted bridge
between runs: a future manager can now compare previous cycle pressure against
new CPU/GPU/RAM/VRAM evidence instead of treating each replay as isolated.

## Runtime State Transition

The v0.42 runtime state transition consumes the previous
`runtime_state_accumulator` and the newly produced accumulator, then emits
`runtime_state_transition`.

It reports:

- whether this is a baseline or a resumed cycle;
- previous and current cycle counts;
- a pressure index for the previous and current states;
- pressure delta and trend: `baseline`, `improving`, `worsening`, or `stable`;
- transitions for profile, policy, convergence, drift, frame budget, copy
  budget, pre-frame window, memory relief, and memory headroom;
- a next advisory action such as `relax-after-pressure-relief`,
  `tighten-after-pressure-regression`, or `preserve-runtime-state`.

This gives the persisted runtime memory a first interpretation layer. It still
does not schedule OS threads or GPU queues, but it can now tell whether the
advisory gateway loop is moving toward less pressure or drifting back into
waste.

## Runtime Supervisor Directive

The v0.43 runtime supervisor directive consumes `runtime_state_accumulator` and
`runtime_state_transition`, then emits `runtime_supervisor_directive`.

It translates trend into a next-cycle posture:

- `establish-supervisor-baseline` for a first persisted cycle;
- `relax-supervisor-pressure` when pressure is improving and the state is
  stable;
- `hold-recovery-supervision` when pressure is improving but the runtime is
  still aggressive;
- `escalate-supervisor-pressure` when pressure regresses;
- `preserve-supervisor-state` or `monitor-supervisor-state` when pressure is
  mostly unchanged.

The directive carries scheduler, admission, memory, frame-budget, copy-queue,
pre-frame, and guardband posture. This is still not a kernel scheduler, driver
hook, or game injection layer. It is the first explicit management translation:
persisted runtime evidence becomes a supervised next-cycle posture.

## Runtime Supervisor Plan

The v0.44 runtime supervisor plan consumes `runtime_supervisor_directive` and
emits `runtime_supervisor_plan`: a structured command list for the next
advisory cycle.

The plan currently emits one command per domain:

- `scheduler`
- `admission`
- `memory`
- `frame-budget`
- `guardband`

Each command has an id, phase, action, target, budget or memory target, blocking
flag, and reason. The plan also summarizes command counts, blocking commands,
escalation level, cooldown cycles, and confidence.

This still does not execute OS scheduling or GPU queue changes. It is the first
bridge from supervisor posture to command-shaped work that a future daemon,
native scheduler, or engine adapter could consume.

## Runtime Supervisor Execution Dry-Run

The v0.45 runtime supervisor execution consumes `runtime_supervisor_plan` and
emits `runtime_supervisor_execution`: a dry-run result for the command-shaped
next-cycle work.

It reports:

- execution action for the plan;
- whether the path is a dry-run;
- `would_modify_system=false`;
- `execution_guard=advisory-only`;
- command executions with `would_apply`, `would_block`, simulated budget, memory
  target, effect, and reason;
- summary counts for scheduler, admission, memory, frame-budget, and guardband
  executions.

This still does not mutate CPU scheduling, GPU queues, RAM, VRAM, or game
state. It creates the execution boundary that a future daemon/native backend
can replace while keeping the same evidence trail.

## Runtime Daemon Dry-Run Loop

The v0.58 runtime daemon dry-run loop repeats adapter event streams while
carrying `runtime_state_accumulator` across cycles and attaching a read-only
`host_snapshot`, a `daemon_decision_plan`, a `daemon_action_queue`, and a
`daemon_action_execution` report, plus a `native_backend_preflight` contract
and a `daemon_arbitration_plan`, a `daemon_control_plan`, and a
`daemon_control_execution` report, followed by a `native_backend_manifest` and
`native_backend_probe`, then a `native_backend_readiness` assessment and a
`native_backend_gate` promotion decision:

```powershell
python -m fluidgateway runtime run-daemon `
  --events tests/fixtures/adapter_budget_pressure_events.jsonl `
  --events tests/fixtures/adapter_state_query_events.jsonl `
  --state tmp/runtime-daemon-state.json `
  --out tmp/runtime-daemon-report.json
```

`--events` can be repeated to model different cycles. `--iterations` sets the
minimum cycle count; if it is larger than the number of supplied event streams,
the last stream repeats. `--state` is required: FluidGateway loads it as the
previous runtime memory when present and overwrites it with the final daemon
state after the loop. `--state` and `--out` must resolve to different JSON
paths.

The daemon report includes:

- `dry_run=true`;
- `would_modify_system=false`;
- `execution_guard=advisory-only`;
- per-cycle transition trend, supervisor action, plan action, execution action,
  apply/block counts, and state digest;
- host CPU/RAM/GPU/VRAM capability evidence when the local OS exposes it;
- `host_profile` and `host_manager_hint` for a future manager loop;
- `daemon_decision_plan` with next-cycle advisory decisions such as
  `collect-host-telemetry`, `tighten-memory-residency-observation`,
  `allow-daemon-supervisor-loop`, and `hold-blocking-supervisor-commands`;
- `daemon_action_queue`, which maps decisions to backend-shaped actions with
  dry-run status, required native backend, required privilege, expected signal,
  and safety boundary;
- `daemon_action_execution`, which evaluates queued work under the
  advisory-only guard: read-only telemetry and advisory loop actions are marked
  as executed in dry-run, while native or privileged actions are blocked before
  system mutation;
- `native_backend_preflight`, which turns each queued action into explicit
  backend capability requirements, native backend blockers, privilege
  blockers, safety-review blockers, and native-promotion status;
- `daemon_arbitration_plan`, which ranks advisory lanes across telemetry,
  memory, GPU, scheduler, and safety using pressure score, preflight blockers,
  and execution readiness;
- `daemon_control_plan`, which converts ranked lanes into control intents for
  telemetry, scheduler, safety, GPU, RAM, and VRAM surfaces with backend
  requirements, readiness, blockers, and expected signals;
- `daemon_control_execution`, which evaluates those control intents in dry-run:
  read-only and advisory surfaces are executed as simulated control steps,
  while native control surfaces remain blocked before host mutation;
- `native_backend_manifest`, which declares which backend surface would satisfy
  each control execution step, whether the backend is read-only/advisory/native,
  whether it is loaded or held, and which privilege, safety-review, or native
  backend blockers still prevent promotion;
- `native_backend_probe`, which binds manifest-approved read-only/advisory
  surfaces to existing host/daemon evidence, reports CPU/RAM/GPU/VRAM signal
  counts, and blocks read-only probing when no host snapshot exists;
- `native_backend_readiness`, which scores whether the safe evidence is enough
  for continued observation/advisory looping, whether more read-only evidence is
  required, or whether native control remains blocked by backend, privilege, and
  safety-review requirements;
- `native_backend_gate`, which turns readiness into an explicit promotion gate:
  read-only observation and advisory loops may continue, while native CPU/GPU,
  RAM, VRAM, scheduler, or host-control promotion remains blocked;
- final accumulated runtime state for the next loop.

This is still a local advisory loop. It does not run as a background service,
change OS process scheduling, mutate GPU queues, pin RAM/VRAM, inject into a
game, or touch drivers. Host probing is observational: on Windows it uses
read-only memory status and video-controller metadata. The decision plan is
also dry-run: it promotes evidence into manager-shaped intent without applying
that intent to the host. The action queue, action execution, native backend
preflight, daemon arbitration, daemon control, and control execution layers are
the next bridge: read-only telemetry actions can be queued and evaluated as
dry-run work, while anything that would require native memory, scheduler, GPU,
VRAM, or privileged host control is explicitly blocked before system mutation
and annotated with the missing backend requirements. The arbitration plan
decides which lane should advance first under the advisory guard; the control
plan maps that lane to the actual system surface a future backend would need to
control; the control execution report shows the simulated outcome; the native
backend manifest turns that outcome into an explicit load/hold contract for the
future backend; the native backend probe binds safe surfaces to existing
evidence; the native backend readiness report converts that evidence into a
conservative readiness and risk policy; the native backend gate converts that
policy into an explicit allow/block decision for the next safe loop. Native
promotion remains `false` in v0.58. This is the first durable loop shape that a
future native manager can replace behind the same JSON contract.

## Supported Input

FluidGateway v0 expects a PresentMon 2.x CSV. It works best when these columns
are available:

- `Application`
- `PresentRuntime`
- `PresentMode`
- `SyncInterval`
- `AllowsTearing`
- `MsCPUBusy`
- `MsCPUWait`
- `MsGPULatency`
- `MsGPUTime`
- `MsGPUBusy`
- `MsGPUWait`
- `DisplayLatency`
- `DisplayedTime`
- `MsAnimationError`
- `MsBetweenPresents`
- `MsInPresentAPI`
- `MsUntilDisplayed`
- `MsRenderPresentLatency`

Missing columns reduce finding confidence but do not fail the analysis.

## Findings

The v0 engine looks for:

- suspicious presentation copy paths;
- excessive presentation/display latency;
- CPU wait or time spent inside `Present()`;
- GPU bubbles or underfeeding;
- unstable frame pacing;
- frames that appear not to reach display;
- composition-related waste patterns.

Every finding is an inference with numerical evidence, not proof of an internal
driver or engine cause.

## Development

```powershell
python -m unittest
python -m fluidgateway analyze --presentmon tests/fixtures/copy_present.csv --out tmp/report.html
```

## License

MIT.
