# Shared Memory: Current Boundary

Fluid's next memory milestone is a cooperative, versioned buffer arena on Windows.
It is not a software switch for hardware UMA, a global allocator, or transparent
memory optimization in games.

## Responsibilities

- **Gateway** keeps policy, budgets, expiry and the existing fail-closed decisions.
  Its C++20 server and in-process DLL remain selectable and unchanged.
- **Runtime** owns native memory, resource lifetimes, content versions, aliases,
  access leases and driver-confirmed completion.
- **FluidLink** retains its current binary contracts. Internal coherence tickets
  are not Gateway authorizations or newly assigned protocol opcodes.

The Runtime foundation provides fixed-capacity C++20 bookkeeping and an owned
Windows/D3D12 validation lab. The lab shares a read-only CPU mapping with a child
process and checks exact GPU roundtrip contents. Required transfers remain; no
copy is removed. This is the prerequisite for an arena, not an arena delivery.

## Next Implementation

Start with registered cooperative linear buffers, one D3D12 device/queue,
64 live slots and a 64-MiB total physical arena limit. Keep authority metadata
private, enforce peer identity and handle rights, reject stale generations, and
never recycle storage with unknown GPU progress. A later C ABI must contain
exceptions and use opaque handles and fixed-width descriptors.

An OS shared mapping is not automatically GPU-visible memory. On discrete GPUs,
Runtime-owned staging and explicit transfers remain necessary for this design.
Only current content plus trusted lifetime/completion evidence and Gateway policy
can justify future reuse. A writable peer mapping cannot certify immutable bytes
merely by publishing a version number.

Before new external messages, define a negotiated capability, normative numeric
schema and golden vectors. Measure copies, CPU cost and latency against the
original-copy path; do not infer FPS, input latency, power or PCIe savings from
successful mapping or hardware capability flags.

See Runtime's [foundation and reproduction guide](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/shared-memory-foundation.md)
and [architecture decision](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/architecture/shared-memory-v1.md).
The [daily terminal monitor](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/daily-use.md)
remains read-only and does not activate this experimental memory work.
