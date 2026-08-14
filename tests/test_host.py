from __future__ import annotations

import unittest

from fluidgateway.host import (
    HostGpuCapability,
    build_host_capability_snapshot,
    gpu_capability_from_cim,
)


class HostCapabilitySnapshotTests(unittest.TestCase):
    def test_host_snapshot_classifies_balanced_gaming_host(self):
        snapshot = build_host_capability_snapshot(
            os_name="Windows",
            os_release="11",
            os_version="test",
            machine="AMD64",
            processor="test-cpu",
            python_version="3.13.0",
            cpu_logical_count=16,
            total_ram_mb=32768,
            available_ram_mb=24576,
            gpus=[
                HostGpuCapability(
                    name="Test GPU",
                    adapter_ram_mb=8192,
                    driver_version="1.2.3",
                    source="test",
                )
            ],
        )
        payload = snapshot.to_dict()

        self.assertEqual(payload["mode"], "host-capability-snapshot-v0.47")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_modify_system"])
        self.assertEqual(payload["capture_guard"], "observe-only")
        self.assertEqual(payload["cpu_class"], "high-parallelism-cpu")
        self.assertEqual(payload["ram_class"], "high-capacity-ram")
        self.assertEqual(payload["ram_pressure_class"], "low-pressure")
        self.assertEqual(payload["gpu_class"], "balanced-vram-gpu")
        self.assertEqual(payload["host_profile"], "balanced-gaming-host")
        self.assertEqual(payload["manager_hint"], "allow-daemon-supervisor-loop")
        self.assertEqual(payload["telemetry_confidence"], "high")
        self.assertEqual(payload["gpu_count"], 1)
        self.assertEqual(payload["total_reported_vram_mb"], 8192)
        self.assertEqual(payload["largest_reported_vram_mb"], 8192)
        self.assertEqual(
            payload["gpu_selection_basis"],
            "largest-reported-adapter-not-active-process-binding",
        )

    def test_multi_gpu_classification_does_not_sum_unrelated_adapters(self):
        snapshot = build_host_capability_snapshot(
            os_name="Windows",
            os_release="11",
            os_version="test",
            machine="AMD64",
            processor="test-cpu",
            python_version="3.13.0",
            cpu_logical_count=16,
            total_ram_mb=32768,
            available_ram_mb=24576,
            gpus=[
                HostGpuCapability("GPU A", 8192, "1", "test"),
                HostGpuCapability("GPU B", 8192, "2", "test"),
            ],
        )

        payload = snapshot.to_dict()

        self.assertEqual(payload["total_reported_vram_mb"], 16384)
        self.assertEqual(payload["largest_reported_vram_mb"], 8192)
        self.assertEqual(payload["gpu_class"], "balanced-vram-gpu")
        self.assertEqual(payload["telemetry_confidence"], "medium")

    def test_host_snapshot_prioritizes_memory_pressure_hint(self):
        snapshot = build_host_capability_snapshot(
            os_name="Windows",
            os_release="11",
            os_version="test",
            machine="AMD64",
            processor="test-cpu",
            python_version="3.13.0",
            cpu_logical_count=12,
            total_ram_mb=16000,
            available_ram_mb=1000,
            gpus=[],
            capture_errors=["gpu-probe-empty"],
        )
        payload = snapshot.to_dict()

        self.assertEqual(payload["ram_pressure_pct"], 93.75)
        self.assertEqual(payload["ram_pressure_class"], "high-pressure")
        self.assertEqual(payload["host_profile"], "memory-pressure-host")
        self.assertEqual(
            payload["manager_hint"],
            "tighten-memory-residency-observation",
        )
        self.assertEqual(payload["telemetry_confidence"], "medium")
        self.assertEqual(payload["capture_errors"], ["gpu-probe-empty"])

    def test_gpu_capability_from_cim_parses_adapter_ram(self):
        gpu = gpu_capability_from_cim(
            {
                "Name": "Example GPU",
                "AdapterRAM": 4294967296,
                "DriverVersion": "31.0.0",
            }
        )
        payload = gpu.to_dict()

        self.assertEqual(payload["name"], "Example GPU")
        self.assertEqual(payload["adapter_ram_mb"], 4096)
        self.assertEqual(payload["driver_version"], "31.0.0")
        self.assertEqual(payload["source"], "win32-video-controller")


if __name__ == "__main__":
    unittest.main()
