from __future__ import annotations

import argparse
import json
from typing import List, Optional

from .crypto import AES256CBC, pbkdf2_sha256, encrypt_with_password, decrypt_with_password, DPAPIProtector


def _bhex(s: str) -> bytes:
    try:
        return bytes.fromhex(s)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"invalid hex: {e}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local crypto utilities (educational)")
    sub = p.add_subparsers(dest="mode", required=False)

    # Flat args to match existing CLI pattern in repo
    p.add_argument("--mode", choices=["aes", "dpapi"], required=True)
    p.add_argument("--op", choices=["encrypt", "decrypt"], required=True)
    p.add_argument("--json", action="store_true", help="Output JSON to stdout")

    # Input forms
    p.add_argument("--in", dest="in_text", type=str, help="Input text (UTF-8)")
    p.add_argument("--in_hex", dest="in_hex", type=str, help="Input as hex bytes")

    # AES specific
    p.add_argument("--key", type=str, help="Raw AES-256 key in hex (32 bytes)")
    p.add_argument("--password", type=str, help="Password for PBKDF2-HMAC-SHA256")
    p.add_argument("--salt", type=str, help="Salt in hex (recommended 16+ bytes)")
    p.add_argument("--iv", type=str, help="IV in hex (16 bytes)")
    p.add_argument("--iterations", type=int, default=200_000, help="PBKDF2 iterations (default 200000)")

    # DPAPI specific
    p.add_argument("--scope", choices=["current_user", "local_machine"], default="current_user")

    return p


def _get_input_bytes(args: argparse.Namespace) -> bytes:
    if args.in_hex is not None:
        return _bhex(args.in_hex)
    if args.in_text is not None:
        return args.in_text.encode("utf-8")
    raise SystemExit(2)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    mode = args.mode
    op = args.op

    if mode == "aes":
        if op == "encrypt":
            pt = _get_input_bytes(args)
            if args.key:
                key = _bhex(args.key)
                if len(key) != 32:
                    print(json.dumps({"error": "AES key must be 32 bytes (hex length 64)"}) if args.json else "Error: AES key must be 32 bytes", flush=True)
                    return 2
                iv = _bhex(args.iv) if args.iv else b""
                if len(iv) != 16:
                    print(json.dumps({"error": "IV must be 16 bytes"}) if args.json else "Error: IV must be 16 bytes", flush=True)
                    return 2
                aes = AES256CBC(key)
                ct = aes.encrypt_cbc(iv, pt)
            else:
                if not (args.password and args.salt and args.iv):
                    print(json.dumps({"error": "--password, --salt, and --iv are required for password mode"}) if args.json else "Error: missing --password/--salt/--iv", flush=True)
                    return 2
                salt = _bhex(args.salt)
                iv = _bhex(args.iv)
                if len(iv) != 16:
                    print(json.dumps({"error": "IV must be 16 bytes"}) if args.json else "Error: IV must be 16 bytes", flush=True)
                    return 2
                ct = encrypt_with_password(pt, args.password, salt, iv, iterations=args.iterations)
            out = {"mode": "aes", "op": "encrypt", "ciphertext": ct.hex()}
            if args.json:
                print(json.dumps(out))
            else:
                print(f"ciphertext={out['ciphertext']}")
            return 0
        else:  # decrypt
            ct = _get_input_bytes(args)
            if args.key:
                key = _bhex(args.key)
                if len(key) != 32:
                    print(json.dumps({"error": "AES key must be 32 bytes (hex length 64)"}) if args.json else "Error: AES key must be 32 bytes", flush=True)
                    return 2
                iv = _bhex(args.iv) if args.iv else b""
                if len(iv) != 16:
                    print(json.dumps({"error": "IV must be 16 bytes"}) if args.json else "Error: IV must be 16 bytes", flush=True)
                    return 2
                aes = AES256CBC(key)
                try:
                    pt = aes.decrypt_cbc(iv, ct)
                except Exception as e:
                    if args.json:
                        print(json.dumps({"error": str(e)}))
                    else:
                        print(f"Error: {e}")
                    return 1
            else:
                if not (args.password and args.salt and args.iv):
                    print(json.dumps({"error": "--password, --salt, and --iv are required for password mode"}) if args.json else "Error: missing --password/--salt/--iv", flush=True)
                    return 2
                salt = _bhex(args.salt)
                iv = _bhex(args.iv)
                if len(iv) != 16:
                    print(json.dumps({"error": "IV must be 16 bytes"}) if args.json else "Error: IV must be 16 bytes", flush=True)
                    return 2
                try:
                    pt = decrypt_with_password(ct, args.password, salt, iv, iterations=args.iterations)
                except Exception as e:
                    if args.json:
                        print(json.dumps({"error": str(e)}))
                    else:
                        print(f"Error: {e}")
                    return 1
            out = {"mode": "aes", "op": "decrypt", "plaintext": pt.decode("utf-8", errors="strict") if args.in_hex is not None else pt.decode("utf-8", errors="replace")}
            if args.json:
                print(json.dumps(out))
            else:
                print(f"plaintext={out['plaintext']}")
            return 0

    elif mode == "dpapi":
        data = _get_input_bytes(args)
        try:
            dp = DPAPIProtector(scope=args.scope)
        except NotImplementedError as e:
            if args.json:
                print(json.dumps({"error": str(e)}))
            else:
                print(f"Error: {e}")
            return 2
        if op == "encrypt":
            blob = dp.protect(data)
            out = {"mode": "dpapi", "op": "encrypt", "blob": blob.hex()}
            if args.json:
                print(json.dumps(out))
            else:
                print(f"blob={out['blob']}")
            return 0
        else:
            try:
                pt = dp.unprotect(data)
            except Exception as e:
                if args.json:
                    print(json.dumps({"error": str(e)}))
                else:
                    print(f"Error: {e}")
                return 1
            out = {"mode": "dpapi", "op": "decrypt", "plaintext": pt.decode("utf-8", errors="replace")}
            if args.json:
                print(json.dumps(out))
            else:
                print(f"plaintext={out['plaintext']}")
            return 0

    else:
        if args.json:
            print(json.dumps({"error": "unknown mode"}))
        else:
            print("Error: unknown mode")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
