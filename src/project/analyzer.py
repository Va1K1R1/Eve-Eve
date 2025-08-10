import os
import sys
import ast
import json
import platform
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple


def _is_python_file(path: str) -> bool:
    return path.endswith(".py") and not os.path.basename(path).startswith("_")


def _iter_python_files(base_dir: str) -> List[str]:
    files: List[str] = []
    for root, dirs, filenames in os.walk(base_dir):
        # Skip __pycache__
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in filenames:
            if _is_python_file(fn):
                files.append(os.path.join(root, fn))
    return files


essential_keys = [
    "packages",
    "tests",
    "cover_files",
    "metadata",
]


def _count_toplevel_defs(py_path: str) -> Tuple[int, int]:
    """Return (classes, functions) counting only top-level defs for determinism."""
    try:
        with open(py_path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        classes = 0
        functions = 0
        for node in getattr(tree, "body", []):
            if isinstance(node, ast.ClassDef):
                classes += 1
            elif isinstance(node, ast.FunctionDef):
                functions += 1
        return classes, functions
    except Exception:
        # Be robust: on any parsing error, return zeros
        return 0, 0


def _dotted_from_file(src_dir: str, file_path: str) -> str:
    rel = os.path.relpath(file_path, src_dir)
    no_ext = os.path.splitext(rel)[0]
    # Normalize to dotted path with backslashes accounted for
    return no_ext.replace("/", ".").replace("\\", ".")


def analyze_project(root_dir: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Analyze current project implementation under src\ and tests\, and summarize.
    Returns a deterministic JSON-serializable dict.
    """
    root = os.path.abspath(root_dir or os.getcwd())
    src_dir = os.path.join(root, "src")
    tests_dir = os.path.join(root, "tests")

    packages: Dict[str, Dict[str, Any]] = {}
    cli_entries: List[str] = []

    if os.path.isdir(src_dir):
        # Top-level packages are immediate subdirectories of src, and also include top-level .py modules
        for entry in sorted(os.listdir(src_dir)):
            full = os.path.join(src_dir, entry)
            if os.path.isdir(full):
                pkg_name = entry
                pkg_info = {"modules": [], "summary": {"files": 0, "classes": 0, "functions": 0}, "cli_modules": []}
                # Walk this package
                for root2, dirs2, files2 in os.walk(full):
                    dirs2[:] = [d for d in dirs2 if d != "__pycache__"]
                    for fn in files2:
                        if not _is_python_file(fn):
                            continue
                        fpath = os.path.join(root2, fn)
                        dotted = _dotted_from_file(src_dir, fpath)
                        classes, functions = _count_toplevel_defs(fpath)
                        pkg_info["modules"].append({
                            "name": dotted,
                            "path": os.path.relpath(fpath, root),
                            "classes": classes,
                            "functions": functions,
                        })
                        pkg_info["summary"]["files"] += 1
                        pkg_info["summary"]["classes"] += classes
                        pkg_info["summary"]["functions"] += functions
                        base = os.path.basename(fn)
                        if base.startswith("cli_") and base.endswith(".py"):
                            pkg_info["cli_modules"].append(dotted)
                # Sort for determinism
                pkg_info["modules"].sort(key=lambda m: m["name"]) 
                pkg_info["cli_modules"].sort()
                packages[pkg_name] = pkg_info
            elif _is_python_file(entry):
                # Top-level module in src (no package dir)
                fpath = full
                dotted = _dotted_from_file(src_dir, fpath)
                classes, functions = _count_toplevel_defs(fpath)
                top_pkg = "__root__"
                if top_pkg not in packages:
                    packages[top_pkg] = {"modules": [], "summary": {"files": 0, "classes": 0, "functions": 0}, "cli_modules": []}
                packages[top_pkg]["modules"].append({
                    "name": dotted,
                    "path": os.path.relpath(fpath, root),
                    "classes": classes,
                    "functions": functions,
                })
                packages[top_pkg]["summary"]["files"] += 1
                packages[top_pkg]["summary"]["classes"] += classes
                packages[top_pkg]["summary"]["functions"] += functions
                base = os.path.basename(entry)
                if base.startswith("cli_") and base.endswith(".py"):
                    packages[top_pkg]["cli_modules"].append(dotted)

    # Aggregate CLI entries from packages
    for pkg in sorted(packages.keys()):
        for m in packages[pkg].get("cli_modules", []):
            cli_entries.append(m)
    cli_entries = sorted(set(cli_entries))

    # Tests
    tests_info: Dict[str, Any] = {"count": 0, "modules": []}
    if os.path.isdir(tests_dir):
        for root3, dirs3, files3 in os.walk(tests_dir):
            dirs3[:] = [d for d in dirs3 if d != "__pycache__"]
            for fn in files3:
                if fn.startswith("test_") and fn.endswith(".py"):
                    fpath = os.path.join(root3, fn)
                    rel = os.path.relpath(fpath, root)
                    mod = os.path.splitext(rel)[0].replace("/", ".").replace("\\", ".")
                    tests_info["modules"].append(mod)
        tests_info["modules"].sort()
        tests_info["count"] = len(tests_info["modules"])

    # Coverage artifacts (.cover files) in root
    cover_files: List[str] = []
    try:
        for entry in os.listdir(root):
            if entry.endswith(".cover"):
                name = entry[:-6]  # strip .cover
                # present as dotted module name if possible
                cover_files.append(name)
    except Exception:
        pass
    cover_files.sort()

    # Metadata
    when = now or datetime.utcnow()
    meta = {
        "generated_at": when.replace(microsecond=0).isoformat() + "Z",
        "root": root,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cli_modules": cli_entries,
    }

    report: Dict[str, Any] = {
        "packages": packages,
        "tests": tests_info,
        "cover_files": {"count": len(cover_files), "items": cover_files},
        "metadata": meta,
    }
    return report


def write_markdown(report: Dict[str, Any], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    lines: List[str] = []
    meta = report.get("metadata", {})
    lines.append("# Project Analysis")
    lines.append("")
    lines.append(f"Generated: {meta.get('generated_at', '')}")
    lines.append(f"Python: {meta.get('python', '')}")
    lines.append(f"Platform: {meta.get('platform', '')}")
    lines.append("")

    packages: Dict[str, Any] = report.get("packages", {})
    total_pkgs = len(packages)
    lines.append(f"## Source Packages ({total_pkgs})")
    for pkg in sorted(packages.keys()):
        info = packages[pkg]
        summ = info.get("summary", {})
        lines.append(f"- {pkg}: files={summ.get('files', 0)}, classes={summ.get('classes', 0)}, functions={summ.get('functions', 0)}")
        # List CLI modules if any
        cli_mods = info.get("cli_modules", [])
        if cli_mods:
            for m in cli_mods:
                lines.append(f"  - CLI: python -m {m}")

    # Global CLI index
    cli_mods_all = meta.get("cli_modules", [])
    lines.append("")
    lines.append(f"## CLI Modules ({len(cli_mods_all)})")
    for m in cli_mods_all:
        lines.append(f"- python -m {m}")

    # Tests
    tests = report.get("tests", {})
    lines.append("")
    lines.append(f"## Tests ({tests.get('count', 0)})")
    for m in tests.get("modules", []):
        lines.append(f"- {m}")

    # Coverage files
    cov = report.get("cover_files", {})
    lines.append("")
    lines.append(f"## Coverage Artifacts (.cover) ({cov.get('count', 0)})")
    for item in cov.get("items", []):
        lines.append(f"- {item}")

    content = "\n".join(lines) + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Minimal, dependency-free argument parsing
    out_path = None
    json_out = False
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--out" and i + 1 < len(argv):
            out_path = argv[i + 1]
            i += 2
            continue
        if tok == "--json":
            json_out = True
            i += 1
            continue
        i += 1

    report = analyze_project()
    # Default output is docs\analysis.md relative to CWD
    out_path = out_path or os.path.join(os.getcwd(), "docs", "analysis.md")
    try:
        write_markdown(report, out_path)
    except Exception:
        # Do not fail the run if docs can't be written
        pass

    if json_out:
        sys.stdout.write(json.dumps(report))
    else:
        # Brief text summary
        pkgs = len(report.get("packages", {}))
        tests = report.get("tests", {}).get("count", 0)
        sys.stdout.write(f"packages={pkgs}; tests={tests}; cli={len(report.get('metadata', {}).get('cli_modules', []))}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
