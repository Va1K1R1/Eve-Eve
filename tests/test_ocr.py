import io
import os
import sys
import json
import tempfile
import unittest

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from vision.ocr import LocalOCR  # noqa: E402
from vision.cli_ocr import main as cli_main  # noqa: E402


def make_pgm_p5(width: int, height: int, pixels: bytes) -> bytes:
    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    return header + pixels


def draw_rects(width: int, height: int, rects):
    # rects: list of (x,y,w,h,value)
    img = bytearray([255] * (width * height))
    for (x, y, w, h, v) in rects:
        for yy in range(y, y + h):
            base = yy * width
            for xx in range(x, x + w):
                img[base + xx] = v
    return img


class OCRTests(unittest.TestCase):
    def test_detect_multiple_regions(self):
        w, h = 80, 60
        rects = [
            (5, 5, 20, 15, 0),   # dark block 1
            (40, 30, 25, 20, 0), # dark block 2
        ]
        pixels = draw_rects(w, h, rects)
        pgm = make_pgm_p5(w, h, bytes(pixels))

        ocr = LocalOCR()
        res = ocr.detect_and_read(pgm)
        self.assertIn("regions", res)
        regions = res["regions"]
        self.assertGreaterEqual(len(regions), 2)
        for r in regions:
            self.assertIn("bbox", r)
            self.assertIn("text", r)
            self.assertTrue(isinstance(r["text"], str) and len(r["text"]) > 0)
        # Expect bboxes roughly match; allow ±1 tolerance
        expected_bboxes = [
            [5, 5, 20, 15],
            [40, 30, 25, 20],
        ]
        # Sort by x,y like implementation
        expected_bboxes.sort(key=lambda b: (b[0], b[1]))
        got_bboxes = [r["bbox"] for r in regions[:2]]
        got_bboxes.sort(key=lambda b: (b[0], b[1]))
        def close(a, b):
            return all(abs(a[i]-b[i]) <= 1 for i in range(4))
        self.assertTrue(close(got_bboxes[0], expected_bboxes[0]))
        self.assertTrue(close(got_bboxes[1], expected_bboxes[1]))

    def test_blank_image_returns_empty(self):
        w, h = 32, 32
        img = bytes([255] * (w * h))
        pgm = make_pgm_p5(w, h, img)
        ocr = LocalOCR()
        res = ocr.detect_and_read(pgm)
        self.assertEqual(res["regions"], [])

    def test_unsupported_format_raises(self):
        ocr = LocalOCR()
        with self.assertRaises(ValueError):
            ocr.detect_and_read(b"GIF89a\x00\x00\x00")

    def test_cli_json_output(self):
        w, h = 20, 20
        rects = [ (2, 2, 6, 6, 0), (12, 10, 6, 8, 0) ]
        pixels = draw_rects(w, h, rects)
        pgm = make_pgm_p5(w, h, bytes(pixels))
        with tempfile.TemporaryDirectory() as td:
            img_path = os.path.join(td, "img.pgm")
            with open(img_path, "wb") as f:
                f.write(pgm)
            buf = io.StringIO()
            from unittest import mock
            with mock.patch("sys.stdout", new=buf):
                rc = cli_main(["--input", img_path, "--json"])  # call main() directly
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertIn("regions", data)
            self.assertIn("engine", data)
            self.assertIn("device", data)
            self.assertTrue(isinstance(data["regions"], list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
