import io
import os
import sys
import math
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

from audio.asr import LocalASR  # noqa: E402
from audio.cli_asr import main as cli_main  # noqa: E402


def _write_wav(path: str, samples, sample_rate: int = 16000):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # PCM16
        wf.setframerate(sample_rate)
        # Pack samples as little-endian 16-bit signed
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _generate_tone(duration_s: float = 1.0, sample_rate: int = 16000, freq: float = 440.0, amp: int = 10000):
    n = int(duration_s * sample_rate)
    two_pi_f = 2.0 * math.pi * freq
    return [int(amp * math.sin(two_pi_f * t / sample_rate)) for t in range(n)]


class ASRTests(unittest.TestCase):
    def test_transcribe_wav_path(self):
        asr = LocalASR()
        with tempfile.TemporaryDirectory() as td:
            wav_path = os.path.join(td, "tone.wav")
            # 0.2 s silence + 0.8 s tone
            sr = 16000
            silence = [0] * int(0.2 * sr)
            tone = _generate_tone(0.8, sr)
            samples = silence + tone
            _write_wav(wav_path, samples, sr)

            res = asr.transcribe(wav_path)
            self.assertEqual(res.text, "hello")
            self.assertEqual(res.language, "en")
            self.assertEqual(res.sample_rate, sr)
            self.assertEqual(len(res.segments), 1)
            seg = res.segments[0]
            self.assertLessEqual(0.0, seg.start)
            self.assertLess(seg.start, seg.end)
            self.assertLessEqual(seg.end, len(samples) / sr)

    def test_transcribe_raw_pcm_bytes(self):
        asr = LocalASR()
        sr = 16000
        samples = _generate_tone(0.5, sr)
        raw = struct.pack(f"<{len(samples)}h", *samples)
        res = asr.transcribe(raw)
        self.assertEqual(res.text, "hello")
        self.assertEqual(res.language, "en")
        self.assertEqual(len(res.segments), 1)

    def test_stream_chunks(self):
        asr = LocalASR()
        sr = 16000
        samples = _generate_tone(0.5, sr)
        raw = struct.pack(f"<{len(samples)}h", *samples)
        chunks = [raw[i:i+2048] for i in range(0, len(raw), 2048)]
        results = list(asr.stream(chunks, sample_rate=sr))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "hello")
        self.assertEqual(results[0].language, "en")

    def test_silence_returns_empty(self):
        asr = LocalASR()
        sr = 16000
        silence = bytes([0, 0] * int(0.5 * sr))  # 0.5s of zeros PCM16
        res = asr.transcribe(silence)
        self.assertEqual(res.text, "")
        self.assertEqual(len(res.segments), 0)

    def test_cli_json_output(self):
        asr = LocalASR()
        with tempfile.TemporaryDirectory() as td:
            wav_path = os.path.join(td, "tone.wav")
            sr = 16000
            samples = _generate_tone(0.5, sr)
            _write_wav(wav_path, samples, sr)

            buf = io.StringIO()
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = cli_main(["--input", wav_path, "--json"])  # call main() directly
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertIn("text", data)
            self.assertEqual(data["text"], "hello")
            self.assertIn("segments", data)
            self.assertTrue(isinstance(data["segments"], list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
