import os
import sys
import time
import json
import unittest

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from orchestrator.scheduler import Scheduler, Job, TaskSpec  # noqa: E402
from orchestrator.cli_orch import main as cli_main  # noqa: E402


class OrchestratorTests(unittest.TestCase):
    def test_sequential_and_dag_order(self):
        # A -> B -> C chain; ensure ordering via started_at timestamps
        A = Job(id="A", task=TaskSpec(type="noop", name="A", args={"value": "A"}))
        B = Job(id="B", task=TaskSpec(type="noop", name="B", args={"value": "B"}), deps=["A"])
        C = Job(id="C", task=TaskSpec(type="noop", name="C", args={"value": "C"}), deps=["B"])
        sched = Scheduler([A, B, C], concurrency=2)
        summary = sched.run()
        jobs = summary["jobs"]
        self.assertEqual(jobs["A"]["status"], "succeeded")
        self.assertEqual(jobs["B"]["status"], "succeeded")
        self.assertEqual(jobs["C"]["status"], "succeeded")
        self.assertLess(jobs["A"]["started_at"], jobs["B"]["started_at"])  # DAG order
        self.assertLess(jobs["B"]["started_at"], jobs["C"]["started_at"])  # DAG order
        # Logs contain expected events
        events = [e["event"] for e in summary["logs"]]
        self.assertIn("scheduler_started", events)
        self.assertIn("scheduler_finished", events)
        self.assertTrue(any(e == "job_started" for e in events))
        self.assertTrue(any(e == "job_finished" for e in events))

    def test_retry_flaky_and_backoff(self):
        # flaky fails first 2 attempts, then succeeds; ensure attempts==3
        flaky = Job(
            id="F",
            task=TaskSpec(type="flaky", name="flaky", args={"fail_until": 2}, max_retries=2, backoff_base=0.0),
        )
        sched = Scheduler([flaky], concurrency=1)
        summary = sched.run()
        j = summary["jobs"]["F"]
        self.assertEqual(j["status"], "succeeded")
        self.assertEqual(j["attempts"], 3)

    def test_timeout(self):
        sleeper = Job(id="S", task=TaskSpec(type="sleep", args={"seconds": 0.05}, timeout=0.01))
        sched = Scheduler([sleeper], concurrency=1)
        summary = sched.run()
        j = summary["jobs"]["S"]
        self.assertEqual(j["status"], "timeout")
        self.assertEqual(j["error"], "timeout")

    def test_stop_on_error_cancels_others(self):
        failing = Job(id="X", task=TaskSpec(type="fail"))
        long = Job(id="Y", task=TaskSpec(type="sleep", args={"seconds": 1.0}))
        sched = Scheduler([failing, long], concurrency=2, stop_on_error=True)
        summary = sched.run()
        self.assertIn(summary["jobs"]["X"]["status"], ("failed",))
        # Long either never started and got cancelled, or started and was cancelled
        self.assertEqual(summary["jobs"]["Y"]["status"], "cancelled")

    def test_cli_json_output(self):
        import io
        buf = io.StringIO()
        argv = [
            "--actions",
            "noop:hello",
            "sleep:0",
            "flaky:fail_until=1",
            "--concurrency", "3",
            "--json",
        ]
        with unittest.mock.patch("sys.stdout", new=buf):
            rc = cli_main(argv)
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIn("jobs", data)
        self.assertIn("logs", data)
        self.assertGreaterEqual(data.get("peak_concurrency", 0), 1)

    def test_throughput_100_noops(self):
        # Ensure we can schedule 100 noops quickly with concurrency=16
        jobs = [Job(id=f"N{i}", task=TaskSpec(type="noop", args={"value": i})) for i in range(100)]
        sched = Scheduler(jobs, concurrency=16)
        t0 = time.perf_counter()
        summary = sched.run()
        dt = time.perf_counter() - t0
        self.assertTrue(all(j["status"] == "succeeded" for j in summary["jobs"].values()))
        # Be generous for CI but keep deterministic expectation (<2s on target machine)
        self.assertLess(dt, 2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
