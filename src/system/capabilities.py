"""
Hardware/Environment capability probe (Windows-first, zero external dependencies).

Exposes pure functions that collect local system information without
any network activity. Designed to be robust on systems without NVIDIA GPU or
without vendor tools, using PowerShell/WMI fallbacks where possible.

Returned field semantics (all optional where unavailable):
- cpu: str | None         Human-readable CPU name
- cores: int              Logical core count (>=1)
- gpu: str | None         Human-readable GPU name
- vram_gb: int | None     Total VRAM in GiB (rounded to nearest int)
- driver: str | None      GPU driver version
- cuda: str | None        CUDA version (if NVIDIA stack available)
- ram_gb: int             Total system RAM in GiB (rounded to nearest int)

Privacy-by-design: no network calls, only local OS queries.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, Optional
import ctypes

logger = logging.getLogger(__name__)


# -----------------------------
# RAM helpers (ctypes on Win32)
# -----------------------------
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _get_total_ram_bytes() -> int:
    """Return total physical memory in bytes using GlobalMemoryStatusEx.
    Cross-platform fallback uses os.sysconf when ctypes call fails.
    """
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            raise OSError("GlobalMemoryStatusEx failed")
        return int(stat.ullTotalPhys)
    except Exception as e:
        logger.debug("ctypes GlobalMemoryStatusEx failed: %s", e)
        # Portable fallback (may not exist on Windows, but safe guard for tests/ports)
        try:
            if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:  # type: ignore[attr-defined]
                page_size = os.sysconf("SC_PAGE_SIZE")  # type: ignore
                phys_pages = os.sysconf("SC_PHYS_PAGES")  # type: ignore
                return int(page_size) * int(phys_pages)
        except Exception as e2:
            logger.debug("sysconf fallback failed: %s", e2)
        # Last resort unknown
        return 0


def get_total_ram_gb() -> int:
    total_bytes = _get_total_ram_bytes()
    if total_bytes <= 0:
        # ensure non-negative integer result
        return 0
    gb = total_bytes / (1024 ** 3)
    return int(round(gb))


# -----------------------------
# CPU helpers (PowerShell WMI)
# -----------------------------

def _run_powershell_capture(cmd: str) -> subprocess.CompletedProcess:
    """Run a PowerShell command without profile; capture output.
    Returns a CompletedProcess regardless of exit status.
    """
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as e:
        logger.debug("PowerShell execution failed: %s", e)
        # Synthesize a failed CompletedProcess-like object
        cp = subprocess.CompletedProcess(args=["powershell"], returncode=1)
        cp.stdout = ""  # type: ignore[attr-defined]
        cp.stderr = str(e)  # type: ignore[attr-defined]
        return cp


def _get_cpu_name_wmi() -> Optional[str]:
    # Use ConvertTo-Json for structured parse
    cmd = (
        "Get-CimInstance Win32_Processor | "
        "Select-Object -First 1 Name | ConvertTo-Json -Depth 2"
    )
    cp = _run_powershell_capture(cmd)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    try:
        data = json.loads(cp.stdout)
        if isinstance(data, dict):
            name = data.get("Name")
            return str(name) if name else None
        elif isinstance(data, list) and data:
            # Some PS versions may output array
            first = data[0]
            if isinstance(first, dict):
                name = first.get("Name")
                return str(name) if name else None
        elif isinstance(data, str):
            return data.strip()
    except Exception as e:
        logger.debug("CPU WMI JSON parse failed: %s", e)
    return None


def get_cpu_name() -> Optional[str]:
    name = _get_cpu_name_wmi()
    if name:
        return name
    # Fallbacks
    try:
        import platform

        name = platform.processor()
        if name:
            return name
    except Exception:
        pass
    return None


def get_cores() -> int:
    c = os.cpu_count() or 1
    return int(c)


# -----------------------------
# GPU helpers (nvidia-smi or WMI)
# -----------------------------

def _detect_gpu_with_nvidia_smi() -> Optional[Dict[str, Any]]:
    """Try NVIDIA stack via nvidia-smi. Returns dict or None if unavailable.
    Output CSV: name,memory.total,driver_version,cuda_version
    memory.total is in MiB (nounits).
    """
    try:
        cp = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version,cuda_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as e:
        logger.debug("nvidia-smi execution failed: %s", e)
        return None

    if cp.returncode != 0:
        return None
    raw = (cp.stdout or "")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    line = lines[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    name, mem_mib_str, driver, cuda = parts[:4]
    try:
        mem_mib = int(mem_mib_str)
        vram_gb = int(round(mem_mib / 1024))
    except Exception:
        vram_gb = None
    result = {
        "gpu": name or None,
        "vram_gb": vram_gb,
        "driver": driver or None,
        "cuda": cuda or None,
    }
    return result


def _detect_gpu_with_wmi() -> Optional[Dict[str, Any]]:
    # Query first GPU via WMI
    cmd = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object -First 1 Name, AdapterRAM, DriverVersion | "
        "ConvertTo-Json -Depth 3"
    )
    cp = _run_powershell_capture(cmd)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    try:
        data = json.loads(cp.stdout)
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            return None
        name = data.get("Name")
        adapter_ram = data.get("AdapterRAM")
        driver = data.get("DriverVersion")
        vram_gb = None
        try:
            if adapter_ram is not None:
                vram_gb = int(round(int(adapter_ram) / (1024 ** 3)))
        except Exception:
            vram_gb = None
        return {
            "gpu": str(name) if name else None,
            "vram_gb": vram_gb,
            "driver": str(driver) if driver else None,
            "cuda": None,  # WMI doesn't expose CUDA; unknown
        }
    except Exception as e:
        logger.debug("GPU WMI JSON parse failed: %s", e)
        return None


def detect_gpu() -> Dict[str, Any]:
    """Detect GPU info using NVIDIA path first, then WMI.
    Always returns a dict with keys: gpu, vram_gb, driver, cuda (values may be None).
    """
    info = _detect_gpu_with_nvidia_smi()
    if not info:
        info = _detect_gpu_with_wmi()
    if not info:
        info = {"gpu": None, "vram_gb": None, "driver": None, "cuda": None}
    # Ensure keys exist
    for k in ("gpu", "vram_gb", "driver", "cuda"):
        info.setdefault(k, None)
    return info


# -----------------------------
# Aggregation
# -----------------------------

def get_capabilities() -> Dict[str, Any]:
    """Aggregate system capabilities into a single dict with defined keys."""
    cpu_name = get_cpu_name()
    cores = get_cores()
    ram_gb = get_total_ram_gb()
    gpu_info = detect_gpu()

    caps = {
        "cpu": cpu_name,
        "cores": int(cores),
        "gpu": gpu_info.get("gpu"),
        "vram_gb": gpu_info.get("vram_gb"),
        "driver": gpu_info.get("driver"),
        "cuda": gpu_info.get("cuda"),
        "ram_gb": int(ram_gb),
    }
    return caps


__all__ = [
    "get_capabilities",
    "get_cpu_name",
    "get_cores",
    "get_total_ram_gb",
    "detect_gpu",
    # internal (for tests)
    "_detect_gpu_with_nvidia_smi",
    "_detect_gpu_with_wmi",
    "_get_total_ram_bytes",
    "_get_cpu_name_wmi",
]
