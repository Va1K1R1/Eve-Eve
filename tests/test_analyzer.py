import io
import os
import sys
import json
import unittest
from contextlib import redirect_stdout

# Ensure src is on sys.path for imports
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from project.analyzer import analyze_project, write_markdown  # type: ignore
import project.cli_analyze as cli_analyze  # type: ignore


class AnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.out_dir = os.path.join(self.root, "tests", "_out")
        os.makedirs(self.out_dir, exist_ok=True)
        self.md_path = os.path.join(self.out_dir, "analysis.md")
        try:
            if os.path.exists(self.md_path):
                os.remove(self.md_path)
        except Exception:
            pass

    def test_analyze_project_schema_and_contents(self):
        report = analyze_project(root_dir=self.root)
        # Essential keys
        for key in ("packages", "tests", "cover_files", "metadata"):
            self.assertIn(key, report)
        # At least one known package exists (system is a core package present in this repo)
        self.assertIn("system", report["packages"])  # package names at top-level keys
        # CLI module orchestrator.cli_orch should be detected
        cli_modules = report["metadata"].get("cli_modules", [])
        self.assertIn("orchestrator.cli_orch", cli_modules)
        # Tests count should be >= 1
        self.assertGreaterEqual(report["tests"].get("count", 0), 1)

    def test_write_markdown_creates_file(self):
        report = analyze_project(root_dir=self.root)
        write_markdown(report, self.md_path)
        self.assertTrue(os.path.exists(self.md_path))
        with open(self.md_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Project Analysis", content)
        self.assertIn("## Tests (", content)

    def test_cli_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_analyze.main(["--json"])  # prints JSON
        self.assertEqual(rc, 0)
        s = buf.getvalue()
        data = json.loads(s)
        self.assertIn("packages", data)
        self.assertIn("metadata", data)
        self.assertIn("tests", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
