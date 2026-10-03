#!/usr/bin/env python3
"""Store a password hash in the repository's .lock; gate Windows full regression."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import warnings


ITERATIONS = 600_000


class GuardError(ValueError):
    """A fixed public diagnostic containing no password or registration data."""


def password_input(prompt):
    if not sys.stdin.isatty():
        raise GuardError("full regression requires password entry in a human-operated console")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (EOFError, getpass.GetPassWarning):
            raise GuardError("password input unavailable or cancelled; no checks started") from None


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def install():
    lock = Path(__file__).resolve().parents[2] / ".lock"
    if lock.exists() or lock.is_symlink():
        raise GuardError("repo .lock already exists; registration will not overwrite it")
    password = password_input("New full-regression password (at least 12 characters): ")
    if len(password) < 12 or len(password.encode("utf-8")) > 1024:
        raise GuardError("password must contain at least 12 characters and at most 1024 UTF-8 bytes")
    if not hmac.compare_digest(password.encode("utf-8"), password_input("Confirm password: ").encode("utf-8")):
        raise GuardError("password confirmation does not match")
    salt = secrets.token_bytes(16)
    record = {"version": 1, "salt": salt.hex(), "hash": password_hash(password, salt).hex()}
    with lock.open("x", encoding="utf-8") as stream:
        try:
            stream.write(json.dumps(record) + "\n")
        except BaseException:
            stream.close()
            lock.unlink()
            raise
    print(f"Full-regression password registered: {lock}")


def verify(root):
    lock = root / ".lock"
    if not lock.is_file():
        raise GuardError("repo .lock is missing; run regression_guard.py --install")
    if lock.is_symlink() or getattr(lock.stat(), "st_file_attributes", 0) & 0x400:
        raise GuardError("repo .lock must be a regular file")
    try:
        record = json.loads(lock.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or set(record) != {"version", "salt", "hash"} or
                type(record["version"]) is not int or record["version"] != 1):
            raise ValueError()
        salt, expected = bytes.fromhex(record["salt"]), bytes.fromhex(record["hash"])
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise GuardError("invalid repo .lock registration") from None
    password = password_input("Full regression password: ")
    if len(password.encode("utf-8")) > 1024 or not hmac.compare_digest(password_hash(password, salt), expected):
        raise GuardError("full regression password does not match; no checks started")
    print("Full regression authorized for this invocation.")


def authorize_full_regression(root):
    # Windows protection remains the requested scope; no persistent unlock state.
    if os.name == "nt":
        verify(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true", help="Register a password in repo .lock; no administrator rights needed")
    mode.add_argument("--verify", action="store_true", help="Interactively verify this repo's .lock")
    args = parser.parse_args()
    try:
        install() if args.install else verify(Path(__file__).resolve().parents[2])
        return 0
    except KeyboardInterrupt:
        print("Regression authorization cancelled; no checks started.", file=sys.stderr)
        return 130
    except GuardError as error:
        print(f"Regression authorization failed: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, EOFError, getpass.GetPassWarning):
        print("Regression authorization failed. Check repo .lock and console/password input.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
