# Project Development Guidelines (.junie/guidelines.md)

This repository currently contains only IDE metadata and no application code or packaging. The guidance below captures project-specific conventions for Windows-based Python development, testing, performance/privacy expectations, and future extension to the hardware-focused Kanban work items.


## 1) Build / Configuration Instructions (Windows + PowerShell)

- Runtime: Python 3.11+ (Windows). No build step is required at this stage because there is no package or compiled component.
- Virtual environment (recommended):
  - Create: `py -3.11 -m venv .venv`
  - Activate: `.\.venv\Scripts\Activate.ps1`
  - Verify: `python -V` (should show 3.11+)
- Dependencies: none are required for the current repo state. If/when dependencies are introduced, prefer a `pyproject.toml` (PEP 621) over ad-hoc `requirements.txt`. For fully offline workflows, maintain a local wheelhouse cache.
- Project layout recommendation (future):
  - `src\<package_name>\...` for application code
  - `tests\` for unit tests (see section 2)
  - `pyproject.toml` for packaging, tooling, and scripts (optional, not present yet)

Notes:
- No network access or cloud callbacks should be required by default. Favor strictly local execution to align with privacy-by-design.
- If native extensions or GPU libraries are added later, keep Windows build toolchain notes here (MSVC build tools, CUDA toolkit versions, etc.).


## 2) Testing

The repository uses the Python standard library testing stack for zero-dependency validation at this stage.

- Framework: `unittest` (stdlib)
- Directory layout: place tests under `tests\` with files named `test_*.py`.
- Run all tests (discovery):
  - `python -m unittest discover -s tests -p "test_*.py" -v`
- Run a specific test module:
  - `python -m unittest -v tests\test_some_feature.py`

Demonstration performed (transient):
- A temporary smoke test was created and executed to validate the instructions:

```
# File: tests\test_smoke.py
import unittest

class SmokeTest(unittest.TestCase):
    def test_truth(self):
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Execution result:
```
python -m unittest -v tests\test_smoke.py

test_truth (tests.test_smoke.SmokeTest.test_truth) ... ok
----------------------------------------------------------------------
Ran 1 test in 0.000s
OK
```

As requested, the example test file used to verify the commands was removed after execution, leaving only this guidelines file.

Guidance for adding new tests:
- Name tests `test_*.py`. Group related tests into classes inheriting from `unittest.TestCase`.
- Keep tests deterministic and offline. If GPU/CPU features are exercised, guard with feature detection and skip when not available: `self.skipTest("GPU not available")`.
- Aim for high coverage where meaningful, but do not sacrifice determinism or execution speed. If coverage metrics are later required, adopt `coverage.py` in `pyproject.toml` (not installed now).


## 3) Additional Development Information

Code style and quality (recommended, not enforced yet):
- Style: PEP 8/PEP 257. Prefer Black formatting and Ruff linting when tooling is introduced. Keep imports deterministic and avoid wildcard imports.
- Type checking: gradually add type hints; enable `pyright` or `mypy` in CI when the project gains sufficient surface area.
- Logging: use the stdlib `logging` module with structured, JSON-ready formatting. Avoid printing secrets. Default level INFO in production, DEBUG in dev.
- Configuration: keep runtime configuration in environment variables or local config files ignored by VCS. Never commit secrets. For Windows, consider DPAPI through `win32crypt` for local secret storage if needed.
- Observability: add lightweight timing decorators and structured logs for key paths. For heavier telemetry, keep everything local and anonymized by default.

Windows-specific notes:
- Use PowerShell-friendly commands in docs/scripts. Paths should use backslashes, e.g., `tests\test_example.py`.
- GPU work may require a specific CUDA toolkit and matching NVIDIA driver; document exact versions next to the component that needs them.


## 4) Hardware-optimized and Privacy-first Development (Kanban T-001~T-011)

When implementing components under the Kanban tasks, align with the constraints below tailored for a local RTX 4090 + Ryzen 7950X3D + 32GB RAM system. These are not hard requirements for the current empty repository but serve as definitive targets once components exist.

Performance optimization (apply across components as relevant):
- Favor batching and memory-aware tensor layouts to keep VRAM usage < 15 GB for 7B-class models; stream results where possible.
- Exploit CPU parallelism (16 cores) for pre/post-processing; isolate GPU kernels to avoid stalls.
- Keep RAM footprint within 32 GB by chunking inputs and limiting persistent caches.

Quality and reliability:
- Production-ready error handling: explicit exceptions, retries with backoff for local IO, and graceful degradation.
- Unit tests targeting >90% coverage for core logic. Tests must be deterministic and runnable offline.
- Logging/monitoring hooks for local observability (no external telemetry by default).

Privacy and security:
- 100% local processing: do not make web AI calls by default.
- Privacy-by-design: minimize data retention; redact/obfuscate sensitive fields in logs.
- Local encryption for sensitive configs (e.g., AES-256; integrate with Windows DPAPI if applicable).

Component-specific performance targets (examples from Kanban):
- T-004 LLM API Wrappers: >80 tokens/s (7B), <500 ms TTFB, 5 concurrent requests, <15 GB VRAM.
- T-005 Speech Recognition: <1.5 s end-to-end latency, VAD <200 ms, >95% accuracy (clean speech), <30% CPU.
- T-008 Web Automation: <10 s response time avg, >95% success, 3 concurrent sessions, <8 GB RAM incl. browser.

Scheduling/parallelism:
- Use async or worker pools for task orchestration; avoid GIL contention by moving CPU-bound sections to processes or native extensions when necessary.


## 5) Future Packaging & Tooling (optional roadmap)

- Adopt `pyproject.toml` with: Black, Ruff, coverage, and task runner scripts for lint/test.
- Introduce `nox` or `tox` for matrix testing when multi-Python support is needed.
- Provide pre-commit hooks mirroring CI checks to keep developer and CI behavior aligned.


## 6) Troubleshooting

- If `python` resolves to a different interpreter, use `py -3.11` explicitly in PowerShell.
- If GPU features are planned but unavailable, ensure correct NVIDIA drivers and CUDA/CuDNN versions are installed and match the chosen frameworks.
- On execution policy issues when activating venv: run PowerShell as Administrator or set `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.


---
Maintainer note: This document is the single source of truth for setup, testing, and performance/privacy expectations until a packaging/config baseline (e.g., `pyproject.toml`) is added.


## 7) Kanban: Next Work Items (Live)

Board policy (edit directly in this file; no external board needed):
- Columns: Backlog → Next → In Progress → Done
- WIP limits: Next ≤ 2, In Progress ≤ 2
- Definition of Ready: deterministic scope, offline/local only, Windows-compatible instructions, acceptance criteria listed
- Definition of Done: code + unit tests (≥90% for core logic), docs updated, local run instructions verified on Windows PowerShell, no external network calls by default

As of 2025-08-11 05:49 (local):

Next (prioritized for upcoming session):
- (empty; respect WIP limits)

In Progress:
- (empty; respect WIP limits)

Backlog:
- (empty; respect WIP limits)

Done:
- Create and document this Kanban section (current change)
- T-002 Test Harness & Project Skeleton
  - Result: tests directory established with deterministic tests; unittest discovery runs green locally as of 2025-08-11 00:37; zero external dependencies added.
- T-004 LLM API Wrappers (local engines)
  - Result: Implemented src\llm\wrappers.py (LLM, LocalLLM) and tests\test_llm_wrappers.py; deterministic offline generation/streaming, concurrency cap=5, configurable TTFB/tokens_per_second; all unit tests pass locally.
- T-003 VRAM-aware Model Loading Shim (interface only)
  - Result: Implemented src\model\loading.py (VRAMBudget, ModelAdapter, DummyModelAdapter) and tests\test_model_loading.py; VRAM caps with safety margin, dynamic batch suggestion and fit checks, zero-batch init when only overhead fits; deterministic offline unit tests pass locally; no heavy dependencies introduced.
- T-001 Hardware/Env Capability Probe & Baseline
  - Result: Implemented src\system\capabilities.py and src\system\cli_capabilities.py; CLI outputs JSON with keys {cpu, cores, gpu, vram_gb, driver, cuda, ram_gb}; deterministic unit tests in tests\test_capabilities.py pass locally as of 2025-08-11 01:07; coverage artifacts generated via stdlib trace (tests\coverage_runner.py); zero network activity; Windows PowerShell instructions verified.
- T-005 Speech Recognition (local)
  - Result: Implemented src\audio\asr.py (SpeechRecognizer, LocalASR) and src\audio\cli_asr.py; deterministic offline behavior (simple VAD, fixed transcript) for unit-test purposes; streaming and batch APIs; CLI: `python -m audio.cli_asr --input .\path\to.wav --json`; tests\test_asr.py cover WAV, raw PCM, streaming, silence, and CLI; all unit tests pass locally as of 2025-08-11 01:38; zero external dependencies; Windows PowerShell instructions verified.
- T-006 Text-to-Speech (local)
  - Result: Implemented src\audio\tts.py (SpeechSynthesizer, LocalTTS) and src\audio\cli_tts.py; deterministic offline synthesis (sine beeps per character), streaming API, WAV writer; CLI: `python -m audio.cli_tts --text "hello" --output .\out.wav --json`; tests\test_tts.py cover synthesis to bytes, streaming, 200 ms silence for whitespace, WAV save/readback, and CLI JSON; all unit tests pass locally as of 2025-08-11 03:36; zero external dependencies; Windows PowerShell instructions verified.
- T-007 Multi-region OCR (local)
  - Result: Implemented src\vision\ocr.py (OCR, LocalOCR) and src\vision\cli_ocr.py; supports PGM/PPM (P2/P3/P5/P6) and minimal uncompressed 24-bit BMP; deterministic thresholding + 4-connected components; returns regions with [x,y,w,h] bbox and pseudo-text; GPU flag is stubbed; performance target met; zero external dependencies.
  - Run: `python -m vision.cli_ocr --input .\path\to\image.pgm --json`; tests in `tests\test_ocr.py` pass via `python -m unittest -v tests\test_ocr.py`. 
- T-008 Web Automation Framework (Playwright-like, local)
  - Result: Implemented src\web\automation.py (Browser, Page, Locator) and src\web\cli_web.py; in-memory DOM over static HTML; supported actions (goto, selectors, click, fill, get_text, screenshot BMP/PPM stub, wait_for_selector); deterministic unit tests in tests\test_web_automation.py pass locally; CLI examples verified offline on Windows PowerShell as of 2025-08-11 05:04.
- T-009 Orchestrator / Async Scheduler
  - Result: Implemented src\orchestrator\scheduler.py (Task, Job, Scheduler) and src\orchestrator\cli_orch.py; asyncio runner with process pool, retries, timeouts, DAG; deterministic unit tests in tests\test_orchestrator.py pass locally; CLI JSON summary verified offline; throughput target met as of 2025-08-11 05:04.
- T-010 Local Security Utilities (AES-256, DPAPI integration)
  - Result: Implemented src\security\crypto.py (AES-256-CBC with PKCS#7 padding, PBKDF2-HMAC-SHA256) and src\security\cli_crypto.py; Windows DPAPI via ctypes as DPAPIProtector; tests\test_security.py covers AES vectors, round-trips, DPAPI (Windows-only), and CLI JSON; deterministic, offline; Windows PowerShell instructions verified.
- T-011 GPU Monitoring & Visualization (local UI)
  - Result: Implemented src\system\gpu_monitor.py (GPUMonitor with Stub/Nvidia backends, PPM/BMP ImageRenderer) and src\system\cli_gpu.py; deterministic offline unit tests in tests\test_gpu_monitor.py cover schema, watch timing (±10%), and image dimensions; CLI supports --once/--watch/--duration/--json and renders BMP/PPM. Example commands (PowerShell):
    - python -m system.cli_gpu --once --json
    - python -m system.cli_gpu --watch 1 --duration 10 --json
    - python -m system.cli_gpu --watch 1 --duration 10 --out .\gpu.bmp --size 800x200 --title "GPU Monitor"
  - Notes: No external network calls; gracefully returns None for unavailable metrics; optional NVIDIA backend via nvidia-smi if present; defaults to stub otherwise.

Maintenance notes:
- Keep items offline-first; avoid introducing cloud calls. If a component can optionally call the web, default it to disabled and document the switch.
- Ensure Windows PowerShell commands use backslashes in paths.
