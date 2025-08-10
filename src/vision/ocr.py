from __future__ import annotations

import io
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional


@dataclass
class Region:
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    text: str


class OCR(ABC):
    @abstractmethod
    def detect_and_read(self, image_bytes: bytes) -> Dict[str, Any]:
        """Detect text regions and return their bounding boxes and recognized text.
        Returns a dict: {"regions": [{"bbox": [x,y,w,h], "text": str}, ...], "engine": "local-ocr", "device": "cpu"|"gpu"}
        """
        raise NotImplementedError


class LocalOCR(OCR):
    """Dependency-free, deterministic local OCR stub.

    - Supports PGM/PPM (P2/P3/P5/P6) and minimal 24-bit uncompressed BMP.
    - Thresholds the image (grayscale) and performs 4-connected component labeling.
    - Generates deterministic pseudo-text per region based on area and position.
    - GPU flag is a stub; computation remains on CPU.
    """

    def __init__(self, use_gpu: bool = False, threshold: int = 128) -> None:
        self.use_gpu = bool(use_gpu)
        self.threshold = int(threshold)

    def detect_and_read(self, image_bytes: bytes) -> Dict[str, Any]:
        if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) < 2:
            raise ValueError("image_bytes must be non-empty bytes")
        # Parse image
        fmt = _sniff_format(image_bytes)
        if fmt in ("P2", "P3", "P5", "P6"):
            w, h, gray = _parse_pnm_to_grayscale(image_bytes)
        elif fmt == "BMP":
            w, h, gray = _parse_bmp24_to_grayscale(image_bytes)
        else:
            raise ValueError("unsupported image format")

        # Threshold
        fg = _threshold(gray, w, h, self.threshold)
        # Label components
        regions = _connected_components(fg, w, h)
        # Convert to result format
        regions_out = []
        for idx, r in enumerate(regions):
            x, y, w0, h0 = r.bbox
            regions_out.append({
                "bbox": [int(x), int(y), int(w0), int(h0)],
                "text": r.text,
            })
        result = {
            "regions": regions_out,
            "engine": "local-ocr",
            "device": "gpu" if self.use_gpu else "cpu",
        }
        return result


# --- Image parsing helpers ---

def _sniff_format(b: bytes) -> str:
    if len(b) >= 2 and b[0:2] in (b"P2", b"P3", b"P5", b"P6"):
        return b[0:2].decode("ascii")
    if len(b) >= 2 and b[0:2] == b"BM":
        return "BMP"
    # Also allow minimal BMP signature check by extension not available; fall back to error
    return "UNKNOWN"


def _parse_pnm_to_grayscale(b: bytes) -> Tuple[int, int, bytearray]:
    # Parse header tokens (magic, width, height, maxval) while skipping comments
    magic = b[0:2].decode("ascii")
    stream = memoryview(b)
    idx = 2

    def _read_token() -> str:
        nonlocal idx
        n = len(stream)
        # Skip whitespace
        while idx < n and chr(stream[idx]).isspace():
            idx += 1
        if idx >= n:
            raise ValueError("invalid PNM header")
        # Skip comments
        if stream[idx] == ord('#'):
            # skip to end of line
            while idx < n and stream[idx] not in (10, 13):
                idx += 1
            return _read_token()
        # Read token until whitespace
        start = idx
        while idx < n and not chr(stream[idx]).isspace():
            idx += 1
        return bytes(stream[start:idx]).decode("ascii")

    try:
        w = int(_read_token())
        h = int(_read_token())
        maxval = int(_read_token())
    except Exception:
        raise ValueError("invalid PNM header")
    if w <= 0 or h <= 0 or maxval <= 0:
        raise ValueError("invalid PNM dimensions")

    # After reading maxval, the next byte should be a single whitespace then data for P5/P6
    if magic in ("P5", "P6"):
        # Skip a single whitespace
        if idx < len(stream) and chr(stream[idx]).isspace():
            idx += 1
        data = bytes(stream[idx:])
        if magic == "P5":
            expected = w * h
            if len(data) < expected:
                raise ValueError("PNM data too short")
            if maxval != 255:
                gray = bytearray((p * 255) // maxval for p in data[:expected])
            else:
                gray = bytearray(data[:expected])
            return w, h, gray
        else:  # P6
            expected = w * h * 3
            if len(data) < expected:
                raise ValueError("PNM data too short")
            gray = bytearray(expected // 3)
            if maxval != 255:
                for i in range(0, expected, 3):
                    r = data[i]
                    g = data[i + 1]
                    b0 = data[i + 2]
                    r = (r * 255) // maxval
                    g = (g * 255) // maxval
                    b1 = (b0 * 255) // maxval
                    # luminance approx
                    y = (30 * r + 59 * g + 11 * b1) // 100
                    gray[i // 3] = y
            else:
                for i in range(0, expected, 3):
                    r = data[i]
                    g = data[i + 1]
                    b1 = data[i + 2]
                    y = (30 * r + 59 * g + 11 * b1) // 100
                    gray[i // 3] = y
            return w, h, gray
    else:
        # ASCII variants P2/P3: tokenize remaining as integers (skip comments)
        rest = bytes(stream[idx:])
        # Remove comments from rest
        tokens: List[str] = []
        cur = []
        i = 0
        n = len(rest)
        while i < n:
            ch = rest[i]
            if ch == 35:  # '#'
                # skip to end of line
                while i < n and rest[i] not in (10, 13):
                    i += 1
                i += 1
                continue
            if chr(ch).isspace():
                if cur:
                    tokens.append(bytes(cur).decode("ascii"))
                    cur = []
                i += 1
                continue
            cur.append(ch)
            i += 1
        if cur:
            tokens.append(bytes(cur).decode("ascii"))
        ints: List[int] = []
        for t in tokens:
            try:
                ints.append(int(t))
            except Exception:
                raise ValueError("invalid PNM pixel data")
        if magic == "P2":
            expected = w * h
            if len(ints) < expected:
                raise ValueError("PNM data too short")
            if maxval != 255:
                gray = bytearray((min(max(v, 0), maxval) * 255) // maxval for v in ints[:expected])
            else:
                gray = bytearray(min(max(v, 0), 255) for v in ints[:expected])
            return w, h, gray
        else:  # P3
            expected = w * h * 3
            if len(ints) < expected:
                raise ValueError("PNM data too short")
            gray = bytearray(expected // 3)
            for i2 in range(0, expected, 3):
                r = ints[i2]
                g = ints[i2 + 1]
                b2 = ints[i2 + 2]
                if maxval != 255:
                    r = (min(max(r, 0), maxval) * 255) // maxval
                    g = (min(max(g, 0), maxval) * 255) // maxval
                    b2 = (min(max(b2, 0), maxval) * 255) // maxval
                else:
                    r = min(max(r, 0), 255)
                    g = min(max(g, 0), 255)
                    b2 = min(max(b2, 0), 255)
                y = (30 * r + 59 * g + 11 * b2) // 100
                gray[i2 // 3] = y
            return w, h, gray


def _parse_bmp24_to_grayscale(b: bytes) -> Tuple[int, int, bytearray]:
    if len(b) < 54:
        raise ValueError("invalid BMP header")
    if b[0:2] != b"BM":
        raise ValueError("invalid BMP signature")
    file_size = int.from_bytes(b[2:6], "little", signed=False)
    pixel_offset = int.from_bytes(b[10:14], "little", signed=False)
    dib_size = int.from_bytes(b[14:18], "little", signed=False)
    if dib_size < 40:
        raise ValueError("unsupported BMP DIB header")
    w = int.from_bytes(b[18:22], "little", signed=True)
    h = int.from_bytes(b[22:26], "little", signed=True)
    planes = int.from_bytes(b[26:28], "little", signed=False)
    bpp = int.from_bytes(b[28:30], "little", signed=False)
    compression = int.from_bytes(b[30:34], "little", signed=False)
    if planes != 1 or bpp != 24 or compression != 0:
        raise ValueError("unsupported BMP format")
    width = w
    height = abs(h)
    bottom_up = h > 0
    row_size = ((bpp * width + 31) // 32) * 4
    data = b[pixel_offset:]
    expected = row_size * height
    if len(data) < expected:
        raise ValueError("BMP data too short")
    gray = bytearray(width * height)
    for row in range(height):
        src_row = (height - 1 - row) if bottom_up else row
        base = src_row * row_size
        for col in range(width):
            i = base + col * 3
            if i + 2 >= len(data):
                raise ValueError("BMP data too short")
            b0 = data[i]
            g0 = data[i + 1]
            r0 = data[i + 2]
            y = (30 * r0 + 59 * g0 + 11 * b0) // 100
            gray[row * width + col] = y
    return width, height, gray


# --- Processing helpers ---

def _threshold(gray: bytearray, w: int, h: int, th: int) -> bytearray:
    thv = max(0, min(255, th))
    n = w * h
    fg = bytearray(n)
    for i in range(n):
        fg[i] = 1 if gray[i] < thv else 0  # dark as foreground
    return fg


def _connected_components(fg: bytearray, w: int, h: int) -> List[Region]:
    n = w * h
    visited = bytearray(n)
    regions: List[Region] = []

    def idx_xy(x: int, y: int) -> int:
        return y * w + x

    for y in range(h):
        base = y * w
        for x in range(w):
            i = base + x
            if fg[i] == 0 or visited[i] == 1:
                continue
            # New component: flood fill
            minx = x
            miny = y
            maxx = x
            maxy = y
            area = 0
            stack = [i]
            visited[i] = 1
            while stack:
                cur = stack.pop()
                cy, cx = divmod(cur, w)[0], divmod(cur, w)[1]
                # above line is inefficient; compute as:
                cy = cur // w
                cx = cur - cy * w
                if cx < minx:
                    minx = cx
                if cx > maxx:
                    maxx = cx
                if cy < miny:
                    miny = cy
                if cy > maxy:
                    maxy = cy
                area += 1
                # neighbors 4-connectivity
                # left
                if cx > 0:
                    ni = cur - 1
                    if fg[ni] == 1 and visited[ni] == 0:
                        visited[ni] = 1
                        stack.append(ni)
                # right
                if cx + 1 < w:
                    ni = cur + 1
                    if fg[ni] == 1 and visited[ni] == 0:
                        visited[ni] = 1
                        stack.append(ni)
                # up
                if cy > 0:
                    ni = cur - w
                    if fg[ni] == 1 and visited[ni] == 0:
                        visited[ni] = 1
                        stack.append(ni)
                # down
                if cy + 1 < h:
                    ni = cur + w
                    if fg[ni] == 1 and visited[ni] == 0:
                        visited[ni] = 1
                        stack.append(ni)
            bbox = (minx, miny, maxx - minx + 1, maxy - miny + 1)
            # Deterministic text based on bbox and area
            text = _region_text(area, bbox)
            regions.append(Region(bbox=bbox, text=text))

    # Sort by x, then y for determinism
    regions.sort(key=lambda r: (r.bbox[0], r.bbox[1]))
    return regions


def _region_text(area: int, bbox: Tuple[int, int, int, int]) -> str:
    x, y, w, h = bbox
    # Simple deterministic pseudo text: base36-like from area and bbox sum
    val = (area * 1315423911 + x * 2654435761 + y * 97 + w * 31 + h * 17) & 0xFFFFFFFF
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    out = []
    for _ in range(6):
        out.append(alphabet[val % len(alphabet)])
        val //= len(alphabet)
    return "".join(out)


__all__ = ["OCR", "LocalOCR", "Region"]
