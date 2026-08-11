<p align="center"><img src="docs/assets/fluidgateway-readme.gif" alt="FluidGateway frame-pipeline visualization" width="960"></p>

# FluidGateway

**Find probable waste across CPU, GPU, RAM, VRAM, graphics resources, and frame presentation, then turn narrow evidence into fail-closed runtime decisions.**

[![CI](https://github.com/maxhuntert1414-max/FluidGateway/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/maxhuntert1414-max/FluidGateway/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.13-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Version](https://img.shields.io/badge/version-0.67.0-ef6c35)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-2ea44f)](LICENSE)

FluidGateway is the diagnostic and decision layer of the Fluid project. The
long-term goal is an intelligent software gateway that reduces avoidable data
movement and synchronization on conventional PCs. Software cannot recreate
physically unified memory, but it can coordinate the path with less waste.

## Current Status

| Capability | State |
| --- | --- |
| PresentMon 2.x diagnosis | Working CLI with HTML and JSON evidence |
| Policy and runtime modeling | Advisory and dry-run by default |
| FluidLink v2 | Strict positional binary IPC with numeric opcodes |
| FluidLink operation batch | 129 logical operations in 1 bounded request/vector pair |
| Local decision server | Loopback-only, 8-worker limit, absolute read deadlines |
| Native intervention | One bounded owned D3D11 path through [FluidRuntime](https://github.com/maxhuntert1414-max/FluidRuntime) |
| External games, driver hooks, general scheduler | Not implemented |

The v0.67 server preserves its eight-connection bound while releasing a slot
before the final `GOODBYE` acknowledgement is sent. This removes a measured
turnover race at concurrency 8 without admitting excess active sessions.
FluidRuntime v0.19 now measures authorization, process startup, native action,
and fallback in one end-to-end window and publishes p50/p95/p99 evidence.

This is protocol and owned-lab evidence. It is not proof of higher game FPS,
lower power, physical RAM/VRAM placement, or reduced PCIe traffic.

## Quick Start

Requires Python 3.10 or newer. The diagnostic CLI has no third-party runtime
dependencies.

```powershell
git clone https://github.com/maxhuntert1414-max/FluidGateway.git
cd FluidGateway

python -m unittest
python -m fluidgateway analyze `
  --presentmon tests/fixtures/copy_present.csv `
  --out tmp/report.html
```

Outputs:

- `tmp/report.html`: ranked, readable diagnostic report
- `tmp/report.json`: the same evidence as structured data

Run the local decision server:

```powershell
python -m fluidgateway runtime serve-events --host 127.0.0.1 --port 8765
```

## Architecture

```text
PresentMon -> diagnosis -> policy/ledger
FluidRuntime intent <-> FluidLink binary IPC <-> FluidGateway decisions
bounded policy -> owned native hook -> evidence and rollback
```

FluidGateway does not inject code, modify drivers, or silently optimize games.
The cooperative native experiments and Windows/GPU telemetry live in
[FluidRuntime](https://github.com/maxhuntert1414-max/FluidRuntime).

## Read More

- [Technical reference](docs/technical-reference.md)
- [FluidLink v2 base protocol](docs/fluidlink-v2.md)
- [FluidLink v2 operation-batch profile](docs/fluidlink-v2-batch.md)
- [Canonical contracts and golden vectors](contracts)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

MIT licensed. Experimental, evidence-first, and intentionally narrow wherever
the project has authority to alter execution.
