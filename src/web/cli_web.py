import argparse
import json
import os
import sys

# Allow running as module: python -m web.cli_web
try:
    from .automation import Browser
except Exception:  # pragma: no cover
    # Fallback when executed as a script directly (not via -m)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from web.automation import Browser  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local web automation (Playwright-like stub)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", help="Path to JSON plan file")
    g.add_argument("--html", help="Path to local HTML file")
    p.add_argument("--actions", nargs="*", help='Actions like click=#id fill=#sel:text get_text=#sel screenshot=out.bmp')
    p.add_argument("--json", action="store_true", help="Output JSON")
    return p


def _run_actions(page, actions):
    results = []
    for a in actions:
        if "=" in a:
            key, val = a.split("=", 1)
        else:
            key, val = a, ""
        key = key.strip().lower()
        if key == "click":
            sel = val
            page.locator(sel).click()
            results.append({"action": "click", "selector": sel, "ok": True})
        elif key == "fill":
            # format: selector:text
            if ":" not in val:
                raise ValueError("fill action requires selector:text")
            sel, text = val.split(":", 1)
            page.locator(sel).fill(text)
            results.append({"action": "fill", "selector": sel, "ok": True})
        elif key == "get_text":
            sel = val
            txt = page.locator(sel).get_text()
            results.append({"action": "get_text", "selector": sel, "text": txt})
        elif key == "screenshot":
            out_path = val
            page.screenshot(out_path)
            results.append({"action": "screenshot", "path": out_path, "ok": True})
        elif key == "wait_for_selector":
            # optional timeout suffix like selector,500
            sel = val
            timeout_ms = 1000
            if "," in val:
                sel, t = val.split(",", 1)
                try:
                    timeout_ms = int(t)
                except Exception:
                    timeout_ms = 1000
            page.wait_for_selector(sel, timeout_ms=timeout_ms)
            results.append({"action": "wait_for_selector", "selector": sel, "ok": True})
        else:
            raise ValueError(f"Unknown action: {key}")
    return results


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.plan:
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
        html_path = plan.get("html")
        actions = plan.get("actions", [])
        # normalize actions: dicts -> strings
        action_strs = []
        for a in actions:
            if isinstance(a, str):
                action_strs.append(a)
            elif isinstance(a, dict):
                t = a.get("type")
                if t == "click":
                    action_strs.append(f"click={a.get('selector','')}")
                elif t == "fill":
                    action_strs.append(f"fill={a.get('selector','')}:{a.get('text','')}")
                elif t == "get_text":
                    action_strs.append(f"get_text={a.get('selector','')}")
                elif t == "screenshot":
                    action_strs.append(f"screenshot={a.get('path','screenshot.bmp')}")
                elif t == "wait_for_selector":
                    tm = a.get("timeout_ms")
                    if tm is None:
                        action_strs.append(f"wait_for_selector={a.get('selector','')}")
                    else:
                        action_strs.append(f"wait_for_selector={a.get('selector','')},{tm}")
                else:
                    raise ValueError(f"Unknown plan action type: {t}")
            else:
                raise ValueError("Unsupported action format")
    else:
        html_path = args.html
        action_strs = args.actions or []

    # Run
    br = Browser()
    try:
        page = br.new_page()
        # Support both plain path and file://
        if html_path.startswith("file://"):
            url = html_path
        else:
            url = html_path
        page.goto(url)
        results = _run_actions(page, action_strs)
    finally:
        br.close()

    if args.json or args.plan:
        sys.stdout.write(json.dumps({"results": results}))
    else:
        for r in results:
            sys.stdout.write(f"{r}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
