import io
import os
import sys
import wave
import struct
import tempfile
import unittest
import json

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from audio.tts import LocalTTS  # noqa: E402
from audio.cli_tts import main as tts_cli_main  # noqa: E402


class TTSTests(unittest.TestCase):
    def test_synthesize_bytes_and_duration(self):
        tts = LocalTTS(char_ms=50, gap_ms=10)
        sr = 16000
        text = "ab"
        res = tts.synthesize(text, sample_rate=sr)
        # Expect: 2 chars -> 50ms tone + 10ms gap + 50ms tone = 110ms total
        expected_samples = int(0.05 * sr) + int(0.01 * sr) + int(0.05 * sr)
        expected_bytes = expected_samples * 2
        self.assertEqual(res.sample_rate, sr)
        self.assertEqual(len(res.pcm16), expected_bytes)
        self.assertAlmostEqual(res.duration_s, expected_samples / sr, places=3)

    def test_whitespace_yields_200ms_silence(self):
        tts = LocalTTS()
        sr = 16000
        res = tts.synthesize("   \t\n", sample_rate=sr)
        expected_samples = int(0.2 * sr)
        self.assertEqual(len(res.pcm16), expected_samples * 2)

    def test_streaming_chunks(self):
        tts = LocalTTS()
        sr = 16000
        chunk_ms = 20
        res = tts.synthesize("abc", sample_rate=sr)
        chunks = list(tts.stream("abc", chunk_ms=chunk_ms, sample_rate=sr))
        # All chunks concatenated should equal the full PCM
        self.assertEqual(b"".join(chunks), res.pcm16)
        # Each chunk (except maybe last) should be chunk_ms duration
        chunk_bytes = int(sr * (chunk_ms / 1000.0)) * 2
        for c in chunks[:-1]:
            self.assertEqual(len(c), chunk_bytes)
        self.assertGreater(len(chunks), 0)

    def test_save_wav_and_read_back(self):
        tts = LocalTTS()
        sr = 16000
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out.wav")
            res = tts.save_wav(out, "test", sample_rate=sr)
            self.assertTrue(os.path.exists(out))
            with wave.open(out, "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertEqual(wf.getframerate(), sr)
                # number of frames should match PCM length / 2
                self.assertEqual(wf.getnframes(), len(res.pcm16) // 2)

    def test_cli_json_no_output(self):
        buf = io.StringIO()
        with unittest.mock.patch("sys.stdout", new=buf):
            rc = tts_cli_main(["--text", "abc", "--json"])  # call main() directly
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("duration_s", data)
        self.assertIn("sample_rate", data)
        self.assertIn("bytes", data)

    def test_cli_json_with_output_path(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "say.wav")
            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = tts_cli_main(["--text", "abc", "--output", out, "--json"])  # call main() directly
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(os.path.abspath(out), data.get("output"))
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
