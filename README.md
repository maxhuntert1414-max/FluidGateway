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

The v0 release does not inject code, hook games, change drivers, or optimize
anything automatically. It ingests PresentMon 2.x CSV data and produces a
ranked report of likely waste patterns with evidence.

> The initial promise is to find probable waste in the frame path, not to
> automatically increase FPS.

## Quick Start

```powershell
python -m fluidgateway analyze --presentmon trace.csv --out report.html
```

The command writes:

- `report.html`: human-readable diagnostic report.
- `report.json`: structured report data next to the HTML file.

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
