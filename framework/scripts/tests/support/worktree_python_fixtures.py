"""Offline shared setup, runtime registration and deletion boundary regression."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import importlib.metadata
import importlib.util
import json
import tempfile
from unittest.mock import patch

import worktree_python as py
import worktree_task as wt

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

spec = importlib.util.spec_from_file_location(
    "lifecycle_checks",
    (
        Path(__file__).resolve().parents[4]
        / "framework/scripts/tests/support/worktree_task_fixtures.py"
    ),
)

checks = importlib.util.module_from_spec(spec)

spec.loader.exec_module(checks)


def blocked(call, text):
    try:
        call()
    except (ValueError, OSError, ImportError) as error:
        assert text in str(error), str(error)
    else:
        raise AssertionError("expected failure: " + text)


__all__ = [
    "Path",
    "blocked",
    "fake_run",
    "checks",
    "importlib",
    "json",
    "patch",
    "py",
    "spec",
    "sys",
    "tempfile",
    "wt",
]


def fake_run(command, root, env=None):
    if "venv" in command:
        directory = Path(command[-1])
        (directory / "pyvenv.cfg").write_text("home = fixture\n")
        py.python_path(directory).parent.mkdir(exist_ok=True)
        py.python_path(directory).touch()
    return ""
