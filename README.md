<p align="center"><img src="docs/assets/fluidgateway-readme.gif" alt="FluidGateway frame-pipeline visualization" width="960"></p>

# FluidGateway

**Find probable waste across CPU, GPU, RAM, VRAM, graphics resources, and frame presentation, then turn narrow evidence into fail-closed runtime decisions.**

[![CI](https://github.com/maxhuntert1414-max/FluidGateway/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/maxhuntert1414-max/FluidGateway/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.13-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![C++](https://img.shields.io/badge/online_core-C%2B%2B20-00599c)](docs/native-gateway.md)
[![Version](https://img.shields.io/badge/version-0.69.0-ef6c35)](pyproject.toml)
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
| Native online server | C++20, no Python dependency, bounded state and loopback IPC |
| In-process backend | Opt-in C ABI DLL, same C++ core, no localhost round trip |
| Local readiness | `doctor` reports available and blocked capabilities without changing system settings |
| Native intervention | Bounded owned D3D11, D3D12 and cooperative Vulkan paths through [FluidRuntime](https://github.com/maxhuntert1414-max/FluidRuntime) |
| Readback authorization | Runtime's owned GPU-to-staging path uses the same server/DLL core and existing Copy opcode |
| Application-session diagnosis | HTML/JSON import of Runtime Vulkan resource hooks, memory-path counters and Windows priority-lease evidence |
| General game optimizer, driver hooks, global scheduler | Not implemented |

The native server moves continuous decisions into C++20 while Python remains
the offline analysis and reporting tool. Existing binary contracts and Runtime
authority gates are preserved. The [v0.68 validation results](docs/release-v0.68.0.md)
include a completed 60-minute soak and 30 paired Runtime authorizations.
See [native usage, limits and verification](docs/native-gateway.md).
The [in-process backend](docs/inprocess-gateway.md) removes socket transport when
explicitly selected; the isolated server remains available and is still the default.

Current `main` also diagnoses opt-in third-party Vulkan sessions from Runtime
v0.23. [Application sessions](docs/application-sessions.md) collect CPU/RAM and
API counters; optional Windows priority changes require explicit bounded consent.
The cooperative GPU library remains separate: external copies are never removed.

This is protocol, owned-lab and scoped observation evidence. It is not proof of higher game FPS,
lower power, physical RAM/VRAM placement, or reduced PCIe traffic.

## Quick Start

Offline diagnostics require Python 3.10 or newer. The CLI has no third-party runtime
dependencies.

```powershell
git clone https://github.com/maxhuntert1414-max/FluidGateway.git
cd FluidGateway

python -m unittest
python -m fluidgateway doctor --out tmp/doctor.json
python -m fluidgateway analyze `
  --presentmon tests/fixtures/copy_present.csv `
  --out tmp/report.html
```

Analyze one application/process/swapchain at a time. Mixed streams are rejected;
filter the source CSV before interpreting frame timing.

Outputs:

- `tmp/report.html`: ranked, readable diagnostic report
- `tmp/report.json`: the same evidence as structured data

Run the native decision server from the Windows x64 release package:

```powershell
.\fluidgateway-native.exe serve-events --host 127.0.0.1 --port 8765
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

The local server is not a privilege boundary: it accepts loopback clients and
returns decisions, while trusted FluidRuntime clients independently pin the
expected server PID and executable hash. Run it only in a trusted user session.

## Read More

- [Code review, fixes and remaining limits](docs/code-review-2026-09-05.md)
- [Native C++20 gateway](docs/native-gateway.md)
- [Technical reference](docs/technical-reference.md)
- [Application-session reports](docs/application-sessions.md)
- [v0.68.0 release and measured results](docs/release-v0.68.0.md)
- [FluidLink v2 base protocol](docs/fluidlink-v2.md)
- [FluidLink v2 operation-batch profile](docs/fluidlink-v2-batch.md)
- [Canonical contracts and golden vectors](contracts)
- [FluidRuntime v0.21 transfer evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/v0.21.0/docs/evidence/v0.21.0-d3d12-transfer-core.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

MIT licensed. Experimental, evidence-first, and intentionally narrow wherever
the project has authority to alter execution.
