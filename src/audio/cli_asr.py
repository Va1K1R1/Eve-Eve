import argparse
import json
import os
import sys

# Allow running as module: python -m audio.cli_asr
try:
    from .asr import LocalASR
except Exception:  # pragma: no cover
    # Fallback when executed as a script directly (not via -m)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from audio.asr import LocalASR  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local deterministic ASR (offline stub)")
    p.add_argument("--input", required=True, help="Path to WAV file (PCM16 mono)")
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument("--language", default=None, help="Optional language hint (e.g., en)")
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    asr = LocalASR()
    result = asr.transcribe(args.__dict__["input"], language=args.language, timestamps=True)

    if args.json:
        out = {
            "text": result.text,
            "language": result.language,
            "sample_rate": result.sample_rate,
            "segments": [
                {"text": s.text, "start": s.start, "end": s.end} for s in result.segments
            ],
        }
        sys.stdout.write(json.dumps(out))
    else:
        sys.stdout.write(result.text + ("\n" if result.text and not result.text.endswith("\n") else ""))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
