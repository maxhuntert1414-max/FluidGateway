from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Any, BinaryIO, Callable
from uuid import uuid4


FLUIDLINK_PROTOCOL = "fluidlink-v1"
FLUIDLINK_MAGIC = b"FLNK"
FLUIDLINK_WIRE_VERSION = 1
FLUIDLINK_HEADER_SIZE = 56
FLUIDLINK_MAX_PAYLOAD_BYTES = 1024 * 1024
FLUIDLINK_MAX_JSON_DEPTH = 64
FLUIDLINK_MAX_CAPABILITIES = 64
FLUIDLINK_MAX_CAPABILITY_NAME_BYTES = 128
FLUIDLINK_MAX_PEER_NAME_BYTES = 128
FLUIDLINK_MAX_PEER_VERSION_BYTES = 64
FLUIDLINK_MAX_NONCE_BYTES = 128
FLUIDLINK_CONTRACT_SHA256 = (
    "10b46685472d13d2d49cc81aa1f7df2d654c1ec53fdc666e086e0d062ad114fa"
)
FLUIDLINK_HEADER = struct.Struct("<4sBBBBBBHQ16s16sI")
FLUIDLINK_CAPABILITIES = frozenset(
    {
        "binary.framing.v1",
        "compact.decisions.v1",
        "heartbeat.v1",
        "memory.transit.v1",
        "runtime.decisions.v1",
        "runtime.events.v1",
        "session.lifecycle.v1",
    }
)


class FluidLinkFrameKind(IntEnum):
    REQUEST = 1
    RESPONSE = 2


class FluidLinkFrameFlag(IntFlag):
    OK = 1
    HAS_SESSION = 2
    JSON_PAYLOAD = 4


class FluidLinkOpcode(IntEnum):
    HELLO = 1
    WELCOME = 2
    RUNTIME_EVENT = 10
    RUNTIME_DECISION = 11
    PING = 20
    PONG = 21
    GOODBYE = 30
    ERROR = 255


class FluidLinkEventOpcode(IntEnum):
    SESSION = 100
    FRAME = 101
    RESOURCE = 102
    OPERATION = 103
    STATE = 104


class FluidLinkDecisionOpcode(IntEnum):
    EXECUTE = 0
    ELIMINATE_SELF_COPY = 1
    DEDUPLICATE_IDENTICAL_TRANSFER = 2
    COLLAPSE_ALIASED_RESOURCE_COPY = 3
    REMOVE_ORPHAN_SYNC = 4
    REMOVE_EMPTY_SYNC = 5
    REUSE_TRANSIENT_BUFFER = 6
    UNKNOWN = 255


EVENT_NAME_BY_OPCODE = {
    FluidLinkEventOpcode.SESSION: "session",
    FluidLinkEventOpcode.FRAME: "frame",
    FluidLinkEventOpcode.RESOURCE: "resource",
    FluidLinkEventOpcode.OPERATION: "operation",
    FluidLinkEventOpcode.STATE: "state",
}
DECISION_OPCODE_BY_POLICY = {
    "eliminate-self-copy": FluidLinkDecisionOpcode.ELIMINATE_SELF_COPY,
    "deduplicate-identical-transfer": (
        FluidLinkDecisionOpcode.DEDUPLICATE_IDENTICAL_TRANSFER
    ),
    "collapse-aliased-resource-copy": (
        FluidLinkDecisionOpcode.COLLAPSE_ALIASED_RESOURCE_COPY
    ),
    "remove-orphan-sync": FluidLinkDecisionOpcode.REMOVE_ORPHAN_SYNC,
    "remove-empty-sync": FluidLinkDecisionOpcode.REMOVE_EMPTY_SYNC,
    "reuse-transient-buffer": FluidLinkDecisionOpcode.REUSE_TRANSIENT_BUFFER,
}


class FluidLinkProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FluidLinkFrame:
    kind: FluidLinkFrameKind
    opcode: int
    subject_opcode: int
    decision_opcode: int
    flags: int
    sequence: int
    message_id: bytes
    session_id: bytes | None
    payload: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.flags & FluidLinkFrameFlag.OK)

    @property
    def wire_size(self) -> int:
        return len(encode_fluidlink_frame(self))


def fluidlink_request(
    *,
    opcode: FluidLinkOpcode | int,
    sequence: int,
    payload: dict[str, Any],
    session_id: bytes | None = None,
    subject_opcode: FluidLinkEventOpcode | int = 0,
    message_id: bytes | None = None,
) -> FluidLinkFrame:
    flags = FluidLinkFrameFlag.JSON_PAYLOAD
    if session_id is not None:
        flags |= FluidLinkFrameFlag.HAS_SESSION
    return FluidLinkFrame(
        kind=FluidLinkFrameKind.REQUEST,
        opcode=int(opcode),
        subject_opcode=int(subject_opcode),
        decision_opcode=0,
        flags=int(flags),
        sequence=sequence,
        message_id=message_id or uuid4().bytes,
        session_id=session_id,
        payload=payload,
    )


def fluidlink_response(
    request: FluidLinkFrame,
    *,
    opcode: FluidLinkOpcode,
    session_id: bytes | None,
    payload: dict[str, Any],
    subject_opcode: FluidLinkEventOpcode | int = 0,
    decision_opcode: FluidLinkDecisionOpcode | int = 0,
    ok: bool = True,
) -> FluidLinkFrame:
    flags = FluidLinkFrameFlag.JSON_PAYLOAD
    if session_id is not None:
        flags |= FluidLinkFrameFlag.HAS_SESSION
    if ok:
        flags |= FluidLinkFrameFlag.OK
    return FluidLinkFrame(
        kind=FluidLinkFrameKind.RESPONSE,
        opcode=int(opcode),
        subject_opcode=int(subject_opcode),
        decision_opcode=int(decision_opcode),
        flags=int(flags),
        sequence=request.sequence,
        message_id=request.message_id,
        session_id=session_id,
        payload=payload,
    )


def fluidlink_error_response(
    request: FluidLinkFrame,
    *,
    code: str,
    message: str,
    session_id: bytes | None = None,
) -> FluidLinkFrame:
    return fluidlink_response(
        request,
        opcode=FluidLinkOpcode.ERROR,
        subject_opcode=request.subject_opcode,
        decision_opcode=FluidLinkDecisionOpcode.UNKNOWN,
        session_id=session_id,
        ok=False,
        payload={"code": code, "message": message},
    )


def encode_fluidlink_frame(frame: FluidLinkFrame) -> bytes:
    validate_frame(frame)
    payload = encode_json(frame.payload)
    if len(payload) > FLUIDLINK_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "payload_too_large",
            "FluidLink payload exceeds the 1 MiB limit.",
        )
    session_id = frame.session_id or bytes(16)
    header = FLUIDLINK_HEADER.pack(
        FLUIDLINK_MAGIC,
        FLUIDLINK_WIRE_VERSION,
        int(frame.kind),
        frame.opcode,
        frame.subject_opcode,
        frame.decision_opcode,
        frame.flags,
        0,
        frame.sequence,
        frame.message_id,
        session_id,
        len(payload),
    )
    return header + payload


def estimate_equivalent_json_envelope_size(frame: FluidLinkFrame) -> int:
    validate_frame(frame)
    envelope: dict[str, Any] = {
        "protocol": FLUIDLINK_PROTOCOL,
        "kind": (
            "request"
            if frame.kind == FluidLinkFrameKind.REQUEST
            else "response"
        ),
        "message_id": frame.message_id.hex(),
        "sequence": frame.sequence,
        "op": frame.opcode,
        "subject_op": frame.subject_opcode,
        "decision_op": frame.decision_opcode,
        "session_id": frame.session_id.hex() if frame.session_id else None,
        "payload": frame.payload,
    }
    if frame.kind == FluidLinkFrameKind.RESPONSE:
        envelope["ok"] = frame.ok
    return len(encode_json(envelope)) + 1


def decode_fluidlink_frame(data: bytes) -> FluidLinkFrame:
    if len(data) < FLUIDLINK_HEADER_SIZE:
        raise FluidLinkProtocolError(
            "truncated_frame",
            "FluidLink frame is shorter than its 56-byte header.",
        )
    (
        magic,
        wire_version,
        kind_value,
        opcode,
        subject_opcode,
        decision_opcode,
        flags,
        reserved,
        sequence,
        message_id,
        session_bytes,
        payload_size,
    ) = FLUIDLINK_HEADER.unpack(data[:FLUIDLINK_HEADER_SIZE])
    validate_decoded_header(
        magic=magic,
        wire_version=wire_version,
        kind_value=kind_value,
        flags=flags,
        reserved=reserved,
        sequence=sequence,
        message_id=message_id,
        session_bytes=session_bytes,
        payload_size=payload_size,
    )
    expected_size = FLUIDLINK_HEADER_SIZE + payload_size
    if len(data) != expected_size:
        raise FluidLinkProtocolError(
            "frame_size_mismatch",
            f"FluidLink frame declares {expected_size} bytes, received {len(data)}.",
        )
    try:
        payload = json.loads(
            data[FLUIDLINK_HEADER_SIZE:].decode("utf-8"),
            parse_constant=reject_json_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload must be valid UTF-8 JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload must be a JSON object.",
        )
    validate_json_value(payload, depth=1)
    session_id = (
        session_bytes if flags & FluidLinkFrameFlag.HAS_SESSION else None
    )
    return FluidLinkFrame(
        kind=FluidLinkFrameKind(kind_value),
        opcode=opcode,
        subject_opcode=subject_opcode,
        decision_opcode=decision_opcode,
        flags=flags,
        sequence=sequence,
        message_id=message_id,
        session_id=session_id,
        payload=payload,
    )


def read_fluidlink_frame(
    stream: BinaryIO,
    prefix: bytes | None = None,
) -> FluidLinkFrame | None:
    if prefix is None:
        prefix = read_exact(stream, len(FLUIDLINK_MAGIC), allow_eof=True)
        if prefix is None:
            return None
    if (
        len(prefix) < len(FLUIDLINK_MAGIC)
        or len(prefix) > FLUIDLINK_HEADER_SIZE
        or prefix[: len(FLUIDLINK_MAGIC)] != FLUIDLINK_MAGIC
    ):
        raise FluidLinkProtocolError(
            "truncated_frame",
            "FluidLink header prefix is invalid.",
        )
    header_tail = read_exact(
        stream,
        FLUIDLINK_HEADER_SIZE - len(prefix),
        allow_eof=False,
    )
    header = prefix + (header_tail or b"")
    payload_size = struct.unpack_from("<I", header, 52)[0]
    if payload_size > FLUIDLINK_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "payload_too_large",
            "FluidLink payload exceeds the 1 MiB limit.",
        )
    payload = read_exact(stream, payload_size, allow_eof=False) or b""
    return decode_fluidlink_frame(header + payload)


def read_exact(
    stream: BinaryIO,
    size: int,
    *,
    allow_eof: bool,
) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if allow_eof and remaining == size:
                return None
            raise FluidLinkProtocolError(
                "truncated_frame",
                "FluidLink peer closed before the complete frame arrived.",
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def validate_frame(frame: FluidLinkFrame) -> None:
    try:
        kind = FluidLinkFrameKind(frame.kind)
    except (TypeError, ValueError) as exc:
        raise FluidLinkProtocolError(
            "invalid_kind",
            f"Unsupported FluidLink frame kind {frame.kind}.",
        ) from exc
    if not isinstance(frame.payload, dict):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload must be a JSON object.",
        )
    validate_json_value(frame.payload, depth=1)
    if (
        not isinstance(frame.message_id, bytes)
        or len(frame.message_id) != 16
        or not any(frame.message_id)
    ):
        raise FluidLinkProtocolError(
            "invalid_message_id",
            "FluidLink message_id must contain 16 nonzero bytes.",
        )
    if (
        isinstance(frame.sequence, bool)
        or not isinstance(frame.sequence, int)
        or not 1 <= frame.sequence <= 0xFFFFFFFFFFFFFFFF
    ):
        raise FluidLinkProtocolError(
            "invalid_sequence",
            "FluidLink sequence must be an unsigned nonzero 64-bit integer.",
        )
    for name, value in (
        ("opcode", frame.opcode),
        ("subject_opcode", frame.subject_opcode),
        ("decision_opcode", frame.decision_opcode),
        ("flags", frame.flags),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise FluidLinkProtocolError(
                f"invalid_{name}",
                f"FluidLink {name} must fit in one byte.",
            )
    allowed_flags = int(
        FluidLinkFrameFlag.OK
        | FluidLinkFrameFlag.HAS_SESSION
        | FluidLinkFrameFlag.JSON_PAYLOAD
    )
    if frame.flags & ~allowed_flags:
        raise FluidLinkProtocolError(
            "invalid_flags",
            "FluidLink frame contains unknown flags.",
        )
    if not frame.flags & FluidLinkFrameFlag.JSON_PAYLOAD:
        raise FluidLinkProtocolError(
            "unsupported_payload_encoding",
            "FluidLink v1 requires the JSON payload flag.",
        )
    has_session = bool(frame.flags & FluidLinkFrameFlag.HAS_SESSION)
    if has_session != (frame.session_id is not None):
        raise FluidLinkProtocolError(
            "invalid_session_flag",
            "FluidLink session flag and session_id disagree.",
        )
    if frame.session_id is not None and (
        not isinstance(frame.session_id, bytes)
        or len(frame.session_id) != 16
        or not any(frame.session_id)
    ):
        raise FluidLinkProtocolError(
            "invalid_session_id",
            "FluidLink session_id must contain 16 nonzero bytes.",
        )
    if kind == FluidLinkFrameKind.REQUEST and frame.ok:
        raise FluidLinkProtocolError(
            "invalid_flags",
            "FluidLink requests cannot carry the OK flag.",
        )


def validate_decoded_header(
    *,
    magic: bytes,
    wire_version: int,
    kind_value: int,
    flags: int,
    reserved: int,
    sequence: int,
    message_id: bytes,
    session_bytes: bytes,
    payload_size: int,
) -> None:
    if magic != FLUIDLINK_MAGIC:
        raise FluidLinkProtocolError("invalid_magic", "Invalid FluidLink magic.")
    if wire_version != FLUIDLINK_WIRE_VERSION:
        raise FluidLinkProtocolError(
            "unsupported_wire_version",
            f"Unsupported FluidLink wire version {wire_version}.",
        )
    try:
        kind = FluidLinkFrameKind(kind_value)
    except ValueError as exc:
        raise FluidLinkProtocolError(
            "invalid_kind",
            f"Unsupported FluidLink frame kind {kind_value}.",
        ) from exc
    if reserved != 0:
        raise FluidLinkProtocolError(
            "invalid_reserved_bits",
            "FluidLink reserved header bits must be zero.",
        )
    if payload_size > FLUIDLINK_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "payload_too_large",
            "FluidLink payload exceeds the 1 MiB limit.",
        )
    session_id = session_bytes if flags & FluidLinkFrameFlag.HAS_SESSION else None
    frame = FluidLinkFrame(
        kind=kind,
        opcode=0,
        subject_opcode=0,
        decision_opcode=0,
        flags=flags,
        sequence=sequence,
        message_id=message_id,
        session_id=session_id,
        payload={},
    )
    validate_frame(frame)
    if session_id is None and any(session_bytes):
        raise FluidLinkProtocolError(
            "invalid_session_flag",
            "FluidLink session bytes require the HAS_SESSION flag.",
        )


class FluidLinkServerSession:
    def __init__(self, *, server_name: str, server_version: str) -> None:
        self.server_name = server_name
        self.server_version = server_version
        self.session_id: bytes | None = None
        self.expected_sequence = 1
        self.accepted_capabilities: frozenset[str] = frozenset()
        self.closed = False

    def process(
        self,
        request: FluidLinkFrame,
        event_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> FluidLinkFrame:
        if request.kind != FluidLinkFrameKind.REQUEST:
            return fluidlink_error_response(
                request,
                code="invalid_kind",
                message="FluidLink server accepts request frames only.",
                session_id=self.session_id,
            )
        if request.sequence != self.expected_sequence:
            return fluidlink_error_response(
                request,
                code="sequence_mismatch",
                message=(
                    f"Expected sequence {self.expected_sequence}, "
                    f"received {request.sequence}."
                ),
                session_id=self.session_id,
            )

        if self.session_id is None:
            self.expected_sequence += 1
            if request.opcode != FluidLinkOpcode.HELLO:
                return fluidlink_error_response(
                    request,
                    code="handshake_required",
                    message="A FluidLink hello request is required first.",
                )
            return self._handle_hello(request)

        if request.session_id != self.session_id:
            return fluidlink_error_response(
                request,
                code="session_mismatch",
                message="FluidLink session_id does not match the negotiated session.",
                session_id=self.session_id,
            )
        if self.closed:
            return fluidlink_error_response(
                request,
                code="session_closed",
                message="The FluidLink session is already closed.",
                session_id=self.session_id,
            )

        self.expected_sequence += 1
        if request.decision_opcode != 0:
            return fluidlink_error_response(
                request,
                code="invalid_request_header",
                message="FluidLink requests must use decision opcode zero.",
                session_id=self.session_id,
            )
        if request.opcode == FluidLinkOpcode.RUNTIME_EVENT:
            return self._handle_runtime_event(request, event_handler)
        if request.subject_opcode != 0:
            return fluidlink_error_response(
                request,
                code="invalid_request_header",
                message="Only runtime event requests may use a subject opcode.",
                session_id=self.session_id,
            )
        if request.opcode == FluidLinkOpcode.PING:
            return self._handle_ping(request)
        if request.opcode == FluidLinkOpcode.GOODBYE:
            return self._handle_goodbye(request)
        return fluidlink_error_response(
            request,
            code="unsupported_opcode",
            message=f"Unsupported FluidLink opcode {request.opcode}.",
            session_id=self.session_id,
        )

    def _handle_hello(self, request: FluidLinkFrame) -> FluidLinkFrame:
        if (
            request.session_id is not None
            or request.subject_opcode != 0
            or request.decision_opcode != 0
        ):
            return fluidlink_error_response(
                request,
                code="invalid_hello",
                message="FluidLink hello must use an empty session and zero sub-opcodes.",
            )
        client = request.payload.get("client")
        if not isinstance(client, dict):
            return fluidlink_error_response(
                request,
                code="invalid_hello",
                message="FluidLink hello requires a client object.",
            )
        name = client.get("name")
        version = client.get("version")
        if not valid_text(name, FLUIDLINK_MAX_PEER_NAME_BYTES):
            return fluidlink_error_response(
                request,
                code="invalid_hello",
                message="FluidLink client.name must contain 1 to 128 UTF-8 bytes.",
            )
        if not valid_text(version, FLUIDLINK_MAX_PEER_VERSION_BYTES):
            return fluidlink_error_response(
                request,
                code="invalid_hello",
                message="FluidLink client.version must contain 1 to 64 UTF-8 bytes.",
            )
        if request.payload.get("contract_sha256") != FLUIDLINK_CONTRACT_SHA256:
            return fluidlink_error_response(
                request,
                code="contract_mismatch",
                message="FluidLink peers do not share the same v1 contract.",
            )
        try:
            requested = string_set(request.payload.get("capabilities", []))
            required = string_set(request.payload.get("required_capabilities", []))
        except FluidLinkProtocolError as exc:
            return fluidlink_error_response(
                request,
                code=exc.code,
                message=str(exc),
            )
        unsupported = sorted(required - FLUIDLINK_CAPABILITIES)
        if unsupported:
            return fluidlink_error_response(
                request,
                code="required_capability_unavailable",
                message="Required capabilities are unavailable: " + ", ".join(unsupported),
            )

        self.session_id = uuid4().bytes
        self.accepted_capabilities = frozenset(
            (requested | required) & FLUIDLINK_CAPABILITIES
        )
        return fluidlink_response(
            request,
            opcode=FluidLinkOpcode.WELCOME,
            session_id=self.session_id,
            payload={
                "contract_sha256": FLUIDLINK_CONTRACT_SHA256,
                "server": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
                "available_capabilities": sorted(FLUIDLINK_CAPABILITIES),
                "accepted_capabilities": sorted(self.accepted_capabilities),
                "limits": {
                    "max_payload_bytes": FLUIDLINK_MAX_PAYLOAD_BYTES,
                    "max_json_depth": FLUIDLINK_MAX_JSON_DEPTH,
                },
            },
        )

    def _handle_runtime_event(
        self,
        request: FluidLinkFrame,
        event_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> FluidLinkFrame:
        required = {
            "binary.framing.v1",
            "compact.decisions.v1",
            "runtime.events.v1",
            "runtime.decisions.v1",
        }
        if not required.issubset(self.accepted_capabilities):
            return fluidlink_error_response(
                request,
                code="capability_not_negotiated",
                message="FluidLink binary runtime capabilities were not negotiated.",
                session_id=self.session_id,
            )
        try:
            event_opcode = FluidLinkEventOpcode(request.subject_opcode)
        except ValueError:
            return fluidlink_error_response(
                request,
                code="unsupported_event_opcode",
                message=f"Unsupported FluidLink event opcode {request.subject_opcode}.",
                session_id=self.session_id,
            )
        event = dict(request.payload)
        event["event"] = EVENT_NAME_BY_OPCODE[event_opcode]
        try:
            response = event_handler(event)
            decision_opcode, compact = compact_runtime_response(
                event_opcode,
                response,
            )
        except Exception as exc:
            return fluidlink_error_response(
                request,
                code="runtime_event_rejected",
                message=str(exc),
                session_id=self.session_id,
            )
        return fluidlink_response(
            request,
            opcode=FluidLinkOpcode.RUNTIME_DECISION,
            subject_opcode=event_opcode,
            decision_opcode=decision_opcode,
            session_id=self.session_id,
            payload=compact,
        )

    def _handle_ping(self, request: FluidLinkFrame) -> FluidLinkFrame:
        if "heartbeat.v1" not in self.accepted_capabilities:
            return fluidlink_error_response(
                request,
                code="capability_not_negotiated",
                message="heartbeat.v1 was not negotiated.",
                session_id=self.session_id,
            )
        nonce = request.payload.get("nonce")
        if not valid_text(nonce, FLUIDLINK_MAX_NONCE_BYTES):
            return fluidlink_error_response(
                request,
                code="invalid_ping",
                message="FluidLink ping nonce must contain 1 to 128 UTF-8 bytes.",
                session_id=self.session_id,
            )
        return fluidlink_response(
            request,
            opcode=FluidLinkOpcode.PONG,
            session_id=self.session_id,
            payload={"nonce": nonce},
        )

    def _handle_goodbye(self, request: FluidLinkFrame) -> FluidLinkFrame:
        self.closed = True
        return fluidlink_response(
            request,
            opcode=FluidLinkOpcode.GOODBYE,
            session_id=self.session_id,
            payload={"closed": True},
        )


def compact_runtime_response(
    event_opcode: FluidLinkEventOpcode,
    response: dict[str, Any],
) -> tuple[FluidLinkDecisionOpcode, dict[str, Any]]:
    compact: dict[str, Any] = {"accepted": response.get("ok") is True}
    decision_opcode = FluidLinkDecisionOpcode.EXECUTE
    if event_opcode != FluidLinkEventOpcode.OPERATION:
        return decision_opcode, compact

    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("Runtime operation response is missing its result object.")
    decision = result.get("decision")
    saved_ms = 0.0
    saved_mb = 0.0
    if isinstance(decision, dict):
        decision_opcode = DECISION_OPCODE_BY_POLICY.get(
            decision.get("policy"),
            FluidLinkDecisionOpcode.UNKNOWN,
        )
        saved_ms = numeric_value(
            decision.get("estimated_saved_ms"),
            "estimated_saved_ms",
        )
        saved_mb = numeric_value(
            decision.get("estimated_saved_mb"),
            "estimated_saved_mb",
        )
    compact.update(
        {
            "executed": result.get("executed") is True,
            "saved_ms": saved_ms,
            "saved_mb": saved_mb,
        }
    )
    return decision_opcode, compact


def numeric_value(value: Any, name: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Runtime decision {name} must be numeric.")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(
            f"Runtime decision {name} must fit in a finite floating-point value."
        ) from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Runtime decision {name} must be finite and non-negative.")
    return result


def string_set(value: Any) -> set[str]:
    if (
        not isinstance(value, list)
        or len(value) > FLUIDLINK_MAX_CAPABILITIES
        or any(
            not isinstance(item, str)
            or not item.strip()
            or utf8_size(item.strip()) is None
            or utf8_size(item.strip()) > FLUIDLINK_MAX_CAPABILITY_NAME_BYTES
            for item in value
        )
    ):
        raise FluidLinkProtocolError(
            "invalid_capabilities",
            "FluidLink capabilities must be a list of non-empty strings.",
    )
    return {item.strip() for item in value}


def encode_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload must contain bounded standard JSON values.",
        ) from exc


def validate_json_value(value: Any, *, depth: int) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        if utf8_size(value) is not None:
            return
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload strings must be valid UTF-8.",
        )
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload numbers must be finite.",
        )
    if isinstance(value, list):
        validate_json_depth(depth)
        for item in value:
            validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        validate_json_depth(depth)
        if any(
            not isinstance(key, str) or utf8_size(key) is None
            for key in value
        ):
            raise FluidLinkProtocolError(
                "invalid_payload",
                "FluidLink payload object keys must be strings.",
            )
        for item in value.values():
            validate_json_value(item, depth=depth + 1)
        return
    raise FluidLinkProtocolError(
        "invalid_payload",
        "FluidLink payload contains a value outside standard JSON.",
    )


def reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is not allowed: {value}.")


def valid_text(value: Any, maximum_utf8_bytes: int) -> bool:
    size = utf8_size(value.strip()) if isinstance(value, str) else None
    return (
        isinstance(value, str)
        and bool(value.strip())
        and size is not None
        and size <= maximum_utf8_bytes
    )


def validate_json_depth(depth: int) -> None:
    if depth > FLUIDLINK_MAX_JSON_DEPTH:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink payload exceeds the maximum JSON depth of 64.",
        )


def utf8_size(value: str) -> int | None:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return None
