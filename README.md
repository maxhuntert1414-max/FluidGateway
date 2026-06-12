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
