from __future__ import annotations

import json
import socketserver
from typing import Any

from .control import FluidGatewayController
from .events import process_event_payload


class RuntimeEventRequestHandler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.controller = FluidGatewayController()

    def handle(self) -> None:
        for raw_line in self.rfile:
            line = raw_line.decode("utf-8").strip()
            if not line or line.startswith("#"):
                continue
            response = self.handle_line(line)
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
            self.wfile.write(b"\n")
            self.wfile.flush()

    def handle_line(self, line: str) -> dict[str, Any]:
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Runtime event must be a JSON object.")
            return process_event_payload(self.controller, payload)
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
