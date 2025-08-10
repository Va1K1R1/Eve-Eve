from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional

logger = logging.getLogger(__name__)


class LLM(ABC):
    """Abstract base interface for local LLM wrappers.

    The interface is fully offline and deterministic by default.
    """

    @abstractmethod
    async def generate_async(
        self,
        prompt: str,
        *,
        max_tokens: int = 16,
    ) -> str:
        """Generate a text completion for a prompt as a single string."""

    @abstractmethod
    async def stream_async(
        self,
        prompt: str,
        *,
        max_tokens: int = 16,
    ) -> AsyncIterator[str]:
        """Async generator yielding tokens/chunks for the completion."""


@dataclass
class LocalLLMConfig:
    # Performance knobs (deterministic, no randomness)
    tokens_per_second: float = 120.0  # >80 t/s by default (target)
    ttfb_ms: int = 50  # <500 ms TTFB by default (target)
    max_concurrency: int = 5  # target concurrent requests
    token_prefix: str = "token_"
    # If <=0, disable per-token delay for tests
    disable_token_delay_if_leq_zero: bool = True


class LocalLLM(LLM):
    """A deterministic, offline local LLM wrapper.

    - Concurrency is limited via an asyncio.Semaphore.
    - Streaming yields synthetic tokens based on a simple counter.
    - Timing is simulated via asyncio.sleep; can be disabled in tests.
    """

    def __init__(self, config: Optional[LocalLLMConfig] = None) -> None:
        self.config = config or LocalLLMConfig()
        if self.config.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._sem = asyncio.Semaphore(self.config.max_concurrency)
        self._current_concurrency = 0
        self._peak_concurrency = 0
        self._cc_lock = asyncio.Lock()

    @property
    def peak_concurrency(self) -> int:
        return self._peak_concurrency

    @property
    def current_concurrency(self) -> int:
        return self._current_concurrency

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

    async def generate_async(self, prompt: str, *, max_tokens: int = 16) -> str:
        tokens: List[str] = []
        async for tok in self.stream_async(prompt, max_tokens=max_tokens):
            tokens.append(tok)
        return " ".join(tokens)

    async def stream_async(self, prompt: str, *, max_tokens: int = 16) -> AsyncIterator[str]:
        if not isinstance(prompt, str) or len(prompt) == 0:
            raise ValueError("prompt must be a non-empty string")
        if max_tokens < 0:
            raise ValueError("max_tokens must be non-negative")

        await self._sem.acquire()
        await self._inc_concurrency()
        try:
            # Simulated TTFB
            if self.config.ttfb_ms > 0:
                await asyncio.sleep(self.config.ttfb_ms / 1000.0)

            # Generate deterministic tokens
            for i in range(max_tokens):
                if not self._should_skip_token_delay():
                    await self._sleep_per_token()
                yield f"{self.config.token_prefix}{i}"
        finally:
            await self._dec_concurrency()
            self._sem.release()

    def _should_skip_token_delay(self) -> bool:
        if self.config.disable_token_delay_if_leq_zero and self.config.tokens_per_second <= 0:
            return True
        return False

    async def _sleep_per_token(self) -> None:
        tps = self.config.tokens_per_second
        if tps <= 0:
            # No delay when disabled for tests
            return
        await asyncio.sleep(1.0 / tps)


__all__ = ["LLM", "LocalLLM", "LocalLLMConfig"]
