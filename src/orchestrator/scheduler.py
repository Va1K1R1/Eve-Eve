from __future__ import annotations

import asyncio
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


def _cpu_work(n: int) -> int:
    s = 0
    for i in range(n):
        s = (s + i) % 1_000_000_007
    return s


@dataclass
class TaskSpec:
    type: str  # "noop" | "sleep" | "cpu" | "fail" | "flaky"
    name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None  # seconds
    max_retries: int = 0
    backoff_base: float = 0.01  # seconds; deterministic, no jitter


@dataclass
class Job:
    id: str
    task: TaskSpec
    deps: List[str] = field(default_factory=list)
    status: str = "pending"  # pending|running|succeeded|failed|timeout|skipped|cancelled
    attempts: int = 0
    error: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    result: Any = None


class Scheduler:
    def __init__(
        self,
        jobs: List[Job],
        *,
        concurrency: int = 4,
        max_workers: Optional[int] = None,
        rate_limit_per_sec: Optional[float] = None,
        stop_on_error: bool = False,
    ) -> None:
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        self.jobs_by_id: Dict[str, Job] = {j.id: j for j in jobs}
        if len(self.jobs_by_id) != len(jobs):
            raise ValueError("duplicate job ids")
        self.concurrency = concurrency
        self.max_workers = min(16, max_workers if isinstance(max_workers, int) and max_workers > 0 else os.cpu_count() or 2)
        self.rate_limit_per_sec = rate_limit_per_sec
        self.stop_on_error = stop_on_error
        self._current_concurrency = 0
        self._peak_concurrency = 0
        self._cc_lock = asyncio.Lock()
        self.logs: List[Dict[str, Any]] = []
        self._cancelled = False
        self._start_time = time.perf_counter()
        self._rate_bucket: List[float] = []  # timestamps of job starts (seconds)

        # Build DAG structures
        self._children: Dict[str, List[str]] = {j.id: [] for j in jobs}
        self._indegree: Dict[str, int] = {j.id: 0 for j in jobs}
        for j in jobs:
            for d in j.deps:
                if d not in self.jobs_by_id:
                    raise ValueError(f"unknown dependency '{d}' for job '{j.id}'")
                self._children[d].append(j.id)
                self._indegree[j.id] += 1
        self._validate_acyclic()

        self._process_pool: Optional[ProcessPoolExecutor] = None

    @property
    def peak_concurrency(self) -> int:
        return self._peak_concurrency

    @property
    def current_concurrency(self) -> int:
        return self._current_concurrency

    def _validate_acyclic(self) -> None:
        # Kahn's algorithm
        indeg = dict(self._indegree)
        q = [jid for jid, deg in indeg.items() if deg == 0]
        seen = 0
        while q:
            n = q.pop(0)
            seen += 1
            for c in self._children[n]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    q.append(c)
        if seen != len(self.jobs_by_id):
            raise ValueError("cycle detected in DAG")

    def _log(self, event: str, job: Optional[Job] = None, **extra: Any) -> None:
        ts = time.perf_counter() - self._start_time
        rec = {"ts": round(ts, 6), "event": event}
        if job is not None:
            rec["job"] = job.id
            rec["status"] = job.status
            rec["attempts"] = job.attempts
        if extra:
            rec.update(extra)
        self.logs.append(rec)

    async def _inc_concurrency(self) -> None:
        async with self._cc_lock:
            self._current_concurrency += 1
            if self._current_concurrency > self._peak_concurrency:
                self._peak_concurrency = self._current_concurrency

    async def _dec_concurrency(self) -> None:
        async with self._cc_lock:
            self._current_concurrency -= 1
            if self._current_concurrency < 0:
                self._current_concurrency = 0

    async def _respect_rate_limit(self) -> None:
        if not self.rate_limit_per_sec or self.rate_limit_per_sec <= 0:
            return
        now = time.perf_counter()
        window = 1.0
        # prune
        self._rate_bucket = [t for t in self._rate_bucket if now - t < window]
        if len(self._rate_bucket) >= math.floor(self.rate_limit_per_sec):
            # sleep until oldest exits window
            oldest = min(self._rate_bucket) if self._rate_bucket else now
            sleep_for = max(0.0, (oldest + window) - now)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
        # record
        self._rate_bucket.append(time.perf_counter())

    async def _run_task(self, job: Job) -> Any:
        t = job.task
        if t.type == "noop":
            return t.args.get("value", t.name or job.id)
        elif t.type == "sleep":
            seconds = float(t.args.get("seconds", t.args.get("s", 0)))
            await asyncio.sleep(seconds)
            return f"slept:{seconds}"
        elif t.type == "fail":
            raise RuntimeError(t.args.get("message", "intentional failure"))
        elif t.type == "flaky":
            fail_until = int(t.args.get("fail_until", 1))
            # attempts is incremented before each try; if attempts <= fail_until, fail
            if job.attempts <= fail_until:
                raise RuntimeError(f"flaky failing attempt {job.attempts} <= {fail_until}")
            return f"flaky_ok_after_{job.attempts}"
        elif t.type == "cpu":
            work = int(t.args.get("work", 100000))
            return await self._cpu_bound_sum(work)
        else:
            raise ValueError(f"unknown task type: {t.type}")

    async def _cpu_bound_sum(self, work: int) -> int:
        if self._process_pool is None:
            self._process_pool = ProcessPoolExecutor(max_workers=self.max_workers)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._process_pool, _cpu_work, work)

    async def _execute_job(self, jid: str, sem: asyncio.Semaphore, ready_queue: asyncio.Queue[str], completed: Set[str]) -> None:
        job = self.jobs_by_id[jid]
        # skip if already marked due to cancellation or dependency failure
        if job.status not in ("pending",):
            return

        await sem.acquire()
        await self._respect_rate_limit()
        await self._inc_concurrency()
        job.status = "running"
        job.started_at = time.perf_counter() - self._start_time
        self._log("job_started", job)
        try:
            attempt = 0
            while True:
                attempt += 1
                job.attempts = attempt
                try:
                    coro = self._run_task(job)
                    if job.task.timeout and job.task.timeout > 0:
                        result = await asyncio.wait_for(coro, timeout=job.task.timeout)
                    else:
                        result = await coro
                    job.result = result
                    job.status = "succeeded"
                    break
                except asyncio.TimeoutError:
                    job.error = "timeout"
                    job.status = "timeout"
                except asyncio.CancelledError:
                    job.error = "cancelled"
                    job.status = "cancelled"
                    break
                except Exception as e:
                    job.error = f"{type(e).__name__}: {e}"
                    job.status = "failed"
                # retry policy
                if job.status in ("failed", "timeout") and attempt <= job.task.max_retries:
                    backoff = job.task.backoff_base * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)
                    continue
                else:
                    break
        finally:
            job.ended_at = time.perf_counter() - self._start_time
            self._log("job_finished", job)
            await self._dec_concurrency()
            sem.release()

        completed.add(jid)
        # enqueue children whose all deps completed successfully
        for child in self._children[jid]:
            cjob = self.jobs_by_id[child]
            if cjob.status not in ("pending",):
                continue
            # If any dependency failed or timed out, mark skipped
            dep_statuses = [self.jobs_by_id[d].status for d in cjob.deps]
            if any(s in ("failed", "timeout", "cancelled", "skipped") for s in dep_statuses):
                cjob.status = "skipped"
                cjob.started_at = cjob.started_at or (time.perf_counter() - self._start_time)
                cjob.ended_at = cjob.ended_at or (time.perf_counter() - self._start_time)
                self._log("job_skipped", cjob, reason="dependency_failed")
                # Still mark as completed for DAG progression; children will inspect too
                completed.add(child)
                # And propagate skip to its children in subsequent iterations
            else:
                # check if all deps are completed (succeeded or skipped)
                if all(d in completed for d in cjob.deps):
                    await ready_queue.put(child)

    async def run_async(self) -> Dict[str, Any]:
        sem = asyncio.Semaphore(self.concurrency)
        ready_queue: asyncio.Queue[str] = asyncio.Queue()

        # seed ready queue with indegree 0 nodes
        for jid, deg in self._indegree.items():
            if deg == 0:
                await ready_queue.put(jid)

        completed: Set[str] = set()
        tasks: Dict[str, asyncio.Task[None]] = {}

        self._log("scheduler_started")
        try:
            while not ready_queue.empty() or tasks:
                # launch while capacity and ready jobs exist
                while not ready_queue.empty() and len(tasks) < self.concurrency and not self._cancelled:
                    jid = await ready_queue.get()
                    job = self.jobs_by_id[jid]
                    if self._cancelled:
                        job.status = "cancelled"
                        self._log("job_cancelled", job, reason="scheduler_cancelled")
                        completed.add(jid)
                        continue
                    t = asyncio.create_task(self._execute_job(jid, sem, ready_queue, completed))
                    tasks[jid] = t

                if not tasks:
                    break

                # wait for any task to finish
                done, _pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED)
                # remove done from dict
                to_remove: List[str] = []
                for jid, tsk in tasks.items():
                    if tsk in done:
                        to_remove.append(jid)
                for jid in to_remove:
                    tasks.pop(jid, None)

                # If stop_on_error, cancel remaining pending jobs and mark cancelled
                if self.stop_on_error and not self._cancelled:
                    any_failed = any(j.status in ("failed", "timeout") for j in self.jobs_by_id.values())
                    if any_failed:
                        self._cancelled = True
                        self._log("scheduler_cancelling", reason="stop_on_error")
                        # Cancel active tasks
                        for t in tasks.values():
                            t.cancel()
                        # Give tasks a chance to handle cancellation and update job states
                        if tasks:
                            try:
                                await asyncio.gather(*tasks.values(), return_exceptions=True)
                            except Exception:
                                pass
                        # Mark any not yet started as cancelled
                        for jid, job in self.jobs_by_id.items():
                            if job.status == "pending":
                                job.status = "cancelled"
                                job.started_at = job.started_at or (time.perf_counter() - self._start_time)
                                job.ended_at = job.ended_at or (time.perf_counter() - self._start_time)
                                self._log("job_cancelled", job, reason="stop_on_error")
                        tasks.clear()
                        break
        finally:
            if self._process_pool is not None:
                self._process_pool.shutdown(cancel_futures=True)
            self._log("scheduler_finished")

        # Prepare summary
        summary = {
            "peak_concurrency": self.peak_concurrency,
            "jobs": {
                jid: {
                    "status": j.status,
                    "attempts": j.attempts,
                    "error": j.error,
                    "started_at": j.started_at,
                    "ended_at": j.ended_at,
                    "result": j.result,
                }
                for jid, j in self.jobs_by_id.items()
            },
            "logs": self.logs,
        }
        return summary

    def run(self) -> Dict[str, Any]:
        return asyncio.run(self.run_async())


def parse_actions(actions: List[str], *, concurrency: int = 4) -> List[Job]:
    """Parse simple action strings into a list of independent jobs.

    Supported forms:
    - "sleep:0.1"
    - "cpu:100000"
    - "noop" or "noop:value"
    - "fail"
    - "flaky:fail_until=2"
    - "task:name=foo;timeout=1" (alias to noop with metadata)
    """
    jobs: List[Job] = []
    for idx, a in enumerate(actions):
        a = a.strip().strip("\"")
        jid = f"job_{idx+1}"
        if a.startswith("sleep:"):
            seconds = float(a.split(":", 1)[1])
            task = TaskSpec(type="sleep", name=f"sleep_{seconds}", args={"seconds": seconds})
        elif a.startswith("cpu:"):
            work = int(a.split(":", 1)[1])
            task = TaskSpec(type="cpu", name=f"cpu_{work}", args={"work": work})
        elif a.startswith("noop"):
            parts = a.split(":", 1)
            value = parts[1] if len(parts) > 1 else jid
            task = TaskSpec(type="noop", name="noop", args={"value": value})
        elif a == "fail":
            task = TaskSpec(type="fail", name="fail")
        elif a.startswith("flaky:"):
            kv = a.split(":", 1)[1]
            if kv.startswith("fail_until="):
                n = int(kv.split("=", 1)[1])
            else:
                n = 1
            task = TaskSpec(type="flaky", name="flaky", args={"fail_until": n}, max_retries=n)
        elif a.startswith("task:"):
            pairs = a.split(":", 1)[1].split(";")
            meta: Dict[str, Any] = {}
            for p in pairs:
                if not p:
                    continue
                if "=" in p:
                    k, v = p.split("=", 1)
                    # try to cast numeric
                    try:
                        v_cast: Any
                        if "." in v:
                            v_cast = float(v)
                        else:
                            v_cast = int(v)
                    except Exception:
                        v_cast = v
                    meta[k] = v_cast
                else:
                    meta[p] = True
            timeout = float(meta.get("timeout", 0)) or None
            task = TaskSpec(type="noop", name=str(meta.get("name", jid)), args={"value": meta.get("name", jid)}, timeout=timeout)
        else:
            # default to noop with given string as value
            task = TaskSpec(type="noop", name="noop", args={"value": a})
        jobs.append(Job(id=jid, task=task, deps=[]))
    return jobs


__all__ = ["TaskSpec", "Job", "Scheduler", "parse_actions"]
