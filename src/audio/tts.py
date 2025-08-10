from __future__ import annotations

import io
import math
import wave
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class SynthesisResult:
    pcm16: bytes  # mono PCM16LE
    sample_rate: int
    duration_s: float


class SpeechSynthesizer(ABC):
    @abstractmethod
    def synthesize(self, text: str, sample_rate: int = 16000, amplitude: float = 0.2) -> SynthesisResult:
        """Synthesize speech-like audio deterministically from text.
        This offline stub generates simple tone beeps per character to keep tests fast and deterministic.
        - text: input text (ASCII/UTF-8). Non-ASCII characters are mapped to a default tone.
        - sample_rate: output PCM sample rate (Hz), default 16 kHz.
        - amplitude: 0.0-1.0 relative amplitude (clamped), default 0.2.
        Returns mono PCM16LE bytes and metadata.
        """
        raise NotImplementedError

    @abstractmethod
    def stream(self, text: str, chunk_ms: int = 20, sample_rate: int = 16000, amplitude: float = 0.2) -> Iterator[bytes]:
        """Yield PCM16LE chunks of size chunk_ms for the synthesized result.
        Deterministic: splits the same buffer produced by synthesize into fixed-size chunks.
        """
        raise NotImplementedError

    def save_wav(self, path: str, text: str, sample_rate: int = 16000, amplitude: float = 0.2) -> SynthesisResult:
        res = self.synthesize(text, sample_rate=sample_rate, amplitude=amplitude)
        _write_wav_mono_pcm16(path, res.sample_rate, res.pcm16)
        return res


class LocalTTS(SpeechSynthesizer):
    """Deterministic offline TTS stub.

    Behavior:
    - Maps each character to a short fixed-duration beep at a frequency derived from the character.
    - Inserts a 10 ms silence between characters to create separations.
    - If text is empty or only whitespace, returns 200 ms of silence.
    - No external dependencies; outputs mono PCM16LE.
    """

    def __init__(self, char_ms: int = 50, gap_ms: int = 10):
        self.char_ms = char_ms
        self.gap_ms = gap_ms

    def synthesize(self, text: str, sample_rate: int = 16000, amplitude: float = 0.2) -> SynthesisResult:
        sr = int(sample_rate)
        if sr <= 0:
            raise ValueError("sample_rate must be positive")
        amp = max(0.0, min(1.0, float(amplitude)))
        # Normalize text
        input_text = text or ""
        # Duration per piece
        char_samples = max(1, int(sr * self.char_ms / 1000.0))
        gap_samples = max(1, int(sr * self.gap_ms / 1000.0))

        frames: list[int] = []

        def tone_freq(ch: str) -> float:
            # Map ASCII letters/digits to a small set of tones; others default.
            # Use a simple hash to keep deterministic mapping.
            base = 220.0  # A3
            step = 20.0
            idx = (ord(ch) % 12)
            return base + step * idx

        def append_silence(n: int):
            frames.extend([0] * n)

        def append_tone(freq: float, n: int):
            # Simple sine wave
            two_pi_f = 2.0 * math.pi * freq
            for i in range(n):
                t = i / sr
                s = math.sin(two_pi_f * t)
                val = int(max(-1.0, min(1.0, s)) * (amp * 32767))
                frames.append(val)

        # Build frames
        effective_chars = [c for c in input_text if not c.isspace()]
        if not effective_chars:
            append_silence(int(0.2 * sr))  # 200 ms silence
        else:
            for idx, ch in enumerate(effective_chars):
                append_tone(tone_freq(ch), char_samples)
                if idx != len(effective_chars) - 1:
                    append_silence(gap_samples)

        # Pack to PCM16LE
        pcm16 = _int16_list_to_pcm16(frames)
        duration = len(frames) / float(sr)
        return SynthesisResult(pcm16=pcm16, sample_rate=sr, duration_s=round(duration, 3))

    def stream(self, text: str, chunk_ms: int = 20, sample_rate: int = 16000, amplitude: float = 0.2) -> Iterator[bytes]:
        res = self.synthesize(text, sample_rate=sample_rate, amplitude=amplitude)
        sr = res.sample_rate
        chunk_samples = max(1, int(sr * chunk_ms / 1000.0))
        # Iterate over the PCM16 in sample-sized chunks
        total_samples = len(res.pcm16) // 2
        for start in range(0, total_samples, chunk_samples):
            end = min(total_samples, start + chunk_samples)
            yield res.pcm16[start * 2 : end * 2]


# --- Helpers ---

def _int16_list_to_pcm16(values: list[int]) -> bytes:
    if not values:
        return b""
    fmt = f"<{len(values)}h"
    return struct.pack(fmt, *values)


def _write_wav_mono_pcm16(path: str, sample_rate: int, pcm16: bytes) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
