"""
Educational AES-256-CBC, PBKDF2-HMAC-SHA256, and Windows DPAPI utilities.

DISCLAIMER: This AES implementation is for educational and testing purposes
only. Do not use it in production. Prefer vetted cryptography libraries or
platform crypto (e.g., Windows CNG) when policy permits.

Public API:
- AES256CBC: block cipher with CBC mode + PKCS#7 padding
- pbkdf2_sha256(password: bytes, salt: bytes, iterations: int, dklen: int = 32) -> bytes
- encrypt_with_password(plaintext: bytes, password: str, salt: bytes, iv: bytes, iterations: int = 200_000) -> bytes
- decrypt_with_password(ciphertext: bytes, password: str, salt: bytes, iv: bytes, iterations: int = 200_000) -> bytes
- DPAPIProtector: Windows DPAPI wrapper using ctypes
"""
from __future__ import annotations

from dataclasses import dataclass
import sys
import ctypes
import ctypes.wintypes as wintypes
from typing import Optional
import hashlib

# ---------------------------
# AES-256 implementation
# ---------------------------

# Rijndael S-box
_SBOX = [
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
]

_INV_SBOX = [0] * 256
for i, v in enumerate(_SBOX):
    _INV_SBOX[v] = i

_RCON = [
    0x00000000,
    0x01000000, 0x02000000, 0x04000000, 0x08000000,
    0x10000000, 0x20000000, 0x40000000, 0x80000000,
    0x1B000000, 0x36000000,
    0x6C000000, 0xD8000000, 0xAB000000, 0x4D000000, 0x9A000000,
]


def _sub_word(w: int) -> int:
    return (
        (_SBOX[(w >> 24) & 0xFF] << 24)
        | (_SBOX[(w >> 16) & 0xFF] << 16)
        | (_SBOX[(w >> 8) & 0xFF] << 8)
        | (_SBOX[w & 0xFF])
    )


def _rot_word(w: int) -> int:
    return ((w << 8) & 0xFFFFFFFF) | ((w >> 24) & 0xFF)


@dataclass
class AES256CBC:
    key: bytes

    def __post_init__(self):
        if not isinstance(self.key, (bytes, bytearray)):
            raise TypeError("key must be bytes")
        if len(self.key) != 32:
            raise ValueError("AES-256 requires 32-byte key")
        self._round_keys = self._expand_key(self.key)

    # Key expansion for AES-256 to generate 15 round keys (0..14), each 16 bytes
    @staticmethod
    def _expand_key(key: bytes):
        Nk = 8
        Nr = 14
        Nb = 4
        words = [0] * (Nb * (Nr + 1))  # 60
        # initial words from key
        for i in range(Nk):
            words[i] = int.from_bytes(key[4*i:4*i+4], 'big')
        for i in range(Nk, Nb * (Nr + 1)):
            temp = words[i - 1]
            if i % Nk == 0:
                temp = _sub_word(_rot_word(temp)) ^ _RCON[i // Nk]
            elif i % Nk == 4:
                temp = _sub_word(temp)
            words[i] = (words[i - Nk] ^ temp) & 0xFFFFFFFF
        # pack round keys
        round_keys = []
        for r in range(Nr + 1):
            rk = b"".join(words[4*r + c].to_bytes(4, 'big') for c in range(4))
            round_keys.append(rk)
        return round_keys

    @staticmethod
    def _add_round_key(state: bytearray, round_key: bytes):
        for i in range(16):
            state[i] ^= round_key[i]

    @staticmethod
    def _sub_bytes(state: bytearray):
        for i in range(16):
            state[i] = _SBOX[state[i]]

    @staticmethod
    def _inv_sub_bytes(state: bytearray):
        for i in range(16):
            state[i] = _INV_SBOX[state[i]]

    @staticmethod
    def _shift_rows(state: bytearray):
        # state is 4x4 bytes in column-major order
        # rows are indices [0,4,8,12], [1,5,9,13], [2,6,10,14], [3,7,11,15]
        s = list(state)
        state[1], state[5], state[9], state[13] = s[5], s[9], s[13], s[1]
        state[2], state[6], state[10], state[14] = s[10], s[14], s[2], s[6]
        state[3], state[7], state[11], state[15] = s[15], s[3], s[7], s[11]

    @staticmethod
    def _inv_shift_rows(state: bytearray):
        s = list(state)
        state[1], state[5], state[9], state[13] = s[13], s[1], s[5], s[9]
        state[2], state[6], state[10], state[14] = s[10], s[14], s[2], s[6]
        state[3], state[7], state[11], state[15] = s[7], s[11], s[15], s[3]

    @staticmethod
    def _xtime(a: int) -> int:
        return ((a << 1) & 0xFF) ^ (0x1B if (a & 0x80) else 0x00)

    @classmethod
    def _mix_single_column(cls, a):
        # Mix one column (4 bytes)
        t = a[0] ^ a[1] ^ a[2] ^ a[3]
        u = a[0]
        a[0] ^= t ^ cls._xtime(a[0] ^ a[1])
        a[1] ^= t ^ cls._xtime(a[1] ^ a[2])
        a[2] ^= t ^ cls._xtime(a[2] ^ a[3])
        a[3] ^= t ^ cls._xtime(a[3] ^ u)

    @classmethod
    def _mix_columns(cls, state: bytearray):
        for c in range(4):
            col = [state[4 * c + r] for r in range(4)]
            cls._mix_single_column(col)
            for r in range(4):
                state[4 * c + r] = col[r]

    @staticmethod
    def _mul(a: int, b: int) -> int:
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xFF
            if hi:
                a ^= 0x1B
            b >>= 1
        return p

    @classmethod
    def _inv_mix_columns(cls, state: bytearray):
        for c in range(4):
            s0 = state[4 * c + 0]
            s1 = state[4 * c + 1]
            s2 = state[4 * c + 2]
            s3 = state[4 * c + 3]
            state[4 * c + 0] = (
                cls._mul(s0, 0x0E) ^ cls._mul(s1, 0x0B) ^ cls._mul(s2, 0x0D) ^ cls._mul(s3, 0x09)
            )
            state[4 * c + 1] = (
                cls._mul(s0, 0x09) ^ cls._mul(s1, 0x0E) ^ cls._mul(s2, 0x0B) ^ cls._mul(s3, 0x0D)
            )
            state[4 * c + 2] = (
                cls._mul(s0, 0x0D) ^ cls._mul(s1, 0x09) ^ cls._mul(s2, 0x0E) ^ cls._mul(s3, 0x0B)
            )
            state[4 * c + 3] = (
                cls._mul(s0, 0x0B) ^ cls._mul(s1, 0x0D) ^ cls._mul(s2, 0x09) ^ cls._mul(s3, 0x0E)
            )

    def encrypt_block(self, block: bytes) -> bytes:
        if len(block) != 16:
            raise ValueError("block must be 16 bytes")
        state = bytearray(block)
        self._add_round_key(state, self._round_keys[0])
        for rnd in range(1, 14):
            self._sub_bytes(state)
            self._shift_rows(state)
            self._mix_columns(state)
            self._add_round_key(state, self._round_keys[rnd])
        # final round
        self._sub_bytes(state)
        self._shift_rows(state)
        self._add_round_key(state, self._round_keys[14])
        return bytes(state)

    def decrypt_block(self, block: bytes) -> bytes:
        if len(block) != 16:
            raise ValueError("block must be 16 bytes")
        state = bytearray(block)
        # Initial AddRoundKey with last round key
        self._add_round_key(state, self._round_keys[14])
        # For rounds 13 down to 1: InvShiftRows, InvSubBytes, AddRoundKey, InvMixColumns
        for rnd in range(13, 0, -1):
            self._inv_shift_rows(state)
            self._inv_sub_bytes(state)
            self._add_round_key(state, self._round_keys[rnd])
            self._inv_mix_columns(state)
        # Final: InvShiftRows, InvSubBytes, AddRoundKey with round 0
        self._inv_shift_rows(state)
        self._inv_sub_bytes(state)
        self._add_round_key(state, self._round_keys[0])
        return bytes(state)

    @staticmethod
    def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
        pad_len = block_size - (len(data) % block_size)
        if pad_len == 0:
            pad_len = block_size
        return data + bytes([pad_len] * pad_len)

    @staticmethod
    def _pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
        if not data or len(data) % block_size != 0:
            raise ValueError("invalid padded data length")
        pad_len = data[-1]
        if pad_len < 1 or pad_len > block_size:
            raise ValueError("invalid padding")
        if data[-pad_len:] != bytes([pad_len] * pad_len):
            raise ValueError("invalid padding")
        return data[:-pad_len]

    def encrypt_cbc(self, iv: bytes, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("plaintext must be bytes")
        if len(iv) != 16:
            raise ValueError("IV must be 16 bytes")
        pt = self._pkcs7_pad(bytes(plaintext), 16)
        out = bytearray()
        prev = iv
        for i in range(0, len(pt), 16):
            block = bytes(a ^ b for a, b in zip(pt[i:i+16], prev))
            enc = self.encrypt_block(block)
            out.extend(enc)
            prev = enc
        return bytes(out)

    def decrypt_cbc(self, iv: bytes, ciphertext: bytes) -> bytes:
        if not isinstance(ciphertext, (bytes, bytearray)):
            raise TypeError("ciphertext must be bytes")
        if len(iv) != 16:
            raise ValueError("IV must be 16 bytes")
        if len(ciphertext) % 16 != 0:
            raise ValueError("ciphertext length must be multiple of 16")
        out = bytearray()
        prev = iv
        for i in range(0, len(ciphertext), 16):
            block = ciphertext[i:i+16]
            dec = self.decrypt_block(block)
            out.extend(bytes(a ^ b for a, b in zip(dec, prev)))
            prev = block
        return self._pkcs7_unpad(bytes(out), 16)


# ---------------------------
# PBKDF2-HMAC-SHA256 helper
# ---------------------------

def pbkdf2_sha256(password: bytes, salt: bytes, iterations: int, dklen: int = 32) -> bytes:
    if not isinstance(password, (bytes, bytearray)):
        raise TypeError("password must be bytes")
    if not isinstance(salt, (bytes, bytearray)):
        raise TypeError("salt must be bytes")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=dklen)


def encrypt_with_password(plaintext: bytes, password: str, salt: bytes, iv: bytes, iterations: int = 200_000) -> bytes:
    key = pbkdf2_sha256(password.encode("utf-8"), salt, iterations, 32)
    aes = AES256CBC(key)
    return aes.encrypt_cbc(iv, plaintext)


def decrypt_with_password(ciphertext: bytes, password: str, salt: bytes, iv: bytes, iterations: int = 200_000) -> bytes:
    key = pbkdf2_sha256(password.encode("utf-8"), salt, iterations, 32)
    aes = AES256CBC(key)
    return aes.decrypt_cbc(iv, ciphertext)


# ---------------------------
# Windows DPAPI via ctypes
# ---------------------------

class DPAPIProtector:
    """Windows DPAPI wrapper using CryptProtectData / CryptUnprotectData.

    On non-Windows platforms, instantiation will raise NotImplementedError.
    """

    CRYPTPROTECT_LOCAL_MACHINE = 0x4

    def __init__(self, scope: str = "current_user") -> None:
        if sys.platform != "win32":
            raise NotImplementedError("DPAPI is only available on Windows")
        self.flags = 0
        if scope == "local_machine":
            self.flags |= self.CRYPTPROTECT_LOCAL_MACHINE
        # Load functions
        self._crypt32 = ctypes.WinDLL("Crypt32.dll")
        self._kernel32 = ctypes.WinDLL("Kernel32.dll")

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        self.DATA_BLOB = DATA_BLOB
        self._CryptProtectData = self._crypt32.CryptProtectData
        self._CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        self._CryptProtectData.restype = wintypes.BOOL

        self._CryptUnprotectData = self._crypt32.CryptUnprotectData
        self._CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        self._CryptUnprotectData.restype = wintypes.BOOL

        self._LocalFree = self._kernel32.LocalFree
        self._LocalFree.argtypes = [wintypes.HLOCAL]
        self._LocalFree.restype = wintypes.HLOCAL

    def _bytes_to_blob(self, b: Optional[bytes]):
        if b is None or len(b) == 0:
            return self.DATA_BLOB(0, None)
        arr = (ctypes.c_ubyte * len(b))(*b)
        return self.DATA_BLOB(len(b), ctypes.cast(arr, ctypes.POINTER(ctypes.c_ubyte)))

    def protect(self, data: bytes, entropy: Optional[bytes] = None) -> bytes:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        in_blob = self._bytes_to_blob(bytes(data))
        ent_blob = self._bytes_to_blob(entropy)
        out_blob = self.DATA_BLOB()
        if not self._CryptProtectData(ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, self.flags, ctypes.byref(out_blob)):
            raise OSError("CryptProtectData failed")
        try:
            res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return res
        finally:
            if out_blob.pbData:
                self._LocalFree(out_blob.pbData)

    def unprotect(self, blob: bytes, entropy: Optional[bytes] = None) -> bytes:
        if not isinstance(blob, (bytes, bytearray)):
            raise TypeError("blob must be bytes")
        in_blob = self._bytes_to_blob(bytes(blob))
        ent_blob = self._bytes_to_blob(entropy)
        out_blob = self.DATA_BLOB()
        descr = wintypes.LPWSTR()
        if not self._CryptUnprotectData(ctypes.byref(in_blob), ctypes.byref(descr), ctypes.byref(ent_blob), None, None, self.flags, ctypes.byref(out_blob)):
            raise OSError("CryptUnprotectData failed")
        try:
            res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return res
        finally:
            if out_blob.pbData:
                self._LocalFree(out_blob.pbData)
            # Free description if provided
            if descr:
                self._LocalFree(descr)
