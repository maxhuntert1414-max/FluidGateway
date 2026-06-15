# STARK RESEARCHER

## Role and Assignment

RESEARCHER inspected the v0.46 runtime daemon dry-run target and mapped the
smallest safe integration points.

## Owned Domain

- Existing adapter, state accumulator, supervisor execution, and CLI seams
- Runtime daemon invariants
- Implementation risks and test evidence

## Output Summary

Confirmed that `replay_adapter_event_stream(path, previous_state=...)` is the
right replay primitive, and that only `RuntimeStateAccumulator` should cross
daemon cycles. Recommended a new `fluidgateway/daemon.py` module instead of
inflating `adapter.py`, plus an aggregate dry-run report with per-cycle
transition, supervisor, plan, execution, and state digest evidence.

## Decisions Made

- Keep the daemon offline and advisory for v0.46.
- Preserve `dry_run=true`, `would_modify_system=false`, and
  `execution_guard=advisory-only`.
- Treat repeated `--events` as ordered daemon cycles.
- Add event counters and initial/final state evidence to the daemon report.

## Open Questions or Risks

- Future native execution still needs a separate safety and permissions review.
- The daemon is not a background service yet.

## Direct File Edits

RESEARCHER did not edit files.
