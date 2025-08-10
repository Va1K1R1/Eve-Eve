"""
Model package: interface-only components for VRAM-aware model loading (Kanban T-003).

This package is stdlib-only and contains no heavy dependencies. It exposes a
simple adapter interface and a dummy implementation suitable for unit tests
and future extension.
"""
from __future__ import annotations

__all__ = [
    "loading",
]
