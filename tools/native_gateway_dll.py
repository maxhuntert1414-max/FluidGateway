"""ctypes ABI test driver; production in-process calls are made directly by .NET."""

from __future__ import annotations

import ctypes as c
from contextlib import nullcontext
import os
from pathlib import Path

from tools.native_gateway_validation import native_executable

ABI_VERSION = 0x10000
MAX_FRAME = 65591


def native_library() -> Path:
    return Path(
        os.environ.get("FLUIDGATEWAY_DLL", native_executable().with_name("FluidGatewayNative.dll"))
    )


class Metrics(c.Structure):
    _fields_ = [
        (name, c.c_uint64)
        for name in (
            "exchanges",
            "request_bytes",
            "response_bytes",
            "wire_payload_copy_bytes",
            "wire_payload_copy_count",
            "state_allocation_count",
            "state_allocated_bytes",
            "state_bytes",
            "state_peak_bytes",
            "active_resources",
            "tracked_operations",
        )
    ] + [("closed", c.c_uint32), ("reserved", c.c_uint32)]


class DllSession:
    def __init__(self, path: Path | None = None):
        asan_directory = os.environ.get("FLUIDGATEWAY_ASAN_DIRECTORY")
        # Python's secure DLL loader intentionally ignores PATH for dependencies.
        with os.add_dll_directory(asan_directory) if asan_directory else nullcontext():
            self.dll = c.CDLL(str((path or native_library()).resolve()))
        self.dll.fgn_session_create.argtypes = [c.c_uint32, c.POINTER(c.c_uint64)]
        self.dll.fgn_session_create.restype = c.c_uint32
        self.dll.fgn_session_exchange.argtypes = [
            c.c_uint64,
            c.c_void_p,
            c.c_uint32,
            c.c_void_p,
            c.c_uint32,
            c.POINTER(c.c_uint32),
        ]
        self.dll.fgn_session_exchange.restype = c.c_uint32
        self.dll.fgn_session_destroy.argtypes = [c.c_uint64]
        self.dll.fgn_session_destroy.restype = c.c_uint32
        self.dll.fgn_session_get_metrics.argtypes = [c.c_uint64, c.POINTER(Metrics), c.c_uint32]
        self.dll.fgn_session_get_metrics.restype = c.c_uint32
        self.handle = c.c_uint64()
        self.output = c.create_string_buffer(MAX_FRAME)
        status = self.dll.fgn_session_create(ABI_VERSION, c.byref(self.handle))
        if status:
            raise RuntimeError(f"DLL create status {status}")

    def exchange_status(self, request: bytes) -> tuple[int, bytes]:
        size = c.c_uint32()
        status = self.dll.fgn_session_exchange(
            self.handle, request, len(request), self.output, MAX_FRAME, c.byref(size)
        )
        return status, self.output.raw[: size.value]

    def exchange(self, request: bytes) -> bytes:
        status, output = self.exchange_status(request)
        if status:
            raise RuntimeError(f"DLL exchange status {status}")
        return output

    def metrics(self) -> Metrics:
        result = Metrics()
        status = self.dll.fgn_session_get_metrics(self.handle, c.byref(result), c.sizeof(result))
        if status:
            raise RuntimeError(f"DLL metrics status {status}")
        return result

    def close(self):
        if self.handle.value:
            status = self.dll.fgn_session_destroy(self.handle)
            self.handle.value = 0
            if status:
                raise RuntimeError(f"DLL destroy status {status}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
