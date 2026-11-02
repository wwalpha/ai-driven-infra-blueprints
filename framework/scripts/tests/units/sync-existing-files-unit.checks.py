#!/usr/bin/env python3
"""Asset synchronization failure responses without child processes."""

import importlib.util
import io
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = Path(__file__).resolve().parents[2] / "sync-existing-files.py"
SPEC = importlib.util.spec_from_file_location("sync_existing_files", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise ImportError(str(SCRIPT))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _callback_check_failure_safety_run(source, target, /) -> int:
    with (
        mock.patch.object(MODULE, "FRAMEWORK_ROOT", source / "framework"),
        mock.patch.object(MODULE, "REPOSITORY_ROOT", source),
        mock.patch.object(sys, "argv", [str(SCRIPT), "--target", str(target)]),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        return MODULE.main()


def _callback_check_failure_safety_fail_once(
    _state_check_failure_safety_44,
    copy2,
    target,
    /,
    src: Path,
    dst: Path,
    *args: object,
    **kwargs: object,
):
    pass
    if Path(dst) == target / "README.md" and not _state_check_failure_safety_44.failed:
        _state_check_failure_safety_44.failed = True
        raise OSError("injected copy failure")
    return copy2(src, dst, *args, **kwargs)


def check_failure_safety() -> None:
    _state_check_failure_safety_44 = _CallbackState()
    with (
        mock.patch.object(sys, "argv", [str(SCRIPT)]),
        pytest.raises(SystemExit) as error,
    ):
        MODULE.parse_args()
    TestCase().assertEqual(error.value.code, 2)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source"
        target = Path(directory) / "target"
        (source / "framework").mkdir(parents=True)
        (source / ".agents").mkdir()
        (source / ".github/workflows").mkdir(parents=True)
        target.mkdir()
        target = target.resolve()
        for relative in (
            "framework/a.txt",
            "framework/b.txt",
            "AGENTS.md",
            "README.md",
            ".github/workflows/framework-it.yml",
        ):
            (source / relative).write_text("original\n", encoding="utf-8")

        for relative in (
            "framework/scripts/tests/new.py",
            "framework/nested/tests/fixture.json",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test asset\n", encoding="utf-8")
        TestCase().assertEqual(_callback_check_failure_safety_run(source, target), 0)
        TestCase().assertTrue(not (target / "framework/scripts/tests").exists())
        TestCase().assertTrue(not (target / "framework/nested/tests").exists())
        TestCase().assertTrue(
            not (target / ".github/workflows/framework-it.yml").exists()
        )
        (target / "framework/b.txt").unlink()
        original = {
            path.relative_to(target): path.read_bytes()
            for path in target.rglob("*")
            if path.is_file()
        }
        (source / "framework/a.txt").write_text("updated\n", encoding="utf-8")
        (source / "README.md").write_text("updated\n", encoding="utf-8")
        (source / ".github/workflows/framework-it.yml").write_text(
            "updated\n", encoding="utf-8"
        )
        copy2 = shutil.copy2
        _state_check_failure_safety_44.failed = False

        fail_once = _bind_framework_callback(
            _callback_check_failure_safety_fail_once,
            _state_check_failure_safety_44,
            copy2,
            target,
        )

        with mock.patch.object(MODULE.shutil, "copy2", side_effect=fail_once):
            result = _callback_check_failure_safety_run(source, target)
            TestCase().assertEqual(
                result, 1, msg=(result, _state_check_failure_safety_44.failed)
            )
        TestCase().assertTrue(_state_check_failure_safety_44.failed)
        TestCase().assertEqual(
            {
                path.relative_to(target): path.read_bytes()
                for path in target.rglob("*")
                if path.is_file()
            },
            original,
        )

        new_source = source / "framework/new.txt"
        new_source.write_text("new\n", encoding="utf-8")
        with mock.patch.object(Path, "is_symlink", lambda self: self == new_source):
            TestCase().assertEqual(
                _callback_check_failure_safety_run(source, target), 1
            )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
