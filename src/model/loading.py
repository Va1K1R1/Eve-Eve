"""
VRAM-aware Model Loading Shim (interface only) — Kanban T-003.

This module defines a small, stdlib-only interface for model loading that is
aware of VRAM budgets. It does not import any heavy ML frameworks and is
designed for deterministic, offline unit tests.

Key ideas:
- Model overhead (GiB) + per-sample memory (GiB) * batch_size must fit into
  the effective VRAM budget after applying a safety margin.
- Suggest a batch size based on the current VRAM cap and simple memory model.

Privacy-by-design: no network calls.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import floor
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VRAMBudget:
    """Represents a VRAM cap in GiB and a safety margin [0.0, 1.0).

    The effective budget used for allocations equals vram_cap_gb * (1 - safety_margin).
    """

    vram_cap_gb: float
    safety_margin: float = 0.10

    def effective_gb(self) -> float:
        if self.vram_cap_gb <= 0:
            raise ValueError("vram_cap_gb must be > 0")
        if not (0.0 <= self.safety_margin < 1.0):
            raise ValueError("safety_margin must be in [0.0, 1.0)")
        return self.vram_cap_gb * (1.0 - self.safety_margin)


class ModelAdapter(ABC):
    """Abstract VRAM-aware model adapter.

    Concrete implementations should avoid heavy imports in module scope.
    """

    @property
    @abstractmethod
    def loaded(self) -> bool:
        """Whether the underlying model is loaded."""

    @abstractmethod
    def estimate_sample_mem_gb(self, input_spec: Optional[Dict[str, Any]] = None) -> float:
        """Estimate memory per sample (GiB) based on an optional input spec.

        Implementations may ignore input_spec and return a fixed value.
        """

    @abstractmethod
    def model_overhead_gb(self) -> float:
        """Return the base model memory overhead (GiB) when loaded."""

    def suggest_batch_size(
        self,
        vram_cap_gb: float,
        safety_margin: float = 0.10,
        input_spec: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Suggest the largest batch size that fits in the given budget.

        Returns 0 if even one sample cannot fit after overhead.
        Raises ValueError for non-positive caps or invalid safety_margin.
        """
        budget = VRAMBudget(vram_cap_gb, safety_margin)
        eff = budget.effective_gb()
        overhead = self.model_overhead_gb()
        per_sample = self.estimate_sample_mem_gb(input_spec)
        if per_sample <= 0 or overhead < 0:
            raise ValueError("per-sample must be > 0 and overhead >= 0")
        usable = eff - overhead
        if usable < per_sample:
            logger.debug(
                "Batch suggest: unusable budget (eff=%.3f, overhead=%.3f, per=%.3f)",
                eff,
                overhead,
                per_sample,
            )
            return 0
        size = int(floor(usable / per_sample))
        logger.debug(
            "Batch suggest: eff=%.3f, overhead=%.3f, per=%.3f => batch=%d",
            eff,
            overhead,
            per_sample,
            size,
        )
        return max(size, 0)

    def can_fit_batch(
        self,
        batch_size: int,
        vram_cap_gb: float,
        safety_margin: float = 0.10,
        input_spec: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if batch_size < 0:
            return False
        budget = VRAMBudget(vram_cap_gb, safety_margin)
        eff = budget.effective_gb()
        required = self.model_overhead_gb() + self.estimate_sample_mem_gb(input_spec) * batch_size
        fits = required <= eff
        logger.debug(
            "can_fit: required=%.3f, eff=%.3f, batch=%d -> %s",
            required,
            eff,
            batch_size,
            fits,
        )
        return fits

    def load(
        self,
        model_path: str,
        vram_cap_gb: float,
        batch_size: Optional[int] = None,
        safety_margin: float = 0.10,
        input_spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate budget and mark model as loaded.

        In this interface-only shim, loading does not allocate real GPU memory.
        Returns metadata including chosen batch_size.
        Raises ValueError/MemoryError on invalid caps or oversubscription.
        """
        if not model_path:
            raise ValueError("model_path must be non-empty")
        if batch_size is not None and batch_size < 0:
            raise ValueError("batch_size cannot be negative")
        chosen = batch_size if batch_size is not None else self.suggest_batch_size(vram_cap_gb, safety_margin, input_spec)
        if chosen == 0:
            # Allow zero-batch "initialize only" if overhead fits, else fail
            overhead_fits = VRAMBudget(vram_cap_gb, safety_margin).effective_gb() >= self.model_overhead_gb()
            if not overhead_fits:
                raise MemoryError("Model overhead does not fit within VRAM budget")
        if not self.can_fit_batch(chosen, vram_cap_gb, safety_margin, input_spec):
            raise MemoryError("Requested batch_size does not fit in VRAM budget")
        self._do_mark_loaded(model_path, chosen, vram_cap_gb, safety_margin)
        logger.info("Model loaded: path=%s, batch=%d, cap_gb=%.2f, margin=%.2f", model_path, chosen, vram_cap_gb, safety_margin)
        return {
            "model_path": model_path,
            "batch_size": chosen,
            "vram_cap_gb": vram_cap_gb,
            "safety_margin": safety_margin,
        }

    @abstractmethod
    def _do_mark_loaded(self, model_path: str, batch_size: int, vram_cap_gb: float, safety_margin: float) -> None:
        """Concrete adapters should mark themselves as loaded and store state."""

    @abstractmethod
    def unload(self) -> None:
        """Unload model and free resources (no-op in dummy)."""


class DummyModelAdapter(ModelAdapter):
    """A small in-memory adapter with fixed memory characteristics.

    Useful for unit tests and for consumers to integrate the interface without
    bringing any heavy runtime.
    """

    def __init__(self, model_overhead_gb: float = 1.0, per_sample_gb: float = 0.5, name: str = "dummy") -> None:
        if model_overhead_gb < 0:
            raise ValueError("model_overhead_gb must be >= 0")
        if per_sample_gb <= 0:
            raise ValueError("per_sample_gb must be > 0")
        self._overhead = float(model_overhead_gb)
        self._per = float(per_sample_gb)
        self._name = name
        self._loaded = False
        self._state: Dict[str, Any] = {}

    @property
    def loaded(self) -> bool:  # type: ignore[override]
        return self._loaded

    def estimate_sample_mem_gb(self, input_spec: Optional[Dict[str, Any]] = None) -> float:  # type: ignore[override]
        return self._per

    def model_overhead_gb(self) -> float:  # type: ignore[override]
        return self._overhead

    def _do_mark_loaded(self, model_path: str, batch_size: int, vram_cap_gb: float, safety_margin: float) -> None:  # type: ignore[override]
        self._loaded = True
        self._state = {
            "model_path": model_path,
            "batch_size": batch_size,
            "vram_cap_gb": vram_cap_gb,
            "safety_margin": safety_margin,
            "name": self._name,
        }

    def unload(self) -> None:  # type: ignore[override]
        if self._loaded:
            logger.info("Model unloaded: %s", self._state.get("model_path", "?"))
        self._loaded = False
        self._state.clear()


__all__ = [
    "VRAMBudget",
    "ModelAdapter",
    "DummyModelAdapter",
]
