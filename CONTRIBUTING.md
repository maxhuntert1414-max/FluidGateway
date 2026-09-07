# Contributing to FluidGateway

Thank you for helping build a more evidence-driven frame pipeline.

## Development Setup

Offline diagnostics require Python 3.10 or newer with no third-party runtime
dependencies. The online server is C++20 and does not load Python. Keep Runtime's
C# coordination and C++ actuation in its separate repository.

```powershell
git clone https://github.com/maxhuntert1414-max/FluidGateway.git
cd FluidGateway
python -m unittest
python -m fluidgateway --help
```

For the native server, install Visual Studio C++ Build Tools and the Windows SDK:

```powershell
cmake -S native -B native/build -A x64
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
python -m unittest tests.test_native_gateway -v
```

Native integration tests skip without a build. A skipped test is not native
validation. Changes to the protocol or state must also pass Debug and ASAN;
see [the native guide](docs/native-gateway.md) for limits and full validation.

## Code Map

| Area | Start Here |
| --- | --- |
| Wire contract and golden vectors | `contracts/fluidlink-v2*.json`, `fluidgateway/fluidlink_v2.py` |
| Native codec and negotiation | `native/include/protocol.hpp`, `native/src/protocol.cpp` |
| Bounded state and decisions | `native/include/core.hpp`, `native/src/core.cpp` |
| Loopback transport and deadlines | `native/src/server.cpp` |
| Differential and failure tests | `tests/test_native_gateway.py`, `native/tests/core_tests.cpp` |
| Benchmark and package verification | `tools/`, `docs/native-gateway.md` |

## Formatting

Use four spaces and the checked-in EditorConfig. Install the pinned, optional
development tools in an isolated environment:

```powershell
python -m venv tmp/dev-tools
tmp/dev-tools/Scripts/python.exe -m pip install -r requirements-dev.txt
$cpp = Get-ChildItem native/include,native/src,native/tests -File | Where-Object Extension -in '.hpp','.cpp'
tmp/dev-tools/Scripts/clang-format.exe -i $cpp.FullName
tmp/dev-tools/Scripts/ruff.exe format tools tests/test_native_gateway.py
```

CI checks `clang-format --dry-run --Werror` for the native core and `ruff format
--check` for the new online validation tools. Existing offline Python files are
not reformatted wholesale by this change; preserve their style when editing them.
Keep formatting-only commits separate from behavior changes where practical.
Use descriptive names and small functions; explain invariants and ownership in
comments, not every assignment. Never compress control flow to save source lines.

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
