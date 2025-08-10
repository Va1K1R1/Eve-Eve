from __future__ import annotations

import argparse
import json
import os
from typing import List, Optional

from .tts import LocalTTS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local deterministic TTS (stub)")
    p.add_argument("--text", type=str, required=True, help="Input text to synthesize")
    p.add_argument("--output", type=str, required=False, default=None, help="Output WAV file path (mono PCM16)")
    p.add_argument("--sample-rate", type=int, default=16000, help="Sample rate in Hz (default: 16000)")
    p.add_argument("--amplitude", type=float, default=0.2, help="Relative amplitude 0..1 (default: 0.2)")
    p.add_argument("--json", action="store_true", help="Print JSON metadata to stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    text = args.text or ""
    if len(text.strip()) == 0:
        print("Error: --text must be non-empty.")
        return 2

    tts = LocalTTS()

    if args.output:
        # Ensure parent dir exists
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        res = tts.save_wav(args.output, text, sample_rate=args.sample_rate, amplitude=args.amplitude)
        output_path = os.path.abspath(args.output)
    else:
        res = tts.synthesize(text, sample_rate=args.sample_rate, amplitude=args.amplitude)
        output_path = None

    if args.json:
        meta = {
            "text": text,
            "sample_rate": res.sample_rate,
            "duration_s": res.duration_s,
            "bytes": len(res.pcm16),
        }
        if output_path:
            meta["output"] = output_path
        print(json.dumps(meta))
    else:
        if output_path:
            print(f"WAV written: {output_path}")
        else:
            print(f"Synthesized {len(res.pcm16)} bytes @ {res.sample_rate} Hz, {res.duration_s}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
