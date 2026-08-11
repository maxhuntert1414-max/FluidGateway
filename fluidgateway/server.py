from __future__ import annotations

import ipaddress
import json
import math
import socket
import socketserver
import threading
import time
from typing import Any

from . import __version__
from .adapter import RuntimeAdapterSession, process_adapter_event_payload
from .fluidlink import (
    FLUIDLINK_MAGIC,
    FLUIDLINK_MAX_PAYLOAD_BYTES,
    FLUIDLINK_WIRE_VERSION,
    FluidLinkProtocolError,
    FluidLinkServerSession,
    encode_fluidlink_frame,
    read_fluidlink_frame,
)
from .fluidlink_v2 import (
    FLUIDLINK_V2_WIRE_VERSION,
    FluidLinkV2ServerSession,
    encode_fluidlink_v2_frame,
    read_fluidlink_v2_frame,
)


LEGACY_MAX_LINE_BYTES = FLUIDLINK_MAX_PAYLOAD_BYTES
DEFAULT_MAX_ACTIVE_CONNECTIONS = 8
DEFAULT_ACCEPT_BACKLOG = 16
DEFAULT_INITIAL_READ_DEADLINE_SECONDS = 1.0
DEFAULT_FRAME_READ_DEADLINE_SECONDS = 2.0
DEFAULT_IDLE_SESSION_TIMEOUT_SECONDS = 30.0
SHUTDOWN_POLL_SECONDS = 0.25


class _DeadlineSocketReader:
    def __init__(
        self,
        connection: socket.socket,
        shutdown_event: threading.Event,
    ) -> None:
        self._connection = connection
        self._shutdown_event = shutdown_event
        self._buffer = bytearray()
        self._deadline: float | None = None
        self._idle_deadline: float | None = None
        self._frame_timeout_seconds: float | None = None

    def start_absolute_deadline(self, timeout_seconds: float) -> None:
        self._deadline = time.monotonic() + timeout_seconds
        self._idle_deadline = None
        self._frame_timeout_seconds = None

    def start_frame_deadline(
        self,
        idle_timeout_seconds: float,
        frame_timeout_seconds: float,
    ) -> None:
        self._deadline = None
        self._idle_deadline = time.monotonic() + idle_timeout_seconds
        self._frame_timeout_seconds = frame_timeout_seconds
        if self._buffer:
            self._activate_frame_deadline()

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise ValueError("Deadline reader requires a bounded read size.")
        if size == 0:
            return b""
        if self._buffer:
            count = min(size, len(self._buffer))
            result = bytes(self._buffer[:count])
            del self._buffer[:count]
            return result
        return self._receive(size)

    def readline(self, limit: int = -1) -> bytes:
        if limit <= 0:
            raise ValueError("Deadline reader requires a positive line limit.")
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                count = min(newline + 1, limit)
                result = bytes(self._buffer[:count])
                del self._buffer[:count]
                return result
            if len(self._buffer) >= limit:
                result = bytes(self._buffer[:limit])
                del self._buffer[:limit]
                return result
            chunk = self._receive(min(4096, limit - len(self._buffer)))
            if not chunk:
                result = bytes(self._buffer)
                self._buffer.clear()
                return result
            self._buffer.extend(chunk)

    def _receive(self, size: int) -> bytes:
        while True:
            if self._shutdown_event.is_set():
                raise ConnectionAbortedError("FluidLink server is shutting down.")
            deadline = self._deadline
            if deadline is None:
                deadline = self._idle_deadline
            if deadline is None:
                raise RuntimeError("Read deadline was not configured.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("FluidLink read deadline expired.")
            self._connection.settimeout(min(remaining, SHUTDOWN_POLL_SECONDS))
            try:
                chunk = self._connection.recv(size)
            except TimeoutError:
                continue
            if chunk and self._deadline is None:
                self._activate_frame_deadline()
            return chunk

    def _activate_frame_deadline(self) -> None:
        if self._frame_timeout_seconds is None:
            return
        self._deadline = time.monotonic() + self._frame_timeout_seconds
        self._idle_deadline = None
        self._frame_timeout_seconds = None


class RuntimeEventRequestHandler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.reader = _DeadlineSocketReader(
            self.connection,
            self.server.shutdown_event,
        )
        self.session = RuntimeAdapterSession()
        self.fluidlink = FluidLinkServerSession(
            server_name="fluidgateway",
            server_version=__version__,
        )
        self.fluidlink_v2 = FluidLinkV2ServerSession(
            server_name="fluidgateway",
            server_version=__version__,
        )

    def handle(self) -> None:
        try:
            self.reader.start_absolute_deadline(
                self.server.initial_read_deadline_seconds
            )
            prefix = bytearray()
            for expected_byte in FLUIDLINK_MAGIC:
                received = self.reader.read(1)
                if not received:
                    if prefix:
                        self._start_in_progress_frame()
                        self._handle_legacy_jsonl(bytes(prefix))
                    return
                prefix.extend(received)
                if received[0] != expected_byte:
                    self._start_in_progress_frame()
                    self._handle_legacy_jsonl(bytes(prefix))
                    return
            wire_version = self.reader.read(1)
            self._start_in_progress_frame()
            if wire_version == bytes((FLUIDLINK_WIRE_VERSION,)):
                self._handle_fluidlink_v1(bytes(prefix) + wire_version)
            elif wire_version == bytes((FLUIDLINK_V2_WIRE_VERSION,)):
                self._handle_fluidlink_v2(bytes(prefix) + wire_version)
        except (ConnectionError, OSError, TimeoutError):
            return

    def _handle_fluidlink_v1(self, prefix: bytes) -> None:
        next_prefix: bytes | None = prefix
        while True:
            try:
                if next_prefix is None:
                    self._start_next_frame()
                request = read_fluidlink_frame(self.reader, next_prefix)
            except (FluidLinkProtocolError, OSError, TimeoutError):
                break
            next_prefix = None
            if request is None:
                break
            response = self.fluidlink.process(
                request,
                lambda event: process_adapter_event_payload(self.session, event),
            )
            if self.fluidlink.closed:
                self.server._release_connection_slot(self.connection)
            self._write_bytes(encode_fluidlink_frame(response))
            if self.fluidlink.closed:
                break

    def _handle_fluidlink_v2(self, prefix: bytes) -> None:
        next_prefix: bytes | None = prefix
        while True:
            try:
                if next_prefix is None:
                    self._start_next_frame()
                request = read_fluidlink_v2_frame(self.reader, next_prefix)
            except (FluidLinkProtocolError, OSError, TimeoutError):
                break
            next_prefix = None
            if request is None:
                break
            response = self.fluidlink_v2.process(
                request,
                lambda event: process_adapter_event_payload(self.session, event),
            )
            if self.fluidlink_v2.closed:
                self.server._release_connection_slot(self.connection)
            self._write_bytes(encode_fluidlink_v2_frame(response))
            if self.fluidlink_v2.closed:
                break

    def _handle_legacy_jsonl(self, prefix: bytes) -> None:
        first_prefix: bytes | None = prefix
        while True:
            if first_prefix is None:
                self._start_next_frame()
                raw_line = self.reader.readline(LEGACY_MAX_LINE_BYTES + 1)
            elif first_prefix.endswith(b"\n"):
                raw_line = first_prefix
                first_prefix = None
            else:
                raw_line = first_prefix + self.reader.readline(
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
        self._write_bytes(payload)

    def _write_bytes(self, payload: bytes) -> None:
        self.connection.settimeout(self.server.frame_read_deadline_seconds)
        self.wfile.write(payload)
        self.wfile.flush()

    def _start_in_progress_frame(self) -> None:
        self.reader.start_absolute_deadline(self.server.frame_read_deadline_seconds)

    def _start_next_frame(self) -> None:
        self.reader.start_frame_deadline(
            self.server.idle_session_timeout_seconds,
            self.server.frame_read_deadline_seconds,
        )

    def handle_line(self, line: str) -> dict[str, Any]:
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Runtime event must be a JSON object.")
            return process_adapter_event_payload(self.session, payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class RuntimeEventTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[socketserver.BaseRequestHandler],
        *,
        max_active_connections: int = DEFAULT_MAX_ACTIVE_CONNECTIONS,
        accept_backlog: int = DEFAULT_ACCEPT_BACKLOG,
        initial_read_deadline_seconds: float = (
            DEFAULT_INITIAL_READ_DEADLINE_SECONDS
        ),
        frame_read_deadline_seconds: float = DEFAULT_FRAME_READ_DEADLINE_SECONDS,
        idle_session_timeout_seconds: float = DEFAULT_IDLE_SESSION_TIMEOUT_SECONDS,
    ) -> None:
        if max_active_connections < 1:
            raise ValueError("Maximum active connections must be positive.")
        if accept_backlog < 1:
            raise ValueError("Accept backlog must be positive.")
        for name, value in (
            ("initial read deadline", initial_read_deadline_seconds),
            ("frame read deadline", frame_read_deadline_seconds),
            ("idle session timeout", idle_session_timeout_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name.capitalize()} must be positive.")
        self.max_active_connections = max_active_connections
        self.request_queue_size = accept_backlog
        self.initial_read_deadline_seconds = initial_read_deadline_seconds
        self.frame_read_deadline_seconds = frame_read_deadline_seconds
        self.idle_session_timeout_seconds = idle_session_timeout_seconds
        self._connection_slots = threading.BoundedSemaphore(max_active_connections)
        self._connection_count_lock = threading.Lock()
        self._active_connection_count = 0
        self._active_requests: set[socket.socket] = set()
        self.shutdown_event = threading.Event()
        self._synchronous_request = False
        super().__init__(server_address, request_handler_class)

    @property
    def active_connection_count(self) -> int:
        with self._connection_count_lock:
            return self._active_connection_count

    def process_request(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
    ) -> None:
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        self._add_active_request(request)
        if self._synchronous_request:
            self._process_request_synchronously(request, client_address)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release_connection_slot(request)
            raise

    def process_request_thread(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_connection_slot(request)

    def server_close(self) -> None:
        self.shutdown_event.set()
        with self._connection_count_lock:
            active_requests = tuple(self._active_requests)
        for request in active_requests:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            request.close()
        super().server_close()

    def handle_request_and_wait(self) -> None:
        self._synchronous_request = True
        try:
            self.handle_request()
        finally:
            self._synchronous_request = False

    def _process_request_synchronously(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
    ) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
            self._release_connection_slot(request)

    def _release_connection_slot(self, request: socket.socket) -> None:
        with self._connection_count_lock:
            if request not in self._active_requests:
                return
            self._active_requests.discard(request)
            self._active_connection_count -= 1
        self._connection_slots.release()

    def _add_active_request(self, request: socket.socket) -> None:
        with self._connection_count_lock:
            self._active_requests.add(request)
            self._active_connection_count += 1


def create_runtime_event_server(
    host: str,
    port: int,
    *,
    max_active_connections: int = DEFAULT_MAX_ACTIVE_CONNECTIONS,
    accept_backlog: int = DEFAULT_ACCEPT_BACKLOG,
    initial_read_deadline_seconds: float = DEFAULT_INITIAL_READ_DEADLINE_SECONDS,
    frame_read_deadline_seconds: float = DEFAULT_FRAME_READ_DEADLINE_SECONDS,
    idle_session_timeout_seconds: float = DEFAULT_IDLE_SESSION_TIMEOUT_SECONDS,
) -> RuntimeEventTCPServer:
    _validate_loopback_host(host)
    return RuntimeEventTCPServer(
        (host, port),
        RuntimeEventRequestHandler,
        max_active_connections=max_active_connections,
        accept_backlog=accept_backlog,
        initial_read_deadline_seconds=initial_read_deadline_seconds,
        frame_read_deadline_seconds=frame_read_deadline_seconds,
        idle_session_timeout_seconds=idle_session_timeout_seconds,
    )


def serve_runtime_events(host: str, port: int, once: bool = False) -> None:
    with create_runtime_event_server(host, port) as server:
        if once:
            server.handle_request_and_wait()
        else:
            server.serve_forever()


def _validate_loopback_host(host: str) -> None:
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                host,
                None,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
            )
        }
    except (socket.gaierror, ValueError) as exc:
        raise ValueError(f"Unable to resolve runtime event host {host!r}.") from exc
    if not addresses or any(not address.is_loopback for address in addresses):
        raise ValueError("Runtime event server must bind to a loopback address.")
