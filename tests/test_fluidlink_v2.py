from __future__ import annotations

import hashlib
import io
import json
import socket
import threading
import unittest
from pathlib import Path

from fluidgateway.fluidlink import (
    FluidLinkDecisionOpcode,
    FluidLinkEventOpcode,
    FluidLinkOpcode,
    FluidLinkProtocolError,
    encode_fluidlink_frame,
    fluidlink_request,
)
from fluidgateway.fluidlink_v2 import (
    FLUIDLINK_V2_BATCH_CAPABILITIES,
    FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
    FLUIDLINK_V2_BATCH_CONTRACT_SHA256,
    FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES,
    FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE,
    FLUIDLINK_V2_CAPABILITIES,
    FLUIDLINK_V2_CONTRACT_SHA256,
    FLUIDLINK_V2_HEADER_SIZE,
    FLUIDLINK_V2_MAX_BATCH_OPERATIONS,
    FLUIDLINK_V2_MAX_PAYLOAD_BYTES,
    FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
    FLUIDLINK_V2_REQUIRED_CAPABILITIES,
    FLUIDLINK_V2_WIRE_VERSION,
    FluidLinkV2Capability,
    FluidLinkV2ErrorCode,
    FluidLinkV2ServerSession,
    decode_error_payload,
    decode_fluidlink_v2_frame,
    decode_hello_payload,
    decode_nonce_payload,
    decode_operation_batch_decision_payload,
    decode_operation_batch_event_payload,
    decode_runtime_decision_payload,
    decode_runtime_event_payload,
    decode_welcome_payload,
    encode_error_payload,
    encode_fluidlink_v2_frame,
    encode_hello_payload,
    encode_nonce_payload,
    encode_operation_batch_decision_payload,
    encode_operation_batch_event_payload,
    encode_runtime_decision_payload,
    encode_runtime_event_payload,
    encode_welcome_payload,
    fluidlink_v2_request,
    fluidlink_v2_response,
    read_fluidlink_v2_frame,
)
from fluidgateway.server import create_runtime_event_server


ROOT = Path(__file__).resolve().parents[1]
MESSAGE_ID = bytes(range(1, 17))
SESSION_ID = bytes(range(17, 33))


class FluidLinkV2Tests(unittest.TestCase):
    def test_contract_fingerprint_and_layout_are_canonical(self):
        path = ROOT / "contracts" / "fluidlink-v2.contract.json"
        content = path.read_bytes()
        contract = json.loads(content)

        self.assertEqual(FLUIDLINK_V2_CONTRACT_SHA256, hashlib.sha256(content).hexdigest())
        self.assertEqual("fluidlink-v2", contract["contract"])
        self.assertEqual(2, contract["wire"]["version"])
        self.assertEqual(FLUIDLINK_V2_HEADER_SIZE, contract["wire"]["header_size"])
        self.assertEqual(
            FLUIDLINK_V2_MAX_PAYLOAD_BYTES,
            contract["wire"]["max_payload_bytes"],
        )
        self.assertEqual(
            int(FLUIDLINK_V2_REQUIRED_CAPABILITIES),
            contract["required_capability_mask"],
        )

    def test_batch_contract_fingerprint_and_extension_are_canonical(self):
        path = ROOT / "contracts" / "fluidlink-v2-batch.contract.json"
        content = path.read_bytes()
        contract = json.loads(content)

        self.assertEqual(
            FLUIDLINK_V2_BATCH_CONTRACT_SHA256,
            hashlib.sha256(content).hexdigest(),
        )
        self.assertEqual(
            FLUIDLINK_V2_CONTRACT_SHA256,
            contract["extends"]["contract_sha256"],
        )
        self.assertEqual(
            FLUIDLINK_V2_MAX_BATCH_OPERATIONS,
            contract["limits"]["max_batch_operations"],
        )
        self.assertEqual(
            FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            contract["event_opcodes"]["operation_batch"],
        )
        self.assertEqual(
            FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE,
            contract["decision_opcodes"]["batch_vector"],
        )

    def test_batch_golden_vectors_match_the_canonical_encoder(self):
        fixture = json.loads(
            (ROOT / "contracts" / "fluidlink-v2-batch.golden.json").read_text(
                encoding="utf-8"
            )
        )
        message_id = bytes.fromhex(fixture["message_id_hex"])
        session_id = bytes.fromhex(fixture["session_id_hex"])
        batch_id = fixture["batch_id_hex"]
        hello = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            message_id=message_id,
            payload=encode_hello_payload(
                client_name="fluidruntime",
                client_version="0.17.0",
                requested_capabilities=FLUIDLINK_V2_BATCH_CAPABILITIES,
                required_capabilities=FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES,
                contract_digest=FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
            ),
        )
        batch = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            sequence=2,
            message_id=message_id,
            session_id=session_id,
            payload=encode_operation_batch_event_payload(
                {
                    "batch_id": batch_id,
                    "operation_count": 2,
                    "operation_type": "upload",
                    "queue": "copy",
                    "source": "ram-buffer",
                    "target": "vram-texture",
                    "reason": "duplicate upload",
                    "cost_us": 800,
                    "size_bytes": 64 * 1024**2,
                    "frame": 42,
                    "depends_on": ["allocate-1"],
                }
            ),
        )
        frames = {
            "batch_hello_request": hello,
            "batch_welcome_response": fluidlink_v2_response(
                hello,
                opcode=FluidLinkOpcode.WELCOME,
                session_id=session_id,
                payload=encode_welcome_payload(
                    available_capabilities=FLUIDLINK_V2_BATCH_CAPABILITIES,
                    accepted_capabilities=FLUIDLINK_V2_BATCH_CAPABILITIES,
                    server_name="fluidgateway",
                    server_version="0.65.0",
                    contract_digest=FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
                ),
            ),
            "operation_batch_request": batch,
            "operation_batch_decision_response": fluidlink_v2_response(
                batch,
                opcode=FluidLinkOpcode.RUNTIME_DECISION,
                subject_opcode=FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
                decision_opcode=FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE,
                session_id=session_id,
                payload=encode_operation_batch_decision_payload(
                    {
                        "batch_id": batch_id,
                        "decisions": [
                            {
                                "decision_opcode": FluidLinkDecisionOpcode.EXECUTE,
                                "accepted": True,
                                "executed": True,
                                "saved_us": 0,
                                "saved_bytes": 0,
                            },
                            {
                                "decision_opcode": (
                                    FluidLinkDecisionOpcode
                                    .DEDUPLICATE_IDENTICAL_TRANSFER
                                ),
                                "accepted": True,
                                "executed": False,
                                "saved_us": 800,
                                "saved_bytes": 64 * 1024**2,
                            },
                        ],
                    }
                ),
            ),
        }

        self.assertEqual(
            FLUIDLINK_V2_BATCH_CONTRACT_SHA256,
            fixture["contract_sha256"],
        )
        for vector in fixture["vectors"]:
            wire = encode_fluidlink_v2_frame(frames[vector["name"]])
            self.assertEqual(vector["wire_bytes"], len(wire), vector["name"])
            self.assertEqual(vector["wire_hex"], wire.hex(), vector["name"])

    def test_operation_batch_payloads_round_trip_and_enforce_limits(self):
        batch_id = "0102030405060708090a0b0c0d0e0f10"
        event = {
            "batch_id": batch_id,
            "operation_count": 2,
            "operation_type": "upload",
            "queue": "copy",
            "source": "ram-buffer",
            "target": "vram-texture",
            "reason": "same upload fingerprint",
            "cost_us": 800,
            "size_bytes": 64 * 1024**2,
            "frame": 42,
            "depends_on": ["allocation-1"],
        }
        encoded_event = encode_operation_batch_event_payload(event)
        decoded_event = decode_operation_batch_event_payload(encoded_event)

        self.assertEqual(batch_id, decoded_event["batch_id"])
        self.assertEqual(2, decoded_event["operation_count"])
        self.assertEqual(800, decoded_event["cost_us"])
        self.assertEqual(64 * 1024**2, decoded_event["size_bytes"])
        self.assertEqual(["allocation-1"], decoded_event["depends_on"])
        self.assertNotIn(b"operation_count", encoded_event)

        encoded_decision = encode_operation_batch_decision_payload(
            {
                "batch_id": batch_id,
                "decisions": [
                    {
                        "decision_opcode": FluidLinkDecisionOpcode.EXECUTE,
                        "accepted": True,
                        "executed": True,
                        "saved_us": 0,
                        "saved_bytes": 0,
                    },
                    {
                        "decision_opcode": (
                            FluidLinkDecisionOpcode.DEDUPLICATE_IDENTICAL_TRANSFER
                        ),
                        "accepted": True,
                        "executed": False,
                        "saved_us": 800,
                        "saved_bytes": 64 * 1024**2,
                    },
                ],
            }
        )
        decoded_decision = decode_operation_batch_decision_payload(encoded_decision)

        self.assertEqual(batch_id, decoded_decision["batch_id"])
        self.assertEqual(2, len(decoded_decision["decisions"]))
        self.assertTrue(decoded_decision["decisions"][0]["executed"])
        self.assertFalse(decoded_decision["decisions"][1]["executed"])
        self.assertEqual(800, decoded_decision["decisions"][1]["saved_us"])

        for invalid_count in (0, FLUIDLINK_V2_MAX_BATCH_OPERATIONS + 1):
            with self.subTest(invalid_count=invalid_count):
                with self.assertRaisesRegex(FluidLinkProtocolError, "between 1 and"):
                    encode_operation_batch_event_payload(
                        {**event, "operation_count": invalid_count}
                    )
        with self.assertRaisesRegex(FluidLinkProtocolError, "nonzero-identity"):
            encode_operation_batch_event_payload(
                {**event, "batch_id": "0" * 32}
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "disagree"):
            encode_operation_batch_decision_payload(
                {
                    "batch_id": batch_id,
                    "decisions": [
                        {
                            "decision_opcode": FluidLinkDecisionOpcode.EXECUTE,
                            "accepted": True,
                            "executed": False,
                        }
                    ],
                }
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "trailing bytes"):
            decode_operation_batch_event_payload(encoded_event + b"\x00")

    def test_server_keeps_batch_messages_out_of_the_base_profile(self):
        session = FluidLinkV2ServerSession(
            server_name="fluidgateway", server_version="0.65.0"
        )
        hello = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=encode_hello_payload(
                client_name="fluidruntime", client_version="0.15.0"
            ),
        )
        welcome_frame = session.process(hello, lambda event: {"ok": True})
        welcome = decode_welcome_payload(welcome_frame.payload)
        self.assertEqual(FLUIDLINK_V2_CAPABILITIES, welcome.available_capabilities)
        self.assertEqual(FLUIDLINK_V2_CAPABILITIES, welcome.accepted_capabilities)

        request = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            sequence=2,
            message_id=MESSAGE_ID,
            session_id=welcome_frame.session_id,
            payload=encode_operation_batch_event_payload(
                {
                    "batch_id": "0102030405060708090a0b0c0d0e0f10",
                    "operation_count": 1,
                    "operation_type": "copy",
                }
            ),
        )
        response = session.process(request, lambda event: {"ok": True})
        code, _ = decode_error_payload(response.payload)

        self.assertEqual(FluidLinkOpcode.ERROR, response.opcode)
        self.assertEqual("capability_not_negotiated", code)

    def test_server_requires_batch_capability_for_batch_contract(self):
        session = FluidLinkV2ServerSession(
            server_name="fluidgateway", server_version="0.65.0"
        )
        hello = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=encode_hello_payload(
                client_name="fluidruntime",
                client_version="0.17.0",
                requested_capabilities=FLUIDLINK_V2_BATCH_CAPABILITIES,
                required_capabilities=FLUIDLINK_V2_REQUIRED_CAPABILITIES,
                contract_digest=FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
            ),
        )

        response = session.process(hello, lambda event: {"ok": True})
        code, message = decode_error_payload(response.payload)

        self.assertEqual(FluidLinkOpcode.ERROR, response.opcode)
        self.assertEqual("invalid_payload", code)
        self.assertIn("requires its batch capability", message)
        self.assertIsNone(session.session_id)

    def test_server_expands_batch_in_order_and_returns_a_decision_vector(self):
        session = FluidLinkV2ServerSession(
            server_name="fluidgateway", server_version="0.65.0"
        )
        hello = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=encode_hello_payload(
                client_name="fluidruntime",
                client_version="0.15.0",
                requested_capabilities=FLUIDLINK_V2_BATCH_CAPABILITIES,
                required_capabilities=FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES,
                contract_digest=FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
            ),
        )
        welcome_frame = session.process(hello, lambda event: {"ok": True})
        welcome = decode_welcome_payload(welcome_frame.payload)
        self.assertEqual(
            FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
            welcome.contract_digest,
        )
        self.assertEqual(
            FLUIDLINK_V2_BATCH_CAPABILITIES,
            welcome.accepted_capabilities,
        )

        batch_id = "0102030405060708090a0b0c0d0e0f10"
        request = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            sequence=2,
            message_id=MESSAGE_ID,
            session_id=welcome_frame.session_id,
            payload=encode_operation_batch_event_payload(
                {
                    "batch_id": batch_id,
                    "operation_count": 2,
                    "operation_type": "upload",
                    "queue": "copy",
                    "source": "ram-buffer",
                    "target": "vram-texture",
                    "cost_us": 800,
                    "size_bytes": 64 * 1024**2,
                    "frame": 42,
                }
            ),
        )
        events: list[dict[str, object]] = []

        def handle_event(event):
            events.append(event)
            if len(events) == 1:
                return {"ok": True, "result": {"executed": True}}
            return {
                "ok": True,
                "result": {
                    "executed": False,
                    "decision": {
                        "policy": "deduplicate-identical-transfer",
                        "estimated_saved_ms": 0.8,
                        "estimated_saved_mb": 64,
                    },
                },
            }

        response = session.process(request, handle_event)
        decision = decode_operation_batch_decision_payload(response.payload)

        self.assertEqual(FluidLinkOpcode.RUNTIME_DECISION, response.opcode)
        self.assertEqual(
            FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            response.subject_opcode,
        )
        self.assertEqual(
            FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE,
            response.decision_opcode,
        )
        self.assertEqual(
            [f"batch-{batch_id}-000", f"batch-{batch_id}-001"],
            [event["id"] for event in events],
        )
        self.assertEqual(batch_id, decision["batch_id"])
        self.assertEqual(
            [
                FluidLinkDecisionOpcode.EXECUTE,
                FluidLinkDecisionOpcode.DEDUPLICATE_IDENTICAL_TRANSFER,
            ],
            [item["decision_opcode"] for item in decision["decisions"]],
        )

    def test_server_closes_batch_session_without_partial_vector_on_failure(self):
        session = FluidLinkV2ServerSession(
            server_name="fluidgateway", server_version="0.65.0"
        )
        hello = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=encode_hello_payload(
                client_name="fluidruntime",
                client_version="0.15.0",
                requested_capabilities=FLUIDLINK_V2_BATCH_CAPABILITIES,
                required_capabilities=FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES,
                contract_digest=FLUIDLINK_V2_BATCH_CONTRACT_DIGEST,
            ),
        )
        welcome = session.process(hello, lambda event: {"ok": True})
        request = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            sequence=2,
            message_id=MESSAGE_ID,
            session_id=welcome.session_id,
            payload=encode_operation_batch_event_payload(
                {
                    "batch_id": "0102030405060708090a0b0c0d0e0f10",
                    "operation_count": 3,
                    "operation_type": "copy",
                }
            ),
        )
        calls = 0

        def fail_second_event(event):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic batch failure")
            return {"ok": True, "result": {"executed": True}}

        response = session.process(request, fail_second_event)
        code, message = decode_error_payload(response.payload)

        self.assertEqual(2, calls)
        self.assertTrue(session.closed)
        self.assertEqual(FluidLinkOpcode.ERROR, response.opcode)
        self.assertNotEqual(
            FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE,
            response.decision_opcode,
        )
        self.assertEqual("runtime_event_rejected", code)
        self.assertIn("synthetic batch failure", message)

    def test_golden_vectors_match_the_canonical_encoder(self):
        fixture = json.loads(
            (ROOT / "contracts" / "fluidlink-v2.golden.json").read_text(
                encoding="utf-8"
            )
        )
        message_id = bytes.fromhex(fixture["message_id_hex"])
        session_id = bytes.fromhex(fixture["session_id_hex"])
        hello = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            message_id=message_id,
            payload=encode_hello_payload(
                client_name="fluidruntime", client_version="0.14.0"
            ),
        )
        session_begin = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.SESSION,
            sequence=2,
            message_id=message_id,
            session_id=session_id,
            payload=encode_runtime_event_payload(
                FluidLinkEventOpcode.SESSION,
                {
                    "action": "begin",
                    "id": "golden",
                    "budgets": {
                        "target_frame_us": 16_667,
                        "ram_bytes": 4 * 1024**3,
                        "vram_bytes": 2 * 1024**3,
                        "shared_bytes": 1024**3,
                        "staging_bytes": 128 * 1024**2,
                        "swapchain_bytes": 64 * 1024**2,
                    },
                },
            ),
        )
        frame_begin = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.FRAME,
            sequence=3,
            message_id=message_id,
            session_id=session_id,
            payload=encode_runtime_event_payload(
                FluidLinkEventOpcode.FRAME,
                {"action": "begin", "frame": 42, "target_frame_us": 16_667},
            ),
        )
        resource_register = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.RESOURCE,
            sequence=4,
            message_id=message_id,
            session_id=session_id,
            payload=encode_runtime_event_payload(
                FluidLinkEventOpcode.RESOURCE,
                {
                    "action": "register",
                    "id": "texture-1",
                    "kind": "texture",
                    "memory": "vram",
                    "lifetime": "asset",
                    "size_bytes": 16 * 1024**2,
                    "aliases": ["hero", "diffuse"],
                },
            ),
        )
        operation = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.OPERATION,
            sequence=5,
            message_id=message_id,
            session_id=session_id,
            payload=encode_runtime_event_payload(
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": "upload-1",
                    "operation_type": "upload",
                    "source": "ram",
                    "target": "vram",
                    "reason": "duplicate upload",
                    "queue": "copy",
                    "cost_us": 800,
                    "size_bytes": 64 * 1024 * 1024,
                    "frame": 0,
                    "depends_on": ["allocate-1"],
                },
            ),
        )
        state = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.STATE,
            sequence=6,
            message_id=message_id,
            session_id=session_id,
            payload=encode_runtime_event_payload(
                FluidLinkEventOpcode.STATE, {"action": "snapshot"}
            ),
        )
        ping = fluidlink_v2_request(
            opcode=FluidLinkOpcode.PING,
            sequence=7,
            message_id=message_id,
            session_id=session_id,
            payload=encode_nonce_payload("nonce-v2"),
        )
        goodbye = fluidlink_v2_request(
            opcode=FluidLinkOpcode.GOODBYE,
            sequence=11,
            message_id=message_id,
            session_id=session_id,
            payload=b"",
        )
        frames = {
            "hello_request": hello,
            "welcome_response": fluidlink_v2_response(
                hello,
                opcode=FluidLinkOpcode.WELCOME,
                session_id=session_id,
                payload=encode_welcome_payload(
                    available_capabilities=FLUIDLINK_V2_CAPABILITIES,
                    accepted_capabilities=FLUIDLINK_V2_CAPABILITIES,
                    server_name="fluidgateway",
                    server_version="0.64.0",
                ),
            ),
            "session_begin_request": session_begin,
            "frame_begin_request": frame_begin,
            "resource_register_request": resource_register,
            "operation_request": operation,
            "operation_decision_response": fluidlink_v2_response(
                operation,
                opcode=FluidLinkOpcode.RUNTIME_DECISION,
                subject_opcode=FluidLinkEventOpcode.OPERATION,
                decision_opcode=(
                    FluidLinkDecisionOpcode.DEDUPLICATE_IDENTICAL_TRANSFER
                ),
                session_id=session_id,
                payload=encode_runtime_decision_payload(
                    {
                        "accepted": True,
                        "executed": False,
                        "saved_us": 800,
                        "saved_bytes": 64 * 1024**2,
                    }
                ),
            ),
            "state_request": state,
            "state_decision_response": fluidlink_v2_response(
                state,
                opcode=FluidLinkOpcode.RUNTIME_DECISION,
                subject_opcode=FluidLinkEventOpcode.STATE,
                decision_opcode=FluidLinkDecisionOpcode.EXECUTE,
                session_id=session_id,
                payload=encode_runtime_decision_payload({"accepted": True}),
            ),
            "ping_request": ping,
            "pong_response": fluidlink_v2_response(
                ping,
                opcode=FluidLinkOpcode.PONG,
                session_id=session_id,
                payload=encode_nonce_payload("nonce-v2"),
            ),
            "resource_release_request": fluidlink_v2_request(
                opcode=FluidLinkOpcode.RUNTIME_EVENT,
                subject_opcode=FluidLinkEventOpcode.RESOURCE,
                sequence=8,
                message_id=message_id,
                session_id=session_id,
                payload=encode_runtime_event_payload(
                    FluidLinkEventOpcode.RESOURCE,
                    {"action": "release", "id": "texture-1"},
                ),
            ),
            "frame_end_request": fluidlink_v2_request(
                opcode=FluidLinkOpcode.RUNTIME_EVENT,
                subject_opcode=FluidLinkEventOpcode.FRAME,
                sequence=9,
                message_id=message_id,
                session_id=session_id,
                payload=encode_runtime_event_payload(
                    FluidLinkEventOpcode.FRAME,
                    {"action": "end", "frame": 42},
                ),
            ),
            "session_end_request": fluidlink_v2_request(
                opcode=FluidLinkOpcode.RUNTIME_EVENT,
                subject_opcode=FluidLinkEventOpcode.SESSION,
                sequence=10,
                message_id=message_id,
                session_id=session_id,
                payload=encode_runtime_event_payload(
                    FluidLinkEventOpcode.SESSION,
                    {"action": "end", "id": ""},
                ),
            ),
            "invalid_payload_response": fluidlink_v2_response(
                state,
                opcode=FluidLinkOpcode.ERROR,
                subject_opcode=FluidLinkEventOpcode.STATE,
                decision_opcode=FluidLinkDecisionOpcode.UNKNOWN,
                session_id=session_id,
                ok=False,
                payload=encode_error_payload(
                    FluidLinkV2ErrorCode.INVALID_PAYLOAD,
                    "state payload malformed",
                ),
            ),
            "goodbye_request": goodbye,
            "goodbye_response": fluidlink_v2_response(
                goodbye,
                opcode=FluidLinkOpcode.GOODBYE,
                session_id=session_id,
                payload=b"",
            ),
        }

        self.assertEqual(FLUIDLINK_V2_CONTRACT_SHA256, fixture["contract_sha256"])
        for vector in fixture["vectors"]:
            wire = encode_fluidlink_v2_frame(frames[vector["name"]])
            self.assertEqual(vector["wire_bytes"], len(wire), vector["name"])
            self.assertEqual(vector["wire_hex"], wire.hex(), vector["name"])
            self.assertEqual(wire, encode_fluidlink_v2_frame(decode_fluidlink_v2_frame(wire)))

    def test_frame_round_trip_uses_version_two_and_binary_payload(self):
        payload = encode_runtime_event_payload(
            FluidLinkEventOpcode.OPERATION,
            {
                "id": "upload-1",
                "operation_type": "upload",
                "source": "ram-buffer",
                "target": "vram-buffer",
                "queue": "copy",
                "cost_us": 800,
                "size_bytes": 64 * 1024 * 1024,
                "frame": 0,
            },
        )
        frame = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.OPERATION,
            sequence=2,
            message_id=MESSAGE_ID,
            session_id=SESSION_ID,
            payload=payload,
        )

        wire = encode_fluidlink_v2_frame(frame)
        decoded = decode_fluidlink_v2_frame(wire)

        self.assertEqual(b"FLNK", wire[:4])
        self.assertEqual(FLUIDLINK_V2_WIRE_VERSION, wire[4])
        self.assertEqual(FluidLinkOpcode.RUNTIME_EVENT, wire[6])
        self.assertEqual(FluidLinkEventOpcode.OPERATION, wire[7])
        self.assertEqual(payload, decoded.payload)
        self.assertEqual(MESSAGE_ID, decoded.message_id)
        self.assertEqual(SESSION_ID, decoded.session_id)
        self.assertNotIn(b"cost_ms", wire)
        self.assertNotIn(b"size_mb", wire)
        self.assertNotIn(b"operation_type", wire)

    def test_hello_welcome_and_nonce_payloads_round_trip(self):
        hello = decode_hello_payload(
            encode_hello_payload(client_name="runtime", client_version="0.14")
        )
        nonce = decode_nonce_payload(encode_nonce_payload("heartbeat-1"))

        self.assertEqual("runtime", hello.client_name)
        self.assertEqual("0.14", hello.client_version)
        self.assertEqual(FLUIDLINK_V2_CAPABILITIES, hello.requested_capabilities)
        self.assertEqual(
            FLUIDLINK_V2_REQUIRED_CAPABILITIES,
            hello.required_capabilities,
        )
        self.assertEqual("heartbeat-1", nonce)

    def test_handshake_encoders_reject_masks_the_decoders_would_reject(self):
        unknown = FluidLinkV2Capability(1 << 63)
        with self.assertRaisesRegex(FluidLinkProtocolError, "unknown bits"):
            encode_hello_payload(
                client_name="runtime",
                client_version="0.14",
                requested_capabilities=unknown,
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "integer mask"):
            encode_hello_payload(
                client_name="runtime",
                client_version="0.14",
                requested_capabilities=True,
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "subset"):
            encode_welcome_payload(
                available_capabilities=FluidLinkV2Capability.BINARY_PAYLOADS,
                accepted_capabilities=FluidLinkV2Capability.FIXED_POINT_UNITS,
                server_name="gateway",
                server_version="0.64",
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "greater than zero"):
            encode_welcome_payload(
                available_capabilities=FLUIDLINK_V2_CAPABILITIES,
                accepted_capabilities=FLUIDLINK_V2_CAPABILITIES,
                server_name="gateway",
                server_version="0.64",
                max_payload_bytes=0,
            )

        invalid_subset = bytearray(
            encode_welcome_payload(
                available_capabilities=FLUIDLINK_V2_CAPABILITIES,
                accepted_capabilities=FLUIDLINK_V2_CAPABILITIES,
                server_name="gateway",
                server_version="0.64",
            )
        )
        invalid_subset[32:40] = int(
            FluidLinkV2Capability.BINARY_PAYLOADS
        ).to_bytes(8, "little")
        invalid_subset[40:48] = int(
            FluidLinkV2Capability.FIXED_POINT_UNITS
        ).to_bytes(8, "little")
        with self.assertRaisesRegex(FluidLinkProtocolError, "subset"):
            decode_welcome_payload(bytes(invalid_subset))

    def test_event_schemas_round_trip_with_fixed_point_units(self):
        cases = [
            (
                FluidLinkEventOpcode.SESSION,
                {
                    "action": "begin",
                    "id": "session-1",
                    "budgets": {
                        "frame_ms": 16.667,
                        "ram_mb": 4096,
                        "vram_mb": 2048,
                    },
                },
            ),
            (
                FluidLinkEventOpcode.FRAME,
                {"action": "begin", "frame": 9, "target_frame_ms": 8.333},
            ),
            (
                FluidLinkEventOpcode.RESOURCE,
                {
                    "action": "register",
                    "id": "texture-1",
                    "kind": "texture",
                    "memory": "vram",
                    "lifetime": "frame",
                    "size_mb": 32,
                    "aliases": ["hero"],
                },
            ),
            (
                FluidLinkEventOpcode.RESOURCE,
                {"action": "release", "id": "texture-1"},
            ),
            (
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": "copy-1",
                    "operation_type": "copy",
                    "source": "a",
                    "target": "b",
                    "queue": "copy",
                    "reason": "upload",
                    "cost_ms": 0.8004,
                    "size_mb": 64,
                    "frame": 9,
                    "depends_on": ["prepare-1"],
                },
            ),
            (FluidLinkEventOpcode.STATE, {"action": "snapshot"}),
        ]

        decoded = [
            decode_runtime_event_payload(opcode, encode_runtime_event_payload(opcode, event))
            for opcode, event in cases
        ]

        self.assertEqual(16.667, decoded[0]["budgets"]["frame_ms"])
        self.assertEqual(4096, decoded[0]["budgets"]["ram_mb"])
        self.assertEqual(8.333, decoded[1]["target_frame_ms"])
        self.assertEqual(32, decoded[2]["size_mb"])
        self.assertEqual("release", decoded[3]["action"])
        self.assertEqual(0.8, decoded[4]["cost_ms"])
        self.assertEqual(64, decoded[4]["size_mb"])
        self.assertEqual(["prepare-1"], decoded[4]["depends_on"])
        self.assertEqual("snapshot", decoded[5]["action"])

    def test_fixed_point_conversion_rounds_half_away_from_zero(self):
        payload = encode_runtime_event_payload(
            FluidLinkEventOpcode.OPERATION,
            {
                "id": "tiny",
                "operation_type": "compute",
                "cost_ms": 0.0005,
                "size_bytes": 0,
            },
        )

        decoded = decode_runtime_event_payload(FluidLinkEventOpcode.OPERATION, payload)

        self.assertEqual(0.001, decoded["cost_ms"])

    def test_decision_payload_is_fixed_seventeen_bytes(self):
        payload = encode_runtime_decision_payload(
            {
                "accepted": True,
                "executed": False,
                "saved_ms": 0.8,
                "saved_mb": 64,
            }
        )
        decoded = decode_runtime_decision_payload(payload)

        self.assertEqual(17, len(payload))
        self.assertTrue(decoded["accepted"])
        self.assertFalse(decoded["executed"])
        self.assertEqual(800, decoded["saved_us"])
        self.assertEqual(64 * 1024 * 1024, decoded["saved_bytes"])

    def test_binary_operation_frame_is_smaller_than_v1_json_payload_frame(self):
        event = {
            "id": "upload-1",
            "operation_type": "upload",
            "source": "ram-buffer",
            "target": "vram-buffer",
            "queue": "copy",
            "cost_ms": 0.8,
            "size_mb": 64,
            "frame": 0,
        }
        v1 = fluidlink_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.OPERATION,
            sequence=2,
            message_id=MESSAGE_ID,
            session_id=SESSION_ID,
            payload=event,
        )
        v2 = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.OPERATION,
            sequence=2,
            message_id=MESSAGE_ID,
            session_id=SESSION_ID,
            payload=encode_runtime_event_payload(FluidLinkEventOpcode.OPERATION, event),
        )

        self.assertLess(len(encode_fluidlink_v2_frame(v2)), len(encode_fluidlink_frame(v1)))

    def test_reader_reassembles_fragmented_frame_with_five_byte_prefix(self):
        frame = fluidlink_v2_request(
            opcode=FluidLinkOpcode.PING,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=encode_nonce_payload("abc"),
        )
        wire = encode_fluidlink_v2_frame(frame)
        stream = FragmentedReader(wire[5:], 2)

        decoded = read_fluidlink_v2_frame(stream, wire[:5])

        self.assertIsNotNone(decoded)
        self.assertEqual("abc", decode_nonce_payload(decoded.payload))

    def test_codec_rejects_unknown_flags_reserved_bits_and_truncation(self):
        frame = fluidlink_v2_request(
            opcode=FluidLinkOpcode.PING,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=encode_nonce_payload("abc"),
        )
        unknown_flags = bytearray(encode_fluidlink_v2_frame(frame))
        unknown_flags[9] |= 0x80
        reserved = bytearray(encode_fluidlink_v2_frame(frame))
        reserved[10] = 1

        with self.assertRaisesRegex(FluidLinkProtocolError, "unknown flags"):
            decode_fluidlink_v2_frame(bytes(unknown_flags))
        with self.assertRaisesRegex(FluidLinkProtocolError, "reserved"):
            decode_fluidlink_v2_frame(bytes(reserved))
        with self.assertRaisesRegex(FluidLinkProtocolError, "declares"):
            decode_fluidlink_v2_frame(encode_fluidlink_v2_frame(frame)[:-1])

    def test_payload_decoders_reject_invalid_utf8_trailing_bytes_and_unknown_enums(self):
        invalid_utf8 = bytes.fromhex("01ff")
        valid_state = encode_runtime_event_payload(
            FluidLinkEventOpcode.STATE, {"action": "snapshot"}
        )

        with self.assertRaisesRegex(FluidLinkProtocolError, "UTF-8"):
            decode_nonce_payload(invalid_utf8)
        with self.assertRaisesRegex(FluidLinkProtocolError, "trailing"):
            decode_runtime_event_payload(FluidLinkEventOpcode.STATE, valid_state + b"\x00")
        with self.assertRaisesRegex(FluidLinkProtocolError, "state action"):
            decode_runtime_event_payload(FluidLinkEventOpcode.STATE, b"\xff")

    def test_encoder_rejects_unbounded_and_non_finite_values(self):
        with self.assertRaises(FluidLinkProtocolError):
            encode_runtime_event_payload(
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": "x" * 257,
                    "operation_type": "copy",
                    "cost_ms": 1,
                    "size_mb": 1,
                },
            )
        with self.assertRaises(FluidLinkProtocolError):
            encode_runtime_event_payload(
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": "x",
                    "operation_type": "copy",
                    "cost_ms": float("nan"),
                    "size_mb": 1,
                },
            )
        with self.assertRaises(FluidLinkProtocolError):
            encode_runtime_event_payload(
                FluidLinkEventOpcode.RESOURCE,
                {
                    "id": "x",
                    "kind": "shader",
                    "memory": "vram",
                    "size_mb": 1,
                },
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "session end"):
            encode_runtime_event_payload(
                FluidLinkEventOpcode.SESSION,
                {"action": "end", "budgets": {"ram_mb": 1}},
            )
        with self.assertRaisesRegex(FluidLinkProtocolError, "frame end"):
            encode_runtime_event_payload(
                FluidLinkEventOpcode.FRAME,
                {"action": "end", "frame": 1, "target_frame_us": 1000},
            )

    def test_session_microsecond_aliases_preserve_their_wire_units(self):
        for payload in (
            {"action": "begin", "id": "s", "target_frame_us": 16_667},
            {
                "action": "begin",
                "id": "s",
                "budgets": {"target_frame_us": 16_667},
            },
            {"action": "begin", "id": "s", "frame_us": 16_667},
            {
                "action": "begin",
                "id": "s",
                "budgets": {"frame_us": 16_667},
            },
        ):
            with self.subTest(payload=payload):
                encoded = encode_runtime_event_payload(
                    FluidLinkEventOpcode.SESSION, payload
                )
                decoded = decode_runtime_event_payload(
                    FluidLinkEventOpcode.SESSION, encoded
                )
                self.assertEqual(16.667, decoded["budgets"]["frame_ms"])

    def test_encoder_rejects_coerced_identifiers_and_release_fields(self):
        invalid_events = (
            (FluidLinkEventOpcode.SESSION, {"action": "begin", "id": 7}),
            (FluidLinkEventOpcode.RESOURCE, {"action": "release", "id": 7}),
            (
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": 7,
                    "operation_type": "copy",
                    "cost_us": 1,
                    "size_bytes": 1,
                },
            ),
            (
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": "copy-1",
                    "operation_type": "copy",
                    "source": 7,
                    "cost_us": 1,
                    "size_bytes": 1,
                },
            ),
            (
                FluidLinkEventOpcode.RESOURCE,
                {
                    "action": "register",
                    "id": "buffer-1",
                    "kind": "buffer",
                    "memory": "ram",
                    "aliases": [7],
                },
            ),
            (
                FluidLinkEventOpcode.RESOURCE,
                {
                    "action": "register",
                    "id": "buffer-1",
                    "aliases": "",
                },
            ),
            (
                FluidLinkEventOpcode.OPERATION,
                {
                    "id": "copy-1",
                    "operation_type": "copy",
                    "cost_us": 1,
                    "size_bytes": 1,
                    "depends_on": 0,
                },
            ),
            (FluidLinkEventOpcode.STATE, {"action": 0}),
        )
        for opcode, payload in invalid_events:
            with self.subTest(opcode=opcode, payload=payload):
                with self.assertRaises(FluidLinkProtocolError):
                    encode_runtime_event_payload(opcode, payload)

        with self.assertRaisesRegex(FluidLinkProtocolError, "release"):
            encode_runtime_event_payload(
                FluidLinkEventOpcode.RESOURCE,
                {
                    "action": "release",
                    "id": "buffer-1",
                    "size_bytes": 0,
                },
            )

    def test_server_classifies_malformed_binary_payload_as_invalid_payload(self):
        session = FluidLinkV2ServerSession(
            server_name="fluidgateway", server_version="0.64.0"
        )
        session.session_id = SESSION_ID
        session.accepted_capabilities = FLUIDLINK_V2_REQUIRED_CAPABILITIES
        request = fluidlink_v2_request(
            opcode=FluidLinkOpcode.RUNTIME_EVENT,
            subject_opcode=FluidLinkEventOpcode.STATE,
            sequence=1,
            message_id=MESSAGE_ID,
            session_id=SESSION_ID,
            payload=b"\xff",
        )

        response = session.process(request, lambda _: self.fail("adapter was called"))
        code, _ = decode_error_payload(response.payload)

        self.assertEqual("invalid_payload", code)
        self.assertEqual(
            int(FluidLinkV2ErrorCode.INVALID_PAYLOAD),
            int.from_bytes(response.payload[:2], "little"),
        )

    def test_server_negotiates_v2_and_returns_real_duplicate_decision(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                stream = connection.makefile("rwb", buffering=0)
                sequence = 1
                hello = self._exchange(
                    stream,
                    fluidlink_v2_request(
                        opcode=FluidLinkOpcode.HELLO,
                        sequence=sequence,
                        payload=encode_hello_payload(
                            client_name="python-test", client_version="1"
                        ),
                    ),
                )
                welcome = decode_welcome_payload(hello.payload)
                session_id = hello.session_id
                self.assertEqual(FLUIDLINK_V2_CAPABILITIES, welcome.accepted_capabilities)
                self.assertIsNotNone(session_id)

                sequence += 1
                pong = self._exchange(
                    stream,
                    fluidlink_v2_request(
                        opcode=FluidLinkOpcode.PING,
                        sequence=sequence,
                        session_id=session_id,
                        payload=encode_nonce_payload("n-1"),
                    ),
                )
                self.assertEqual("n-1", decode_nonce_payload(pong.payload))

                events = [
                    (
                        FluidLinkEventOpcode.SESSION,
                        {"action": "begin", "id": "v2-test"},
                    ),
                    (
                        FluidLinkEventOpcode.FRAME,
                        {"action": "begin", "frame": 0},
                    ),
                    (
                        FluidLinkEventOpcode.RESOURCE,
                        {
                            "id": "ram",
                            "kind": "buffer",
                            "memory": "ram",
                            "size_mb": 64,
                        },
                    ),
                    (
                        FluidLinkEventOpcode.RESOURCE,
                        {
                            "id": "vram",
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
                            "source": "ram",
                            "target": "vram",
                            "queue": "copy",
                            "cost_ms": 0.8,
                            "size_mb": 64,
                            "frame": 0,
                        },
                    ),
                    (
                        FluidLinkEventOpcode.OPERATION,
                        {
                            "id": "upload-2",
                            "operation_type": "upload",
                            "source": "ram",
                            "target": "vram",
                            "queue": "copy",
                            "cost_ms": 0.8,
                            "size_mb": 64,
                            "frame": 0,
                        },
                    ),
                ]
                decisions = []
                for event_opcode, event in events:
                    sequence += 1
                    response = self._exchange(
                        stream,
                        fluidlink_v2_request(
                            opcode=FluidLinkOpcode.RUNTIME_EVENT,
                            subject_opcode=event_opcode,
                            sequence=sequence,
                            session_id=session_id,
                            payload=encode_runtime_event_payload(event_opcode, event),
                        ),
                    )
                    decisions.append((response, decode_runtime_decision_payload(response.payload)))

                first_frame, first = decisions[-2]
                duplicate_frame, duplicate = decisions[-1]
                self.assertEqual(FluidLinkDecisionOpcode.EXECUTE, first_frame.decision_opcode)
                self.assertTrue(first["executed"])
                self.assertEqual(
                    FluidLinkDecisionOpcode.DEDUPLICATE_IDENTICAL_TRANSFER,
                    duplicate_frame.decision_opcode,
                )
                self.assertFalse(duplicate["executed"])
                self.assertEqual(800, duplicate["saved_us"])
                self.assertEqual(64 * 1024 * 1024, duplicate["saved_bytes"])

                for event_opcode, event in (
                    (FluidLinkEventOpcode.FRAME, {"action": "end", "frame": 0}),
                    (FluidLinkEventOpcode.SESSION, {"action": "end"}),
                ):
                    sequence += 1
                    self._exchange(
                        stream,
                        fluidlink_v2_request(
                            opcode=FluidLinkOpcode.RUNTIME_EVENT,
                            subject_opcode=event_opcode,
                            sequence=sequence,
                            session_id=session_id,
                            payload=encode_runtime_event_payload(event_opcode, event),
                        ),
                    )
                sequence += 1
                goodbye = self._exchange(
                    stream,
                    fluidlink_v2_request(
                        opcode=FluidLinkOpcode.GOODBYE,
                        sequence=sequence,
                        session_id=session_id,
                        payload=b"",
                    ),
                )
                self.assertEqual(b"", goodbye.payload)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_server_rejects_contract_drift_with_numeric_error(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                stream = connection.makefile("rwb", buffering=0)
                request = fluidlink_v2_request(
                    opcode=FluidLinkOpcode.HELLO,
                    sequence=1,
                    payload=encode_hello_payload(
                        client_name="test",
                        client_version="1",
                        contract_digest=bytes(32),
                    ),
                )
                response = self._exchange(stream, request)
                code, message = decode_error_payload(response.payload)

                self.assertFalse(response.ok)
                self.assertEqual(FluidLinkOpcode.ERROR, response.opcode)
                self.assertEqual(FluidLinkDecisionOpcode.UNKNOWN, response.decision_opcode)
                self.assertEqual("contract_mismatch", code)
                self.assertIn("v2 contract", message)
                stream.close()
            thread.join(timeout=5)

    def test_server_rejects_sequence_drift(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            server.timeout = 5
            host, port = server.server_address
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.create_connection((host, port), timeout=5) as connection:
                stream = connection.makefile("rwb", buffering=0)
                welcome = self._exchange(
                    stream,
                    fluidlink_v2_request(
                        opcode=FluidLinkOpcode.HELLO,
                        sequence=1,
                        payload=encode_hello_payload(client_name="test", client_version="1"),
                    ),
                )
                response = self._exchange(
                    stream,
                    fluidlink_v2_request(
                        opcode=FluidLinkOpcode.PING,
                        sequence=3,
                        session_id=welcome.session_id,
                        payload=encode_nonce_payload("x"),
                    ),
                )
                code, _ = decode_error_payload(response.payload)
                self.assertEqual("sequence_mismatch", code)
                stream.close()
            thread.join(timeout=5)

    def test_encoder_rejects_payload_above_contract_limit(self):
        frame = fluidlink_v2_request(
            opcode=FluidLinkOpcode.PING,
            sequence=1,
            message_id=MESSAGE_ID,
            payload=b"x" * (FLUIDLINK_V2_MAX_PAYLOAD_BYTES + 1),
        )

        with self.assertRaisesRegex(FluidLinkProtocolError, "65,535"):
            encode_fluidlink_v2_frame(frame)

    @staticmethod
    def _exchange(stream, request):
        stream.write(encode_fluidlink_v2_frame(request))
        stream.flush()
        response = read_fluidlink_v2_frame(stream)
        if response is None:
            raise AssertionError("FluidLink v2 server closed without a response.")
        if response.message_id != request.message_id or response.sequence != request.sequence:
            raise AssertionError("FluidLink v2 response correlation drifted.")
        return response


class FragmentedReader(io.BytesIO):
    def __init__(self, data: bytes, chunk_size: int) -> None:
        super().__init__(data)
        self.chunk_size = chunk_size

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.chunk_size
        return super().read(min(size, self.chunk_size))


if __name__ == "__main__":
    unittest.main()
