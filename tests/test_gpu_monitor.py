import io
import os
import sys
import json
import math
import tempfile
import unittest
from typing import List, Dict, Any

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from system.gpu_monitor import GPUMonitor, StubBackend, ImageRenderer  # noqa: E402
from system.cli_gpu import main as cli_main  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def perf_counter(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        # advance exactly by dt
        self.t += float(dt)

    def time(self) -> float:
        # wallclock tied to same counter for determinism
        return self.t


class GPUMonitorTests(unittest.TestCase):
    def test_sample_once_schema_stub(self):
        mon = GPUMonitor(backend=StubBackend())
        s = mon.sample_once()
        self.assertIsInstance(s, dict)
        for k in ("gpu", "vram_gb", "utilization", "temperature_c", "power_w", "timestamp"):
            self.assertIn(k, s)
        # timestamp must be a float
        self.assertTrue(isinstance(s["timestamp"], float))
        # other fields None on stub
        self.assertIsNone(s["gpu"])
        self.assertIsNone(s["vram_gb"])
        self.assertIsNone(s["utilization"])
        self.assertIsNone(s["temperature_c"])
        self.assertIsNone(s["power_w"])

    def test_watch_timing_monkeypatched(self):
        # Patch time module functions within system.gpu_monitor
        import system.gpu_monitor as gm

        fc = FakeClock(start=1000.0)
        # monkeypatch
        orig_sleep = gm.time.sleep
        orig_perf = gm.time.perf_counter
        orig_time = gm.time.time
        try:
            gm.time.sleep = fc.sleep  # type: ignore
            gm.time.perf_counter = fc.perf_counter  # type: ignore
            gm.time.time = fc.time  # type: ignore
            mon = GPUMonitor(backend=StubBackend())
            interval = 1.0
            duration = 10.0
            samples = mon.watch(interval, duration)
            # Expect exactly duration/interval samples
            self.assertEqual(len(samples), int(duration / interval))
            # Timestamps should increase by ~1.0 each within ±10%
            for i in range(1, len(samples)):
                dt = samples[i]["timestamp"] - samples[i - 1]["timestamp"]
                self.assertGreaterEqual(dt, 0.9)
                self.assertLessEqual(dt, 1.1)
        finally:
            gm.time.sleep = orig_sleep  # type: ignore
            gm.time.perf_counter = orig_perf  # type: ignore
            gm.time.time = orig_time  # type: ignore

    def test_image_renderer_dimensions_ppm_bmp(self):
        # Create synthetic samples
        samples: List[Dict[str, Any]] = []
        for i in range(20):
            samples.append({
                "gpu": "Stub",
                "vram_gb": i * 0.1,
                "utilization": (i * 5) % 100,
                "temperature_c": None,
                "power_w": None,
                "timestamp": 1000.0 + i,
            })
        w, h = 80, 20
        renderer = ImageRenderer(w, h, title="Test")
        renderer.plot(samples, total_vram_gb=2.0)
        with tempfile.TemporaryDirectory() as td:
            ppm = os.path.join(td, "out.ppm")
            bmp = os.path.join(td, "out.bmp")
            renderer.save_ppm(ppm)
            renderer.save_bmp(bmp)
            # Parse PPM header
            with open(ppm, "rb") as f:
                header = f.readline().strip()  # P6
                self.assertEqual(header, b"P6")
                dims = f.readline().strip().split()
                self.assertEqual(int(dims[0]), w)
                self.assertEqual(int(dims[1]), h)
                maxv = f.readline().strip()
                self.assertEqual(maxv, b"255")
            # Parse BMP header
            with open(bmp, "rb") as f:
                sig = f.read(2)
                self.assertEqual(sig, b"BM")
                f.seek(18)
                width = int.from_bytes(f.read(4), "little", signed=True)
                height = int.from_bytes(f.read(4), "little", signed=True)
                self.assertEqual(width, w)
                self.assertEqual(height, h)

    def test_cli_once_json_stub(self):
        # Call CLI main directly with stub backend
        buf = io.StringIO()
        from unittest import mock
        with mock.patch("sys.stdout", new=buf):
            rc = cli_main(["--once", "--json", "--backend", "stub"])  # no image
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("gpu", data)
        self.assertIn("vram_gb", data)
        self.assertIn("utilization", data)
        self.assertIn("temperature_c", data)
        self.assertIn("power_w", data)
        self.assertIn("timestamp", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
