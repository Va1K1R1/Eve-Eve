import io
import os
import sys
import json
import unittest
import contextlib

# Ensure src is importable when running tests from repo root
THIS_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(THIS_DIR, "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from security.crypto import AES256CBC, pbkdf2_sha256, encrypt_with_password, decrypt_with_password, DPAPIProtector  # noqa: E402
from security.cli_crypto import main as cli_main  # noqa: E402


class SecurityTests(unittest.TestCase):
    def test_aes256_cbc_nist_vectors(self):
        # NIST SP 800-38A F.2.5 CBC-AES256
        key_hex = (
            "603deb1015ca71be2b73aef0857d7781"
            "1f352c073b6108d72d9810a30914dff4"
        )
        iv_hex = "000102030405060708090a0b0c0d0e0f"
        pt_hex = (
            "6bc1bee22e409f96e93d7e117393172a"
            "ae2d8a571e03ac9c9eb76fac45af8e51"
            "30c81c46a35ce411e5fbc1191a0a52ef"
            "f69f2445df4f9b17ad2b417be66c3710"
        )
        ct_expected_hex = (
            "f58c4c04d6e5f1ba779eabfb5f7bfbd6"
            "9cfc4e967edb808d679f777bc6702c7d"
            "39f23369a9d9bacfa530e26304231461"
            "b2eb05e2c39be9fcda6c19078c6a9d1b"
        )
        key = bytes.fromhex(key_hex)
        iv = bytes.fromhex(iv_hex)
        pt = bytes.fromhex(pt_hex)
        ct_expected = bytes.fromhex(ct_expected_hex)

        aes = AES256CBC(key)
        # Manual CBC without padding
        ct_out = bytearray()
        prev = iv
        for i in range(0, len(pt), 16):
            block = pt[i:i+16]
            x = bytes(a ^ b for a, b in zip(block, prev))
            enc = aes.encrypt_block(x)
            ct_out.extend(enc)
            prev = enc
        self.assertEqual(bytes(ct_out), ct_expected)

        # Now decrypt manually
        out = bytearray()
        prev = iv
        for i in range(0, len(ct_expected), 16):
            block = ct_expected[i:i+16]
            dec = aes.decrypt_block(block)
            out.extend(bytes(a ^ b for a, b in zip(dec, prev)))
            prev = block
        self.assertEqual(bytes(out), pt)

    def test_pbkdf2_and_password_roundtrip(self):
        password = "pass"
        salt = bytes.fromhex("00112233aabbccdd00112233aabbccdd")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        iterations = 10000  # keep tests fast
        # Determinism vs hashlib
        dk1 = pbkdf2_sha256(password.encode("utf-8"), salt, iterations, 32)
        import hashlib as _hashlib
        dk2 = _hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
        self.assertEqual(dk1, dk2)
        # Roundtrip
        plaintext = b"hello"
        ct = encrypt_with_password(plaintext, password, salt, iv, iterations=iterations)
        pt2 = decrypt_with_password(ct, password, salt, iv, iterations=iterations)
        self.assertEqual(pt2, plaintext)

    def test_dpapi_roundtrip_windows_only(self):
        if sys.platform != "win32":
            self.skipTest("DPAPI only on Windows")
        dp = DPAPIProtector()
        secret = b"secret-bytes"
        blob = dp.protect(secret)
        self.assertIsInstance(blob, (bytes, bytearray))
        back = dp.unprotect(blob)
        self.assertEqual(back, secret)

    def test_cli_aes_and_dpapi(self):
        # AES CLI
        buf = io.StringIO()
        password = "pass"
        salt_hex = "00112233AABBCCDD00112233AABBCCDD"
        iv_hex = "000102030405060708090A0B0C0D0E0F"
        with contextlib.redirect_stdout(buf):
            rc = cli_main([
                "--mode", "aes", "--op", "encrypt", "--password", password,
                "--salt", salt_hex, "--iv", iv_hex, "--in", "hello", "--json",
            ])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertIn("ciphertext", out)
        ct_hex = out["ciphertext"]
        # Decrypt
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc = cli_main([
                "--mode", "aes", "--op", "decrypt", "--password", password,
                "--salt", salt_hex, "--iv", iv_hex, "--in_hex", ct_hex, "--json",
            ])
        self.assertEqual(rc, 0)
        out2 = json.loads(buf2.getvalue())
        self.assertEqual(out2.get("plaintext"), "hello")

        # DPAPI CLI (Windows-only)
        if sys.platform == "win32":
            buf3 = io.StringIO()
            with contextlib.redirect_stdout(buf3):
                rc = cli_main(["--mode", "dpapi", "--op", "encrypt", "--in", "secret", "--json"]) 
            self.assertEqual(rc, 0)
            out3 = json.loads(buf3.getvalue())
            self.assertIn("blob", out3)
            blob_hex = out3["blob"]

            buf4 = io.StringIO()
            with contextlib.redirect_stdout(buf4):
                rc = cli_main(["--mode", "dpapi", "--op", "decrypt", "--in_hex", blob_hex, "--json"]) 
            self.assertEqual(rc, 0)
            out4 = json.loads(buf4.getvalue())
            self.assertEqual(out4.get("plaintext"), "secret")


if __name__ == "__main__":
    unittest.main(verbosity=2)
