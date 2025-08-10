"""
Local security utilities (educational).

This package provides:
- AES-256-CBC (pure Python) with PKCS#7 padding for educational purposes.
- PBKDF2-HMAC-SHA256 key derivation (via hashlib, stdlib only).
- Windows DPAPI integration (CryptProtectData/CryptUnprotectData) via ctypes.

DISCLAIMER: The AES implementation is for educational/testing use only and
must not be used as a substitute for vetted cryptographic libraries in
production. Prefer platform crypto (e.g., Windows CNG) or well-reviewed
libraries when policy permits.
"""

from .crypto import (
    AES256CBC,
    pbkdf2_sha256,
    encrypt_with_password,
    decrypt_with_password,
    DPAPIProtector,
)

__all__ = [
    "AES256CBC",
    "pbkdf2_sha256",
    "encrypt_with_password",
    "decrypt_with_password",
    "DPAPIProtector",
]
