import os
import sys
import time
import math
import json
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

# Public JSON schema keys for samples
SAMPLE_KEYS = ("gpu", "vram_gb", "utilization", "temperature_c", "power_w", "timestamp")


class GPUBackend:
    """Interface for GPU metric backends.

    Implementations should return a dict with a subset of keys from SAMPLE_KEYS
    (timestamp will be filled by GPUMonitor). Values may be None when unavailable.
    """

    def __init__(self) -> None:
        self.total_vram_gb: Optional[float] = None
        self.name: Optional[str] = None

    def sample(self) -> Dict[str, Any]:  # pragma: no cover - overridden
        return {}


class StubBackend(GPUBackend):
    """Backend that returns None for all metrics. Always available."""

    def sample(self) -> Dict[str, Any]:
        return {
            "gpu": self.name,  # None
            "vram_gb": None,
            "utilization": None,
            "temperature_c": None,
            "power_w": None,
        }


class NvidiaSmiBackend(GPUBackend):
    """NVIDIA backend using nvidia-smi if present. Fails closed to Stub-like values."""

    def __init__(self) -> None:
        super().__init__()
        self._available = self._check_available()
        # Try to fetch static fields (name and total vram)
        if self._available:
            try:
                cp = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if cp.returncode == 0 and cp.stdout.strip():
                    line = cp.stdout.strip().splitlines()[0]
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        self.name = parts[0] or None
                        try:
                            mem_mib = float(parts[1])
                            self.total_vram_gb = mem_mib / 1024.0
                        except Exception:
                            self.total_vram_gb = None
            except Exception:
                # leave defaults
                pass

    @staticmethod
    def _check_available() -> bool:
        try:
            cp = subprocess.run(["nvidia-smi", "--help"], capture_output=True, text=True, timeout=2)
            return cp.returncode == 0 or cp.returncode == 2  # some versions return 2 on --help
        except Exception:
            return False

    def sample(self) -> Dict[str, Any]:
        if not self._available:
            return {
                "gpu": self.name,
                "vram_gb": None,
                "utilization": None,
                "temperature_c": None,
                "power_w": None,
            }
        try:
            # Query instantaneous metrics; nounits for easy parsing
            cp = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,name",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if cp.returncode != 0 or not cp.stdout.strip():
                raise RuntimeError("nvidia-smi query failed")
            line = cp.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            util, temp, power, mem_used, name = (parts + [None] * 5)[:5]
            util_f = float(util) if util not in (None, "") else None
            temp_f = float(temp) if temp not in (None, "") else None
            power_f = float(power) if power not in (None, "") else None
            vram_gb = (float(mem_used) / 1024.0) if mem_used not in (None, "") else None
            if name:
                self.name = name
            return {
                "gpu": self.name,
                "vram_gb": vram_gb,
                "utilization": util_f,
                "temperature_c": temp_f,
                "power_w": power_f,
            }
        except Exception:
            # Graceful fallback to None metrics
            return {
                "gpu": self.name,
                "vram_gb": None,
                "utilization": None,
                "temperature_c": None,
                "power_w": None,
            }


class GPUMonitor:
    """Sampling and aggregation API with pluggable backends."""

    def __init__(self, backend: Optional[GPUBackend] = None) -> None:
        if backend is None:
            backend_name = os.environ.get("GPU_MONITOR_BACKEND", "auto").lower()
            if backend_name == "stub":
                backend = StubBackend()
            elif backend_name in ("nvidia", "nvidia-smi", "smi"):
                backend = NvidiaSmiBackend()
            else:
                # Auto: prefer NVIDIA if available else stub
                b = NvidiaSmiBackend()
                backend = b if b._check_available() else StubBackend()
        self.backend = backend

    def sample_once(self) -> Dict[str, Any]:
        d = self.backend.sample() or {}
        # Normalize and ensure keys
        out: Dict[str, Any] = {}
        for k in SAMPLE_KEYS:
            out[k] = None
        # Copy known fields
        for k in ("gpu", "vram_gb", "utilization", "temperature_c", "power_w"):
            if k in d:
                out[k] = d[k]
        # timestamp last to avoid monkeypatch conflicts
        out["timestamp"] = float(time.time())
        return out

    def watch(
        self,
        interval_sec: float,
        duration_sec: Optional[float] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Collect samples at fixed intervals.

        Semantics: samples are taken after each interval tick, not immediately.
        For example, duration=10 and interval=1 yields 10 samples.
        """
        if interval_sec <= 0:
            raise ValueError("interval_sec must be > 0")
        if duration_sec is not None and duration_sec < 0:
            raise ValueError("duration_sec must be >= 0")

        samples: List[Dict[str, Any]] = []
        start = time.perf_counter()
        next_tick = start + interval_sec
        if duration_sec is None:
            # Run until externally stopped; here we limit to a safety cap to avoid runaway in tests.
            duration_sec = 0.0
        end = start + duration_sec

        # expected count
        expected = int(duration_sec / interval_sec + 1e-9) if duration_sec > 0 else 0
        while duration_sec > 0 and next_tick <= end + 1e-9:
            now = time.perf_counter()
            sleep_time = next_tick - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            s = self.sample_once()
            samples.append(s)
            if callback:
                try:
                    callback(s)
                except Exception:
                    pass
            next_tick += interval_sec
        return samples


class ImageRenderer:
    """Minimal image rendering for time series to PPM (P6) or BMP (24-bit)."""

    def __init__(self, width: int, height: int, title: str = "") -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width/height must be positive")
        self.w = int(width)
        self.h = int(height)
        self.title = title
        # RGB buffer, origin top-left
        self.pixels = bytearray([0] * (self.w * self.h * 3))

    def _put_pixel(self, x: int, y: int, rgb: Tuple[int, int, int]) -> None:
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        idx = (y * self.w + x) * 3
        r, g, b = rgb
        self.pixels[idx] = max(0, min(255, r))
        self.pixels[idx + 1] = max(0, min(255, g))
        self.pixels[idx + 2] = max(0, min(255, b))

    def _draw_line(self, x0: int, y0: int, x1: int, y1: int, rgb: Tuple[int, int, int]) -> None:
        # Bresenham
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self._put_pixel(x, y, rgb)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def plot(self, samples: List[Dict[str, Any]], total_vram_gb: Optional[float] = None) -> None:
        # Draw axes background (dark gray)
        for y in range(self.h):
            row = y * self.w * 3
            for x in range(self.w):
                base = row + x * 3
                self.pixels[base:base+3] = b"\x10\x10\x10"
        # Axis lines
        for x in range(self.w):
            self._put_pixel(x, self.h - 1, (80, 80, 80))
        for y in range(self.h):
            self._put_pixel(0, y, (80, 80, 80))
        n = len(samples)
        if n <= 1:
            return
        # X spacing
        def clamp(v: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, v))

        max_vram = total_vram_gb
        if max_vram is None:
            vals = [s.get("vram_gb") for s in samples if isinstance(s.get("vram_gb"), (int, float))]
            max_vram = max(vals) if vals else None
        if not max_vram or max_vram <= 0:
            max_vram = 1.0  # avoid div by zero

        # Build polyline points
        xs = [int(round(i * (self.w - 1) / (n - 1))) for i in range(n)]
        # Utilization: 0..100 -> top..bottom
        util_pts: List[Tuple[int, int]] = []
        vram_pts: List[Tuple[int, int]] = []
        for i, s in enumerate(samples):
            util = s.get("utilization")
            vram = s.get("vram_gb")
            u = 0.0 if not isinstance(util, (int, float)) else float(util)
            u = clamp(u, 0.0, 100.0)
            # invert y (0 at bottom)
            y_util = int(round((1.0 - (u / 100.0)) * (self.h - 1)))
            if isinstance(vram, (int, float)):
                r = clamp(float(vram) / float(max_vram), 0.0, 1.0)
            else:
                r = 0.0
            y_vram = int(round((1.0 - r) * (self.h - 1)))
            util_pts.append((xs[i], y_util))
            vram_pts.append((xs[i], y_vram))
        # Draw lines
        for i in range(1, n):
            x0, y0 = util_pts[i - 1]
            x1, y1 = util_pts[i]
            self._draw_line(x0, y0, x1, y1, (0, 255, 0))  # green
            x0, y0 = vram_pts[i - 1]
            x1, y1 = vram_pts[i]
            self._draw_line(x0, y0, x1, y1, (0, 128, 255))  # blue

    def save_ppm(self, path: str) -> None:
        with open(path, "wb") as f:
            header = f"P6\n{self.w} {self.h}\n255\n".encode("ascii")
            f.write(header)
            f.write(self.pixels)

    def save_bmp(self, path: str) -> None:
        # 24-bit BMP, rows bottom-up, padded to 4-byte boundaries
        row_stride = (self.w * 3 + 3) & ~3
        image_size = row_stride * self.h
        file_size = 14 + 40 + image_size
        # BITMAPFILEHEADER
        bfType = b"BM"
        bfSize = file_size.to_bytes(4, "little")
        bfReserved1 = (0).to_bytes(2, "little")
        bfReserved2 = (0).to_bytes(2, "little")
        bfOffBits = (14 + 40).to_bytes(4, "little")
        # BITMAPINFOHEADER
        biSize = (40).to_bytes(4, "little")
        biWidth = int(self.w).to_bytes(4, "little", signed=True)
        biHeight = int(self.h).to_bytes(4, "little", signed=True)
        biPlanes = (1).to_bytes(2, "little")
        biBitCount = (24).to_bytes(2, "little")
        biCompression = (0).to_bytes(4, "little")
        biSizeImage = image_size.to_bytes(4, "little")
        biXPelsPerMeter = (2835).to_bytes(4, "little")  # ~72 DPI
        biYPelsPerMeter = (2835).to_bytes(4, "little")
        biClrUsed = (0).to_bytes(4, "little")
        biClrImportant = (0).to_bytes(4, "little")
        with open(path, "wb") as f:
            f.write(bfType)
            f.write(bfSize)
            f.write(bfReserved1)
            f.write(bfReserved2)
            f.write(bfOffBits)
            f.write(biSize)
            f.write(biWidth)
            f.write(biHeight)
            f.write(biPlanes)
            f.write(biBitCount)
            f.write(biCompression)
            f.write(biSizeImage)
            f.write(biXPelsPerMeter)
            f.write(biYPelsPerMeter)
            f.write(biClrUsed)
            f.write(biClrImportant)
            # Pixel data: bottom-up rows, BGR order with padding
            pad = b"\x00" * (row_stride - self.w * 3)
            for row in range(self.h):
                y = self.h - 1 - row
                base = y * self.w * 3
                # convert RGB to BGR
                row_bytes = bytearray()
                for x in range(self.w):
                    idx = base + x * 3
                    r = self.pixels[idx]
                    g = self.pixels[idx + 1]
                    b = self.pixels[idx + 2]
                    row_bytes += bytes((b, g, r))
                f.write(row_bytes)
                if pad:
                    f.write(pad)


__all__ = [
    "GPUBackend",
    "StubBackend",
    "NvidiaSmiBackend",
    "GPUMonitor",
    "ImageRenderer",
    "SAMPLE_KEYS",
]
