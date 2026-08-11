from __future__ import annotations

import socket
import threading
import time
import unittest

from fluidgateway.fluidlink import FLUIDLINK_MAGIC, FluidLinkOpcode
from fluidgateway.fluidlink_v2 import (
    encode_fluidlink_v2_frame,
    encode_hello_payload,
    fluidlink_v2_request,
    read_fluidlink_v2_frame,
)
from fluidgateway.server import create_runtime_event_server


class RuntimeEventServerResilienceTests(unittest.TestCase):
    def test_stalled_connection_does_not_block_healthy_handshake(self):
        with create_runtime_event_server("127.0.0.1", 0) as server:
            host, port = server.server_address
            server_thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.01},
            )
            server_thread.start()
            stalled_ready = threading.Event()
            release_stalled = threading.Event()

            def hold_partial_header() -> None:
                with socket.create_connection((host, port), timeout=1) as connection:
                    connection.sendall(FLUIDLINK_MAGIC[:1])
                    stalled_ready.set()
                    release_stalled.wait(timeout=2)

            stalled_thread = threading.Thread(target=hold_partial_header)
            stalled_thread.start()
            self.assertTrue(stalled_ready.wait(timeout=1))
            self.assertTrue(
                self._wait_until(lambda: server.active_connection_count == 1)
            )

            release_timer = threading.Timer(1.0, release_stalled.set)
            release_timer.start()
            try:
                started = time.monotonic()
                self._perform_healthy_handshake(host, port)
                elapsed = time.monotonic() - started
            finally:
                release_stalled.set()
                release_timer.cancel()
                stalled_thread.join(timeout=2)
                server.shutdown()
                server_thread.join(timeout=2)

            self.assertFalse(stalled_thread.is_alive())
            self.assertFalse(server_thread.is_alive())
            self.assertLess(elapsed, 0.5)

    def test_saturation_rejects_excess_and_recovers_a_released_slot(self):
        with create_runtime_event_server(
            "127.0.0.1",
            0,
            initial_read_deadline_seconds=2,
        ) as server:
            host, port = server.server_address
            server_thread = self._start_server(server)
            connections = [
                socket.create_connection((host, port), timeout=1)
                for _ in range(server.max_active_connections)
            ]
            try:
                for connection in connections:
                    connection.sendall(FLUIDLINK_MAGIC[:1])
                self.assertTrue(
                    self._wait_until(
                        lambda: server.active_connection_count ==
                        server.max_active_connections
                    )
                )

                with socket.create_connection((host, port), timeout=1) as excess:
                    excess.settimeout(0.5)
                    self.assertEqual(b"", excess.recv(1))

                connections[0].close()
                self.assertTrue(
                    self._wait_until(
                        lambda: server.active_connection_count ==
                        server.max_active_connections - 1
                    )
                )
                self._perform_healthy_handshake(host, port)
            finally:
                for connection in connections:
                    connection.close()
                server.shutdown()
                server_thread.join(timeout=2)

            self.assertEqual(0, server.active_connection_count)
            self.assertFalse(server_thread.is_alive())

    def test_initial_prefix_uses_an_absolute_slow_drip_deadline(self):
        with create_runtime_event_server(
            "127.0.0.1",
            0,
            initial_read_deadline_seconds=0.12,
        ) as server:
            host, port = server.server_address
            server_thread = self._start_server(server)
            closed = False
            started = time.monotonic()
            try:
                with socket.create_connection((host, port), timeout=1) as connection:
                    connection.settimeout(0.5)
                    for value in FLUIDLINK_MAGIC + bytes((2,)):
                        try:
                            connection.sendall(bytes((value,)))
                        except OSError:
                            closed = True
                            break
                        time.sleep(0.04)
                    if not closed:
                        try:
                            closed = connection.recv(1) == b""
                        except ConnectionError:
                            closed = True
            finally:
                elapsed = time.monotonic() - started
                server.shutdown()
                server_thread.join(timeout=2)

            self.assertTrue(closed)
            self.assertLess(elapsed, 0.35)
            self.assertFalse(server_thread.is_alive())

    def test_in_progress_frame_uses_an_absolute_slow_drip_deadline(self):
        with create_runtime_event_server(
            "127.0.0.1",
            0,
            frame_read_deadline_seconds=0.12,
        ) as server:
            host, port = server.server_address
            server_thread = self._start_server(server)
            request = fluidlink_v2_request(
                opcode=FluidLinkOpcode.HELLO,
                sequence=1,
                payload=encode_hello_payload(
                    client_name="frame-deadline-test",
                    client_version="1",
                ),
            )
            wire = encode_fluidlink_v2_frame(request)
            closed = False
            started = time.monotonic()
            try:
                with socket.create_connection((host, port), timeout=1) as connection:
                    connection.settimeout(0.5)
                    connection.sendall(wire[:5])
                    for value in wire[5:]:
                        try:
                            connection.sendall(bytes((value,)))
                        except OSError:
                            closed = True
                            break
                        time.sleep(0.04)
                    if not closed:
                        try:
                            closed = connection.recv(1) == b""
                        except ConnectionError:
                            closed = True
            finally:
                elapsed = time.monotonic() - started
                server.shutdown()
                server_thread.join(timeout=2)

            self.assertTrue(closed)
            self.assertLess(elapsed, 0.35)
            self.assertFalse(server_thread.is_alive())

    def test_idle_completed_session_is_closed(self):
        with create_runtime_event_server(
            "127.0.0.1",
            0,
            idle_session_timeout_seconds=0.1,
        ) as server:
            host, port = server.server_address
            server_thread = self._start_server(server)
            request = fluidlink_v2_request(
                opcode=FluidLinkOpcode.HELLO,
                sequence=1,
                payload=encode_hello_payload(
                    client_name="idle-test",
                    client_version="1",
                ),
            )
            with socket.create_connection((host, port), timeout=1) as connection:
                connection.settimeout(0.5)
                stream = connection.makefile("rwb", buffering=0)
                stream.write(encode_fluidlink_v2_frame(request))
                self.assertIsNotNone(read_fluidlink_v2_frame(stream))
                self.assertEqual(b"", connection.recv(1))
                stream.close()
            server.shutdown()
            server_thread.join(timeout=2)

            self.assertFalse(server_thread.is_alive())

    def test_once_handler_waits_for_selected_connection_to_finish(self):
        with create_runtime_event_server(
            "127.0.0.1",
            0,
            idle_session_timeout_seconds=1,
        ) as server:
            host, port = server.server_address
            once_thread = threading.Thread(target=server.handle_request_and_wait)
            once_thread.start()
            with socket.create_connection((host, port), timeout=1) as connection:
                request = fluidlink_v2_request(
                    opcode=FluidLinkOpcode.HELLO,
                    sequence=1,
                    payload=encode_hello_payload(
                        client_name="once-test",
                        client_version="1",
                    ),
                )
                with connection.makefile("rwb", buffering=0) as stream:
                    stream.write(encode_fluidlink_v2_frame(request))
                    self.assertIsNotNone(read_fluidlink_v2_frame(stream))
                    self.assertTrue(once_thread.is_alive())
            once_thread.join(timeout=2)

            self.assertFalse(once_thread.is_alive())
            self.assertEqual(0, server.active_connection_count)

    def test_server_close_terminates_active_workers(self):
        server = create_runtime_event_server(
            "127.0.0.1",
            0,
            initial_read_deadline_seconds=30,
        )
        host, port = server.server_address
        server_thread = self._start_server(server)
        connection = socket.create_connection((host, port), timeout=1)
        try:
            connection.sendall(FLUIDLINK_MAGIC[:1])
            self.assertTrue(
                self._wait_until(lambda: server.active_connection_count == 1)
            )
            server.shutdown()
            server_thread.join(timeout=2)

            started = time.monotonic()
            server.server_close()
            elapsed = time.monotonic() - started
        finally:
            connection.close()
            server.server_close()

        self.assertLess(elapsed, 0.5)
        self.assertEqual(0, server.active_connection_count)
        self.assertFalse(server_thread.is_alive())

    def test_server_rejects_non_loopback_bind(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_runtime_event_server("0.0.0.0", 0)

    @staticmethod
    def _perform_healthy_handshake(host: str, port: int) -> None:
        request = fluidlink_v2_request(
            opcode=FluidLinkOpcode.HELLO,
            sequence=1,
            payload=encode_hello_payload(
                client_name="resilience-test",
                client_version="1",
            ),
        )
        with socket.create_connection((host, port), timeout=1) as connection:
            connection.settimeout(1)
            with connection.makefile("rwb", buffering=0) as stream:
                stream.write(encode_fluidlink_v2_frame(request))
                response = read_fluidlink_v2_frame(stream)
        if response is None or response.opcode != FluidLinkOpcode.WELCOME:
            raise AssertionError("Healthy FluidLink v2 handshake did not complete.")

    @staticmethod
    def _start_server(server):
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
        )
        thread.start()
        return thread

    @staticmethod
    def _wait_until(predicate, timeout: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return predicate()


if __name__ == "__main__":
    unittest.main()
