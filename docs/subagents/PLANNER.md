# STARK PLANNER

## Role and Assignment

PLANNER turned the v0.46 daemon dry-run brief into a small implementation
contract and test matrix.

## Owned Domain

- CLI contract for `runtime run-daemon`
- JSON report schema expectations
- State persistence edge cases
- Test matrix and release criteria

## Output Summary

Recommended `runtime run-daemon --events ... --state ... --out ...
[--iterations N]`, with `--state` required. Multiple `--events` are processed in
order; if `--iterations` is larger than the number of streams, the last stream
repeats. Missing state starts fresh, invalid state fails before writes, and
`--state`/`--out` must resolve to different JSON paths.

## Decisions Made

- A daemon cycle equals one adapter replay with the previous accumulator passed
  into the next replay.
- `--state` is required so every daemon invocation has an explicit persistence
  boundary.
- State and report paths must be compared after JSON suffix normalization.

## Open Questions or Risks

- A future daemon service should define crash-safe write ordering if report and
  state persistence become long-running operations.

## Direct File Edits

PLANNER did not edit files.
