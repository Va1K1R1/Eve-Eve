import io
import json
import os
import sys
import types
import unittest
import ctypes
from unittest import mock

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import system.capabilities as caps  # noqa: E402
from system.cli_capabilities import main as cli_main  # noqa: E402


def _cp(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class CapabilitiesTests(unittest.TestCase):
    def test_run_powershell_capture_success(self):
        # Simulate successful PowerShell command
        with mock.patch("subprocess.run", return_value=_cp(0, '{"Name":"CPU"}', "")):
            cp = caps._run_powershell_capture("Get-CimInstance Win32_Processor")
        self.assertEqual(cp.returncode, 0)
        self.assertTrue(cp.stdout)


    def test_get_total_ram_bytes_sysconf_failure(self):
        with mock.patch.object(caps.ctypes, "windll", side_effect=AttributeError("no windll")), \
             mock.patch.object(caps.os, "sysconf_names", new={}, create=True), \
             mock.patch.object(caps.os, "sysconf", side_effect=OSError("no sysconf"), create=True):
            val = caps._get_total_ram_bytes()
        self.assertEqual(val, 0)

    def test_nvidia_smi_parsing(self):
        """nvidia-smi CSV nounits path should parse correctly and round MiB→GiB."""
        fake_out = "NVIDIA GeForce RTX 4090,24576,555.55,12.2\n"
        with mock.patch("subprocess.run", return_value=_cp(0, fake_out, "")):
            info = caps._detect_gpu_with_nvidia_smi()
        self.assertIsNotNone(info)
        self.assertEqual(info["gpu"], "NVIDIA GeForce RTX 4090")
        self.assertEqual(info["vram_gb"], 24)  # 24576 MiB ≈ 24 GiB
        self.assertEqual(info["driver"], "555.55")
        self.assertEqual(info["cuda"], "12.2")

    def test_wmi_gpu_fallback_parsing(self):
        """WMI fallback JSON should parse correctly; CUDA unknown (None)."""
        obj = {
            "Name": "NVIDIA GeForce RTX 4090",
            "AdapterRAM": 25769803776,  # 24 GiB
            "DriverVersion": "555.55",
        }
        with mock.patch.object(caps, "_run_powershell_capture", return_value=_cp(0, json.dumps(obj), "")):
            info = caps._detect_gpu_with_wmi()
        self.assertIsNotNone(info)
        self.assertEqual(info["gpu"], "NVIDIA GeForce RTX 4090")
        self.assertEqual(info["vram_gb"], 24)
        self.assertEqual(info["driver"], "555.55")
        self.assertIsNone(info["cuda"])  # WMI path cannot infer CUDA

    def test_detect_gpu_both_fail(self):
        with mock.patch.object(caps, "_detect_gpu_with_nvidia_smi", return_value=None), \
             mock.patch.object(caps, "_detect_gpu_with_wmi", return_value=None):
            info = caps.detect_gpu()
        self.assertIsInstance(info, dict)
        self.assertIn("gpu", info)
        self.assertIn("vram_gb", info)
        self.assertIn("driver", info)
        self.assertIn("cuda", info)
        self.assertIsNone(info["gpu"])  # all None when undetected

    def test_ram_rounding_and_zero(self):
        giB = 1024 ** 3
        with mock.patch.object(caps, "_get_total_ram_bytes", return_value=int(15.4 * giB)):
            self.assertEqual(caps.get_total_ram_gb(), 15)
        with mock.patch.object(caps, "_get_total_ram_bytes", return_value=int(15.6 * giB)):
            self.assertEqual(caps.get_total_ram_gb(), 16)
        with mock.patch.object(caps, "_get_total_ram_bytes", return_value=0):
            self.assertEqual(caps.get_total_ram_gb(), 0)

    def test_cpu_name_paths(self):
        with mock.patch.object(caps, "_get_cpu_name_wmi", return_value="AMD Ryzen 9 7950X3D"):
            self.assertEqual(caps.get_cpu_name(), "AMD Ryzen 9 7950X3D")
        with mock.patch.object(caps, "_get_cpu_name_wmi", return_value=None), \
             mock.patch("platform.processor", return_value="SomeCPU"):
            self.assertEqual(caps.get_cpu_name(), "SomeCPU")

    def test_get_cores(self):
        with mock.patch("os.cpu_count", return_value=16):
            self.assertEqual(caps.get_cores(), 16)
        with mock.patch("os.cpu_count", return_value=None):
            self.assertEqual(caps.get_cores(), 1)

    def test_get_capabilities_aggregation(self):
        gpu = {"gpu": "RTX 4090", "vram_gb": 24, "driver": "555.55", "cuda": "12.2"}
        with mock.patch.object(caps, "get_cpu_name", return_value="CPU"), \
             mock.patch.object(caps, "get_cores", return_value=16), \
             mock.patch.object(caps, "get_total_ram_gb", return_value=32), \
             mock.patch.object(caps, "detect_gpu", return_value=gpu):
            out = caps.get_capabilities()
        self.assertEqual(out["cpu"], "CPU")
        self.assertEqual(out["cores"], 16)
        self.assertEqual(out["gpu"], "RTX 4090")
        self.assertEqual(out["vram_gb"], 24)
        self.assertEqual(out["driver"], "555.55")
        self.assertEqual(out["cuda"], "12.2")
        self.assertEqual(out["ram_gb"], 32)

    def test_cli_outputs_json_with_required_keys(self):
        buf = io.StringIO()
        with mock.patch("system.cli_capabilities.get_capabilities", return_value={
            "cpu": "CPU",
            "cores": 16,
            "gpu": "RTX 4090",
            "vram_gb": 24,
            "driver": "555.55",
            "cuda": "12.2",
            "ram_gb": 32,
        }), mock.patch("sys.stdout", new=buf):
            rc = cli_main(["--pretty"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        for k in ("cpu", "cores", "gpu", "vram_gb", "driver", "cuda", "ram_gb"):
            self.assertIn(k, data)

    def test_run_powershell_capture_exception_path(self):
        with mock.patch("subprocess.run", side_effect=RuntimeError("ps not available")):
            cp = caps._run_powershell_capture("Get-Whatever")
        self.assertEqual(cp.returncode, 1)
        self.assertEqual(cp.stdout, "")

    def test_total_ram_bytes_ctypes_path(self):
        # Mock the successful ctypes/GlobalMemoryStatusEx path
        class K32:
            def GlobalMemoryStatusEx(self, pstat):
                # Set ullTotalPhys to 16 GiB
                stat = pstat._obj  # extract underlying object from byref()
                stat.ullTotalPhys = 16 * (1024 ** 3)
                return 1
        fake_windll = types.SimpleNamespace(kernel32=K32())
        with mock.patch.object(ctypes, "windll", new=fake_windll):
            val = caps._get_total_ram_bytes()
            gb = caps.get_total_ram_gb()
        self.assertGreater(val, 0)
        self.assertEqual(gb, 16)

    def test_nvidia_smi_error_and_malformed(self):
        # Returncode non-zero -> None
        with mock.patch("subprocess.run", return_value=_cp(1, "", "err")):
            self.assertIsNone(caps._detect_gpu_with_nvidia_smi())
        # Empty stdout -> None
        with mock.patch("subprocess.run", return_value=_cp(0, "\n", "")):
            self.assertIsNone(caps._detect_gpu_with_nvidia_smi())
        # Malformed parts -> None
        with mock.patch("subprocess.run", return_value=_cp(0, "OnlyTwo,123\n", "")):
            self.assertIsNone(caps._detect_gpu_with_nvidia_smi())

    def test_cpu_wmi_json_array_and_string_variants(self):
        # Array variant
        arr_json = json.dumps([{"Name": "CPU WMI"}])
        with mock.patch.object(caps, "_run_powershell_capture", return_value=_cp(0, arr_json, "")):
            self.assertEqual(caps._get_cpu_name_wmi(), "CPU WMI")
        # String variant
        str_json = json.dumps("CPU Simple")
        with mock.patch.object(caps, "_run_powershell_capture", return_value=_cp(0, str_json, "")):
            self.assertEqual(caps._get_cpu_name_wmi(), "CPU Simple")


if __name__ == "__main__":
    unittest.main(verbosity=2)
