from __future__ import annotations

import io
import os
import wave
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Tuple, Union


@dataclass
class Segment:
    text: str
    start: float
    end: float


@dataclass
class TranscriptionResult:
    text: str
    segments: List[Segment]
    language: Optional[str] = None
    sample_rate: Optional[int] = None


class SpeechRecognizer(ABC):
    @abstractmethod
    def transcribe(self, source: Union[str, bytes], language: Optional[str] = None, timestamps: bool = True) -> TranscriptionResult:
        """Transcribe an audio source.
        - source: path to WAV file OR raw PCM16 (mono, little-endian) bytes when not a file path
        - language: optional language hint; if None, default to 'en' in this offline stub
        - timestamps: whether to populate segment timestamps
        """
        raise NotImplementedError

    @abstractmethod
    def stream(self, samples_iter: Iterable[bytes], language: Optional[str] = None, timestamps: bool = True, sample_rate: int = 16000) -> Iterator[TranscriptionResult]:
        """Stream transcription from an iterator of raw PCM16 bytes.
        For this deterministic offline stub, we yield a single final result at the end.
        """
        raise NotImplementedError


class LocalASR(SpeechRecognizer):
    """Deterministic offline ASR stub.

    Behavior:
    - Detects presence of non-silent audio using a simple amplitude threshold (VAD-like).
    - If non-silent content exists, returns the fixed transcript "hello" with one segment covering the speech span.
    - If only silence, returns empty transcript with no segments.
    - Supports WAV file path inputs and raw PCM16 (mono) bytes.
    - Stream method accepts chunks of raw PCM16 bytes and yields final result at iterator end.
    """

    def __init__(self, vad_frame_ms: int = 30, vad_threshold: int = 200):
        self.vad_frame_ms = vad_frame_ms
        self.vad_threshold = vad_threshold  # amplitude threshold (0-32767)

    # --- Public API ---
    def transcribe(self, source: Union[str, bytes], language: Optional[str] = None, timestamps: bool = True) -> TranscriptionResult:
        if isinstance(source, (bytes, bytearray, memoryview)):
            sample_rate = 16000
            samples = _pcm16_mono_to_list(bytes(source))
            duration = len(samples) / float(sample_rate)
        elif isinstance(source, str):
            if not os.path.exists(source):
                raise FileNotFoundError(source)
            sample_rate, samples = _read_wav_mono_pcm16(source)
            duration = len(samples) / float(sample_rate)
        else:
            raise TypeError("source must be file path (str) or raw PCM16 bytes")

        lang = language or "en"
        has_speech, span = self._detect_speech_span(samples, sample_rate)

        if not has_speech:
            return TranscriptionResult(text="", segments=[], language=lang, sample_rate=sample_rate)

        seg_start_s, seg_end_s = span if timestamps else (0.0, duration)
        seg = Segment(text="hello", start=seg_start_s, end=seg_end_s)
        return TranscriptionResult(text="hello", segments=[seg], language=lang, sample_rate=sample_rate)

    def stream(self, samples_iter: Iterable[bytes], language: Optional[str] = None, timestamps: bool = True, sample_rate: int = 16000) -> Iterator[TranscriptionResult]:
        buf = io.BytesIO()
        for chunk in samples_iter:
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("stream expects an iterable of bytes-like chunks")
            buf.write(chunk)
        # End of stream -> transcribe accumulated raw PCM16
        result = self.transcribe(buf.getvalue(), language=language, timestamps=timestamps)
        # Ensure sample_rate is recorded even for bytes path
        result.sample_rate = sample_rate
        yield result

    # --- Internals ---
    def _detect_speech_span(self, samples: List[int], sample_rate: int) -> Tuple[bool, Tuple[float, float]]:
        """Return (has_speech, (start_s, end_s)).
        Simple VAD: energy per frame (mean absolute amplitude) vs threshold.
        """
        total = len(samples)
        if total == 0:
            return False, (0.0, 0.0)
        frame_len = max(1, int(sample_rate * self.vad_frame_ms / 1000))
        non_silent_frames = []
        for i in range(0, total, frame_len):
            frame = samples[i : min(i + frame_len, total)]
            mean_abs = sum(abs(x) for x in frame) / float(len(frame))
            non_silent_frames.append(mean_abs > self.vad_threshold)
        # Find first and last True
        try:
            first_idx = non_silent_frames.index(True)
        except ValueError:
            return False, (0.0, 0.0)
        last_idx = len(non_silent_frames) - 1 - non_silent_frames[::-1].index(True)
        start_sample = first_idx * frame_len
        end_sample = min(total, (last_idx + 1) * frame_len)
        start_s = start_sample / float(sample_rate)
        end_s = end_sample / float(sample_rate)
        # Clamp
        if end_s <= start_s:
            end_s = min(start_s + (frame_len / float(sample_rate)), total / float(sample_rate))
        return True, (round(start_s, 3), round(end_s, 3))


def _read_wav_mono_pcm16(path: str) -> Tuple[int, List[int]]:
    with wave.open(path, "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        if sw != 2:
            raise ValueError("Only PCM16 WAV supported")
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
        if nch == 1:
            fmt = f"<{nframes}h"
            samples = list(struct.unpack(fmt, raw))
        else:
            # Downmix to mono by averaging channels
            total_samples = nframes * nch
            fmt = f"<{total_samples}h"
            all_samples = struct.unpack(fmt, raw)
            samples = []
            for i in range(0, len(all_samples), nch):
                s = sum(all_samples[i : i + nch]) // nch
                samples.append(int(s))
        return sr, samples


def _pcm16_mono_to_list(raw: bytes) -> List[int]:
    if len(raw) % 2 != 0:
        raise ValueError("PCM16 byte length must be even")
    count = len(raw) // 2
    fmt = f"<{count}h"
    return list(struct.unpack(fmt, raw))
