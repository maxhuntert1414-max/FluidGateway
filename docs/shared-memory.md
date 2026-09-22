# Shared Memory: Current Boundary

FluidRuntime now has an experimental cooperative, versioned D3D12 arena on Windows.
It is not a software switch for hardware UMA, a global allocator, or transparent
memory optimization in games.

## Responsibilities

- **Gateway** keeps policy, budgets, expiry and the existing fail-closed decisions.
  Its C++20 server and in-process DLL remain selectable and unchanged.
- **Runtime** owns native memory, resource lifetimes, content versions, aliases,
  access leases and driver-confirmed completion.
- **FluidLink** retains its current binary contracts. Internal coherence tickets
  are not Gateway authorizations or newly assigned protocol opcodes.

The Runtime arena reuses the fixed-capacity coherence core through
`FluidMemoryArena.dll`, with a versioned C ABI, explicit local leases and verified
read-only peer exports. Backing is bounded to 64 MiB across page-rounded CPU sections
and aligned UPLOAD/DEFAULT/READBACK resources, with 64 slots and one device/queue.
It owns its buffers, not arbitrary application graphics resources.

The lab checks real cross-process mapping, exact GPU contents, stale aliases,
budget/lease failures and timeout cleanup. An allocation-reuse benchmark retains
every required transfer; no GPU copy is removed and existing Gateway authority
is not widened. The daily monitor does not load this experimental library.

## Next Implementation

Next integrate a trusted managed/native client and resource binding, keeping
authority metadata private and reusing the arena's C ABI. External readers are
currently held until process exit; writable external producers, textures,
multi-queue workloads and application-transparent arenas remain unsupported.

An OS shared mapping is not automatically GPU-visible memory. On discrete GPUs,
Runtime-owned staging and explicit transfers remain necessary for this design.
Only current content plus trusted lifetime/completion evidence and Gateway policy
can justify future reuse. A writable peer mapping cannot certify immutable bytes
merely by publishing a version number.

Before new external GPU-control messages, define a negotiated capability, normative numeric
schema and golden vectors. Measure copies, CPU cost and latency against the
original-copy path; do not infer FPS, input latency, power or PCIe savings from
successful mapping or hardware capability flags.

See Runtime's [arena and reproduction guide](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/shared-arena.md),
[ABI/local-reader protocol](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/shared-arena-abi.md)
and [architecture decision](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/architecture/shared-memory-v1.md).
The [daily terminal monitor](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/daily-use.md)
remains read-only and does not activate this experimental memory work.
