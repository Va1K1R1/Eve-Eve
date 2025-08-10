# Vision package (local, dependency-free)
# Provides offline OCR stubs for unit-test purposes.

from .ocr import OCR, LocalOCR  # re-export for convenience

__all__ = ["OCR", "LocalOCR"]
