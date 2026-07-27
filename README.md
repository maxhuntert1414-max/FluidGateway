<div align="center">

# FluidGateway

**An evidence-driven gateway for finding and reducing wasted work across CPU,
GPU, RAM, VRAM, graphics resources, and frame presentation.**

*The future of performance is not only more power. It is less waste.*

[![CI](https://github.com/maxhuntert1414-max/FluidGateway/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/maxhuntert1414-max/FluidGateway/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.13-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/badge/License-MIT-2ea44f)](LICENSE)
[![FluidRuntime](https://img.shields.io/badge/FluidRuntime-v0.11.0-6f42c1)](https://github.com/maxhuntert1414-max/FluidRuntime/releases/tag/v0.11.0)

[Quick Start](#quick-start) | [Evidence](#measured-actuation) |
[Architecture](#architecture) | [Roadmap](#roadmap) |
[Contributing](CONTRIBUTING.md)

</div>

## Why FluidGateway

Traditional PCs cannot reproduce physically unified memory through software.
They can still waste less.

FluidGateway explores how early, evidence-based decisions can reduce redundant
copies, late synchronization, buffer churn, unnecessary memory transit, and
poor frame-pipeline coordination. The project deliberately separates diagnosis,
policy, observation, and actuation so each layer can be tested and rolled back.

The public promise today is precise:

> Find probable waste in the frame path, turn it into structured policy, and
> prove narrowly scoped interventions before expanding their authority.

## Project At A Glance

| Component | Role | Current state |
| --- | --- | --- |
| **FluidGateway v0.62.0** | PresentMon analysis, policy modeling, runtime protocols, operational ledger | Usable diagnostic CLI; management remains advisory |
| **[FluidRuntime v0.11.0](https://github.com/maxhuntert1414-max/FluidRuntime)** | Windows/GPU telemetry, cooperative D3D11 hook, managed-to-native control | Generic copy, readback, and upload actuation proven in an owned, opt-in laboratory |
| External game integration | Allowlisted observation and future reversible control | Not implemented |
| CPU scheduler and RAM/VRAM residency backends | Deeper system-level efficiency management | Research roadmap |

## See It Working

The report below was generated directly from the bundled PresentMon fixture. It
ranks probable waste, shows numerical evidence, assigns confidence, and proposes
technical next steps without pretending that inference is internal-cause proof.

![FluidGateway HTML report with ranked frame-pipeline findings](docs/assets/report-preview.png)

## Capabilities Today

| Capability | Output | Authority |
| --- | --- | --- |
| Tolerant PresentMon 2.x ingestion | Parsed frame samples despite `NA`, missing columns, and legacy names | Read-only |
| Ranked waste diagnosis | HTML and JSON findings with severity, confidence, percentiles, and evidence | Read-only |
| Advisory management planning | CPU/GPU handoff, pacing, queue, presentation, and memory recommendations | Dry run |
| Trace tracking | Local history with SHA-256 identity, labels, findings, and policy pressure | Local data only |
| Pipeline optimizer prototype | Removes redundant modeled copies/syncs and reuses modeled transient buffers | Simulation |
| Runtime event protocol | JSONL replay, TCP decision server, lifecycle adapter, persisted manager state | Local prototype |
| PresentMon-to-daemon bridge | Operational ledger and repeated advisory control cycles | Dry run |
| Native copy-path intervention | Bounded D3D11 copy elision through FluidRuntime | Owned target only |
| Native readback intervention | Bounded `DEFAULT -> STAGING + CPU_READ` elision through FluidRuntime | Owned target only |
| Native upload intervention | Bounded `STAGING + CPU_WRITE -> DEFAULT` elision through FluidRuntime | Owned target only |

FluidGateway has no third-party runtime dependencies. The Python v0.62.0 suite
currently contains 199 tests and runs on Python 3.10 and 3.13 in GitHub Actions.

## Measured Actuation

FluidRuntime v0.11.0 proves both API-visible memory directions with separate,
bounded action bits rather than treating every resource copy as the same
operation. The newest evidence covers uploads from a CPU-writable staging
buffer into a default resource.

In an owned D3D11 workload on an AMD Radeon RX 580:

| Signal | Baseline | Optimized |
| --- | ---: | ---: |
| Upload copies observed | 65 | 65 |
| CPU write map/unmap completed | 1 | 1 |
| Upload copies forwarded | 65 | 1 |
| Proven redundant upload copies skipped | 0 | 64 |
| Logical copy traffic avoided | 0 | 268,435,456 bytes |
| CPU submission p95 | 13.397 ms | 12.391 ms |
| GPU timestamp interval p95 | 32.520 ms | 1.734 ms |
| Measured GPU pair wins | 0/10 | 10/10 |

Every measured run retained the staging write and required exact expected,
source, and destination hashes; complete event/snapshot agreement; adapter
identity; valid GPU timestamps; and restored dispatch after detach. All 10 CPU
submission pairs remained inside the declared +1 ms / +10% overhead envelope;
CPU won 6/10, so this is not a CPU-acceleration claim. A 320-process
Release/Debug policy matrix also proved valid, rejected, expired, and no-opt-in
behavior.

This is a deliberately narrow
`owned-d3d11-writable-staging-to-default-upload-copy-workload-only` result.
D3D11 usage classes do not prove physical RAM/VRAM placement, and 256 MiB of
logical removed calls does not mean 256 MiB of physical PCIe traffic. The GPU
number is a timestamp interval around the workload, not a GPU-busy hardware
counter. The
project does **not** claim higher game FPS, lower power, or external-game support
from this experiment.

[Read the evidence and raw traces](https://github.com/maxhuntert1414-max/FluidRuntime/blob/v0.11.0/docs/evidence/v0.11.0-upload-elision.md)

## Architecture

```mermaid
flowchart LR
    PM["PresentMon 2.x trace"] --> FG["FluidGateway diagnosis"]
    FG --> HR["HTML and JSON report"]
    FG --> OL["Operational ledger"]
    OL --> MR["FluidRuntime manager"]
    WT["Windows and GPU telemetry"] --> MR
    MR --> CP["Bounded shared-memory policy"]
    CP --> HK["Owned D3D11 hook"]
    HK --> EV["Events, snapshots, hashes, rollback"]
    EV --> MR
```

The current native arrow is cooperative and opt-in. It does not represent
remote injection, a driver hook, or authorization to touch protected software.

## Quick Start

Requirements: Python 3.10 or newer. The diagnostic CLI uses only the standard
library.

```powershell
git clone https://github.com/maxhuntert1414-max/FluidGateway.git
cd FluidGateway

python -m unittest
python -m fluidgateway analyze `
  --presentmon tests/fixtures/copy_present.csv `
  --out tmp/report.html
```

The analysis writes:

- `tmp/report.html`: visual diagnostic report;
- `tmp/report.json`: the same evidence as structured data.

Generate an advisory management plan:

```powershell
python -m fluidgateway manage `
  --presentmon tests/fixtures/gpu_wait.csv `
  --out tmp/management.json
```

Run the persistent PresentMon-to-manager dry-run bridge:

```powershell
python -m fluidgateway runtime run-presentmon-daemon `
  --presentmon tests/fixtures/gpu_wait.csv `
  --events-out tmp/presentmon-events.jsonl `
  --state tmp/runtime-state.json `
  --out tmp/runtime-daemon.json
```

Use `python -m fluidgateway --help` and
`python -m fluidgateway runtime --help` for the complete command surface.

## Findings

The diagnostic engine looks for:

- suspicious copy/GDI presentation paths;
- excessive display and render-present latency;
- CPU wait and time spent inside `Present()`;
- GPU bubbles or underfeeding;
- unstable frame pacing;
- frames that appear not to reach display;
- composition-related waste.

Missing columns reduce confidence instead of fabricating zeros. Every finding is
an inference supported by numerical evidence, not proof of a hidden engine or
driver cause.

## Design Principles

1. **Evidence before authority.** Observation and equivalence gates come before
   actuation.
2. **Fail closed.** Missing identity, timing, provenance, or rollback evidence
   blocks the claim or action.
3. **Bounded intervention.** Policies have explicit lifetime, scope, budget, and
   target opt-in.
4. **Reversible by construction.** Dispatch and policy authority must return to
   a known state.
5. **Claims match measurements.** GPU workload, CPU time, frame time, FPS, and
   power are different claims.
6. **No anti-cheat bypass.** Protected targets and covert injection are outside
   the project boundary.

## Roadmap

- [x] PresentMon diagnostics with ranked HTML/JSON evidence.
- [x] Advisory CPU/GPU/RAM/VRAM policy and persistent daemon contracts.
- [x] Cooperative D3D11 observation with shared-memory telemetry.
- [x] Bounded managed-to-native copy elision with hardware evidence.
- [x] Direction-specific D3D11 readback elision with per-map equivalence and
  hardware evidence.
- [x] Prototype the API-visible `RAM -> GPU` upload direction in the owned lab.
- [ ] Extend upload provenance to dynamic buffers, `UpdateSubresource`, partial
  regions, reuse, batching, fences, and synchronization.
- [ ] Harden provenance for aliases, shader writes, fences, deferred contexts,
  and synchronization.
- [ ] Add explicit allowlisted external observation for authorized,
  unprotected software.
- [ ] Derive shadow policies from live FluidGateway evidence and promote only
  after regression/rollback gates pass.
- [ ] Build separate CPU scheduling and RAM/VRAM residency backends.
- [ ] Expand observation and control research to D3D12 and Vulkan.

The ambition is large, but promotion is intentionally incremental: owned lab,
reproducible evidence, narrow claim, then the next layer of authority.

## Repository Map

- [`fluidgateway/`](fluidgateway): Python diagnostic, policy, control, and daemon
  implementation.
- [`tests/`](tests): 199 unit and integration tests plus deterministic fixtures.
- [`docs/technical-reference.md`](docs/technical-reference.md): complete v0.62
  protocol and feature history preserved from the original long-form README.
- [`FluidRuntime`](https://github.com/maxhuntert1414-max/FluidRuntime): native
  observation, actuation, evidence, and rollback companion.
- [`FluidRuntime v0.11.0 evidence`](https://github.com/maxhuntert1414-max/FluidRuntime/blob/v0.11.0/docs/evidence/v0.11.0-upload-elision.md): raw policy,
  WARP, and RX 580 upload results.

## Contributing

Contributions are welcome in diagnostics, trace compatibility, conservative
heuristics, telemetry adapters, provenance research, reproducible workloads,
documentation, and tests. Start with [CONTRIBUTING.md](CONTRIBUTING.md), follow
the [Code of Conduct](CODE_OF_CONDUCT.md), and report vulnerabilities according
to [SECURITY.md](SECURITY.md).

## License

FluidGateway is open source under the [MIT License](LICENSE).
