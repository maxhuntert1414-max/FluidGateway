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
optimize anything automatically. It ingests PresentMon 2.x CSV data and
produces a ranked report of likely waste patterns with evidence.

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
