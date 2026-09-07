"""Launch two owned peers and the actual .NET authorizer benchmark (no GPU execution)."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

from native_gateway_validation import ROOT, native_executable, server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=ROOT.parent / "FluidRuntime")
    parser.add_argument("--native", type=Path, default=native_executable())
    parser.add_argument("--runtime-native-build", type=Path, default=Path("native/build-vulkan"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    tool = runtime / "tools/GatewayComparison/bin/Release/net10.0/GatewayComparison.dll"
    build = runtime / args.runtime_native_build / "Release"
    target = build / "fluidruntime-hook-target.exe"
    hook = build / "fluidruntime-present-hook.dll"
    for path in (tool, target, hook, args.native):
        if not path.is_file():
            parser.error(f"Required built file missing: {path}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with server("Python") as (python, pport), server("Native", args.native.resolve()) as (native, nport):
        subprocess.run(["dotnet", str(tool), str(pport), str(python.pid),
            hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(), str(nport), str(native.pid),
            hashlib.sha256(args.native.read_bytes()).hexdigest(), str(target), str(hook),
            str(args.out.resolve())], check=True, timeout=300)


if __name__ == "__main__":
    main()
