from __future__ import annotations

import hashlib
import io
import json
import socket
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from fluidgateway.fluidlink import (
    FLUIDLINK_CONTRACT_SHA256,
    FLUIDLINK_HEADER_SIZE,
    FLUIDLINK_MAGIC,
    FLUIDLINK_MAX_JSON_DEPTH,
    FLUIDLINK_MAX_PAYLOAD_BYTES,
    FLUIDLINK_PROTOCOL,
    FLUIDLINK_WIRE_VERSION,
    FluidLinkDecisionOpcode,
    FluidLinkEventOpcode,
    FluidLinkFrame,
    FluidLinkOpcode,
    FluidLinkProtocolError,
    decode_fluidlink_frame,
    encode_fluidlink_frame,
    estimate_equivalent_json_envelope_size,
    fluidlink_request,
    read_fluidlink_frame,
)
from fluidgateway.server import create_runtime_event_server


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CAPABILITIES = [
    "binary.framing.v1",
    "compact.decisions.v1",
    "heartbeat.v1",
    "runtime.decisions.v1",
    "runtime.events.v1",
    "session.lifecycle.v1",
]
REQUIRED_CAPABILITIES = [
    "binary.framing.v1",
    "compact.decisions.v1",
    "runtime.decisions.v1",
    "runtime.events.v1",
]


class FluidLinkTests(unittest.TestCase):
    def test_negotiates_and_returns_a_real_runtime_decision(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            with socket.create_connection((host, port), timeout=5) as connection:
                with connection.makefile("rwb", buffering=0) as stream:
                    welcome = exchange(
                        stream,
                        request(
                            1,
                            FluidLinkOpcode.HELLO,
                            hello_payload(),
                        ),
                    )
                    self.assertTrue(welcome.ok)
                    self.assertEqual(welcome.opcode, FluidLinkOpcode.WELCOME)
                    self.assertEqual(
                        welcome.payload["contract_sha256"],
                        FLUIDLINK_CONTRACT_SHA256,
                    )
                    self.assertIsNotNone(welcome.session_id)
                    session_id = welcome.session_id

                    events = [
                        (
                            FluidLinkEventOpcode.SESSION,
                            {"action": "begin", "id": "link-test"},
                        ),
                        (
                            FluidLinkEventOpcode.RESOURCE,
                            {
                                "id": "ram-buffer",
                                "kind": "buffer",
                                "memory": "ram",
                                "size_mb": 64,
                            },
                        ),
                        (
                            FluidLinkEventOpcode.RESOURCE,
                            {
                                "id": "vram-buffer",
                                "kind": "buffer",
                                "memory": "vram",
                                "size_mb": 64,
                            },
                        ),
                        (
                            FluidLinkEventOpcode.OPERATION,
                            {
                                "id": "upload-1",
                                "operation_type": "upload",
                                "source": "ram-buffer",
                                "target": "vram-buffer",
                                "queue": "copy",
                                "cost_ms": 0.8,
                                "size_mb": 64,
                            },
                        ),
                        (
                            FluidLinkEventOpcode.OPERATION,
                            {
                                "id": "upload-2",
                                "operation_type": "upload",
                                "source": "ram-buffer",
                                "target": "vram-buffer",
                                "queue": "copy",
                                "cost_ms": 0.8,
                                "size_mb": 64,
                            },
                        ),
                    ]
                    responses = [
                        exchange(
                            stream,
                            request(
                                sequence,
                                FluidLinkOpcode.RUNTIME_EVENT,
                                event,
                                session_id,
                                event_opcode,
                            ),
                        )
                        for sequence, (event_opcode, event) in enumerate(
                            events, start=2
                        )
                    ]
                    first = responses[-2]
                    duplicate = responses[-1]
                    self.assertTrue(first.payload["executed"])
                    self.assertEqual(
                        first.decision_opcode,
                        FluidLinkDecisionOpcode.EXECUTE,
                    )
                    self.assertFalse(duplicate.payload["executed"])
                    self.assertEqual(
                        duplicate.decision_opcode,
                        FluidLinkDecisionOpcode.DEDUPLICATE_IDENTICAL_TRANSFER,
                    )
                    self.assertEqual(duplicate.subject_opcode, 103)
                    self.assertEqual(duplicate.payload["saved_ms"], 0.8)
                    self.assertEqual(duplicate.payload["saved_mb"], 64.0)
                    self.assertNotIn("policy", duplicate.payload)

                    pong = exchange(
                        stream,
                        request(
                            7,
                            FluidLinkOpcode.PING,
                            {"nonce": "probe"},
                            session_id,
                        ),
                    )
                    self.assertEqual(pong.opcode, FluidLinkOpcode.PONG)
                    self.assertEqual(pong.payload["nonce"], "probe")

                    goodbye = exchange(
                        stream,
                        request(8, FluidLinkOpcode.GOODBYE, {}, session_id),
                    )
                    self.assertEqual(goodbye.payload, {"closed": True})

            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_requires_hello_before_runtime_events(self):
        response = single_binary_exchange(
            request(
                1,
                FluidLinkOpcode.RUNTIME_EVENT,
                {"action": "snapshot"},
                subject_opcode=FluidLinkEventOpcode.STATE,
            )
        )
        self.assertFalse(response.ok)
        self.assertEqual(response.opcode, FluidLinkOpcode.ERROR)
        self.assertEqual(response.payload["code"], "handshake_required")

    def test_rejects_unavailable_required_capability(self):
        response = single_binary_exchange(
            request(
                1,
                FluidLinkOpcode.HELLO,
                {
                    "contract_sha256": FLUIDLINK_CONTRACT_SHA256,
                    "client": {"name": "test-runtime", "version": "0.1"},
                    "capabilities": ["kernel.scheduler.write.v1"],
                    "required_capabilities": ["kernel.scheduler.write.v1"],
                },
            )
        )
        self.assertFalse(response.ok)
        self.assertEqual(
            response.payload["code"],
            "required_capability_unavailable",
        )

    def test_rejects_contract_drift_during_handshake(self):
        payload = hello_payload()
        payload["contract_sha256"] = "0" * 64
        response = single_binary_exchange(
            request(1, FluidLinkOpcode.HELLO, payload)
        )
        self.assertFalse(response.ok)
        self.assertEqual(response.payload["code"], "contract_mismatch")

    def test_rejects_sequence_drift_after_handshake(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                with connection.makefile("rwb", buffering=0) as stream:
                    welcome = exchange(
                        stream,
                        request(1, FluidLinkOpcode.HELLO, hello_payload()),
                    )
                    response = exchange(
                        stream,
                        request(
                            4,
                            FluidLinkOpcode.PING,
                            {},
                            welcome.session_id,
                        ),
                    )
                    self.assertFalse(response.ok)
                    self.assertEqual(response.payload["code"], "sequence_mismatch")
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_capability_error_consumes_the_valid_request_sequence(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                with connection.makefile("rwb", buffering=0) as stream:
                    welcome = exchange(
                        stream,
                        request(
                            1,
                            FluidLinkOpcode.HELLO,
                            hello_payload(
                                capabilities=["runtime.events.v1"],
                                required=[],
                            ),
                        ),
                    )
                    rejected = exchange(
                        stream,
                        request(
                            2,
                            FluidLinkOpcode.RUNTIME_EVENT,
                            {},
                            welcome.session_id,
                            FluidLinkEventOpcode.STATE,
                        ),
                    )
                    self.assertEqual(
                        rejected.payload["code"],
                        "capability_not_negotiated",
                    )
                    goodbye = exchange(
                        stream,
                        request(
                            3,
                            FluidLinkOpcode.GOODBYE,
                            {},
                            welcome.session_id,
                        ),
                    )
                    self.assertTrue(goodbye.ok)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_legacy_jsonl_event_remains_supported(self):
        response = single_legacy_exchange(
            {
                "event": "resource",
                "id": "legacy-buffer",
                "kind": "buffer",
                "memory": "ram",
                "size_mb": 4,
            }
        )
        self.assertTrue(response["ok"])
        self.assertEqual(response["event"], "resource")

    def test_legacy_jsonl_rejects_invalid_utf8_without_crashing(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                with connection.makefile("rwb") as stream:
                    stream.write(b"\xff\n")
                    stream.flush()
                    response = json.loads(stream.readline())
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertFalse(response["ok"])
        self.assertIn("UTF-8", response["error"])

    def test_legacy_short_line_does_not_consume_the_next_event(self):
        event = {
            "event": "resource",
            "id": "legacy-buffer",
            "kind": "buffer",
            "memory": "ram",
            "size_mb": 4,
        }
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                with connection.makefile("rwb") as stream:
                    stream.write(b"F\n")
                    stream.write(json.dumps(event).encode("utf-8") + b"\n")
                    stream.flush()
                    invalid_response = json.loads(stream.readline())
                    event_response = json.loads(stream.readline())
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertFalse(invalid_response["ok"])
        self.assertTrue(event_response["ok"])
        self.assertEqual(event_response["event"], "resource")

    def test_rejects_unknown_message_opcode_after_handshake(self):
        response = negotiated_binary_exchange(opcode=99, payload={})
        self.assertEqual(response.opcode, FluidLinkOpcode.ERROR)
        self.assertEqual(response.payload["code"], "unsupported_opcode")

    def test_rejects_unknown_runtime_event_opcode(self):
        response = negotiated_binary_exchange(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=199,
            payload={},
        )
        self.assertEqual(response.opcode, FluidLinkOpcode.ERROR)
        self.assertEqual(response.payload["code"], "unsupported_event_opcode")

    def test_binary_header_encodes_opcodes_without_symbolic_names(self):
        frame = request(
            2,
            FluidLinkOpcode.RUNTIME_EVENT,
            {"id": "upload-1"},
            b"\x02" * 16,
            FluidLinkEventOpcode.OPERATION,
            message_id=b"\x01" * 16,
        )
        wire = encode_fluidlink_frame(frame)
        decoded = decode_fluidlink_frame(wire)

        self.assertEqual(len(wire), FLUIDLINK_HEADER_SIZE + 17)
        self.assertEqual(wire[:4], FLUIDLINK_MAGIC)
        self.assertEqual(wire[4], FLUIDLINK_WIRE_VERSION)
        self.assertEqual(wire[6], FluidLinkOpcode.RUNTIME_EVENT)
        self.assertEqual(wire[7], FluidLinkEventOpcode.OPERATION)
        self.assertEqual(wire[8], FluidLinkDecisionOpcode.EXECUTE)
        self.assertNotIn(b"runtime.event", wire)
        self.assertNotIn(b"operation", wire[:FLUIDLINK_HEADER_SIZE])
        self.assertEqual(decoded, frame)

    def test_binary_frame_is_smaller_than_symbolic_json_envelope(self):
        frame = request(
            2,
            FluidLinkOpcode.RUNTIME_EVENT,
            {"id": "x"},
            b"\x02" * 16,
            FluidLinkEventOpcode.OPERATION,
            message_id=b"\x01" * 16,
        )
        binary = encode_fluidlink_frame(frame)
        equivalent_json_bytes = estimate_equivalent_json_envelope_size(frame)
        self.assertLess(len(binary), equivalent_json_bytes)

    def test_fragmented_reader_reassembles_a_complete_frame(self):
        frame = request(1, FluidLinkOpcode.HELLO, hello_payload())
        reader = FragmentedReader(encode_fluidlink_frame(frame), chunk_size=3)
        decoded = read_fluidlink_frame(reader)
        self.assertEqual(decoded, frame)

    def test_truncated_frame_fails_closed(self):
        frame = request(1, FluidLinkOpcode.HELLO, hello_payload())
        reader = io.BytesIO(encode_fluidlink_frame(frame)[:-1])
        with self.assertRaises(FluidLinkProtocolError) as context:
            read_fluidlink_frame(reader)
        self.assertEqual(context.exception.code, "truncated_frame")

    def test_payload_over_limit_is_rejected_before_transport(self):
        frame = request(
            1,
            FluidLinkOpcode.HELLO,
            {"value": "x" * FLUIDLINK_MAX_PAYLOAD_BYTES},
        )
        with self.assertRaises(FluidLinkProtocolError) as context:
            encode_fluidlink_frame(frame)
        self.assertEqual(context.exception.code, "payload_too_large")

    def test_encoder_rejects_boolean_sequence_and_invalid_identity_type(self):
        boolean_sequence = request(
            True,
            FluidLinkOpcode.HELLO,
            hello_payload(),
        )
        with self.assertRaises(FluidLinkProtocolError) as sequence_context:
            encode_fluidlink_frame(boolean_sequence)
        self.assertEqual(sequence_context.exception.code, "invalid_sequence")

        invalid_identity = replace(
            request(
                1,
                FluidLinkOpcode.HELLO,
                hello_payload(),
            ),
            message_id="not-bytes",  # type: ignore[arg-type]
        )
        with self.assertRaises(FluidLinkProtocolError) as identity_context:
            encode_fluidlink_frame(invalid_identity)
        self.assertEqual(identity_context.exception.code, "invalid_message_id")

    def test_non_finite_json_number_is_rejected(self):
        frame = request(
            1,
            FluidLinkOpcode.HELLO,
            {"value": float("nan")},
        )
        with self.assertRaises(FluidLinkProtocolError) as context:
            encode_fluidlink_frame(frame)
        self.assertEqual(context.exception.code, "invalid_payload")

    def test_decoder_rejects_non_finite_json_number(self):
        frame = request(1, FluidLinkOpcode.HELLO, {"value": 0.0})
        wire = encode_fluidlink_frame(frame).replace(b"0.0", b"NaN")
        with self.assertRaises(FluidLinkProtocolError) as context:
            decode_fluidlink_frame(wire)
        self.assertEqual(context.exception.code, "invalid_payload")

    def test_decoder_rejects_unknown_flags_and_reserved_bits(self):
        frame = request(1, FluidLinkOpcode.HELLO, hello_payload())
        unknown_flags = bytearray(encode_fluidlink_frame(frame))
        unknown_flags[9] |= 0x80
        with self.assertRaises(FluidLinkProtocolError) as flags_context:
            decode_fluidlink_frame(bytes(unknown_flags))
        self.assertEqual(flags_context.exception.code, "invalid_flags")

        reserved = bytearray(encode_fluidlink_frame(frame))
        reserved[10] = 1
        with self.assertRaises(FluidLinkProtocolError) as reserved_context:
            decode_fluidlink_frame(bytes(reserved))
        self.assertEqual(
            reserved_context.exception.code,
            "invalid_reserved_bits",
        )

    def test_payload_over_json_depth_limit_is_rejected(self):
        value: dict[str, Any] = {"leaf": True}
        for _ in range(FLUIDLINK_MAX_JSON_DEPTH):
            value = {"nested": value}
        frame = request(1, FluidLinkOpcode.HELLO, value)
        with self.assertRaises(FluidLinkProtocolError) as context:
            encode_fluidlink_frame(frame)
        self.assertEqual(context.exception.code, "invalid_payload")

    def test_ping_requires_a_bounded_string_nonce(self):
        response = negotiated_binary_exchange(
            opcode=FluidLinkOpcode.PING,
            payload={"nonce": "x" * 129},
        )
        self.assertFalse(response.ok)
        self.assertEqual(response.payload["code"], "invalid_ping")

    def test_contract_manifest_is_bundled(self):
        path = ROOT / "contracts" / "fluidlink-v1.contract.json"
        content = path.read_bytes()
        contract = json.loads(content)
        self.assertEqual(contract["contract"], FLUIDLINK_PROTOCOL)
        self.assertEqual(contract["wire"]["header_size"], FLUIDLINK_HEADER_SIZE)
        self.assertEqual(contract["header"][-1]["offset"], 52)
        self.assertEqual(contract["opcodes"]["runtime_event"], 10)
        self.assertEqual(contract["event_opcodes"]["operation"], 103)
        self.assertEqual(contract["decision_opcodes"]["unknown"], 255)
        self.assertEqual(
            contract["limits"]["max_json_depth"],
            FLUIDLINK_MAX_JSON_DEPTH,
        )
        self.assertEqual(
            contract["handshake"]["contract_rule"],
            "exact-sha256-match",
        )
        self.assertEqual(
            hashlib.sha256(content).hexdigest(),
            FLUIDLINK_CONTRACT_SHA256,
        )


class FragmentedReader(io.BytesIO):
    def __init__(self, data: bytes, *, chunk_size: int) -> None:
        super().__init__(data)
        self.chunk_size = chunk_size

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.chunk_size
        return super().read(min(size, self.chunk_size))


def hello_payload(
    *,
    capabilities: list[str] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_sha256": FLUIDLINK_CONTRACT_SHA256,
        "client": {"name": "test-runtime", "version": "0.1"},
        "capabilities": capabilities if capabilities is not None else RUNTIME_CAPABILITIES,
        "required_capabilities": (
            required if required is not None else REQUIRED_CAPABILITIES
        ),
    }


def request(
    sequence: int,
    opcode: int,
    payload: dict[str, Any],
    session_id: bytes | None = None,
    subject_opcode: int = 0,
    *,
    message_id: bytes | None = None,
) -> FluidLinkFrame:
    return fluidlink_request(
        opcode=opcode,
        sequence=sequence,
        payload=payload,
        session_id=session_id,
        subject_opcode=subject_opcode,
        message_id=message_id,
    )


def exchange(stream, frame: FluidLinkFrame) -> FluidLinkFrame:
    stream.write(encode_fluidlink_frame(frame))
    response = read_fluidlink_frame(stream)
    if response is None:
        raise AssertionError("FluidLink server closed without a response.")
    return response


def single_binary_exchange(frame: FluidLinkFrame) -> FluidLinkFrame:
    with create_runtime_event_server("127.0.0.1", 0) as server:
        server.timeout = 5
        host, port = server.server_address
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        with socket.create_connection((host, port), timeout=5) as connection:
            with connection.makefile("rwb", buffering=0) as stream:
                response = exchange(stream, frame)
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("FluidLink test server did not stop.")
        return response


def single_legacy_exchange(payload: dict[str, Any]) -> dict[str, Any]:
    with create_runtime_event_server("127.0.0.1", 0) as server:
        server.timeout = 5
        host, port = server.server_address
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        with socket.create_connection((host, port), timeout=5) as connection:
            with connection.makefile("rwb") as stream:
                stream.write(json.dumps(payload).encode("utf-8") + b"\n")
                stream.flush()
                line = stream.readline()
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("FluidLink legacy test server did not stop.")
        return json.loads(line)


def negotiated_binary_exchange(
    *,
    opcode: int,
    payload: dict[str, Any],
    subject_opcode: int = 0,
) -> FluidLinkFrame:
    with create_runtime_event_server("127.0.0.1", 0) as server:
        server.timeout = 5
        host, port = server.server_address
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        with socket.create_connection((host, port), timeout=5) as connection:
            with connection.makefile("rwb", buffering=0) as stream:
                welcome = exchange(
                    stream,
                    request(1, FluidLinkOpcode.HELLO, hello_payload()),
                )
                response = exchange(
                    stream,
                    request(
                        2,
                        opcode,
                        payload,
                        welcome.session_id,
                        subject_opcode,
                    ),
                )
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("FluidLink test server did not stop.")
        return response


if __name__ == "__main__":
    unittest.main()
