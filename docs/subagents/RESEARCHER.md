# STARK RESEARCHER

## Role and Assignment

RESEARCHER inspected the current FluidGateway runtime pipeline and assessed
whether a v0.34 `runtime_control_packet` slice is aligned with the project.

## Owned Domain

- Existing pipeline shape from `execution_packet` through `runtime_manager`
- Naming and contract risks
- Integration and test-risk brief

## Output Summary

The research brief confirmed that adding `runtime_control_packet` after
`runtime_manager` is aligned with the current architecture:

`execution_packet -> dispatch_plan -> dispatch_execution -> runtime_calibration -> runtime_manager -> runtime_control_packet`

Recommended contract:

- `RuntimeControlPacket`
- `RuntimeControlCommand`
- `build_runtime_control_packet(runtime_manager)`
- `mode = runtime-control-packet-v0.34`
- command domains: `frame`, `queue`, `scheduler`, `memory`
- command counters and aggregate budget fields

## Decisions Made

- Keep `runtime_control_packet` as an advisory command stream, not a game hook,
  driver hook, or OS scheduler.
- Use `runtime_control_packet` rather than `control_plane` to avoid competing
  with existing `fluidgateway/control.py`.
- Avoid a per-command JSON field named `mode`; use `setting` so it does not
  conflict with packet-level `mode`.

## Open Questions or Risks

- `tests/test_fluidgateway.py` is large and should be split in a future hygiene
  slice.
- Stable scenarios still emit active frame/queue/scheduler commands; memory
  `hold_residency` commands are counted as inactive by design.

## Direct File Edits

RESEARCHER did not edit files.
