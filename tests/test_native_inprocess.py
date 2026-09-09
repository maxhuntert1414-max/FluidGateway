from __future__ import annotations

from dataclasses import replace
import json
import socket
import unittest

from fluidgateway import fluidlink_v2 as wire
from tests import test_native_gateway as reference
from tools.native_gateway_dll import DllSession, native_library
from tools.native_gateway_validation import ROOT, native_executable, server


@unittest.skipUnless(
    native_library().exists() and native_executable().exists(), "Build the native DLL/server"
)
class NativeInProcessTests(unittest.TestCase):
    def compare(self, events, batch=False):
        hello = wire.encode_hello_payload(
            client_name="parity",
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
        requests = [(1, 0, hello)] + [(10, subject, payload) for subject, payload in events]
        with (
            DllSession() as dll,
            socket.create_connection(("127.0.0.1", self.port), timeout=5) as tcp,
        ):
            tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with tcp.makefile("rb") as stream:
                identities = [None, None]
                for sequence, (opcode, subject, payload) in enumerate(requests, 1):
                    request = wire.fluidlink_v2_request(
                        opcode=opcode,
                        subject_opcode=subject,
                        sequence=sequence,
                        payload=payload,
                        session_id=identities[0],
                    )
                    tcp.sendall(wire.encode_fluidlink_v2_frame(request))
                    actual = wire.read_fluidlink_v2_frame(stream)
                    other = wire.decode_fluidlink_v2_frame(
                        dll.exchange(
                            wire.encode_fluidlink_v2_frame(
                                replace(request, session_id=identities[1])
                            )
                        )
                    )
                    self.assertIsNotNone(actual)
                    # Only the fresh session UUID is nondeterministic, not error text or payload.
                    self.assertEqual(
                        wire.encode_fluidlink_v2_frame(
                            replace(actual, session_id=other.session_id)
                        ),
                        wire.encode_fluidlink_v2_frame(other),
                        sequence,
                    )
                    if sequence == 1:
                        identities = [actual.session_id, other.session_id]
                    if dll.metrics().closed:
                        self.assertIsNone(wire.read_fluidlink_v2_frame(stream))
                        self.assertEqual(
                            dll.exchange_status(wire.encode_fluidlink_v2_frame(request))[0], 6
                        )
                        break
                return dll.metrics()

    def test_existing_differential_corpus(self):
        with server() as (_, self.port):
            corpus = reference.NativeGatewayTests()
            corpus.compare = self.compare
            for name in (
                "copy_write_and_dependency",
                "readback_source_write",
                "alias_release_resize",
                "frame_queue_and_unknown_write",
                "invalid_events",
                "utf8_and_trim",
                "batch_parity_and_partial_rejection",
                "randomized_operation",
            ):
                method = (
                    "test_"
                    + name
                    + ("" if name == "batch_parity_and_partial_rejection" else "_parity")
                )
                with self.subTest(case=method):
                    getattr(corpus, method)()

    def test_golden_requests(self):
        with server() as (_, self.port):
            for name in ("fluidlink-v2.golden.json", "fluidlink-v2-batch.golden.json"):
                for vector in json.loads((ROOT / "contracts" / name).read_text())["vectors"]:
                    frame = wire.decode_fluidlink_v2_frame(bytes.fromhex(vector["wire_hex"]))
                    if frame.opcode == 10 and frame.kind == 1:
                        with self.subTest(vector=vector.get("name")):
                            self.compare(
                                reference.setup_events() + [(frame.subject_opcode, frame.payload)],
                                batch="batch" in name,
                            )

    def test_truncation_and_fresh_session(self):
        with DllSession() as first:
            initial = first.metrics().state_bytes
            self.assertEqual(first.exchange_status(b"FLNK")[0], 7)
            self.assertEqual(first.metrics().closed, 1)
        with DllSession() as fresh:
            metrics = fresh.metrics()
            self.assertEqual(
                (metrics.closed, metrics.exchanges, metrics.tracked_operations), (0, 0, 0)
            )
            self.assertEqual(metrics.state_bytes, initial)

    def test_state_bounds_match_server_and_retire_without_partial_batch(self):
        with server() as (_, self.port):
            cases = [
                [reference.event(102, id=f"r{i}") for i in range(4097)],
                [
                    reference.event(
                        102, id=f"r{i}", aliases=[f"{j:03d}" + "x" * 253 for j in range(32)]
                    )
                    for i in range(1100)
                ],
                reference.setup_events()
                + [
                    (
                        105,
                        wire.encode_operation_batch_event_payload(
                            dict(
                                batch_id=f"{i + 1:032x}",
                                operation_count=256,
                                operation_type="upload",
                                source="ram",
                                target="vram",
                                queue="copy",
                                size_bytes=4096,
                                cost_us=0,
                            )
                        ),
                    )
                    for i in range(65)
                ],
            ]
            for index, events in enumerate(cases):
                with self.subTest(bound=index):
                    metrics = self.compare(events, batch=True)
                    self.assertEqual(metrics.closed, 1)
                    self.assertLessEqual(metrics.state_peak_bytes, 8 * 1024 * 1024)
                    self.assertLessEqual(metrics.active_resources, 4096)
                    self.assertLessEqual(metrics.tracked_operations, 16384)

    def test_integer_extremes_and_alias_writes(self):
        with server() as (_, self.port):
            self.compare(
                reference.setup_events()
                + [
                    reference.op("a", size_bytes=2**53),
                    reference.op("b", size_bytes=2**53 + 1),
                    reference.op("c", size_bytes=2**64 - 1, cost_us=2**32 - 1),
                    reference.op("d", size_bytes=2**64 - 1, cost_us=2**32 - 1),
                ]
            )
