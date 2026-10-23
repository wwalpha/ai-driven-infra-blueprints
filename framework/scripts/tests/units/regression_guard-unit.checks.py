#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from support.regression_guard_fixtures import (
    Path,
    guard,
    io,
    patch,
    redirect_stderr,
    rejected,
    sys,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_password_input_diagnostics():
    with patch.object(guard.sys, "argv", ["regression_guard.py", "--verify"]), \
         patch.object(guard, "verify") as verify:
        assert guard.main() == 0
        verify.assert_called_once_with(Path.cwd().resolve())
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



if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
