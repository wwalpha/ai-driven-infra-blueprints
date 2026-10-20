"""Offline shared setup, runtime registration and deletion boundary regression."""

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

import importlib.util

import importlib.metadata

import json

import tempfile

from unittest.mock import patch

import worktree_task as wt

import worktree_python as py

spec = importlib.util.spec_from_file_location("lifecycle_checks", (Path(__file__).resolve().parents[4] / 'framework/scripts/tests/support/worktree_task_fixtures.py'))

checks = importlib.util.module_from_spec(spec)

spec.loader.exec_module(checks)

def blocked(call, text):
    try:
        call()
    except (ValueError, OSError, ImportError) as error:
        assert text in str(error), str(error)
    else:
        raise AssertionError("expected failure: " + text)


__all__ = ['Path', 'blocked', 'checks', 'importlib', 'json', 'patch', 'py', 'spec', 'sys', 'tempfile', 'wt']
