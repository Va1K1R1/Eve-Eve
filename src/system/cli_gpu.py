import argparse
import json
import os
import sys
from typing import List, Optional

# Allow running as module: python -m system.cli_gpu
try:
    from .gpu_monitor import GPUMonitor, ImageRenderer
except Exception:  # pragma: no cover
    # Fallback when executed as a script directly (not via -m)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from system.gpu_monitor import GPUMonitor, ImageRenderer  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local GPU monitor (offline; privacy-first)")
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--once", action="store_true", help="Take a single sample and exit")
    g.add_argument("--watch", type=float, help="Watch mode: interval seconds", default=None)
    p.add_argument("--duration", type=float, help="Duration in seconds (watch mode)")
    p.add_argument("--json", action="store_true", help="Output JSON (lines in watch mode)")
    p.add_argument("--out", help="Output image path (.bmp or .ppm)")
    p.add_argument("--size", default="800x200", help="Image size WxH (default 800x200)")
    p.add_argument("--title", default="GPU Monitor", help="Optional title (unused in stub renderer)")
    # Hidden/testing backend selector
    p.add_argument("--backend", choices=["auto", "stub", "nvidia"], default="auto", help=argparse.SUPPRESS)
    return p


def _parse_size(s: str) -> Optional[tuple[int, int]]:
    try:
        if "x" in s:
            w, h = s.lower().split("x", 1)
        elif "X" in s:
            w, h = s.split("X", 1)
        else:
            return None
        return int(w), int(h)
    except Exception:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.backend and args.backend != "auto":
        os.environ["GPU_MONITOR_BACKEND"] = "stub" if args.backend == "stub" else "nvidia"

    mon = GPUMonitor()

    if args.once or args.watch is None:
        sample = mon.sample_once()
        if args.json:
            sys.stdout.write(json.dumps(sample))
        else:
            # Human-friendly single line
            util = sample.get("utilization")
            vram = sample.get("vram_gb")
            name = sample.get("gpu") or "GPU"
            sys.stdout.write(f"{name}: util={util}% vram={vram} GB\n")
        # Optional image output
        if args.out:
            size = _parse_size(args.size)
            if not size:
                raise SystemExit(2)
            w, h = size
            renderer = ImageRenderer(w, h, title=args.title)
            renderer.plot([sample])
            out_lower = args.out.lower()
            if out_lower.endswith(".bmp"):
                renderer.save_bmp(args.out)
            else:
                renderer.save_ppm(args.out)
        return 0

    # Watch mode
    interval = float(args.watch)
    duration = float(args.duration) if args.duration is not None else 10.0
    samples = []

    def on_sample(s):
        samples.append(s)
        if args.json:
            sys.stdout.write(json.dumps(s) + "\n")
        else:
            util = s.get("utilization")
            vram = s.get("vram_gb")
            name = s.get("gpu") or "GPU"
            sys.stdout.write(f"{name}: util={util}% vram={vram} GB\n")
        sys.stdout.flush()

    mon.watch(interval, duration, callback=on_sample)

    if args.out and samples:
        size = _parse_size(args.size)
        if not size:
            raise SystemExit(2)
        w, h = size
        renderer = ImageRenderer(w, h, title=args.title)
        # Prefer total vram from backend if exposed
        total_vram = getattr(mon.backend, "total_vram_gb", None)
        renderer.plot(samples, total_vram_gb=total_vram)
        out_lower = args.out.lower()
        if out_lower.endswith(".bmp"):
            renderer.save_bmp(args.out)
        else:
            renderer.save_ppm(args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
