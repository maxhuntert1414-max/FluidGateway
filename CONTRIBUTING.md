# Contributing to FluidGateway

Thank you for helping build a more evidence-driven frame pipeline.

## Development Setup

FluidGateway requires Python 3.10 or newer and has no third-party runtime
dependencies.

```powershell
git clone https://github.com/maxhuntert1414-max/FluidGateway.git
cd FluidGateway
python -m unittest
python -m fluidgateway --help
```

## Good Contribution Areas

- PresentMon column and version compatibility;
- conservative frame-pipeline heuristics;
- report clarity and accessibility;
- runtime event adapters and protocol validation;
- deterministic fixtures and regression tests;
- D3D11/D3D12/Vulkan telemetry research;
- CPU, RAM, VRAM, queue, and synchronization evidence models;
- documentation and reproducible benchmarks.

## Pull Request Standard

1. Keep the change scoped and explain the failure mode or capability it adds.
2. Add or update a deterministic test for behavioral changes.
3. Run `python -m unittest` and include the result in the pull request.
4. Preserve structured JSON contracts or version them explicitly.
5. Include raw before/after evidence for performance claims.
6. Separate GPU workload, CPU, frame-time, FPS, power, and memory claims.
7. Document negative or inconclusive results instead of hiding them.

## Safety Boundary

FluidGateway does not accept contributions whose purpose is to bypass
anti-cheat, DRM, target consent, process protection, or platform security.
External-process work must be allowlisted, operator-authorized, identity-bound,
bounded, observable, and reversible. Missing safety evidence must fail closed.

## Commit Style

Use concise imperative messages when practical, for example:

```text
feat: add PresentMon legacy column mapping
fix: reject mismatched runtime ledger identity
docs: record RX 580 benchmark caveat
```

By contributing, you agree that your contribution is licensed under the MIT
License used by this repository.
