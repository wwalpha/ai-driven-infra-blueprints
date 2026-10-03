#!/usr/bin/env python3
"""Runnable repo .lock checks using temporary fixtures only."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import regression_guard as guard


def rejected(operation, exception=ValueError):
    try:
        operation()
    except exception:
        return
    raise AssertionError("unsafe authorization/registration was accepted")


def main():
    with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
        root = Path(temporary).resolve()
        password = "fixture-only-long-password"
        lock = root / ".lock"
        with patch.object(guard, "__file__", str(root / "framework/scripts/regression_guard.py")), \
             patch.object(guard, "password_input", side_effect=[password, "different-confirmation"]):
            rejected(guard.install)
            assert not lock.exists()
        with patch.object(guard, "__file__", str(root / "framework/scripts/regression_guard.py")), \
             patch.object(guard, "password_input", return_value=password) as entry:
            guard.install()
            assert [path.name for path in root.iterdir()] == [".lock"], "registration created extra files/directories"
            saved = lock.read_text(encoding="utf-8")
            assert password not in saved
            entry.reset_mock()
            rejected(guard.install)
            entry.assert_not_called()
            assert lock.read_text(encoding="utf-8") == saved, "registration overwrote existing .lock"
        record = json.loads(saved)
        assert record["version"] == 1 and len(bytes.fromhex(record["salt"])) == 16
        assert bytes.fromhex(record["hash"]) == guard.password_hash(password, bytes.fromhex(record["salt"]))
        with patch.object(guard, "password_input", return_value=password) as entry:
            guard.verify(root)
            entry.return_value = "incorrect-password"
            rejected(lambda: guard.verify(root))
            entry.side_effect = EOFError()
            rejected(lambda: guard.verify(root), EOFError)
            entry.side_effect = KeyboardInterrupt()
            rejected(lambda: guard.verify(root), KeyboardInterrupt)
            entry.side_effect = None
            entry.reset_mock()
            for malformed in ('{}', 'not JSON', '{"version":1,"salt":"00","hash":"00"}',
                              '{"version":1,"salt":null,"hash":"00"}'):
                lock.write_text(malformed, encoding="utf-8")
                rejected(lambda: guard.verify(root))
                entry.assert_not_called()
            lock.unlink()
            rejected(lambda: guard.verify(root))
            entry.assert_not_called()
            lock.write_text(saved, encoding="utf-8")
            with patch.object(guard, "os", SimpleNamespace(name="nt")):
                entry.return_value = password
                guard.authorize_full_regression(root)
                entry.return_value = "incorrect-password"
                rejected(lambda: guard.authorize_full_regression(root))
            # Every invocation prompts again; no reusable authorization flag/state.
            assert entry.call_count == 2
        with patch.object(guard.sys.stdin, "isatty", return_value=False), \
             patch.object(guard.getpass, "getpass") as entry:
            rejected(lambda: guard.password_input("Password: "))
            entry.assert_not_called()
        with patch.object(guard.sys.stdin, "isatty", return_value=True), \
             patch.object(guard.getpass, "getpass", side_effect=EOFError()):
            rejected(lambda: guard.password_input("Password: "))
        for error, visible in ((guard.GuardError("repo .lock already exists"), "repo .lock already exists"),
                               (ValueError("fixture-private-password-and-hash"), "Check repo .lock")):
            output = io.StringIO()
            with patch.object(guard.sys, "argv", ["regression_guard.py", "--install"]), \
                 patch.object(guard, "install", side_effect=error), redirect_stderr(output):
                assert guard.main() == 2
            assert visible in output.getvalue() and "fixture-private-password-and-hash" not in output.getvalue()
    print("regression_guard: PASS (single repo .lock, preserved registration, password matching and failure checks)")


if __name__ == "__main__":
    main()
