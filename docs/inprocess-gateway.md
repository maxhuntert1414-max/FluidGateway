# In-Process Gateway

FluidGateway v0.69 adds an opt-in Windows x64 `FluidGatewayNative.dll` alongside
the existing server. Both link the same C++20 `fluidgateway-core` and execute
the same `ProtocolSession`, `State`, payload validation and decisions.

| Backend | Boundary | Default |
| --- | --- | --- |
| `server` | FluidLink v2 over IPv4 loopback; separate process | Yes |
| `inprocess` | FluidLink v2 frames through a versioned C ABI; no socket | No |

There is no automatic backend switch. Failed DLL loading or a returned error
does not grant authority. Choose `server` explicitly when isolation is needed.
This release still encodes/decodes FluidLink frames inside the process: it is
not zero-copy. Python is used only for offline analysis and test drivers.

## Build and Contract

```powershell
cmake -S native -B native/build -A x64
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
python -m unittest tests.test_native_gateway tests.test_native_inprocess
cmake --install native/build --config Release --prefix tmp/native-release
```

The package includes the server, DLL, import library and
[`fluidgateway_native.h`](../native/include/fluidgateway_native.h).
Release uses the static MSVC runtime and contains no ASAN dependency.
Debug/ASAN builds are development tools, not redistributable replacements.

ABI version `0x00010000` is distinct from package and FluidLink versions.
The supported FluidLink base and batch contract hashes/opcodes/units are unchanged.
The exported interface contains only fixed-width integers, C structures and pointers:

- `fgn_get_abi_info`: check exact ABI, features, structure sizes and limits.
- `fgn_session_create`: acquire an opaque 64-bit generation-tagged handle.
- `fgn_session_exchange`: process exactly one complete FluidLink v2 frame.
- `fgn_session_get_metrics`: read explicitly scoped counters while the handle exists.
- `fgn_session_destroy`: wait for an active call, release all session state.

The caller owns the input and output storage. Allocate at least 65,591 output
bytes. `BUFFER_TOO_SMALL` returns that capacity before consuming any request;
retry with the same sequence. On success, only `output_size` bytes are valid.
`FGN_OK` means a complete frame, not an authorization: check the wire error flag,
correlation, contract, capabilities, session and ordered decision vector.

No C++ exception crosses the ABI. Returnable framing/allocation/internal failures
retire the session and return no usable output. Protocol errors retain their
existing fatal/nonfatal semantics; a failed batch never returns a partial vector.
`BUSY` means a simultaneous call on the same session, not permission to execute.
Runtime serializes calls and discards that connection on a returned ABI error.

## Lifetime, Bounds and Trust

Each loaded module permits eight live sessions. Each session retains at most
8 MiB of PMR allocation requests, 4,096 resources and 16,384 operation IDs.
Transient codec buffers and caller storage are separate, explicitly bounded by
frame size; these limits are not a promise that process RSS is only 8 MiB.
Fresh sessions must handshake and redeclare resources. Old handle generations
cannot alias renewed sessions. Creating a session never locks an active session's
exchange path. Sessions can run concurrently; calls within one session serialize.

Destroy every handle before unloading the DLL. The Runtime binding uses SafeHandle
references, a locked file and a restricted DLL dependency search. It verifies the
explicit absolute path, expected SHA-256, actually loaded module path, ABI and
limits before creating sessions. It binds authorizations to the host image/PID/
start time and the DLL SHA-256/ABI. Reports do not claim OS TCP-owner verification
for in-process execution.

The DLL is trusted code, **not a security or crash boundary**. Valid, nonoverlapping
caller pointers are mandatory. Invalid pointers, access violations, DLL loader
bugs and memory corruption can terminate or corrupt the host; catching C++
exceptions cannot make those faults recoverable. DLL hashing is not a signature
or authentication of another principal. Use only a binary you trust.

There are no network deadlines in an in-process session. Runtime retains its
total authorization deadline and checks cancellation before/after synchronous
calls. It cannot safely preempt a running native call; late decisions are discarded.
No per-call worker thread or unsafe thread abort is introduced.

## Verification and Measurements

See the [v0.69 measured results and raw evidence](release-v0.69.0.md).

The differential suite replays existing Python/C++ corpus cases and golden request
payloads against the real server and DLL. Responses must match byte-for-byte after
normalizing only the independently generated session UUID, including error text.
The existing golden encoder roundtrips still verify the unchanged wire contract.
Bounds, aliases, writes, duplicate IDs, batch rejection, integer extremes and
malformed frames are covered alongside C/C++ lifetime and concurrency tests.

The Runtime repository contains the real .NET A/B driver and owned D3D11/D3D12/
Vulkan checks. See [Runtime in-process usage](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/inprocess-gateway.md).
CPU cycles supplement coarse Windows CPU-time sampling. Managed allocated bytes
are measured for both backends. Native PMR allocation counters cover retained
state, not all CRT allocations. DLL copy counters count explicit request/response
payload copies in the wire codec, not STL or kernel copies. Missing metrics must
remain unmeasured, never be reported as zero.

This change targets Gateway overhead, not game FPS, input delay, power, physical
RAM/VRAM placement or equivalence to unified-memory hardware.

## Optional Typed Calls

The wire adapter is separate from the policy core. A later, separately versioned
typed C ABI may call the same validated core with borrowed spans, but must retain
alias/dependency validation, overflow checks, batch atomicity and differential
coverage. New exports/features must be negotiated explicitly. No typed or
zero-copy capability is advertised by ABI v1.
