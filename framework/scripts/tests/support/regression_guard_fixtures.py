"""Runnable repo .lock checks using temporary fixtures only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import io
import json
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import regression_guard as guard

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def rejected(operation, exception=ValueError):
    try:
        operation()
    except exception:
        return
    raise AssertionError("unsafe authorization/service_source was accepted")


__all__ = [
    "Path",
    "SimpleNamespace",
    "guard",
    "io",
    "json",
    "patch",
    "redirect_stderr",
    "redirect_stdout",
    "rejected",
    "sys",
    "tempfile",
]
