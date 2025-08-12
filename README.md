---

# Local AI & Automation Toolkit (Windows, Offline-First)

Windows + PowerShell 환경에서 동작하는 **로컬 전용 AI 및 자동화 툴킷**입니다.
**Privacy-by-Design**과 **Offline-First** 원칙을 준수하며, 네트워크 기능은 기본 차단 상태에서 선택적으로만 허용됩니다.

---

## Quickstart

```powershell
# Python 3.11+ 가상환경 생성 및 활성화
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -V  # expect 3.11+

# Option A: src 폴더로 이동 후 실행
Set-Location src
python -m system.cli_capabilities --pretty
Set-Location ..

# Option B: repo root에서 PYTHONPATH 설정
$env:PYTHONPATH = "$PWD\src"
python -m system.cli_capabilities --pretty
```

---

## Project Layout

```
src\
  system\         # 하드웨어/환경, GPU 모니터링
  model\          # VRAM-aware 모델 로딩
  llm\            # 로컬 LLM Wrapper
  audio\          # 오디오 ASR/TTS
  vision\         # 로컬 OCR
  web\            # 오프라인 웹 자동화
  orchestrator\   # Async/DAG 작업 스케줄러
  security\       # AES-256 & DPAPI 유틸
  network\        # 선택적 외부 API
  project\        # 프로젝트 분석 CLI
tests\            # unittest 기반 테스트
.junie\           # 개발 가이드 & Kanban
docs\             # 분석 및 추가 문서
```

---

## CLI Modules (10)

```powershell
# System
python -m system.cli_capabilities --pretty
python -m system.cli_gpu --once --json

# Audio
python -m audio.cli_asr --input .\audio.wav --json
python -m audio.cli_tts --text "Hello" --output .\out.wav --json

# Vision
python -m vision.cli_ocr --input .\image.pgm --json

# Web
python -m web.cli_web --html .\page.html --actions click=#ok get_text=#result --json

# Orchestrator
python -m orchestrator.cli_orch --actions sleep:0.5 noop:done --json

# Security
python -m security.cli_crypto --mode aes --op encrypt --in secret.txt --password pass --json

# Network (기본 차단)
python -m network.cli_external_api --url https://example.com/data.json --json
# 명시적 허용
$env:PY_LOCAL_ALLOW_NETWORK = "1"
python -m network.cli_external_api --url https://api.test/data --allow-network --allow-domain api.test --json

# Project Analysis
python -m project.cli_analyze --out .\docs\analysis.md --json
```

---

## Running Tests

```powershell
# 전체 테스트
python -m unittest discover -s tests -p "test_*.py" -v

# 단일 모듈
python -m unittest -v tests\test_capabilities.py
```

* 네트워크/GPU 종속 기능은 조건부 skip 처리
* 모든 테스트는 **Deterministic + Offline** 실행 보장

---

## CLI ↔ Test Coverage Map

| CLI Module                           | 주요 기능                                  | 테스트 모듈                      | 커버리지 포인트                                                              |
| ------------------------------------ | -------------------------------------- | --------------------------- | --------------------------------------------------------------------- |
| `python -m system.cli_capabilities`  | CPU, GPU, RAM, 드라이버 정보 JSON 출력         | `tests.test_capabilities`   | 키셋 `{cpu, cores, gpu, vram_gb, driver, cuda, ram_gb}` 검증, JSON 스키마 체크 |
| `python -m system.cli_gpu`           | GPU 모니터링 (Stub/NVIDIA), BMP/PPM 렌더링    | `tests.test_gpu_monitor`    | `--once`/`--watch` 동작, 타이밍 오차(±10%) 검증, 이미지 크기 확인                     |
| `python -m audio.cli_asr`            | 로컬 ASR (WAV/PCM), 스트리밍/배치              | `tests.test_asr`            | WAV/RAW PCM 처리, 스트리밍 분할, 무음 처리, CLI JSON 출력                           |
| `python -m audio.cli_tts`            | 로컬 TTS, sine wave 기반 WAV 생성            | `tests.test_tts`            | 바이트 출력, 스트리밍, 공백 시 무음 삽입, 저장 후 읽기                                     |
| `python -m vision.cli_ocr`           | PGM/PPM/BMP OCR, bbox + pseudo-text 반환 | `tests.test_ocr`            | 포맷별 처리, threshold 적용, 연결 요소 분석                                        |
| `python -m web.cli_web`              | 오프라인 HTML DOM 자동화                      | `tests.test_web_automation` | `goto`, `click`, `fill`, `get_text`, `screenshot` 로직 검증               |
| `python -m orchestrator.cli_orch`    | Async DAG 실행, retries, timeouts        | `tests.test_orchestrator`   | Job/Task 실행 순서, 동시성 제한, 재시도 로직                                        |
| `python -m security.cli_crypto`      | AES-256-CBC, DPAPI 암·복호화               | `tests.test_security`       | AES 벡터 검증, round-trip, DPAPI Windows-only 분기                          |
| `python -m network.cli_external_api` | 선택적 외부 API 호출 (기본 차단)                  | `tests.test_external_api`   | 기본 차단, allowlist 허용, URL/메서드 제한 검증                                    |
| `python -m project.cli_analyze`      | 코드/구성 분석, JSON/Markdown 출력             | `tests.test_analyzer`       | 소스/테스트/CLI 매핑 검증, 보고서 생성 확인                                           |
| *(내부)* LLM Wrapper                   | 로컬 LLM 인터페이스                           | `tests.test_llm_wrappers`   | 로컬 모델 객체 생성, 스트리밍/배치 응답                                               |
| *(내부)* VRAM-aware 모델 로딩              | VRAM 예산, 배치 크기 계산                      | `tests.test_model_loading`  | VRAM 한계, 배치 추천, zero-batch init                                       |

---

## Privacy & Offline Defaults

* 기본 **네트워크 차단**
* 외부 API 호출은 `--allow-network` + `--allow-domain` 또는 `PY_LOCAL_ALLOW_NETWORK=1` 환경 변수로만 허용
* 로컬 저장소만 사용, 민감 데이터는 AES-256 또는 DPAPI 암호화 가능
* GPU/네트워크 미지원 환경에서도 graceful degradation 지원

---

## Example Workflows

```powershell
# 1. 하드웨어 상태 확인 → GPU 모니터링
python -m system.cli_capabilities --pretty
python -m system.cli_gpu --watch 1 --duration 5 --json

# 2. 음성 파일 인식 후 결과 텍스트 저장
python -m audio.cli_asr --input .\speech.wav --json > result.json

# 3. 이미지에서 텍스트 추출
python -m vision.cli_ocr --input .\doc.pgm --json

# 4. 웹 페이지 자동화
python -m web.cli_web --html .\form.html --actions fill=#name:John click=#submit get_text=#status --json

# 5. 프로젝트 분석 리포트 생성
python -m project.cli_analyze --out .\docs\analysis.md --json
```

---

## Troubleshooting

* **Python 버전** 강제:

  ```powershell
  py -3.11
  ```
* **PowerShell Execution Policy**:

  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```
* **GPU 기능 없음**: NVIDIA 드라이버와 CUDA 버전 확인
* **네트워크 기능 필요 시**: 환경 변수 + 플래그 설정 필수

---

## Kanban Policy

* 컬럼: Backlog → Next → In Progress → Done
* WIP 제한: Next ≤ 2, In Progress ≤ 2
* DoD(완료 정의): 코드 + ≥90% 커버리지, Windows PowerShell 실행 검증, 기본 네트워크 차단 상태 유지

자세한 정책은 [`.junie\guidelines.md`](..junie\guidelines.md) 참고.

---
