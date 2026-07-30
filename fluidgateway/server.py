from __future__ import annotations

import json
import socketserver
from typing import Any

from . import __version__
from .adapter import RuntimeAdapterSession, process_adapter_event_payload
from .fluidlink import (
    FLUIDLINK_MAGIC,
    FLUIDLINK_MAX_PAYLOAD_BYTES,
    FluidLinkProtocolError,
    FluidLinkServerSession,
    encode_fluidlink_frame,
    read_fluidlink_frame,
)


LEGACY_MAX_LINE_BYTES = FLUIDLINK_MAX_PAYLOAD_BYTES


class RuntimeEventRequestHandler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.session = RuntimeAdapterSession()
        self.fluidlink = FluidLinkServerSession(
            server_name="fluidgateway",
            server_version=__version__,
        )

    def handle(self) -> None:
        prefix = bytearray()
        for expected_byte in FLUIDLINK_MAGIC:
            received = self.rfile.read(1)
            if not received:
                if prefix:
                    self._handle_legacy_jsonl(bytes(prefix))
                return
            prefix.extend(received)
            if received[0] != expected_byte:
                self._handle_legacy_jsonl(bytes(prefix))
                return
        self._handle_fluidlink(bytes(prefix))

    def _handle_fluidlink(self, prefix: bytes) -> None:
        next_prefix: bytes | None = prefix
        while True:
            try:
                request = read_fluidlink_frame(self.rfile, next_prefix)
            except FluidLinkProtocolError:
                break
            next_prefix = None
            if request is None:
                break
            response = self.fluidlink.process(
                request,
                lambda event: process_adapter_event_payload(self.session, event),
            )
            self.wfile.write(encode_fluidlink_frame(response))
            self.wfile.flush()
            if self.fluidlink.closed:
                break

    def _handle_legacy_jsonl(self, prefix: bytes) -> None:
        first_prefix: bytes | None = prefix
        while True:
            if first_prefix is None:
                raw_line = self.rfile.readline(LEGACY_MAX_LINE_BYTES + 1)
            elif first_prefix.endswith(b"\n"):
                raw_line = first_prefix
                first_prefix = None
            else:
                raw_line = first_prefix + self.rfile.readline(
                    LEGACY_MAX_LINE_BYTES + 1 - len(first_prefix)
                )
                first_prefix = None
            if not raw_line:
                break
            if len(raw_line) > LEGACY_MAX_LINE_BYTES:
                response = {
                    "ok": False,
                    "error": (
                        f"Runtime event line exceeds {LEGACY_MAX_LINE_BYTES} bytes."
                    ),
                }
                self._write_response(response)
                break
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                self._write_response(
                    {"ok": False, "error": "Runtime event must be valid UTF-8."}
                )
                break
            if not line or line.startswith("#"):
                continue
            response = self.handle_line(line)
            self._write_response(response)

    def _write_response(self, response: dict[str, Any]) -> None:
        payload = (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()

    def handle_line(self, line: str) -> dict[str, Any]:
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Runtime event must be a JSON object.")
            return process_adapter_event_payload(self.session, payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class RuntimeEventTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def create_runtime_event_server(host: str, port: int) -> RuntimeEventTCPServer:
    return RuntimeEventTCPServer((host, port), RuntimeEventRequestHandler)


def serve_runtime_events(host: str, port: int, once: bool = False) -> None:
    with create_runtime_event_server(host, port) as server:
        if once:
            server.handle_request()
        else:
            server.serve_forever()
