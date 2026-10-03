#!/usr/bin/env python3
"""Runnable password/authority-boundary checks using temporary fixtures only."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
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
        directory = Path(temporary).resolve() / "protected"
        password = "fixture-only-long-password"
        with patch.object(guard, "guard_directory", return_value=directory), \
             patch.object(guard, "is_administrator", return_value=False), \
             patch.object(guard, "password_input") as entry:
            rejected(guard.install)
            entry.assert_not_called()
            assert not directory.exists()
        with patch.object(guard, "guard_directory", return_value=directory), \
             patch.object(guard, "is_administrator", return_value=True), \
             patch.object(guard, "password_input", side_effect=[password, "different-confirmation"]), \
             patch.object(guard, "protect") as protect:
            rejected(guard.install)
            protect.assert_not_called()
            assert not directory.exists()
        with patch.object(guard, "guard_directory", return_value=directory), \
             patch.object(guard, "is_administrator", return_value=True), \
             patch.object(guard, "password_input", return_value=password), \
             patch.object(guard, "protect") as protect, \
             patch.object(guard, "check_protection") as check:
            guard.install()
            assert [call.args[0] for call in protect.call_args_list] == [
                directory, directory / "regression_guard.py", directory / ".lock"]
            check.assert_called_once_with(directory)
            rejected(guard.install)
        saved = (directory / ".lock").read_text(encoding="utf-8")
        assert password not in saved
        record = json.loads(saved)
        assert record["version"] == 1 and len(bytes.fromhex(record["salt"])) == 16
        assert bytes.fromhex(record["hash"]) == guard.password_hash(password, bytes.fromhex(record["salt"]))
        with ExitStack() as stack:
            stack.enter_context(patch.object(guard, "guard_directory", return_value=directory))
            stack.enter_context(patch.object(guard, "__file__", str(directory / "regression_guard.py")))
            admin = stack.enter_context(patch.object(guard, "is_administrator", return_value=False))
            protection = stack.enter_context(patch.object(guard, "check_protection"))
            entry = stack.enter_context(patch.object(guard, "password_input", return_value=password))
            guard.verify()
            entry.return_value = "incorrect-password"
            rejected(guard.verify)
            entry.side_effect = EOFError()
            rejected(guard.verify, EOFError)
            entry.side_effect = KeyboardInterrupt()
            rejected(guard.verify, KeyboardInterrupt)
            entry.side_effect = None
            entry.reset_mock()
            admin.return_value = True
            rejected(guard.verify)
            entry.assert_not_called()
            admin.return_value = False
            protection.side_effect = ValueError("unprotected ACL")
            rejected(guard.verify)
            entry.assert_not_called()
            protection.side_effect = None
            for malformed in ('{}', 'not JSON', '{"version":1,"salt":"00","hash":"00"}',
                              '{"version":1,"salt":null,"hash":"00"}'):
                (directory / ".lock").write_text(malformed, encoding="utf-8")
                rejected(guard.verify, (ValueError, TypeError))
                entry.assert_not_called()
            (directory / ".lock").write_text(saved, encoding="utf-8")
        with patch.object(guard.sys.stdin, "isatty", return_value=False), \
             patch.object(guard.getpass, "getpass") as entry:
            rejected(lambda: guard.password_input("Password: "))
            entry.assert_not_called()
        with patch.object(guard, "powershell") as powershell:
            guard.check_protection(directory)
            acl_script = powershell.call_args.args[0]
            assert "AreAccessRulesProtected" in acl_script and "GetOwner" in acl_script
            assert "2032127" in acl_script and "1179817" in acl_script
            (directory / ".lock").unlink()
            powershell.reset_mock()
            rejected(lambda: guard.check_protection(directory))
            powershell.assert_not_called()
        with ExitStack() as stack:
            stack.enter_context(patch.object(guard, "os", SimpleNamespace(name="nt")))
            stack.enter_context(patch.object(guard, "guard_directory", return_value=directory))
            admin = stack.enter_context(patch.object(guard, "is_administrator", return_value=False))
            protection = stack.enter_context(patch.object(guard, "check_protection"))
            run = stack.enter_context(patch.object(guard.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)))
            guard.authorize_full_regression()
            command = run.call_args.args[0]
            assert command[1:] == ["-I", "-B", str(directory / "regression_guard.py"), "--verify"]
            assert not run.call_args.kwargs, "password must not travel through arguments, input or environment"
            run.return_value = subprocess.CompletedProcess([], 2)
            rejected(guard.authorize_full_regression)
            run.reset_mock()
            protection.side_effect = ValueError("unprotected")
            rejected(guard.authorize_full_regression)
            run.assert_not_called()
            protection.side_effect = None
            admin.return_value = True
            rejected(guard.authorize_full_regression)
            run.assert_not_called()
    print("regression_guard: PASS (fixture authentication, ACL boundary, failure and console checks)")


if __name__ == "__main__":
    main()
