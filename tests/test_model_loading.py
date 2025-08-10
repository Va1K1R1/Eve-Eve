import os
import sys
import unittest

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from model.loading import VRAMBudget, DummyModelAdapter  # noqa: E402


class VRAMBudgetTests(unittest.TestCase):
    def test_effective_budget_and_validation(self):
        b = VRAMBudget(10.0, 0.1)
        self.assertAlmostEqual(b.effective_gb(), 9.0)
        with self.assertRaises(ValueError):
            VRAMBudget(0.0, 0.1).effective_gb()
        with self.assertRaises(ValueError):
            VRAMBudget(10.0, -0.1).effective_gb()
        with self.assertRaises(ValueError):
            VRAMBudget(10.0, 1.0).effective_gb()


class DummyAdapterTests(unittest.TestCase):
    def test_suggest_batch_and_can_fit(self):
        adapter = DummyModelAdapter(model_overhead_gb=1.0, per_sample_gb=0.5)
        # cap=8, margin=0.1 -> eff=7.2; usable=6.2; batch=floor(6.2/0.5)=12
        self.assertEqual(adapter.suggest_batch_size(8.0, safety_margin=0.1), 12)
        self.assertTrue(adapter.can_fit_batch(12, 8.0, safety_margin=0.1))
        self.assertFalse(adapter.can_fit_batch(13, 8.0, safety_margin=0.1))

    def test_load_and_unload(self):
        adapter = DummyModelAdapter(model_overhead_gb=1.0, per_sample_gb=0.5, name="A")
        info = adapter.load(model_path="/path/model", vram_cap_gb=8.0, safety_margin=0.1)
        self.assertTrue(adapter.loaded)
        self.assertIn("batch_size", info)
        adapter.unload()
        self.assertFalse(adapter.loaded)

    def test_edge_cases_caps_and_overhead(self):
        adapter = DummyModelAdapter(model_overhead_gb=1.0, per_sample_gb=0.6)
        # Non-positive cap -> suggest should raise via VRAMBudget
        with self.assertRaises(ValueError):
            adapter.suggest_batch_size(0.0)
        # Overhead does not fit -> load should raise MemoryError when chosen==0
        # eff = 0.945 < overhead=1.0
        with self.assertRaises(MemoryError):
            adapter.load(model_path="m", vram_cap_gb=1.05, safety_margin=0.10)
        # Overhead fits but per-sample doesn't -> allow zero-batch init
        adapter_ok = DummyModelAdapter(model_overhead_gb=0.5, per_sample_gb=0.6)
        # eff=0.9; usable=0.4 < per -> suggest=0 -> load with chosen None allowed
        info = adapter_ok.load(model_path="m2", vram_cap_gb=1.0, safety_margin=0.10)
        self.assertEqual(info["batch_size"], 0)
        self.assertTrue(adapter_ok.loaded)
        adapter_ok.unload()
        self.assertFalse(adapter_ok.loaded)

    def test_invalid_inputs(self):
        adapter = DummyModelAdapter(model_overhead_gb=0.0, per_sample_gb=0.5)
        with self.assertRaises(ValueError):
            adapter.load(model_path="", vram_cap_gb=2.0)
        with self.assertRaises(ValueError):
            adapter.load(model_path="m", vram_cap_gb=2.0, batch_size=-1)
        # Invalid safety margin
        with self.assertRaises(ValueError):
            adapter.suggest_batch_size(2.0, safety_margin=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
