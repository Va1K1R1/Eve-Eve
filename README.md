# PythonProject — Test Harness & Project Skeleton (Kanban T-002)

This repository provides a minimal, zero-dependency Python project skeleton with a deterministic unittest harness. It is Windows/PowerShell oriented and designed for strictly local execution (no network calls by default).

## 1) Runtime and Environment (Windows + PowerShell)
- Python 3.11+
- Recommended virtual environment:
  - Create: `py -3.11 -m venv .venv`
  - Activate: `.\.venv\Scripts\Activate.ps1`
  - Verify: `python -V` (expect 3.11+)
- Dependencies: none (stdlib only)

## 2) Project Layout
- `src\system\capabilities.py` — pure functions to detect local CPU, cores, RAM, and GPU details (Windows-first; offline only)
- `src\system\cli_capabilities.py` — CLI entrypoint that prints a JSON summary of capabilities
- `src\model\loading.py` — VRAM-aware Model Loading Shim (interface-only) providing `VRAMBudget`, `ModelAdapter`, and `DummyModelAdapter`
- `src\audio\asr.py` — deterministic offline ASR stub (SpeechRecognizer, LocalASR) with VAD-like detection, streaming and batch APIs
- `src\audio\cli_asr.py` — CLI entry for ASR: `python -m audio.cli_asr --input .\\path\\to.wav --json`
- `tests\test_capabilities.py` — deterministic unit tests using unittest + mocks (no GPU/network required)
- `tests\test_model_loading.py` — unit tests for the VRAM-aware loading shim (deterministic, offline)
- `tests\test_asr.py` — unit tests for ASR (WAV/PCM/streaming/silence/CLI)
- `tests\coverage_runner.py` — optional stdlib trace-based coverage emitter (.cover files written to project root)

## 3) Running Tests
- Discover and run all tests:
  - `python -m unittest discover -s tests -p "test_*.py" -v`
- Run a specific test module:
  - `python -m unittest -v tests\test_capabilities.py`

Notes:
- Tests are designed to be deterministic and offline. GPU-specific paths are mocked.
- No external packages or internet connectivity are required.

## 4) Optional: Generate Coverage Artifacts (stdlib `trace`)
- Run: `python tests\coverage_runner.py`
- Output: `.cover` text files written to the project root (one per module traced)

## 5) CLI Usage (Local Only)
Because this project is not yet packaged, run the CLI with the source directory on `sys.path`.

- Capabilities pretty-printed JSON example:
  - PowerShell one-liner:
    - `python -c "import sys, os; sys.path.insert(0, os.path.abspath('src')); from system.cli_capabilities import main; raise SystemExit(main(['--pretty']))"`
  - Output keys: `{cpu, cores, gpu, vram_gb, driver, cuda, ram_gb}`.

- ASR JSON example (deterministic offline stub):
  - PowerShell one-liner (assumes WAV path exists):
    - `python -c "import sys, os, json; sys.path.insert(0, os.path.abspath('src')); from audio.cli_asr import main; raise SystemExit(main(['--input', '.\\path\\to.wav', '--json']))"`
  - Output keys: `{text, language, sample_rate, segments:[{text,start,end}]}`.

## 6) Style and Future Tooling
- Follow PEP 8/257 informally for now. Type hints welcome.
- If/when adding tooling, prefer `pyproject.toml` (Black/Ruff/coverage) and keep everything runnable offline.

## 7) Troubleshooting
- If `python` maps to a different version, use `py -3.11` explicitly.
- On PowerShell script execution issues when activating venv: run PowerShell as Administrator or
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 8) Live Kanban (Work Items)
- See .junie\guidelines.md for the live Kanban board (Backlog → Next → In Progress → Done).
- As of 2025-08-11 01:36 (local), T-005 Speech Recognition (local Whisper-like pipeline) is listed under "Next" with scope, acceptance criteria, Windows PowerShell instructions, constraints, and risks/mitigations.
- When implementing T-005, follow the APIs/CLI/tests spec there and keep everything offline/local by default.


## 9) Additional Components & CLI Examples

Additional components present in this repository (all offline/local by default):
- src\system\gpu_monitor.py — GPU monitor with stub/NVIDIA backends and simple image renderer (PPM/BMP)
- src\system\cli_gpu.py — CLI for GPU monitor (flags: --once | --watch, --duration, --json, --out, --size WxH, --title)
- src\llm\wrappers.py — local LLM wrapper interfaces (deterministic offline stubs)
- src\audio\tts.py — deterministic offline TTS stub (SpeechSynthesizer, LocalTTS) with WAV save
- src\audio\cli_tts.py — CLI for TTS
- src\vision\ocr.py — local OCR (PGM/PPM and minimal 24-bit BMP), threshold + connected components
- src\vision\cli_ocr.py — CLI for OCR
- src\web\automation.py — in-memory DOM and actions (goto, click, fill, get_text, screenshot, wait_for_selector)
- src\web\cli_web.py — CLI for web automation (--plan or --html + --actions)
- src\orchestrator\scheduler.py — async scheduler (DAG, retries, timeouts, process pool)
- src\orchestrator\cli_orch.py — CLI for orchestrator (--plan or --actions ...)
- src\security\crypto.py — AES-256-CBC utilities + Windows DPAPI protector
- src\security\cli_crypto.py — CLI for crypto (--mode aes|dpapi, encrypt/decrypt)

Windows PowerShell CLI examples (ensure `src` is on sys.path or use `python -m ...`):
- TTS: `python -m audio.cli_tts --text "hello" --output .\out.wav --json`
- OCR: `python -m vision.cli_ocr --input .\path\to\image.pgm --json`
- Web automation: `python -m web.cli_web --html .\page.html --actions click=#submit fill=#name:Alice get_text=#result --json`
- Orchestrator: `python -m orchestrator.cli_orch --actions sleep:0.1 noop:hello --concurrency 2 --json`
- Crypto (AES password): `python -m security.cli_crypto --mode aes --op encrypt --in secret --password pass --salt 00112233445566778899aabbccddeeff --iv 000102030405060708090a0b0c0d0e0f --json`
  - DPAPI (Windows): `python -m security.cli_crypto --mode dpapi --op encrypt --in secret --json`
- GPU monitor (stub backend): `python -m system.cli_gpu --once --json --backend stub`
  - Watch and render BMP: `python -m system.cli_gpu --watch 1 --duration 5 --out .\gpu.bmp --size 800x200 --title "GPU Monitor" --backend stub`

All commands above run strictly locally; no external network calls are made by default.

## 10) Project Analysis (docs\analysis.md)
Generate a deterministic summary of the current implementation and write docs\analysis.md.

Windows PowerShell examples:
- JSON to stdout and write default Markdown:
  - `python -c "import sys, os; sys.path.insert(0, os.path.abspath('src')); from project.cli_analyze import main; raise SystemExit(main(['--json']))"`
- Explicit output path (still writes JSON):
  - `python -c "import sys, os; sys.path.insert(0, os.path.abspath('src')); from project.cli_analyze import main; raise SystemExit(main(['--out', '.\\docs\\analysis.md', '--json']))"`
- Alternatively, run as a module from the src directory:
  - `Set-Location src; python -m project.cli_analyze --out ..\\docs\\analysis.md --json; Set-Location ..`