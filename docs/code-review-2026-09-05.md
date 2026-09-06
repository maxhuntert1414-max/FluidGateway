# Cross-Repository Code Review: 2026-09-05

Scope: FluidGateway main `65c9595` and FluidRuntime main `5f25677`, followed by
the fixes in this review. This was a risk-oriented architecture/code review with
reproductions and integration tests, not proof that every possible execution is
correct. No broad rewrite, protocol-version change or expansion of authority.

## Fixed Findings

| Priority | Finding | Correction and regression |
| --- | --- | --- |
| P1 | A wait on an eliminated duplicate transfer was removed even though the retained transfer still needed synchronization. | Rewrite dependencies to retained operations; preserve their waits and other prerequisites. `test_runtime_provenance.py` covers both manifest and incremental paths. |
| P1 | Cached transfers survived writes to source/destination/aliases and resource release/recreation. Allocation reuse also survived resizing. | Shared `RuntimeOptimizationState` invalidates affected provenance, scopes deduplication to the same frame/queue, retires allocation state, and rejects duplicate operation IDs. |
| P2 | Missing/unknown endpoints could compare equal and be removed as self-copies. | Require registered source and destination before any transfer-elision suggestion. |
| P2 | Native probe timeout covered process exit but not stdout/stderr held open by descendants. Pre-cancelled calls still touched files/launched work. | Cancellable output reads share the deadline; check cancellation before file access/launch. A Windows regression spawns and cleans up a pipe-holding descendant. |
| P2 | Application exit was detected only at 250 ms sampling ticks, and watchdog cleanup was included in capture duration. | Wait on process exit with a bounded sampling interval, stop counters/timer before cleanup, and cancel/detach the exit waiter when capture ends. Check cancellation before launch. |
| P2 | Absent/all-NA supporting metrics were truthy summary objects and produced high confidence. | Use actual numeric availability for CPU-wait/GPU-bubble confidence. Valid zero is not missing data. |
| P2 | NaN, infinity, negatives and oversized integers could poison runtime costs/budgets or escape validation as OverflowError. | Validate finite nonnegative operation/resource numbers at the shared boundary; ignore invalid policy budgets consistently with existing invalid-text behavior. |
| P2 | Application reports accepted contradictory restoration states and counted the 16 MiB cap as characters. | Validate restoration/applied/after consistency and enforce the limit on UTF-8 bytes before decoding. |
| P2 | Multi-application/process/swapchain traces were aggregated and labelled as the most frequent application. | Refuse ambiguous mixed streams with an explicit filtering error. Single-stream files and absent optional identity columns remain supported. |

The refactor is intentionally concentrated in provenance/dependency tracking.
Manifest optimization and live controller input previously duplicated that state
machine. Both now use one implementation; native graphics code was not rewritten.
Old tests that demanded dropping a still-required wait were corrected, including
the resulting cost/decision counts. A lower estimated saving is the correct result.

The advisory model still requires complete, sequential write information and
truthful resource/alias declarations. It does not infer exact byte equality from
resource names in real games. Native content checks and authorization gates remain
independent and mandatory. Route/packet simulations cover selected proposed
actions, not a complete measurement of every original operation or GPU dependency.

## Open Findings And Limits

- **P2: unbounded live-session history.** `RuntimeAdapterSession` retains frames,
  results, commands and policy history for the lifetime of the connection. A local
  reproduction retained 1,000 frames after 2,000 begin/end events. Connection and
  packet bounds do not bound that history. Long-running use needs an explicit
  retention/rollup contract and soak tests that preserve resource and dependency
  correctness; this review does not silently discard historical evidence.
- **Compatibility remains experimental.** Native lifecycle/provenance paths were
  inspected and existing GPU, mock and sanitizer regressions rerun. No new native
  corruption was reproduced in those tests. This does not establish arbitrary
  game/driver/extension compatibility or permit third-party copy removal.
- **Observation has overhead and coverage limits.** The Vulkan layer uses shared
  dispatch bookkeeping and fixed instance/device/allocation tables. Stop disables
  collection, not layer unloading. See Runtime's application-session guide.
- **Timing is not a product benchmark.** The collector no longer deliberately
  waits for the next tick after exit. CPU/RAM samples are still approximately
  250 ms apart, terminal CPU/RAM values are carried from the last live sample,
  and collector duration is not input latency or exact GPU execution time.
- **Rollback is bounded, not absolute.** The independent priority helper passed
  collector-crash restoration. Killing that helper or concurrent external priority
  changes remain limitations; Windows priority read/set is not an atomic lease.

Next priorities: bounded streaming state with long-session soak/fault testing;
then per-process/swapchain report aggregation and real-engine compatibility
measurements. Keep manifest estimates, observed counters and native execution
evidence visibly separate before adding more actuation.

## Verification

- Baseline: 278 Python and 245 .NET tests passed before changes.
- Final: **294 Python**, **250 .NET** tests passed, .NET warnings as errors.
- Native CTest: **32/32 each in Release, Debug and ASAN**. Leak detection is
  disabled in this Windows ASAN configuration; this is not a leak-freedom claim.
- FluidLink cross-process gate: 11 round trips; matching base/batch contracts and
  golden vectors; v2 1,880 frame bytes vs v1 3,189 for the same synthetic flow.
- Owned D3D11, D3D12 and Vulkan: two paired correctness runs each, 128 exact
  actions per controlled run, plus malformed/stalled/slow-peer baseline fallbacks.
  D3D11/D3D12 used WARP here; all general performance-claim gates remained closed.
- Actual Khronos vkcube: AB and BA at 120 frames, device/counter identity and clean
  teardown; one-second priority restored, forced collector exit restored priority
  in approximately two seconds and the disposable target exited naturally.
- Gateway successfully imported the resulting priority session to HTML/JSON.
- `doctor`: offline/server ready; default PATH discovery did not find optional
  PresentMon/Runtime and no native directory was supplied. Explicit-path integration
  tests above ran successfully. Partial host telemetry remains reduced-confidence.

Local generated evidence is in Runtime `artifacts/review-*`,
`artifacts/fluidlink-cross-process.json`, and Gateway `tmp/review-application.*`.
It is not a new release or a claimed FPS improvement. No game, keyboard, Codex
configuration, driver, registry, service, task or global environment was changed.
