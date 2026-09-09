from __future__ import annotations

from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import json
import random
import socket
import struct
import subprocess
import time
import unittest

from fluidgateway.adapter import RuntimeAdapterSession
from fluidgateway import __version__
from fluidgateway import fluidlink_v2 as wire
from tools.native_gateway_validation import Peer, ROOT, native_executable, server

NATIVE = native_executable()
TEST_BINARY = NATIVE.with_name("fluidgateway-native-tests.exe")
IDENTITY = bytes(range(17, 33))


def process_thread_ids(pid):
    class ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("thread_id", wintypes.DWORD),
            ("process_id", wintypes.DWORD),
            ("base_priority", wintypes.LONG),
            ("delta_priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.argtypes = kernel.Thread32First.argtypes
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(4, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry(size=ctypes.sizeof(ThreadEntry))
        present = kernel.Thread32First(handle, ctypes.byref(entry))
        threads = set()
        while present:
            if entry.process_id == pid:
                threads.add(entry.thread_id)
            entry.size = ctypes.sizeof(ThreadEntry)
            present = kernel.Thread32Next(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return threads
    finally:
        kernel.CloseHandle(handle)


def event(subject, **payload):
    return subject, wire.encode_runtime_event_payload(subject, payload)


def setup_events():
    return [
        event(100, action="begin", id="test"),
        event(101, action="begin", frame=0),
        event(102, id="ram", memory="ram"),
        event(102, id="vram", memory="vram"),
    ]


def op(name, **overrides):
    payload = dict(
        id=name,
        operation_type="upload",
        source="ram",
        target="vram",
        queue="copy",
        cost_us=320,
        size_bytes=1048576,
    )
    payload.update(overrides)
    return event(103, **payload)


@unittest.skipUnless(
    NATIVE.exists() and TEST_BINARY.exists(), "Build the native Gateway or set FLUIDGATEWAY_NATIVE"
)
class NativeGatewayTests(unittest.TestCase):
    def compare(self, events, batch=False):
        protocol = wire.FluidLinkV2ServerSession(
            server_name="fluidgateway", server_version=__version__
        )
        adapter = RuntimeAdapterSession()
        hello = wire.encode_hello_payload(
            client_name="test",
            client_version="1",
            contract_digest=wire.FLUIDLINK_V2_BATCH_CONTRACT_DIGEST
            if batch
            else wire.FLUIDLINK_V2_CONTRACT_DIGEST,
            requested_capabilities=wire.FLUIDLINK_V2_BATCH_CAPABILITIES
            if batch
            else wire.FLUIDLINK_V2_CAPABILITIES,
            required_capabilities=wire.FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES
            if batch
            else wire.FLUIDLINK_V2_REQUIRED_CAPABILITIES,
        )
        requests = [wire.fluidlink_v2_request(opcode=1, sequence=1, payload=hello)]
        expected = [protocol.process(requests[0], adapter.process_event)]
        protocol.session_id = IDENTITY
        for sequence, (subject, payload) in enumerate(events, 2):
            request = wire.fluidlink_v2_request(
                opcode=10,
                sequence=sequence,
                session_id=IDENTITY,
                payload=payload,
                subject_opcode=subject,
            )
            requests.append(request)
            expected.append(protocol.process(request, adapter.process_event))
        result = subprocess.run(
            [str(TEST_BINARY), "--replay"],
            text=True,
            capture_output=True,
            input="\n".join(wire.encode_fluidlink_v2_frame(r).hex() for r in requests),
            check=True,
            timeout=30,
        )
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), len(expected))
        for index, (line, reference) in enumerate(zip(lines, expected)):
            actual = wire.decode_fluidlink_v2_frame(bytes.fromhex(line))
            self.assertEqual(
                (actual.opcode, actual.subject_opcode, actual.decision_opcode, actual.ok),
                (
                    reference.opcode,
                    reference.subject_opcode,
                    reference.decision_opcode,
                    reference.ok,
                ),
                index,
            )
            if actual.opcode == 255:
                self.assertEqual(actual.payload[:2], reference.payload[:2], index)
            else:
                self.assertEqual(actual.payload, reference.payload, index)
        return result

    def test_golden_frame_roundtrips(self):
        vectors = []
        for name in ("fluidlink-v2.golden.json", "fluidlink-v2-batch.golden.json"):
            vectors.extend(json.loads((ROOT / "contracts" / name).read_text())["vectors"])
        encoded = [v["wire_hex"] for v in vectors]
        result = subprocess.run(
            [str(TEST_BINARY), "--roundtrip"],
            input="\n".join(encoded),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        self.assertEqual(result.stdout.splitlines(), encoded)

    def test_copy_write_and_dependency_parity(self):
        self.compare(
            setup_events()
            + [
                op("seed"),
                op("duplicate"),
                op("wait", operation_type="sync", depends_on=["duplicate"]),
                op("write", operation_type="compute", target="ram"),
                op("after-write"),
                op("self", target="ram"),
                op("orphan", operation_type="sync", depends_on=["self"]),
                op("unknown", source="missing", target="missing"),
                op("empty", operation_type="sync", cost_us=0),
                event(101, action="end", frame=0),
                event(100, action="end", id=""),
            ]
        )

    def test_readback_source_write_parity(self):
        def readback(name):
            return op(name, operation_type="copy", source="vram", target="ram")

        self.compare(
            setup_events()
            + [
                readback("seed-readback"),
                readback("repeat-readback"),
                op("gpu-write", operation_type="compute", target="vram"),
                readback("after-gpu-write"),
                readback("repeat-after-write"),
                op("cpu-write", operation_type="compute", target="ram"),
                readback("after-staging-write"),
                event(102, id="vram", action="release"),
                event(102, id="vram", memory="vram"),
                readback("after-source-reuse"),
                event(101, action="end", frame=0),
                event(100, action="end", id=""),
            ]
        )

    def test_alias_release_resize_parity(self):
        self.compare(
            [
                event(102, id="ram", memory="ram", aliases=["x"]),
                event(102, id="alias", memory="ram", aliases=["x", "y"]),
                event(102, id="alias2", memory="ram", aliases=["y"]),
                event(102, id="vram", memory="vram"),
                op("seed"),
                op("write", operation_type="draw", target="alias2"),
                op("fresh"),
                op("aliased-copy", source="ram", target="alias"),
                event(102, action="release", id="vram"),
                event(102, id="vram", memory="vram"),
                op("reregistered"),
                op("alloc", operation_type="allocate", reason="temporary"),
                op("reuse", operation_type="allocate", reason="temporary"),
                op("resize", operation_type="allocate", size_bytes=2048),
                op("old", operation_type="allocate", reason="temporary"),
            ]
        )

    def test_frame_queue_and_unknown_write_parity(self):
        self.compare(
            setup_events()
            + [
                op("a"),
                op("b", queue="graphics"),
                op("c", frame=1),
                op("d", operation_type="draw", target="unknown"),
                op("e", frame=1),
                event(101, action="end", frame=3),
                event(100, action="end", id=""),
                event(101, action="end", frame=0),
                event(101, action="begin", frame=0),
            ]
        )

    def test_invalid_events_parity(self):
        self.compare(
            setup_events()
            + [
                event(102, id="ram"),
                op("a"),
                op("a"),
                (103, b"\xff"),
                (102, b"\x01\x01\x00\xff"),
                (104, b"\x01x"),
                (101, b"\x01\xff"),
                (199, b""),
            ]
        )

    def test_utf8_and_trim_parity(self):
        self.compare(
            [
                event(102, id="\u2003ram\u00a0", memory="ram"),
                event(102, id="vram", memory="vram"),
                op(" spaced ", source="\t ram \n"),
                op("second", source="ram"),
                event(102, action="release", id=" ram "),
                op("released"),
            ]
        )

    def test_batch_parity_and_partial_rejection(self):
        batch = dict(
            batch_id="aabbccdd" * 4,
            operation_count=128,
            operation_type="upload",
            source="ram",
            target="vram",
            queue="copy",
            size_bytes=4096,
            cost_us=300,
        )
        payload = wire.encode_operation_batch_event_payload(batch)
        self.compare(setup_events() + [(105, payload), (105, payload)], batch=True)

    def test_randomized_operation_parity(self):
        rng = random.Random(6851)
        events = setup_events()
        for i in range(300):
            events.append(
                op(
                    str(i),
                    operation_type=rng.choice(
                        ["copy", "upload", "allocate", "draw", "compute", "sync"]
                    ),
                    source=rng.choice(["ram", "vram", "missing"]),
                    target=rng.choice(["ram", "vram", "missing"]),
                    queue=rng.choice(["copy", "graphics"]),
                    frame=rng.randrange(3),
                    reason=rng.choice(["normal", "transient"]),
                    size_bytes=rng.choice([0, 1024, 2048]),
                    depends_on=[str(rng.randrange(i))] if i and rng.randrange(3) == 0 else [],
                )
            )
        self.compare(events)

    def test_network_authorization_and_identity(self):
        with server(executable=NATIVE) as (_, port), Peer(port) as peer:
            self.assertEqual(
                wire.decode_welcome_payload(peer.welcome.payload).server_name, "fluidgateway"
            )
            peer.initialize()
            result = wire.decode_operation_batch_decision_payload(peer.batch().payload)
            self.assertEqual([d["decision_opcode"] for d in result["decisions"]], [0] + [2] * 128)
            peer.finish()

    def test_header_rejections(self):
        frame = wire.fluidlink_v2_request(opcode=20, sequence=1, payload=b"\x01a")
        original = wire.encode_fluidlink_v2_frame(frame)
        invalid = []
        for offset, value in ((0, 0), (4, 1), (5, 3), (9, 1), (10, 1)):
            data = bytearray(original)
            data[offset] = value
            invalid.append(data.hex())
        invalid.append((original[:52] + struct.pack("<I", 65536) + original[56:]).hex())
        result = subprocess.run(
            [str(TEST_BINARY), "--roundtrip"],
            input="\n".join(invalid),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        self.assertEqual(result.stdout.splitlines(), ["error"] * len(invalid))

    def test_sequence_and_session_rejected(self):
        with server(executable=NATIVE) as (_, port), Peer(port) as peer:
            peer.sequence += 1
            response = peer.request(20, b"\x01x")
            self.assertEqual(int.from_bytes(response.payload[:2], "little"), 6)
            peer.sequence -= 2
            peer.session = bytes(range(1, 17))
            request = wire.fluidlink_v2_request(
                opcode=20, sequence=2, payload=b"\x01x", session_id=peer.session
            )
            peer.socket.sendall(wire.encode_fluidlink_v2_frame(request))
            response = wire.read_fluidlink_v2_frame(peer.stream)
            self.assertEqual(int.from_bytes(response.payload[:2], "little"), 7)

    def test_connection_limit_and_recovery(self):
        peers = []
        with server(executable=NATIVE) as (_, port):
            try:
                time.sleep(0.1)
                peers = [Peer(port) for _ in range(8)]
                with self.assertRaises((OSError, AssertionError)):
                    Peer(port)
            finally:
                for peer in peers:
                    peer.close()
            time.sleep(0.1)
            with Peer(port) as peer:
                self.assertEqual(peer.request(20, b"\x01x").opcode, 21)

    def test_worker_threads_and_fresh_state_survive_reconnections(self):
        identities = set()
        with server(executable=NATIVE) as (process, port):
            retained_threads = None
            for _ in range(4):
                time.sleep(0.1)
                with ExitStack() as stack:
                    peers = [stack.enter_context(Peer(port)) for _ in range(8)]
                    threads = process_thread_ids(process.pid)
                    retained_threads = (
                        threads if retained_threads is None else retained_threads & threads
                    )
                    for peer in peers:
                        self.assertNotIn(peer.session, identities)
                        identities.add(peer.session)
                        peer.initialize()
                        response = peer.batch(2, batch_id=IDENTITY.hex())
                        decisions = wire.decode_operation_batch_decision_payload(response.payload)
                        self.assertEqual(
                            [item["decision_opcode"] for item in decisions["decisions"]], [0, 2]
                        )
                        peer.finish()
                time.sleep(0.1)
                retained_threads &= process_thread_ids(process.pid)
            # Eight persistent workers and the listener, not newly created session threads.
            self.assertGreaterEqual(len(retained_threads), 9)

    def test_slow_header_deadline_and_recovery(self):
        with server(executable=NATIVE) as (_, port):
            with socket.create_connection(("127.0.0.1", port), timeout=4) as connection:
                connection.sendall(b"FLNK\x02")
                started = time.monotonic()
                self.assertEqual(connection.recv(1), b"")
                self.assertLess(time.monotonic() - started, 3.5)
            with Peer(port) as peer:
                self.assertEqual(peer.request(20, b"\x01x").opcode, 21)

    def test_cli_rejects_nonloopback(self):
        result = subprocess.run([str(NATIVE), "serve-events", "--host", "0.0.0.0"], timeout=5)
        self.assertEqual(result.returncode, 2)

    def test_mutated_frame_codec_matches_reference(self):
        rng = random.Random(6800)
        golden = json.loads((ROOT / "contracts/fluidlink-v2.golden.json").read_text())["vectors"]
        inputs, expected = [], []
        for _ in range(3000):
            data = bytearray.fromhex(rng.choice(golden)["wire_hex"])
            for _ in range(rng.randint(1, 4)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            if rng.randrange(5) == 0:
                data = data[: rng.randrange(len(data))]
            inputs.append(data.hex())
            try:
                expected.append(
                    wire.encode_fluidlink_v2_frame(
                        wire.decode_fluidlink_v2_frame(bytes(data))
                    ).hex()
                )
            except wire.FluidLinkProtocolError:
                expected.append("error")
        result = subprocess.run(
            [str(TEST_BINARY), "--roundtrip"],
            input="\n".join(inputs),
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        self.assertEqual(result.stdout.splitlines(), expected)

    def test_frame_history_does_not_grow_retained_state(self):
        hello = wire.fluidlink_v2_request(
            opcode=1,
            sequence=1,
            payload=wire.encode_hello_payload(client_name="test", client_version="1"),
        )
        requests = [wire.encode_fluidlink_v2_frame(hello).hex()]
        empty = subprocess.run(
            [str(TEST_BINARY), "--replay"],
            input=requests[0],
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        for frame in range(10000):
            for action in ("begin", "end"):
                requests.append(
                    wire.encode_fluidlink_v2_frame(
                        wire.fluidlink_v2_request(
                            opcode=10,
                            sequence=len(requests) + 1,
                            session_id=IDENTITY,
                            subject_opcode=101,
                            payload=wire.encode_runtime_event_payload(
                                101, dict(action=action, frame=frame)
                            ),
                        )
                    ).hex()
                )
        result = subprocess.run(
            [str(TEST_BINARY), "--replay"],
            input="\n".join(requests),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        self.assertEqual(result.stderr, empty.stderr)
        self.assertEqual(len(result.stdout.splitlines()), len(requests))
        for line in result.stdout.splitlines():
            self.assertTrue(wire.decode_fluidlink_v2_frame(bytes.fromhex(line)).ok)

    def test_resource_memory_limit_closes_session_and_recovers(self):
        with server(executable=NATIVE) as (_, port):
            with Peer(port) as peer:
                for index in range(4096):
                    response = peer.event(
                        102, id=f"r{index}", aliases=[f"{j:03d}" + "x" * 253 for j in range(32)]
                    )
                    if response.opcode == 255:
                        self.assertEqual(int.from_bytes(response.payload[:2], "little"), 11)
                        self.assertLess(index, 4096)
                        self.assertEqual(peer.stream.read(1), b"")
                        break
                else:
                    self.fail("8 MiB allocation limit was not enforced")
            with Peer(port) as fresh:
                fresh.initialize()
                self.assertEqual(fresh.batch(1).decision_opcode, 7)

    def test_partial_batch_failure_never_returns_a_decision_vector(self):
        with server(executable=NATIVE) as (_, port), Peer(port) as peer:
            peer.initialize()
            batch_id = "bb" * 16
            peer.event(103, id=f"batch-{batch_id}-001", operation_type="draw")
            response = peer.batch(3, batch_id=batch_id)
            self.assertEqual(response.opcode, 255)
            self.assertEqual(int.from_bytes(response.payload[:2], "little"), 11)
            self.assertEqual(peer.stream.read(1), b"")

    def test_integer_wire_units_are_exact_beyond_double_precision(self):
        with server(executable=NATIVE) as (_, port), Peer(port) as peer:
            peer.initialize()
            peer.event(
                103, id="a", operation_type="upload", source="ram", target="vram", size_bytes=2**53
            )
            changed = peer.event(
                103,
                id="b",
                operation_type="upload",
                source="ram",
                target="vram",
                size_bytes=2**53 + 1,
            )
            self.assertEqual(changed.decision_opcode, 0)
            maximum = dict(
                operation_type="upload",
                source="ram",
                target="vram",
                size_bytes=2**64 - 1,
                cost_us=2**32 - 1,
            )
            peer.event(103, id="c", **maximum)
            response = peer.event(103, id="d", **maximum)
            self.assertEqual(response.decision_opcode, 2)
            status, microseconds, size = struct.unpack("<BQQ", response.payload)
            self.assertEqual((status, microseconds, size), (3, 2**32 - 1, 2**64 - 1))

    def test_partial_payload_timeout_and_legacy_rejection(self):
        with server(executable=NATIVE) as (_, port):
            with socket.create_connection(("127.0.0.1", port), timeout=4) as connection:
                request = wire.fluidlink_v2_request(opcode=20, sequence=1, payload=b"\x01x")
                connection.sendall(wire.encode_fluidlink_v2_frame(request)[:-1])
                self.assertEqual(connection.recv(1), b"")
            with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                connection.sendall(b"FLNK\x01")
                self.assertEqual(connection.recv(1), b"")
            with Peer(port) as peer:
                self.assertEqual(peer.request(20, b"\x01x").opcode, 21)

    def test_idle_session_expires_and_worker_is_reusable(self):
        with server(executable=NATIVE) as (_, port):
            with Peer(port) as peer:
                peer.socket.settimeout(33)
                started = time.monotonic()
                self.assertEqual(peer.stream.read(1), b"")
                elapsed = time.monotonic() - started
                self.assertGreater(elapsed, 28)
                self.assertLess(elapsed, 33)
            with Peer(port) as peer:
                self.assertEqual(peer.request(20, b"\x01x").opcode, 21)

    def test_receiver_backpressure_releases_worker(self):
        with server(executable=NATIVE) as (_, port), ExitStack() as connections:
            bystanders = [connections.enter_context(Peer(port)) for _ in range(7)]
            peer = connections.enter_context(Peer(port, receive_buffer_bytes=512))
            peer.socket.settimeout(0.5)
            frame = wire.encode_fluidlink_v2_frame(
                wire.fluidlink_v2_request(
                    opcode=20, sequence=2, session_id=peer.session, payload=b"\x80" + b"x" * 128
                )
            )
            requests = bytearray(frame * 256)
            sequence = 2
            deadline = time.monotonic() + 10
            closed = False
            sent = 0
            # A client-side send timeout is not proof that server writes are blocked.
            # Resume partial sends until the server closes, without reading responses.
            while time.monotonic() < deadline and not closed:
                for i in range(256):
                    struct.pack_into("<Q", requests, i * len(frame) + 12, sequence + i)
                sequence += 256
                offset = 0
                while offset < len(requests) and time.monotonic() < deadline:
                    try:
                        count = peer.socket.send(requests[offset:])
                        if count == 0:
                            closed = True
                            break
                        offset += count
                        sent += count
                    except socket.timeout:
                        continue
                    except (ConnectionResetError, ConnectionAbortedError):
                        closed = True
                        break
            self.assertTrue(closed, f"Stalled peer retained its worker after sending {sent} bytes")
            time.sleep(0.05)
            for bystander in bystanders:
                self.assertEqual(bystander.request(20, b"\x01x").opcode, 21)
            with Peer(port) as recovered:
                self.assertEqual(recovered.request(20, b"\x01x").opcode, 21)

    def test_dense_alias_invalidation_at_resource_limit(self):
        requests = [
            wire.fluidlink_v2_request(
                opcode=1,
                sequence=1,
                payload=wire.encode_hello_payload(
                    client_name="dense-alias-test", client_version="1"
                ),
            )
        ]
        events = [event(102, id=str(i), memory="ram", aliases=["shared"]) for i in range(4095)]
        events += [
            event(102, id="vram", memory="vram"),
            op("seed", source="0"),
            op("duplicate", source="0"),
            op("write", operation_type="draw", target="4094"),
            op("fresh", source="0"),
        ]
        requests.extend(
            wire.fluidlink_v2_request(
                opcode=10, sequence=i, session_id=IDENTITY, subject_opcode=subject, payload=payload
            )
            for i, (subject, payload) in enumerate(events, 2)
        )
        result = subprocess.run(
            [str(TEST_BINARY), "--replay"],
            text=True,
            capture_output=True,
            input="\n".join(wire.encode_fluidlink_v2_frame(r).hex() for r in requests),
            check=True,
            timeout=10,
        )
        responses = [
            wire.decode_fluidlink_v2_frame(bytes.fromhex(line))
            for line in result.stdout.splitlines()
        ]
        self.assertEqual(len(responses), len(requests))
        self.assertTrue(all(response.ok for response in responses))
        self.assertEqual([response.decision_opcode for response in responses[-4:]], [0, 2, 0, 0])
