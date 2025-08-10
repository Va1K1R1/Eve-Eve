import argparse
import json
import os
import sys

# Allow running as module: python -m vision.cli_ocr
try:
    from .ocr import LocalOCR
except Exception:  # pragma: no cover
    # Fallback when executed as a script directly (not via -m)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from vision.ocr import LocalOCR  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local deterministic OCR (offline stub)")
    p.add_argument("--input", required=True, help="Path to PGM/PPM/BMP image")
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument("--gpu", action="store_true", help="Use GPU (stub; computation remains local)")
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Read file bytes
    with open(args.__dict__["input"], "rb") as f:
        data = f.read()

    ocr = LocalOCR(use_gpu=args.gpu)
    result = ocr.detect_and_read(data)

    if args.json:
        sys.stdout.write(json.dumps(result))
    else:
        # Print regions line by line for human readability
        for r in result["regions"]:
            sys.stdout.write(f"bbox={r['bbox']} text={r['text']}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
