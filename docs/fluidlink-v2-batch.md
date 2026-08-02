# FluidLink v2 Operation Batch Profile

FluidGateway 0.65.0 adds an opt-in binary profile for repeated runtime
operations. It removes repeated field bodies and request/response turns while
leaving the original FluidLink v2 contract unchanged.

## Canonical Artifacts

- [`fluidlink-v2-batch.contract.json`](../contracts/fluidlink-v2-batch.contract.json)
- [`fluidlink-v2-batch.golden.json`](../contracts/fluidlink-v2-batch.golden.json)
- contract SHA-256:
  `bf8727c22ac878ceff6dd0f462d6db5e81174737e839ecdf2e263a6f55268542`

The profile extends base contract
`0d24d96aec32d74e123f9e198e51adde74ddf190e8c40b0ac18bddf5c4108b2f`.
Base clients still negotiate that original hash and capability mask `0x7f`.

## Wire Additions

| Registry | Value | Meaning |
| --- | ---: | --- |
| Capability bit | `7` | `batched_runtime_events` |
| Event opcode | `105` | `operation_batch` |
| Decision opcode | `7` | `batch_vector` |
| Maximum operations | `256` | hard codec and server limit |

An operation batch contains a nonzero 16-byte identity, a `u16` count, and one
shared operation template. FluidGateway expands it in order with IDs
`batch-{id}-{ordinal}` and returns one numeric decision entry per operation.
This profile is for homogeneous repetition; it is not a general heterogeneous
command stream.

## Safety Invariants

- exact extension hash and capability bit are mandatory in Hello/Welcome;
- opcode 105 is rejected on a base-profile session;
- batch IDs, counts, enums, masks, UTF-8 bounds, and trailing bytes are strict;
- response ID and cardinality must exactly match the request;
- every decision must agree with its execution state;
- an adapter failure closes the session and returns no partial vector.

The server can process earlier operations before a later adapter failure. The
closed session prevents the caller from treating that incomplete result as an
authorization. The profile does not claim transactional rollback of adapter
state.

## Controlled Result

The owned D3D11 authorization workload carries one seed upload and 64 duplicate
candidates. FluidLink now transports those 65 logical events in one batch.
The complete authorization sequence keeps 71 logical runtime events while
falling from 74 to 10 loopback round trips.

In the local WARP verification on 2026-08-02, complete FluidLink frame bytes for
one authorization fell from 26,756 in the published v0.15 serial trace to 3,138
with the batch profile. These counters exclude TCP/IP overhead. This is protocol
overhead evidence, not proof of FPS, power, PCIe, or physical RAM/VRAM traffic.

## Verify

```powershell
# FluidGateway
python -m unittest tests.test_fluidlink_v2

# Adjacent FluidRuntime repository
dotnet test tests\FluidRuntime.Tests\FluidRuntime.Tests.csproj `
  --filter FullyQualifiedName~FluidLinkV2
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\Test-GatewayManagedUpdateUpload.ps1 `
  -GatewayPath ..\FluidGateway -TrialPairs 2 -WarmupPairs 0 -Hardware $false
```

The managed integration also checks OS loopback peer ownership, exact contract
artifacts, native content guards, rollback, malformed responses, stalled peers,
and cumulative timeout failure.
