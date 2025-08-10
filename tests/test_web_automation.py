import io
import json
import os
import sys
import tempfile
import unittest

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from web.automation import Browser  # noqa: E402
from web.cli_web import main as cli_main  # noqa: E402


_HTML = """
<html>
  <body>
    <div id="container" class="wrap">
      <p class="text">Hello <span>World</span></p>
      <button id="login" class="btn primary">Login</button>
      <input id="user" class="field" value="" />
    </div>
    <div class="footer"><span id="copy">C</span></div>
  </body>
</html>
""".strip()


class WebAutomationTests(unittest.TestCase):
    def _write_html(self, dirpath: str, name: str = "page.html") -> str:
        path = os.path.join(dirpath, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_HTML)
        return path

    def test_dom_and_selectors(self):
        with tempfile.TemporaryDirectory() as td:
            html_path = self._write_html(td)
            br = Browser()
            try:
                page = br.new_page()
                page.goto(html_path)
                self.assertEqual(page.locator("#login").count(), 1)
                self.assertEqual(page.locator(".btn").count(), 1)
                self.assertEqual(page.locator("button").count(), 1)
                self.assertEqual(page.locator("div .text span").count(), 1)
                self.assertEqual(page.locator(".text").first().get_text(), "Hello World")
            finally:
                br.close()

    def test_click_and_fill_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            html_path = self._write_html(td)
            br = Browser()
            try:
                page = br.new_page()
                page.goto(html_path)
                page.locator("#login").click()
                self.assertEqual(page.locator("#login").first().get_attribute("data-clicked"), "true")
                page.locator("#user").fill("alice")
                self.assertEqual(page.locator("#user").first().get_attribute("value"), "alice")
                page.locator(".text").fill("Replaced")
                self.assertEqual(page.locator(".text").get_text(), "Replaced")
            finally:
                br.close()

    def test_wait_for_selector_and_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            html_path = self._write_html(td)
            br = Browser()
            try:
                page = br.new_page()
                page.goto(html_path)
                loc = page.wait_for_selector("#login", timeout_ms=10)
                self.assertIsNotNone(loc)
                with self.assertRaises(TimeoutError):
                    page.wait_for_selector("#missing", timeout_ms=10)
            finally:
                br.close()

    def test_screenshot_writes_bmp(self):
        with tempfile.TemporaryDirectory() as td:
            html_path = self._write_html(td)
            bmp_path = os.path.join(td, "shot.bmp")
            br = Browser()
            try:
                page = br.new_page()
                page.goto(html_path)
                page.screenshot(bmp_path)
            finally:
                br.close()
            with open(bmp_path, "rb") as f:
                data = f.read()
            self.assertGreater(len(data), 54)
            self.assertEqual(data[:2], b"BM")

    def test_concurrency_limit(self):
        b1 = Browser()
        b2 = Browser()
        b3 = Browser()
        with self.assertRaises(RuntimeError):
            Browser()
        # Free a slot
        b2.close()
        b4 = Browser()
        # Clean up
        b1.close(); b3.close(); b4.close()

    def test_cli_json_and_image(self):
        with tempfile.TemporaryDirectory() as td:
            html_path = self._write_html(td)
            bmp_path = os.path.join(td, "out.bmp")
            buf = io.StringIO()
            argv = [
                "--html", html_path,
                "--actions",
                "click=#login",
                "fill=#user:alice",
                "get_text=.text",
                f"screenshot={bmp_path}",
                "--json",
            ]
            with unittest.mock.patch("sys.stdout", new=buf):
                rc = cli_main(argv)
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertIn("results", data)
            self.assertTrue(any(r.get("action") == "get_text" for r in data["results"]))
            self.assertTrue(os.path.exists(bmp_path))
            with open(bmp_path, "rb") as f:
                self.assertEqual(f.read(2), b"BM")


if __name__ == "__main__":
    unittest.main(verbosity=2)
