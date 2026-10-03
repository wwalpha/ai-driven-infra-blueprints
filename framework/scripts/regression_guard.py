#!/usr/bin/env python3
"""Windows full-regression password gate; install its verifier as administrator."""

from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import warnings


ITERATIONS = 600_000
SDDL = "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)"


def windows_directory(function, *arguments):
    buffer = ctypes.create_unicode_buffer(32768)
    if function(*arguments, buffer, len(buffer)) == 0:
        raise OSError("cannot locate Windows system directory")
    return Path(buffer.value)


def guard_directory():
    if os.name != "nt":
        raise ValueError("regression password registration requires Windows")
    buffer = ctypes.create_unicode_buffer(260)
    # CSIDL_COMMON_APPDATA comes from Windows, never an environment override.
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x23, None, 0, buffer) != 0:
        raise OSError("cannot locate Windows common application data")
    return Path(buffer.value) / "BlueprintRegressionGuard"


def is_administrator():
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def powershell(script):
    system = windows_directory(ctypes.windll.kernel32.GetSystemDirectoryW)
    command = [str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile",
               "-NonInteractive", "-EncodedCommand",
               base64.b64encode(("$ErrorActionPreference='Stop'; " + script).encode("utf-16-le")).decode("ascii")]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise ValueError("Windows regression guard ACL check/configuration failed")


def ps_path(path):
    return "'" + str(path).replace("'", "''") + "'"


def protect(path):
    security_type = "DirectorySecurity" if path.is_dir() else "FileSecurity"
    powershell(f"$acl=New-Object System.Security.AccessControl.{security_type}; "
               f"$acl.SetSecurityDescriptorSddlForm('{SDDL}'); "
               f"Set-Acl -LiteralPath {ps_path(path)} -AclObject $acl")


def check_protection(directory):
    paths = [directory, directory / "regression_guard.py", directory / ".lock"]
    if not directory.is_dir() or not all(path.is_file() for path in paths[1:]):
        raise ValueError("full regression is locked: administrator registration is missing")
    # Reject redirects, including a junction on any ancestor of the protected files.
    for path in {*paths, *directory.parents}:
        if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("regression guard path must not contain reparse points")
    powershell("$paths=@(" + ",".join(ps_path(path) for path in paths) + "); " + """
foreach($path in $paths) {
    $acl=Get-Acl -LiteralPath $path;
    $owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;
    if($owner -notin @('S-1-5-32-544','S-1-5-18') -or !$acl.AreAccessRulesProtected) {
        throw 'unprotected owner/inheritance';
    }
    $rules=$acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]);
    $expected=@{'S-1-5-32-544'=2032127; 'S-1-5-18'=2032127; 'S-1-5-32-545'=1179817};
    if($rules.Count -ne 3) { throw 'unexpected ACL'; }
    foreach($rule in $rules) {
        $sid=$rule.IdentityReference.Value;
        if(!$expected.ContainsKey($sid) -or $rule.AccessControlType -ne 'Allow' -or
           [int64]$rule.FileSystemRights -ne $expected[$sid]) { throw 'unexpected permission'; }
        $expected.Remove($sid);
    }
    if($expected.Count) { throw 'missing permission'; }
}
""")


def password_input(prompt):
    if not sys.stdin.isatty():
        raise ValueError("full regression requires password entry in a human-operated console")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)


def install():
    directory = guard_directory()
    if not is_administrator():
        raise ValueError("only a human-operated administrator console may register the guard")
    if directory.exists():
        raise ValueError("guard already exists; administrator removal is required before re-registration")
    password = password_input("New full-regression password (at least 12 characters): ")
    if len(password) < 12 or len(password.encode("utf-8")) > 1024:
        raise ValueError("password must contain at least 12 characters and at most 1024 UTF-8 bytes")
    if not hmac.compare_digest(password.encode("utf-8"), password_input("Confirm password: ").encode("utf-8")):
        raise ValueError("password confirmation does not match")
    salt = secrets.token_bytes(16)
    record = {"version": 1, "salt": salt.hex(), "hash": password_hash(password, salt).hex()}
    directory.mkdir()
    try:
        protect(directory)
        helper = directory / "regression_guard.py"
        shutil.copyfile(Path(__file__).resolve(), helper)
        protect(helper)
        lock = directory / ".lock"
        lock.write_text(json.dumps(record) + "\n", encoding="utf-8")
        protect(lock)
        check_protection(directory)
    except BaseException:
        shutil.rmtree(directory)
        raise
    print(f"Full-regression guard registered: {directory}")


def verify():
    directory = guard_directory()
    if Path(__file__).resolve() != (directory / "regression_guard.py").resolve():
        raise ValueError("password verification must use the protected installed helper")
    if is_administrator():
        raise ValueError("run regression from a non-elevated console; elevated agents cannot be separated")
    check_protection(directory)
    record = json.loads((directory / ".lock").read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or set(record) != {"version", "salt", "hash"} or
            type(record["version"]) is not int or record["version"] != 1):
        raise ValueError("invalid regression guard registration")
    salt, expected = bytes.fromhex(record["salt"]), bytes.fromhex(record["hash"])
    if len(salt) != 16 or len(expected) != 32:
        raise ValueError("invalid regression guard registration")
    password = password_input("Full regression password: ")
    if len(password.encode("utf-8")) > 1024 or not hmac.compare_digest(password_hash(password, salt), expected):
        raise ValueError("full regression password does not match; no checks started")
    print("Full regression authorized for this invocation.")


def authorize_full_regression():
    # Only Windows was selected for password protection; other platforms are unchanged.
    if os.name != "nt":
        return
    directory = guard_directory()
    if is_administrator():
        raise ValueError("full regression requires a non-elevated agent/console")
    check_protection(directory)
    # No input/password/token arguments or environment overrides; no reusable unlock.
    result = subprocess.run([sys.executable, "-I", "-B", str(directory / "regression_guard.py"), "--verify"])
    if result.returncode:
        raise ValueError("full regression authorization failed; no checks started")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true", help="Human-only initial registration in an elevated Windows console")
    mode.add_argument("--verify", action="store_true", help="Used only by the installed protected helper")
    args = parser.parse_args()
    try:
        install() if args.install else verify()
        return 0
    except KeyboardInterrupt:
        print("Regression authorization cancelled; no checks started.", file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError, EOFError, getpass.GetPassWarning):
        # Do not echo malformed registration contents or any secret from an exception.
        print("Regression authorization failed. Check registration, ACL and console/password input.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
