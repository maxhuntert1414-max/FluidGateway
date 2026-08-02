from __future__ import annotations

import struct
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import IntEnum, IntFlag
from typing import Any, BinaryIO, Callable, Iterable
from uuid import uuid4

from .fluidlink import (
    EVENT_NAME_BY_OPCODE,
    FluidLinkDecisionOpcode,
    FluidLinkEventOpcode,
    FluidLinkFrameKind,
    FluidLinkOpcode,
    FluidLinkProtocolError,
    compact_runtime_response,
    read_exact,
)


FLUIDLINK_V2_PROTOCOL = "fluidlink-v2"
FLUIDLINK_V2_MAGIC = b"FLNK"
FLUIDLINK_V2_WIRE_VERSION = 2
FLUIDLINK_V2_HEADER_SIZE = 56
FLUIDLINK_V2_MAX_PAYLOAD_BYTES = 65_535
FLUIDLINK_V2_MAX_PEER_NAME_BYTES = 128
FLUIDLINK_V2_MAX_PEER_VERSION_BYTES = 64
FLUIDLINK_V2_MAX_NONCE_BYTES = 128
FLUIDLINK_V2_MAX_IDENTIFIER_BYTES = 256
FLUIDLINK_V2_MAX_REASON_BYTES = 512
FLUIDLINK_V2_MAX_ALIASES = 32
FLUIDLINK_V2_MAX_DEPENDENCIES = 32
FLUIDLINK_V2_CONTRACT_SHA256 = (
    "0d24d96aec32d74e123f9e198e51adde74ddf190e8c40b0ac18bddf5c4108b2f"
)
FLUIDLINK_V2_CONTRACT_DIGEST = bytes.fromhex(FLUIDLINK_V2_CONTRACT_SHA256)
FLUIDLINK_V2_BATCH_CONTRACT_SHA256 = (
    "bf8727c22ac878ceff6dd0f462d6db5e81174737e839ecdf2e263a6f55268542"
)
FLUIDLINK_V2_BATCH_CONTRACT_DIGEST = bytes.fromhex(
    FLUIDLINK_V2_BATCH_CONTRACT_SHA256
)
FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE = 105
FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE = 7
FLUIDLINK_V2_MAX_BATCH_OPERATIONS = 256
FLUIDLINK_V2_HEADER = struct.Struct("<4sBBBBBBHQ16s16sI")
MEBIBYTE = 1024 * 1024


class FluidLinkV2FrameFlag(IntFlag):
    OK = 1
    HAS_SESSION = 2


class FluidLinkV2Capability(IntFlag):
    BINARY_PAYLOADS = 1 << 0
    FIXED_POINT_UNITS = 1 << 1
    HEARTBEAT = 1 << 2
    RUNTIME_EVENTS = 1 << 3
    RUNTIME_DECISIONS = 1 << 4
    MEMORY_TRANSIT = 1 << 5
    SESSION_LIFECYCLE = 1 << 6
    BATCHED_RUNTIME_EVENTS = 1 << 7


FLUIDLINK_V2_CAPABILITIES = (
    FluidLinkV2Capability.BINARY_PAYLOADS
    | FluidLinkV2Capability.FIXED_POINT_UNITS
    | FluidLinkV2Capability.HEARTBEAT
    | FluidLinkV2Capability.RUNTIME_EVENTS
    | FluidLinkV2Capability.RUNTIME_DECISIONS
    | FluidLinkV2Capability.MEMORY_TRANSIT
    | FluidLinkV2Capability.SESSION_LIFECYCLE
)
FLUIDLINK_V2_REQUIRED_CAPABILITIES = (
    FluidLinkV2Capability.BINARY_PAYLOADS
    | FluidLinkV2Capability.FIXED_POINT_UNITS
    | FluidLinkV2Capability.RUNTIME_EVENTS
    | FluidLinkV2Capability.RUNTIME_DECISIONS
)
FLUIDLINK_V2_SUPPORTED_CAPABILITIES = (
    FLUIDLINK_V2_CAPABILITIES | FluidLinkV2Capability.BATCHED_RUNTIME_EVENTS
)
FLUIDLINK_V2_BATCH_CAPABILITIES = FLUIDLINK_V2_SUPPORTED_CAPABILITIES
FLUIDLINK_V2_BATCH_REQUIRED_CAPABILITIES = (
    FLUIDLINK_V2_REQUIRED_CAPABILITIES
    | FluidLinkV2Capability.BATCHED_RUNTIME_EVENTS
)


class FluidLinkV2ErrorCode(IntEnum):
    INVALID_FRAME = 1
    HANDSHAKE_REQUIRED = 2
    CONTRACT_MISMATCH = 3
    REQUIRED_CAPABILITY_UNAVAILABLE = 4
    CAPABILITY_NOT_NEGOTIATED = 5
    SEQUENCE_MISMATCH = 6
    SESSION_MISMATCH = 7
    UNSUPPORTED_OPCODE = 8
    UNSUPPORTED_EVENT_OPCODE = 9
    INVALID_PAYLOAD = 10
    RUNTIME_EVENT_REJECTED = 11
    SESSION_CLOSED = 12


ERROR_NAME_BY_CODE = {
    FluidLinkV2ErrorCode.INVALID_FRAME: "invalid_frame",
    FluidLinkV2ErrorCode.HANDSHAKE_REQUIRED: "handshake_required",
    FluidLinkV2ErrorCode.CONTRACT_MISMATCH: "contract_mismatch",
    FluidLinkV2ErrorCode.REQUIRED_CAPABILITY_UNAVAILABLE: (
        "required_capability_unavailable"
    ),
    FluidLinkV2ErrorCode.CAPABILITY_NOT_NEGOTIATED: (
        "capability_not_negotiated"
    ),
    FluidLinkV2ErrorCode.SEQUENCE_MISMATCH: "sequence_mismatch",
    FluidLinkV2ErrorCode.SESSION_MISMATCH: "session_mismatch",
    FluidLinkV2ErrorCode.UNSUPPORTED_OPCODE: "unsupported_opcode",
    FluidLinkV2ErrorCode.UNSUPPORTED_EVENT_OPCODE: "unsupported_event_opcode",
    FluidLinkV2ErrorCode.INVALID_PAYLOAD: "invalid_payload",
    FluidLinkV2ErrorCode.RUNTIME_EVENT_REJECTED: "runtime_event_rejected",
    FluidLinkV2ErrorCode.SESSION_CLOSED: "session_closed",
}


LIFECYCLE_ACTIONS = {"begin": 1, "end": 2}
RESOURCE_ACTIONS = {"register": 1, "release": 2}
STATE_ACTIONS = {"snapshot": 1}
RESOURCE_KINDS = {
    "unknown": 0,
    "buffer": 1,
    "texture": 2,
    "framebuffer": 3,
    "command": 4,
}
MEMORY_LAYERS = {
    "ram": 1,
    "vram": 2,
    "shared": 3,
    "staging": 4,
    "swapchain": 5,
    "display": 6,
}
LIFETIMES = {
    "unknown": 0,
    "asset": 1,
    "frame": 2,
    "transient": 3,
    "session": 4,
}
OPERATION_TYPES = {
    "copy": 1,
    "sync": 2,
    "allocate": 3,
    "upload": 4,
    "present": 5,
    "compute": 6,
    "draw": 7,
}
QUEUES = {
    "unknown": 0,
    "cpu": 1,
    "copy": 2,
    "graphics": 3,
    "compute": 4,
    "present": 5,
}


@dataclass(frozen=True)
class FluidLinkV2Frame:
    kind: FluidLinkFrameKind
    opcode: int
    subject_opcode: int
    decision_opcode: int
    flags: int
    sequence: int
    message_id: bytes
    session_id: bytes | None
    payload: bytes

    @property
    def ok(self) -> bool:
        return bool(self.flags & FluidLinkV2FrameFlag.OK)

    @property
    def wire_size(self) -> int:
        return FLUIDLINK_V2_HEADER_SIZE + len(self.payload)


@dataclass(frozen=True)
class FluidLinkV2Hello:
    contract_digest: bytes
    requested_capabilities: FluidLinkV2Capability
    required_capabilities: FluidLinkV2Capability
    client_name: str
    client_version: str


@dataclass(frozen=True)
class FluidLinkV2Welcome:
    contract_digest: bytes
    available_capabilities: FluidLinkV2Capability
    accepted_capabilities: FluidLinkV2Capability
    max_payload_bytes: int
    server_name: str
    server_version: str


class _PayloadWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    def u8(self, value: int) -> None:
        self._integer(value, 0xFF, "u8")
        self.data.append(value)

    def u16(self, value: int) -> None:
        self._integer(value, 0xFFFF, "u16")
        self.data.extend(struct.pack("<H", value))

    def u32(self, value: int) -> None:
        self._integer(value, 0xFFFFFFFF, "u32")
        self.data.extend(struct.pack("<I", value))

    def u64(self, value: int) -> None:
        self._integer(value, 0xFFFFFFFFFFFFFFFF, "u64")
        self.data.extend(struct.pack("<Q", value))

    def raw(self, value: bytes, expected_size: int | None = None) -> None:
        if not isinstance(value, bytes):
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 binary field must be bytes."
            )
        if expected_size is not None and len(value) != expected_size:
            raise FluidLinkProtocolError(
                "invalid_payload",
                f"FluidLink v2 binary field must contain {expected_size} bytes.",
            )
        self.data.extend(value)

    def text8(
        self,
        value: str,
        maximum_bytes: int,
        *,
        allow_empty: bool = False,
    ) -> None:
        encoded = encode_bounded_text(value, maximum_bytes, allow_empty=allow_empty)
        if len(encoded) > 0xFF:
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 text8 field is too large."
            )
        self.u8(len(encoded))
        self.raw(encoded)

    def text16(
        self,
        value: str,
        maximum_bytes: int,
        *,
        allow_empty: bool = False,
    ) -> None:
        encoded = encode_bounded_text(value, maximum_bytes, allow_empty=allow_empty)
        self.u16(len(encoded))
        self.raw(encoded)

    @staticmethod
    def _integer(value: int, maximum: int, kind: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise FluidLinkProtocolError(
                "invalid_payload", f"FluidLink v2 {kind} field is out of range."
            )

    def finish(self) -> bytes:
        payload = bytes(self.data)
        if len(payload) > FLUIDLINK_V2_MAX_PAYLOAD_BYTES:
            raise FluidLinkProtocolError(
                "payload_too_large",
                "FluidLink v2 payload exceeds the 65,535-byte limit.",
            )
        return payload


class _PayloadReader:
    def __init__(self, payload: bytes) -> None:
        if not isinstance(payload, bytes):
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 payload must be bytes."
            )
        self.payload = payload
        self.offset = 0

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if size < 0 or end > len(self.payload):
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 payload is truncated."
            )
        value = self.payload[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def text8(self, maximum_bytes: int, *, allow_empty: bool = False) -> str:
        return self._text(self.u8(), maximum_bytes, allow_empty=allow_empty)

    def text16(self, maximum_bytes: int, *, allow_empty: bool = False) -> str:
        return self._text(self.u16(), maximum_bytes, allow_empty=allow_empty)

    def _text(self, size: int, maximum_bytes: int, *, allow_empty: bool) -> str:
        if size > maximum_bytes or (size == 0 and not allow_empty):
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 text field violates its size limit."
            )
        try:
            value = self.take(size).decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 text field is not valid UTF-8."
            ) from exc
        if not allow_empty and not value.strip():
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 text field cannot be blank."
            )
        return value

    def finish(self) -> None:
        if self.offset != len(self.payload):
            raise FluidLinkProtocolError(
                "invalid_payload", "FluidLink v2 payload has trailing bytes."
            )


def encode_bounded_text(
    value: str,
    maximum_bytes: int,
    *,
    allow_empty: bool,
) -> bytes:
    if not isinstance(value, str):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 text field must be a string."
        )
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 text field is not valid UTF-8."
        ) from exc
    if len(encoded) > maximum_bytes or (not allow_empty and not value.strip()):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 text field violates its size limit."
        )
    return encoded


def encode_fluidlink_v2_frame(frame: FluidLinkV2Frame) -> bytes:
    validate_fluidlink_v2_frame(frame)
    session_id = frame.session_id or bytes(16)
    header = FLUIDLINK_V2_HEADER.pack(
        FLUIDLINK_V2_MAGIC,
        FLUIDLINK_V2_WIRE_VERSION,
        int(frame.kind),
        frame.opcode,
        frame.subject_opcode,
        frame.decision_opcode,
        frame.flags,
        0,
        frame.sequence,
        frame.message_id,
        session_id,
        len(frame.payload),
    )
    return header + frame.payload


def decode_fluidlink_v2_frame(data: bytes) -> FluidLinkV2Frame:
    if len(data) < FLUIDLINK_V2_HEADER_SIZE:
        raise FluidLinkProtocolError(
            "truncated_frame",
            "FluidLink v2 frame is shorter than its 56-byte header.",
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
    ) = FLUIDLINK_V2_HEADER.unpack(data[:FLUIDLINK_V2_HEADER_SIZE])
    if magic != FLUIDLINK_V2_MAGIC:
        raise FluidLinkProtocolError("invalid_magic", "Invalid FluidLink magic.")
    if wire_version != FLUIDLINK_V2_WIRE_VERSION:
        raise FluidLinkProtocolError(
            "unsupported_wire_version",
            f"Unsupported FluidLink wire version {wire_version}.",
        )
    if reserved != 0:
        raise FluidLinkProtocolError(
            "invalid_reserved_bits", "FluidLink reserved header bits must be zero."
        )
    if payload_size > FLUIDLINK_V2_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "payload_too_large",
            "FluidLink v2 payload exceeds the 65,535-byte limit.",
        )
    expected_size = FLUIDLINK_V2_HEADER_SIZE + payload_size
    if len(data) != expected_size:
        raise FluidLinkProtocolError(
            "frame_size_mismatch",
            f"FluidLink frame declares {expected_size} bytes, received {len(data)}.",
        )
    try:
        kind = FluidLinkFrameKind(kind_value)
    except ValueError as exc:
        raise FluidLinkProtocolError(
            "invalid_kind", f"Unsupported FluidLink frame kind {kind_value}."
        ) from exc
    session_id = (
        session_bytes if flags & FluidLinkV2FrameFlag.HAS_SESSION else None
    )
    frame = FluidLinkV2Frame(
        kind=kind,
        opcode=opcode,
        subject_opcode=subject_opcode,
        decision_opcode=decision_opcode,
        flags=flags,
        sequence=sequence,
        message_id=message_id,
        session_id=session_id,
        payload=data[FLUIDLINK_V2_HEADER_SIZE:],
    )
    validate_fluidlink_v2_frame(frame)
    if session_id is None and any(session_bytes):
        raise FluidLinkProtocolError(
            "invalid_session_flag",
            "FluidLink session bytes require the HAS_SESSION flag.",
        )
    return frame


def read_fluidlink_v2_frame(
    stream: BinaryIO,
    prefix: bytes | None = None,
) -> FluidLinkV2Frame | None:
    if prefix is None:
        prefix = read_exact(stream, len(FLUIDLINK_V2_MAGIC), allow_eof=True)
        if prefix is None:
            return None
    if (
        len(prefix) < len(FLUIDLINK_V2_MAGIC)
        or len(prefix) > FLUIDLINK_V2_HEADER_SIZE
        or prefix[:4] != FLUIDLINK_V2_MAGIC
    ):
        raise FluidLinkProtocolError(
            "truncated_frame", "FluidLink v2 header prefix is invalid."
        )
    header_tail = read_exact(
        stream,
        FLUIDLINK_V2_HEADER_SIZE - len(prefix),
        allow_eof=False,
    )
    header = prefix + (header_tail or b"")
    payload_size = struct.unpack_from("<I", header, 52)[0]
    if payload_size > FLUIDLINK_V2_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "payload_too_large",
            "FluidLink v2 payload exceeds the 65,535-byte limit.",
        )
    payload = read_exact(stream, payload_size, allow_eof=False) or b""
    return decode_fluidlink_v2_frame(header + payload)


def validate_fluidlink_v2_frame(frame: FluidLinkV2Frame) -> None:
    try:
        kind = FluidLinkFrameKind(frame.kind)
    except (TypeError, ValueError) as exc:
        raise FluidLinkProtocolError(
            "invalid_kind", f"Unsupported FluidLink frame kind {frame.kind}."
        ) from exc
    if not isinstance(frame.payload, bytes):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 payload must be bytes."
        )
    if len(frame.payload) > FLUIDLINK_V2_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "payload_too_large",
            "FluidLink v2 payload exceeds the 65,535-byte limit.",
        )
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
                f"invalid_{name}", f"FluidLink {name} must fit in one byte."
            )
    allowed_flags = int(FluidLinkV2FrameFlag.OK | FluidLinkV2FrameFlag.HAS_SESSION)
    if frame.flags & ~allowed_flags:
        raise FluidLinkProtocolError(
            "invalid_flags", "FluidLink v2 frame contains unknown flags."
        )
    has_session = bool(frame.flags & FluidLinkV2FrameFlag.HAS_SESSION)
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
            "invalid_flags", "FluidLink requests cannot carry the OK flag."
        )


def fluidlink_v2_request(
    *,
    opcode: FluidLinkOpcode | int,
    sequence: int,
    payload: bytes,
    session_id: bytes | None = None,
    subject_opcode: FluidLinkEventOpcode | int = 0,
    message_id: bytes | None = None,
) -> FluidLinkV2Frame:
    flags = FluidLinkV2FrameFlag(0)
    if session_id is not None:
        flags |= FluidLinkV2FrameFlag.HAS_SESSION
    return FluidLinkV2Frame(
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


def fluidlink_v2_response(
    request: FluidLinkV2Frame,
    *,
    opcode: FluidLinkOpcode | int,
    payload: bytes,
    session_id: bytes | None,
    subject_opcode: FluidLinkEventOpcode | int = 0,
    decision_opcode: FluidLinkDecisionOpcode | int = 0,
    ok: bool = True,
) -> FluidLinkV2Frame:
    flags = FluidLinkV2FrameFlag(0)
    if session_id is not None:
        flags |= FluidLinkV2FrameFlag.HAS_SESSION
    if ok:
        flags |= FluidLinkV2FrameFlag.OK
    return FluidLinkV2Frame(
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


def encode_hello_payload(
    *,
    client_name: str,
    client_version: str,
    requested_capabilities: FluidLinkV2Capability = FLUIDLINK_V2_CAPABILITIES,
    required_capabilities: FluidLinkV2Capability = (
        FLUIDLINK_V2_REQUIRED_CAPABILITIES
    ),
    contract_digest: bytes = FLUIDLINK_V2_CONTRACT_DIGEST,
) -> bytes:
    requested_mask = _encode_capability_mask(
        requested_capabilities, "requested_capabilities"
    )
    required_mask = _encode_capability_mask(
        required_capabilities, "required_capabilities"
    )
    writer = _PayloadWriter()
    writer.raw(contract_digest, 32)
    writer.u64(requested_mask)
    writer.u64(required_mask)
    writer.text8(client_name, FLUIDLINK_V2_MAX_PEER_NAME_BYTES)
    writer.text8(client_version, FLUIDLINK_V2_MAX_PEER_VERSION_BYTES)
    return writer.finish()


def decode_hello_payload(payload: bytes) -> FluidLinkV2Hello:
    reader = _PayloadReader(payload)
    result = FluidLinkV2Hello(
        contract_digest=reader.take(32),
        requested_capabilities=_decode_capability_mask(reader.u64()),
        required_capabilities=_decode_capability_mask(reader.u64()),
        client_name=reader.text8(FLUIDLINK_V2_MAX_PEER_NAME_BYTES),
        client_version=reader.text8(FLUIDLINK_V2_MAX_PEER_VERSION_BYTES),
    )
    reader.finish()
    return result


def encode_welcome_payload(
    *,
    available_capabilities: FluidLinkV2Capability,
    accepted_capabilities: FluidLinkV2Capability,
    server_name: str,
    server_version: str,
    max_payload_bytes: int = FLUIDLINK_V2_MAX_PAYLOAD_BYTES,
    contract_digest: bytes = FLUIDLINK_V2_CONTRACT_DIGEST,
) -> bytes:
    available_mask = _encode_capability_mask(
        available_capabilities, "available_capabilities"
    )
    accepted_mask = _encode_capability_mask(
        accepted_capabilities, "accepted_capabilities"
    )
    if accepted_mask & ~available_mask:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 accepted capabilities must be a subset of available capabilities.",
        )
    maximum_payload = _unsigned(
        max_payload_bytes, FLUIDLINK_V2_MAX_PAYLOAD_BYTES, "max_payload_bytes"
    )
    if maximum_payload == 0:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 max_payload_bytes must be greater than zero.",
        )
    writer = _PayloadWriter()
    writer.raw(contract_digest, 32)
    writer.u64(available_mask)
    writer.u64(accepted_mask)
    writer.u32(maximum_payload)
    writer.text8(server_name, FLUIDLINK_V2_MAX_PEER_NAME_BYTES)
    writer.text8(server_version, FLUIDLINK_V2_MAX_PEER_VERSION_BYTES)
    return writer.finish()


def decode_welcome_payload(payload: bytes) -> FluidLinkV2Welcome:
    reader = _PayloadReader(payload)
    result = FluidLinkV2Welcome(
        contract_digest=reader.take(32),
        available_capabilities=_decode_capability_mask(reader.u64()),
        accepted_capabilities=_decode_capability_mask(reader.u64()),
        max_payload_bytes=reader.u32(),
        server_name=reader.text8(FLUIDLINK_V2_MAX_PEER_NAME_BYTES),
        server_version=reader.text8(FLUIDLINK_V2_MAX_PEER_VERSION_BYTES),
    )
    reader.finish()
    if result.accepted_capabilities & ~result.available_capabilities:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 accepted capabilities must be a subset of available capabilities.",
        )
    if not 1 <= result.max_payload_bytes <= FLUIDLINK_V2_MAX_PAYLOAD_BYTES:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 welcome payload limit is invalid."
        )
    return result


def encode_nonce_payload(nonce: str) -> bytes:
    writer = _PayloadWriter()
    writer.text8(nonce, FLUIDLINK_V2_MAX_NONCE_BYTES)
    return writer.finish()


def decode_nonce_payload(payload: bytes) -> str:
    reader = _PayloadReader(payload)
    nonce = reader.text8(FLUIDLINK_V2_MAX_NONCE_BYTES)
    reader.finish()
    return nonce


def encode_error_payload(code: FluidLinkV2ErrorCode, message: str) -> bytes:
    writer = _PayloadWriter()
    writer.u16(int(code))
    writer.text16(
        _truncate_utf8(message, FLUIDLINK_V2_MAX_REASON_BYTES),
        FLUIDLINK_V2_MAX_REASON_BYTES,
    )
    return writer.finish()


def decode_error_payload(payload: bytes) -> tuple[str, str]:
    reader = _PayloadReader(payload)
    value = reader.u16()
    try:
        code = FluidLinkV2ErrorCode(value)
    except ValueError as exc:
        raise FluidLinkProtocolError(
            "invalid_payload", f"Unknown FluidLink v2 error code {value}."
        ) from exc
    message = reader.text16(FLUIDLINK_V2_MAX_REASON_BYTES)
    reader.finish()
    return ERROR_NAME_BY_CODE[code], message


def encode_runtime_decision_payload(compact: dict[str, Any]) -> bytes:
    accepted = compact.get("accepted") is True
    has_executed = "executed" in compact and compact.get("executed") is not None
    executed = compact.get("executed") is True
    flags = (1 if accepted else 0) | (2 if has_executed else 0) | (4 if executed else 0)
    saved_us = _time_value(compact, "saved_us", "saved_ms", maximum=0xFFFFFFFFFFFFFFFF)
    saved_bytes = _memory_value(compact, "saved_bytes", "saved_mb")
    writer = _PayloadWriter()
    writer.u8(flags)
    writer.u64(saved_us)
    writer.u64(saved_bytes)
    return writer.finish()


def decode_runtime_decision_payload(payload: bytes) -> dict[str, Any]:
    reader = _PayloadReader(payload)
    flags = reader.u8()
    saved_us = reader.u64()
    saved_bytes = reader.u64()
    reader.finish()
    if flags & ~0x07 or (flags & 0x04 and not flags & 0x02):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 decision flags are invalid."
        )
    result: dict[str, Any] = {
        "accepted": bool(flags & 0x01),
        "saved_us": saved_us,
        "saved_bytes": saved_bytes,
        "saved_ms": saved_us / 1000,
        "saved_mb": saved_bytes / MEBIBYTE,
    }
    if flags & 0x02:
        result["executed"] = bool(flags & 0x04)
    return result


def encode_operation_batch_event_payload(payload: dict[str, Any]) -> bytes:
    if not isinstance(payload, dict):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 operation batch must be an object."
        )
    batch_id = _batch_id_bytes(payload.get("batch_id"))
    operation_count = _batch_count(payload.get("operation_count"))
    operation_type = payload.get("operation_type")
    if operation_type is None:
        operation_type = payload.get("op")
    if operation_type is None:
        operation_type = payload.get("kind")
    source = _optional_text(payload.get("source"))
    target = _optional_text(payload.get("target"))
    reason = _optional_text(payload.get("reason"))
    frame = payload.get("frame")
    presence = (
        (1 if source is not None else 0)
        | (2 if target is not None else 0)
        | (4 if reason is not None else 0)
        | (8 if frame is not None else 0)
    )
    dependencies = _text_list(
        _value_or_default(payload, "depends_on", []),
        FLUIDLINK_V2_MAX_DEPENDENCIES,
        "dependencies",
    )
    writer = _PayloadWriter()
    writer.raw(batch_id, 16)
    writer.u16(operation_count)
    writer.u8(_enum_value(operation_type, OPERATION_TYPES, "operation type"))
    writer.u8(
        _enum_value(
            _value_or_default(payload, "queue", "unknown"), QUEUES, "queue"
        )
    )
    writer.u8(presence)
    if source is not None:
        writer.text16(source, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if target is not None:
        writer.text16(target, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if reason is not None:
        writer.text16(reason, FLUIDLINK_V2_MAX_REASON_BYTES)
    writer.u32(_time_value(payload, "cost_us", "cost_ms", maximum=0xFFFFFFFF))
    writer.u64(_memory_value(payload, "size_bytes", "size_mb"))
    if frame is not None:
        writer.u64(_unsigned(frame, 0xFFFFFFFFFFFFFFFF, "frame"))
    writer.u8(len(dependencies))
    for dependency in dependencies:
        writer.text16(dependency, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    return writer.finish()


def decode_operation_batch_event_payload(payload: bytes) -> dict[str, Any]:
    reader = _PayloadReader(payload)
    batch_id = reader.take(16)
    _validate_batch_id(batch_id)
    operation_count = _batch_count(reader.u16())
    operation_type = _enum_name(reader.u8(), OPERATION_TYPES, "operation type")
    queue = _enum_name(reader.u8(), QUEUES, "queue")
    presence = reader.u8()
    if presence & ~0x0F:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch presence mask is invalid.",
        )
    result: dict[str, Any] = {
        "batch_id": batch_id.hex(),
        "operation_count": operation_count,
        "operation_type": operation_type,
        "queue": queue,
    }
    if presence & 1:
        result["source"] = reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if presence & 2:
        result["target"] = reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if presence & 4:
        result["reason"] = reader.text16(FLUIDLINK_V2_MAX_REASON_BYTES)
    cost_us = reader.u32()
    size_bytes = reader.u64()
    result.update(
        {
            "cost_us": cost_us,
            "cost_ms": cost_us / 1000,
            "size_bytes": size_bytes,
            "size_mb": size_bytes / MEBIBYTE,
        }
    )
    if presence & 8:
        result["frame"] = reader.u64()
    count = reader.u8()
    if count > FLUIDLINK_V2_MAX_DEPENDENCIES:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 dependency count exceeds its limit."
        )
    result["depends_on"] = [
        reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES) for _ in range(count)
    ]
    reader.finish()
    return result


def encode_operation_batch_decision_payload(payload: dict[str, Any]) -> bytes:
    if not isinstance(payload, dict):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch decision must be an object.",
        )
    batch_id = _batch_id_bytes(payload.get("batch_id"))
    decisions = payload.get("decisions")
    if not isinstance(decisions, (list, tuple)):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch decisions must be a list.",
        )
    _batch_count(len(decisions))
    writer = _PayloadWriter()
    writer.raw(batch_id, 16)
    writer.u16(len(decisions))
    for decision in decisions:
        opcode, compact = _batch_decision(decision)
        writer.u8(opcode)
        writer.raw(encode_runtime_decision_payload(compact), 17)
    return writer.finish()


def decode_operation_batch_decision_payload(payload: bytes) -> dict[str, Any]:
    reader = _PayloadReader(payload)
    batch_id = reader.take(16)
    _validate_batch_id(batch_id)
    decision_count = _batch_count(reader.u16())
    decisions: list[dict[str, Any]] = []
    for _ in range(decision_count):
        opcode = reader.u8()
        compact = decode_runtime_decision_payload(reader.take(17))
        _validate_batch_decision(opcode, compact)
        decisions.append({"decision_opcode": opcode, **compact})
    reader.finish()
    return {"batch_id": batch_id.hex(), "decisions": decisions}


def encode_runtime_event_payload(
    event_opcode: FluidLinkEventOpcode | int,
    payload: dict[str, Any],
) -> bytes:
    if not isinstance(payload, dict):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 runtime event must be an object."
        )
    try:
        event = FluidLinkEventOpcode(event_opcode)
    except ValueError as exc:
        raise FluidLinkProtocolError(
            "unsupported_event_opcode",
            f"Unsupported FluidLink event opcode {event_opcode}.",
        ) from exc
    if event == FluidLinkEventOpcode.SESSION:
        return _encode_session_event(payload)
    if event == FluidLinkEventOpcode.FRAME:
        return _encode_frame_event(payload)
    if event == FluidLinkEventOpcode.RESOURCE:
        return _encode_resource_event(payload)
    if event == FluidLinkEventOpcode.OPERATION:
        return _encode_operation_event(payload)
    if event == FluidLinkEventOpcode.STATE:
        return _encode_state_event(payload)
    raise AssertionError("unreachable")


def decode_runtime_event_payload(
    event_opcode: FluidLinkEventOpcode | int,
    payload: bytes,
) -> dict[str, Any]:
    try:
        event = FluidLinkEventOpcode(event_opcode)
    except ValueError as exc:
        raise FluidLinkProtocolError(
            "unsupported_event_opcode",
            f"Unsupported FluidLink event opcode {event_opcode}.",
        ) from exc
    reader = _PayloadReader(payload)
    if event == FluidLinkEventOpcode.SESSION:
        result = _decode_session_event(reader)
    elif event == FluidLinkEventOpcode.FRAME:
        result = _decode_frame_event(reader)
    elif event == FluidLinkEventOpcode.RESOURCE:
        result = _decode_resource_event(reader)
    elif event == FluidLinkEventOpcode.OPERATION:
        result = _decode_operation_event(reader)
    elif event == FluidLinkEventOpcode.STATE:
        result = _decode_state_event(reader)
    else:
        raise AssertionError("unreachable")
    reader.finish()
    result["event"] = EVENT_NAME_BY_OPCODE[event]
    return result


def _encode_session_event(payload: dict[str, Any]) -> bytes:
    action = _enum_value(
        _value_or_default(payload, "action", "begin"),
        LIFECYCLE_ACTIONS,
        "session action",
    )
    session_id = payload.get("id")
    if session_id is None:
        session_id = payload.get("session_id")
    if session_id is None:
        session_id = ""
    budgets = payload.get("budgets")
    if budgets is None:
        budgets = {}
    if not isinstance(budgets, dict):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 session budgets must be an object."
        )
    target, target_key = _first_present(
        payload,
        budgets,
        "target_frame_us",
        "target_frame_ms",
        "frame_us",
        "frame_ms",
    )
    memory_fields = (
        ("ram", 1),
        ("vram", 2),
        ("shared", 3),
        ("staging", 4),
        ("swapchain", 5),
    )
    presence = 1 if target is not None else 0
    memory_values: list[tuple[int, int]] = []
    for name, bit in memory_fields:
        value, value_key = _first_present(
            payload, budgets, f"{name}_bytes", f"{name}_mb"
        )
        if value is not None:
            presence |= 1 << bit
            memory_values.append(
                (bit, _memory_scalar(value, value_key == f"{name}_bytes"))
            )
    if action == LIFECYCLE_ACTIONS["end"] and presence:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 session end cannot carry budget fields.",
        )
    writer = _PayloadWriter()
    writer.u8(action)
    writer.u8(presence)
    writer.text16(
        session_id,
        FLUIDLINK_V2_MAX_IDENTIFIER_BYTES,
        allow_empty=action == LIFECYCLE_ACTIONS["end"],
    )
    if target is not None:
        is_microseconds = target_key in {"target_frame_us", "frame_us"}
        writer.u32(_time_scalar(target, is_microseconds, 0xFFFFFFFF))
    memory_by_bit = dict(memory_values)
    for _, bit in memory_fields:
        if presence & (1 << bit):
            writer.u64(memory_by_bit[bit])
    return writer.finish()


def _decode_session_event(reader: _PayloadReader) -> dict[str, Any]:
    action = _enum_name(reader.u8(), LIFECYCLE_ACTIONS, "session action")
    presence = reader.u8()
    if presence & ~0x3F:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 session presence mask is invalid."
        )
    if action == "end" and presence:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 session end cannot carry budget fields.",
        )
    session_id = reader.text16(
        FLUIDLINK_V2_MAX_IDENTIFIER_BYTES,
        allow_empty=action == "end",
    )
    result: dict[str, Any] = {"action": action}
    if session_id:
        result["id"] = session_id
    budgets: dict[str, Any] = {}
    if presence & 1:
        budgets["frame_ms"] = reader.u32() / 1000
    for name, bit in (
        ("ram", 1),
        ("vram", 2),
        ("shared", 3),
        ("staging", 4),
        ("swapchain", 5),
    ):
        if presence & (1 << bit):
            budgets[f"{name}_mb"] = reader.u64() / MEBIBYTE
    if budgets:
        result["budgets"] = budgets
    return result


def _encode_frame_event(payload: dict[str, Any]) -> bytes:
    action = _enum_value(
        _value_or_default(payload, "action", "begin"),
        LIFECYCLE_ACTIONS,
        "frame action",
    )
    frame = _required_unsigned(payload, ("frame", "frame_id"), 0xFFFFFFFFFFFFFFFF)
    target, target_key = _first_present(
        payload, {}, "target_frame_us", "target_frame_ms"
    )
    if action == LIFECYCLE_ACTIONS["end"] and target is not None:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 frame end cannot carry a target budget.",
        )
    writer = _PayloadWriter()
    writer.u8(action)
    writer.u8(1 if target is not None else 0)
    writer.u64(frame)
    if target is not None:
        writer.u32(_time_scalar(target, target_key == "target_frame_us", 0xFFFFFFFF))
    return writer.finish()


def _decode_frame_event(reader: _PayloadReader) -> dict[str, Any]:
    action = _enum_name(reader.u8(), LIFECYCLE_ACTIONS, "frame action")
    presence = reader.u8()
    if presence & ~1:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 frame presence mask is invalid."
        )
    if action == "end" and presence:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 frame end cannot carry a target budget.",
        )
    result: dict[str, Any] = {"action": action, "frame": reader.u64()}
    if presence & 1:
        result["target_frame_ms"] = reader.u32() / 1000
    return result


def _encode_resource_event(payload: dict[str, Any]) -> bytes:
    action = _enum_value(
        _value_or_default(payload, "action", "register"),
        RESOURCE_ACTIONS,
        "resource action",
    )
    resource_id = payload.get("id")
    if resource_id is None:
        resource_id = payload.get("resource_id")
    if resource_id is None:
        resource_id = ""
    writer = _PayloadWriter()
    writer.u8(action)
    writer.text16(resource_id, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if action == RESOURCE_ACTIONS["release"]:
        registration_fields = (
            "kind",
            "memory",
            "lifetime",
            "size_bytes",
            "size_mb",
            "aliases",
        )
        if any(field in payload for field in registration_fields):
            raise FluidLinkProtocolError(
                "invalid_payload",
                "FluidLink v2 resource release cannot carry registration fields.",
            )
        return writer.finish()
    writer.u8(
        _enum_value(
            _value_or_default(payload, "kind", "unknown"),
            RESOURCE_KINDS,
            "resource kind",
        )
    )
    writer.u8(
        _enum_value(
            _value_or_default(payload, "memory", "ram"),
            MEMORY_LAYERS,
            "memory layer",
        )
    )
    writer.u8(
        _enum_value(
            _value_or_default(payload, "lifetime", "unknown"),
            LIFETIMES,
            "lifetime",
        )
    )
    writer.u64(_memory_value(payload, "size_bytes", "size_mb"))
    aliases = _text_list(
        _value_or_default(payload, "aliases", []),
        FLUIDLINK_V2_MAX_ALIASES,
        "aliases",
    )
    writer.u8(len(aliases))
    for alias in aliases:
        writer.text16(alias, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    return writer.finish()


def _decode_resource_event(reader: _PayloadReader) -> dict[str, Any]:
    action = _enum_name(reader.u8(), RESOURCE_ACTIONS, "resource action")
    resource_id = reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    result: dict[str, Any] = {"action": action, "id": resource_id}
    if action == "release":
        return result
    result.update(
        {
            "kind": _enum_name(reader.u8(), RESOURCE_KINDS, "resource kind"),
            "memory": _enum_name(reader.u8(), MEMORY_LAYERS, "memory layer"),
            "lifetime": _enum_name(reader.u8(), LIFETIMES, "lifetime"),
            "size_mb": reader.u64() / MEBIBYTE,
        }
    )
    count = reader.u8()
    if count > FLUIDLINK_V2_MAX_ALIASES:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 alias count exceeds its limit."
        )
    result["aliases"] = [
        reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES) for _ in range(count)
    ]
    return result


def _encode_operation_event(payload: dict[str, Any]) -> bytes:
    operation_type = payload.get("operation_type")
    if operation_type is None:
        operation_type = payload.get("op")
    if operation_type is None:
        operation_type = payload.get("kind")
    operation_id = payload.get("id")
    if operation_id is None:
        operation_id = payload.get("operation_id")
    if operation_id is None:
        operation_id = ""
    source = _optional_text(payload.get("source"))
    target = _optional_text(payload.get("target"))
    reason = _optional_text(payload.get("reason"))
    frame = payload.get("frame")
    presence = (
        (1 if source is not None else 0)
        | (2 if target is not None else 0)
        | (4 if reason is not None else 0)
        | (8 if frame is not None else 0)
    )
    writer = _PayloadWriter()
    writer.u8(_enum_value(operation_type, OPERATION_TYPES, "operation type"))
    writer.u8(
        _enum_value(
            _value_or_default(payload, "queue", "unknown"), QUEUES, "queue"
        )
    )
    writer.u8(presence)
    writer.text16(operation_id, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if source is not None:
        writer.text16(source, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if target is not None:
        writer.text16(target, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if reason is not None:
        writer.text16(reason, FLUIDLINK_V2_MAX_REASON_BYTES)
    writer.u32(_time_value(payload, "cost_us", "cost_ms", maximum=0xFFFFFFFF))
    writer.u64(_memory_value(payload, "size_bytes", "size_mb"))
    if frame is not None:
        writer.u64(_unsigned(frame, 0xFFFFFFFFFFFFFFFF, "frame"))
    dependencies = _text_list(
        _value_or_default(payload, "depends_on", []),
        FLUIDLINK_V2_MAX_DEPENDENCIES,
        "dependencies",
    )
    writer.u8(len(dependencies))
    for dependency in dependencies:
        writer.text16(dependency, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    return writer.finish()


def _decode_operation_event(reader: _PayloadReader) -> dict[str, Any]:
    operation_type = _enum_name(reader.u8(), OPERATION_TYPES, "operation type")
    queue = _enum_name(reader.u8(), QUEUES, "queue")
    presence = reader.u8()
    if presence & ~0x0F:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 operation presence mask is invalid."
        )
    result: dict[str, Any] = {
        "operation_type": operation_type,
        "queue": queue,
        "id": reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES),
    }
    if presence & 1:
        result["source"] = reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if presence & 2:
        result["target"] = reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES)
    if presence & 4:
        result["reason"] = reader.text16(FLUIDLINK_V2_MAX_REASON_BYTES)
    result["cost_ms"] = reader.u32() / 1000
    result["size_mb"] = reader.u64() / MEBIBYTE
    if presence & 8:
        result["frame"] = reader.u64()
    count = reader.u8()
    if count > FLUIDLINK_V2_MAX_DEPENDENCIES:
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 dependency count exceeds its limit."
        )
    result["depends_on"] = [
        reader.text16(FLUIDLINK_V2_MAX_IDENTIFIER_BYTES) for _ in range(count)
    ]
    return result


def _encode_state_event(payload: dict[str, Any]) -> bytes:
    writer = _PayloadWriter()
    writer.u8(
        _enum_value(
            _value_or_default(payload, "action", "snapshot"),
            STATE_ACTIONS,
            "state action",
        )
    )
    return writer.finish()


def _decode_state_event(reader: _PayloadReader) -> dict[str, Any]:
    return {"action": _enum_name(reader.u8(), STATE_ACTIONS, "state action")}


class FluidLinkV2ServerSession:
    def __init__(self, *, server_name: str, server_version: str) -> None:
        encode_bounded_text(
            server_name, FLUIDLINK_V2_MAX_PEER_NAME_BYTES, allow_empty=False
        )
        encode_bounded_text(
            server_version, FLUIDLINK_V2_MAX_PEER_VERSION_BYTES, allow_empty=False
        )
        self.server_name = server_name
        self.server_version = server_version
        self.session_id: bytes | None = None
        self.contract_digest: bytes | None = None
        self.expected_sequence = 1
        self.accepted_capabilities = FluidLinkV2Capability(0)
        self.closed = False

    def process(
        self,
        request: FluidLinkV2Frame,
        event_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> FluidLinkV2Frame:
        if request.kind != FluidLinkFrameKind.REQUEST:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_FRAME,
                "FluidLink v2 server accepts request frames only.",
            )
        if request.sequence != self.expected_sequence:
            return self._error(
                request,
                FluidLinkV2ErrorCode.SEQUENCE_MISMATCH,
                f"Expected sequence {self.expected_sequence}, received {request.sequence}.",
            )
        if self.session_id is None:
            self.expected_sequence += 1
            if request.opcode != FluidLinkOpcode.HELLO:
                return self._error(
                    request,
                    FluidLinkV2ErrorCode.HANDSHAKE_REQUIRED,
                    "A FluidLink v2 hello request is required first.",
                )
            return self._handle_hello(request)
        if request.session_id != self.session_id:
            return self._error(
                request,
                FluidLinkV2ErrorCode.SESSION_MISMATCH,
                "FluidLink v2 session_id does not match the negotiated session.",
            )
        if self.closed:
            return self._error(
                request,
                FluidLinkV2ErrorCode.SESSION_CLOSED,
                "The FluidLink v2 session is already closed.",
            )
        self.expected_sequence += 1
        if request.decision_opcode != 0:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_FRAME,
                "FluidLink v2 requests must use decision opcode zero.",
            )
        if request.opcode == FluidLinkOpcode.RUNTIME_EVENT:
            return self._handle_runtime_event(request, event_handler)
        if request.subject_opcode != 0:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_FRAME,
                "Only runtime event requests may use a subject opcode.",
            )
        if request.opcode == FluidLinkOpcode.PING:
            return self._handle_ping(request)
        if request.opcode == FluidLinkOpcode.GOODBYE:
            return self._handle_goodbye(request)
        return self._error(
            request,
            FluidLinkV2ErrorCode.UNSUPPORTED_OPCODE,
            f"Unsupported FluidLink opcode {request.opcode}.",
        )

    def _handle_hello(self, request: FluidLinkV2Frame) -> FluidLinkV2Frame:
        if request.session_id is not None or request.subject_opcode or request.decision_opcode:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_FRAME,
                "FluidLink v2 hello header is invalid.",
            )
        try:
            hello = decode_hello_payload(request.payload)
        except FluidLinkProtocolError as exc:
            return self._error(request, FluidLinkV2ErrorCode.INVALID_PAYLOAD, str(exc))
        if hello.contract_digest == FLUIDLINK_V2_CONTRACT_DIGEST:
            available_capabilities = FLUIDLINK_V2_CAPABILITIES
        elif hello.contract_digest == FLUIDLINK_V2_BATCH_CONTRACT_DIGEST:
            available_capabilities = FLUIDLINK_V2_BATCH_CAPABILITIES
            if not (
                hello.required_capabilities
                & FluidLinkV2Capability.BATCHED_RUNTIME_EVENTS
            ):
                return self._error(
                    request,
                    FluidLinkV2ErrorCode.INVALID_PAYLOAD,
                    "The FluidLink v2 batch profile requires its batch capability.",
                )
        else:
            return self._error(
                request,
                FluidLinkV2ErrorCode.CONTRACT_MISMATCH,
                "FluidLink peers do not share the same v2 contract.",
            )
        unavailable = int(hello.required_capabilities) & ~int(available_capabilities)
        if unavailable:
            return self._error(
                request,
                FluidLinkV2ErrorCode.REQUIRED_CAPABILITY_UNAVAILABLE,
                f"Required capability mask 0x{unavailable:x} is unavailable.",
            )
        self.session_id = uuid4().bytes
        self.contract_digest = hello.contract_digest
        self.accepted_capabilities = FluidLinkV2Capability(
            (int(hello.requested_capabilities) | int(hello.required_capabilities))
            & int(available_capabilities)
        )
        return fluidlink_v2_response(
            request,
            opcode=FluidLinkOpcode.WELCOME,
            session_id=self.session_id,
            payload=encode_welcome_payload(
                available_capabilities=available_capabilities,
                accepted_capabilities=self.accepted_capabilities,
                server_name=self.server_name,
                server_version=self.server_version,
                contract_digest=hello.contract_digest,
            ),
        )

    def _handle_runtime_event(
        self,
        request: FluidLinkV2Frame,
        event_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> FluidLinkV2Frame:
        if (
            self.accepted_capabilities & FLUIDLINK_V2_REQUIRED_CAPABILITIES
        ) != FLUIDLINK_V2_REQUIRED_CAPABILITIES:
            return self._error(
                request,
                FluidLinkV2ErrorCode.CAPABILITY_NOT_NEGOTIATED,
                "FluidLink v2 runtime capabilities were not negotiated.",
            )
        if request.subject_opcode == FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE:
            return self._handle_operation_batch(request, event_handler)
        try:
            event_opcode = FluidLinkEventOpcode(request.subject_opcode)
        except ValueError:
            return self._error(
                request,
                FluidLinkV2ErrorCode.UNSUPPORTED_EVENT_OPCODE,
                f"Unsupported FluidLink event opcode {request.subject_opcode}.",
            )
        try:
            event = decode_runtime_event_payload(event_opcode, request.payload)
        except FluidLinkProtocolError as exc:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_PAYLOAD,
                str(exc),
            )
        try:
            response = event_handler(event)
            decision_opcode, compact = compact_runtime_response(event_opcode, response)
            decision_payload = encode_runtime_decision_payload(compact)
        except Exception as exc:
            return self._error(
                request,
                FluidLinkV2ErrorCode.RUNTIME_EVENT_REJECTED,
                str(exc),
            )
        return fluidlink_v2_response(
            request,
            opcode=FluidLinkOpcode.RUNTIME_DECISION,
            subject_opcode=event_opcode,
            decision_opcode=decision_opcode,
            session_id=self.session_id,
            payload=decision_payload,
        )

    def _handle_operation_batch(
        self,
        request: FluidLinkV2Frame,
        event_handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> FluidLinkV2Frame:
        if (
            self.contract_digest != FLUIDLINK_V2_BATCH_CONTRACT_DIGEST
            or not self.accepted_capabilities
            & FluidLinkV2Capability.BATCHED_RUNTIME_EVENTS
        ):
            return self._error(
                request,
                FluidLinkV2ErrorCode.CAPABILITY_NOT_NEGOTIATED,
                "FluidLink v2 batched runtime events were not negotiated.",
            )
        try:
            batch = decode_operation_batch_event_payload(request.payload)
        except FluidLinkProtocolError as exc:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_PAYLOAD,
                str(exc),
            )

        decisions: list[dict[str, Any]] = []
        batch_id = batch["batch_id"]
        try:
            for ordinal in range(batch["operation_count"]):
                event = {
                    key: value
                    for key, value in batch.items()
                    if key not in {"batch_id", "operation_count"}
                }
                event.update(
                    {
                        "event": "operation",
                        "id": f"batch-{batch_id}-{ordinal:03d}",
                    }
                )
                response = event_handler(event)
                decision_opcode, compact = compact_runtime_response(
                    FluidLinkEventOpcode.OPERATION,
                    response,
                )
                decisions.append(
                    {"decision_opcode": int(decision_opcode), **compact}
                )
            decision_payload = encode_operation_batch_decision_payload(
                {"batch_id": batch_id, "decisions": decisions}
            )
        except Exception as exc:
            self.closed = True
            return self._error(
                request,
                FluidLinkV2ErrorCode.RUNTIME_EVENT_REJECTED,
                str(exc),
            )

        return fluidlink_v2_response(
            request,
            opcode=FluidLinkOpcode.RUNTIME_DECISION,
            subject_opcode=FLUIDLINK_V2_OPERATION_BATCH_EVENT_OPCODE,
            decision_opcode=FLUIDLINK_V2_BATCH_VECTOR_DECISION_OPCODE,
            session_id=self.session_id,
            payload=decision_payload,
        )

    def _handle_ping(self, request: FluidLinkV2Frame) -> FluidLinkV2Frame:
        if not self.accepted_capabilities & FluidLinkV2Capability.HEARTBEAT:
            return self._error(
                request,
                FluidLinkV2ErrorCode.CAPABILITY_NOT_NEGOTIATED,
                "FluidLink v2 heartbeat capability was not negotiated.",
            )
        try:
            nonce = decode_nonce_payload(request.payload)
        except FluidLinkProtocolError as exc:
            return self._error(request, FluidLinkV2ErrorCode.INVALID_PAYLOAD, str(exc))
        return fluidlink_v2_response(
            request,
            opcode=FluidLinkOpcode.PONG,
            session_id=self.session_id,
            payload=encode_nonce_payload(nonce),
        )

    def _handle_goodbye(self, request: FluidLinkV2Frame) -> FluidLinkV2Frame:
        if request.payload:
            return self._error(
                request,
                FluidLinkV2ErrorCode.INVALID_PAYLOAD,
                "FluidLink v2 goodbye payload must be empty.",
            )
        self.closed = True
        return fluidlink_v2_response(
            request,
            opcode=FluidLinkOpcode.GOODBYE,
            session_id=self.session_id,
            payload=b"",
        )

    def _error(
        self,
        request: FluidLinkV2Frame,
        code: FluidLinkV2ErrorCode,
        message: str,
    ) -> FluidLinkV2Frame:
        return fluidlink_v2_response(
            request,
            opcode=FluidLinkOpcode.ERROR,
            subject_opcode=request.subject_opcode,
            decision_opcode=FluidLinkDecisionOpcode.UNKNOWN,
            session_id=self.session_id,
            ok=False,
            payload=encode_error_payload(code, message),
        )


def _batch_id_bytes(value: Any) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 batch_id must contain exactly 16 hexadecimal bytes.",
        )
    result = bytes.fromhex(value)
    _validate_batch_id(result)
    return result


def _validate_batch_id(value: bytes) -> None:
    if len(value) != 16 or not any(value):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 batch_id must contain 16 nonzero-identity bytes.",
        )


def _batch_count(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= FLUIDLINK_V2_MAX_BATCH_OPERATIONS
    ):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch count must be between 1 and "
            f"{FLUIDLINK_V2_MAX_BATCH_OPERATIONS}.",
        )
    return value


def _batch_decision(value: Any) -> tuple[int, dict[str, Any]]:
    if not isinstance(value, dict):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch decision entry must be an object.",
        )
    opcode = value.get("decision_opcode")
    _validate_batch_decision(opcode, value)
    return int(opcode), value


def _validate_batch_decision(opcode: Any, compact: dict[str, Any]) -> None:
    if isinstance(opcode, bool) or not isinstance(opcode, int) or not 0 <= opcode <= 6:
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch contains an invalid decision opcode.",
        )
    executed = compact.get("executed")
    if not isinstance(executed, bool) or executed != (
        opcode == int(FluidLinkDecisionOpcode.EXECUTE)
    ):
        raise FluidLinkProtocolError(
            "invalid_payload",
            "FluidLink v2 operation batch decision execution state and opcode disagree.",
        )


def _decode_capability_mask(value: int) -> FluidLinkV2Capability:
    unknown = value & ~int(FLUIDLINK_V2_SUPPORTED_CAPABILITIES)
    if unknown:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 capability mask has unknown bits 0x{unknown:x}."
        )
    return FluidLinkV2Capability(value)


def _encode_capability_mask(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be an integer mask."
        )
    try:
        return int(_decode_capability_mask(value))
    except FluidLinkProtocolError as exc:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} contains unknown bits."
        ) from exc


def _enum_value(value: Any, values: dict[str, int], name: str) -> int:
    if not isinstance(value, str):
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be a string."
        )
    key = value.strip().lower()
    try:
        return values[key]
    except KeyError as exc:
        raise FluidLinkProtocolError(
            "invalid_payload", f"Unsupported FluidLink v2 {name}: {key or 'missing'}."
        ) from exc


def _enum_name(value: int, values: dict[str, int], name: str) -> str:
    for key, number in values.items():
        if value == number:
            return key
    raise FluidLinkProtocolError(
        "invalid_payload", f"Unsupported FluidLink v2 {name} opcode {value}."
    )


def _time_value(
    payload: dict[str, Any],
    microseconds_key: str,
    milliseconds_key: str,
    *,
    maximum: int,
) -> int:
    if microseconds_key in payload:
        return _unsigned(payload[microseconds_key], maximum, microseconds_key)
    return _time_scalar(payload.get(milliseconds_key, 0), False, maximum)


def _time_scalar(value: Any, is_microseconds: bool, maximum: int) -> int:
    if is_microseconds:
        return _unsigned(value, maximum, "microseconds")
    return _scaled_decimal(value, 1000, maximum, "milliseconds")


def _memory_value(
    payload: dict[str, Any],
    bytes_key: str,
    megabytes_key: str,
) -> int:
    if bytes_key in payload:
        return _unsigned(payload[bytes_key], 0xFFFFFFFFFFFFFFFF, bytes_key)
    return _scaled_decimal(
        payload.get(megabytes_key, 0),
        MEBIBYTE,
        0xFFFFFFFFFFFFFFFF,
        megabytes_key,
    )


def _memory_scalar(value: Any, is_bytes: bool) -> int:
    if is_bytes:
        return _unsigned(value, 0xFFFFFFFFFFFFFFFF, "bytes")
    return _scaled_decimal(value, MEBIBYTE, 0xFFFFFFFFFFFFFFFF, "megabytes")


def _scaled_decimal(value: Any, scale: int, maximum: int, name: str) -> int:
    if isinstance(value, bool):
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be numeric."
        )
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be numeric."
        ) from exc
    if not number.is_finite() or number < 0:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be finite and non-negative."
        )
    scaled = int((number * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if scaled > maximum:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} exceeds its wire range."
        )
    return scaled


def _unsigned(value: Any, maximum: int, name: str) -> int:
    if isinstance(value, bool):
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be an unsigned integer."
        )
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be an unsigned integer."
        ) from exc
    if result != value or not 0 <= result <= maximum:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} is out of range."
        )
    return result


def _required_unsigned(
    payload: dict[str, Any],
    keys: Iterable[str],
    maximum: int,
) -> int:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _unsigned(payload[key], maximum, key)
    raise FluidLinkProtocolError(
        "invalid_payload", "FluidLink v2 event is missing a required integer."
    )


def _first_present(
    primary: dict[str, Any],
    secondary: dict[str, Any],
    *keys: str,
) -> tuple[Any | None, str | None]:
    for key in keys:
        if key in primary and primary[key] is not None:
            return primary[key], key
        if key in secondary and secondary[key] is not None:
            return secondary[key], key
    return None, None


def _value_or_default(
    payload: dict[str, Any], key: str, default: Any
) -> Any:
    value = payload.get(key)
    return default if value is None else value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FluidLinkProtocolError(
            "invalid_payload", "FluidLink v2 optional text field must be a string."
        )
    return value


def _text_list(value: Any, maximum_count: int, name: str) -> list[str]:
    if not isinstance(value, list):
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} must be a list."
        )
    if len(value) > maximum_count:
        raise FluidLinkProtocolError(
            "invalid_payload", f"FluidLink v2 {name} list exceeds its limit."
        )
    for item in value:
        encode_bounded_text(
            item, FLUIDLINK_V2_MAX_IDENTIFIER_BYTES, allow_empty=False
        )
    return value


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    text = str(value).strip() or "FluidLink v2 request failed."
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum_bytes:
        return text
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore") or "FluidLink v2 error."
