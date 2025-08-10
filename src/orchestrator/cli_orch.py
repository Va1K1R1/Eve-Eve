import argparse
import json
import os
import sys
from typing import Any, Dict, List

# Allow running as module: python -m orchestrator.cli_orch
try:
    from .scheduler import Scheduler, Job, TaskSpec, parse_actions
except Exception:  # pragma: no cover
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from orchestrator.scheduler import Scheduler, Job, TaskSpec, parse_actions  # type: ignore


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local async orchestrator (offline, deterministic)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", help="Path to JSON plan file")
    g.add_argument("--actions", nargs=argparse.REMAINDER, help="Inline action strings (e.g., 'sleep:0.1' 'noop:hello')")
    p.add_argument("--concurrency", type=int, default=4, help="Max concurrent jobs")
    p.add_argument("--rate", type=float, default=None, help="Rate limit (jobs per second)")
    p.add_argument("--stop-on-error", action="store_true", help="Cancel remaining jobs on first error/timeout")
    p.add_argument("--json", action="store_true", help="Output JSON summary to stdout")
    return p


def _load_plan(path: str) -> List[Job]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    jobs: List[Job] = []
    for item in data.get("jobs", []):
        jid = str(item["id"]) if "id" in item else f"job_{len(jobs)+1}"
        t = item.get("task", {})
        task = TaskSpec(
            type=t.get("type", "noop"),
            name=t.get("name", jid),
            args=t.get("args", {}),
            timeout=t.get("timeout"),
            max_retries=t.get("max_retries", 0),
            backoff_base=t.get("backoff_base", 0.01),
        )
        deps = list(item.get("deps", []))
        jobs.append(Job(id=jid, task=task, deps=deps))
    return jobs


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    json_out = bool(args.json)
    concurrency = max(1, int(args.concurrency))
    rate = args.rate
    stop_on_error = bool(args.stop_on_error)

    if args.plan:
        jobs = _load_plan(args.plan)
    else:
        remainder = args.actions or []
        # Parse flags that may appear in the remainder, updating our local settings
        actions: List[str] = []
        i = 0
        while i < len(remainder):
            tok = remainder[i]
            if tok == "--json":
                json_out = True
                i += 1
                continue
            if tok == "--concurrency" and i + 1 < len(remainder):
                try:
                    concurrency = max(1, int(remainder[i + 1]))
                except Exception:
                    pass
                i += 2
                continue
            if tok == "--rate" and i + 1 < len(remainder):
                try:
                    rate = float(remainder[i + 1])
                except Exception:
                    pass
                i += 2
                continue
            if tok == "--stop-on-error":
                stop_on_error = True
                i += 1
                continue
            if tok.startswith("--"):
                # Unknown flag in remainder; skip it
                i += 1
                continue
            actions.append(tok)
            i += 1

        if not actions:
            parser.error("No actions provided after --actions")
            return 2
        jobs = parse_actions(actions, concurrency=concurrency)

    sched = Scheduler(
        jobs,
        concurrency=concurrency,
        rate_limit_per_sec=rate,
        stop_on_error=stop_on_error,
    )
    summary: Dict[str, Any] = sched.run()

    if json_out:
        sys.stdout.write(json.dumps(summary))
    else:
        # Brief text summary
        ok = all(j.get("status") == "succeeded" for j in summary["jobs"].values())
        sys.stdout.write(f"OK={ok}; peak_concurrency={summary['peak_concurrency']}; jobs={len(summary['jobs'])}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
