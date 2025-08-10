import os
import sys
import unittest
import asyncio

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from llm.wrappers import LocalLLM, LocalLLMConfig  # noqa: E402


class LocalLLMTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_async_deterministic(self):
        cfg = LocalLLMConfig(tokens_per_second=0.0, ttfb_ms=0)
        llm = LocalLLM(cfg)
        text = await llm.generate_async("Hello", max_tokens=5)
        self.assertEqual(text, "token_0 token_1 token_2 token_3 token_4")

    async def test_stream_async_tokens_and_order(self):
        cfg = LocalLLMConfig(tokens_per_second=0.0, ttfb_ms=0)
        llm = LocalLLM(cfg)
        tokens = []
        async for tok in llm.stream_async("Prompt", max_tokens=4):
            tokens.append(tok)
        self.assertEqual(tokens, ["token_0", "token_1", "token_2", "token_3"])

    async def test_concurrency_cap(self):
        # Use small TTFB and small per-token delay to ensure overlap
        cfg = LocalLLMConfig(tokens_per_second=500.0, ttfb_ms=2, max_concurrency=5)
        llm = LocalLLM(cfg)

        async def worker(i: int):
            # Make each request produce a handful of tokens
            return await llm.generate_async(f"P{i}", max_tokens=3)

        # Launch more tasks than the concurrency cap
        tasks = [asyncio.create_task(worker(i)) for i in range(10)]
        await asyncio.gather(*tasks)

        # Peak concurrency should be capped at 5
        self.assertEqual(llm.peak_concurrency, 5)
        # Basic sanity: outputs are deterministic
        self.assertTrue(all(t == "token_0 token_1 token_2" for t in [task.result() for task in tasks]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
