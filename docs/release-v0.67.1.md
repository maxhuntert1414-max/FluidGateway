# FluidGateway v0.67.1 Hardening

This patch release prepares the diagnostic and decision layer for cautious
local use without widening its authority.

## Changes

- All generated JSON, JSONL, HTML, registry, ledger, and daemon-state files are
  flushed to a same-directory temporary file and atomically replaced.
- The Windows FluidLink server uses exclusive address ownership. Existing
  loopback-only, connection-count, backlog, payload, and deadline limits remain.
- `python -m fluidgateway doctor` writes a structured readiness report for
  offline diagnosis, FluidLink, PresentMon, and owned FluidRuntime labs.
- Ctrl+C exits the CLI with status 130 and no Python traceback.
- Multi-GPU VRAM classification uses the largest reported adapter instead of
  summing unrelated adapters. The report retains the aggregate and states that
  active-process GPU binding is not yet known.

## Verification

- 268 Python unit tests passed on both Python 3.12 and Python 3.14 on the
  release worktree.
- Atomic replacement failure preserves the previous file and removes its
  temporary file.
- A second Windows server cannot bind the active FluidLink endpoint.
- The doctor remains fail-closed for external-process hooks and system-wide
  actuation.

These checks establish operational safety for the current diagnostic and
owned-lab boundary. They do not establish game-performance gains or support for
third-party process injection.
