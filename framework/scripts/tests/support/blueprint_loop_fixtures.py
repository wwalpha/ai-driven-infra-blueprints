"""Focused check for complete diagnostics and assertion-safe execution."""

from __future__ import annotations

import sys

from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from support.model_sources import snapshot_model

from model_files import read_model

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from support.model_sources import write_model, write_fixture_files

import pytest

from support.pytest_cli import run

import os

import importlib.util

import io

import json

import shutil

import subprocess

from contextlib import redirect_stdout

from unittest.mock import patch

from types import SimpleNamespace

import task_contract as tasks

SCRIPT = (Path(__file__).resolve().parents[2] / 'blueprint-loop.py')

SPEC = importlib.util.spec_from_file_location("blueprint_loop", SCRIPT)

MODULE = importlib.util.module_from_spec(SPEC)

SPEC.loader.exec_module(MODULE)

from support.it_workspace import copy_framework

def events(directory):
    return [json.loads(line) for line in (directory / "timing.jsonl").read_text(encoding="utf-8").splitlines()]

def make_framework_fixture(source, root):
    # Copy framework inputs only; never inherit consumer issues, models or tasks.
    copy_framework(root / 'framework', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ("AGENTS.md", "README.md"):
        shutil.copyfile(source / name, root / name)
    for name in ("tasks", "docs/designs", "model", "infra", "tests/scenarios", "tests/results"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "docs/system-overview.md").write_text("# Fixture\n", encoding="utf-8")


__all__ = ['MODULE', 'Path', 'SCRIPT', 'SPEC', 'SimpleNamespace', 'annotations', 'events', 'importlib', 'io', 'json', 'make_framework_fixture', 'os', 'patch', 'pytest', 'read_model', 'redirect_stdout', 'run', 'shutil', 'snapshot_model', 'subprocess', 'sys', 'tasks', 'write_fixture_files', 'write_model']
