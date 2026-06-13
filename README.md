# FluidGateway

FluidGateway is an open source project for finding and, over time, reducing
unnecessary friction between CPU, GPU, RAM, VRAM, frame buffers, textures, and
presentation.

The long-term goal is an intelligent software gateway/scheduler that shortens
the practical distance between processing stages as much as normal PC software
can. The inspiration is not to clone DLSS, FSR, or Lossless Scaling, but to
borrow the efficiency philosophy of tightly integrated systems such as Apple
Silicon: less redundant movement, fewer late sync points, more useful work per
watt.

The current release does not inject code, hook games, change drivers, or
optimize anything automatically. It ingests PresentMon 2.x CSV data, produces a
ranked report of likely waste patterns with evidence, and includes user-space
runtime prototypes for modeling early CPU/GPU/RAM/VRAM decisions.

> The initial promise is to find probable waste in the frame path, not to
> automatically increase FPS.

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

In v0.2 this is still advisory. The tool generates a management plan that says
which policies a future gateway/scheduler should apply and why. Direct RAM/VRAM
control requires additional telemetry beyond PresentMon.

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
python -m fluidgateway runtime serve-events --host 127.0.0.1 --port 8765
python -m fluidgateway runtime send-events --events runtime-events.jsonl --host 127.0.0.1 --port 8765 --out server-responses.json
python -m fluidgateway runtime run-adapter --events adapter-events.jsonl --out adapter-session.json
```

The command writes:

- `report.html`: human-readable diagnostic report.
- `report.json`: structured report data next to the HTML file.
- `management.json`: advisory management plan when using `manage`.
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
