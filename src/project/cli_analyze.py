import argparse
import json
import os
import sys
from typing import Any, Dict

# Allow running as module: python -m project.cli_analyze
try:
    from .analyzer import analyze_project, write_markdown
except Exception:  # pragma: no cover
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from project.analyzer import analyze_project, write_markdown  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Project analyzer (offline, stdlib-only)")
    p.add_argument("--out", help="Path to write Markdown report (default: .\\docs\\analysis.md)")
    p.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    report: Dict[str, Any] = analyze_project()
    out_path = args.out or os.path.join(os.getcwd(), "docs", "analysis.md")

    try:
        write_markdown(report, out_path)
    except Exception:
        # Keep CLI robust: ignore write errors
        pass

    if args.json:
        sys.stdout.write(json.dumps(report))
    else:
        pkgs = len(report.get("packages", {}))
        tests = report.get("tests", {}).get("count", 0)
        clis = len(report.get("metadata", {}).get("cli_modules", []))
        sys.stdout.write(f"packages={pkgs}; tests={tests}; cli={clis}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
