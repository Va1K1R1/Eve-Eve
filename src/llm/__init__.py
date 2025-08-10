"""LLM package exposing local, offline wrappers.

This module provides lightweight, deterministic wrappers for local LLM-like
behavior without external dependencies or network calls.
"""

from .wrappers import LLM, LocalLLM  # noqa: F401
