"""Focused check for complete diagnostics and assertion-safe execution."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import importlib.util
import io
import json
import os
import shutil
import subprocess
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import task_contract as tasks
from model.files import read_model
from support.model_sources import snapshot_model, write_fixture_files, write_model
from support.pytest_cli import run
from utils.script_loader import module
from validation import loop as MODULE

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = (Path(__file__).resolve().parents[2] / 'blueprint-loop.py')


CLI = module("blueprint-loop.py", "blueprint_loop_cli")


def events(directory):
    return [json.loads(line) for line in (directory / "timing.jsonl").read_text(encoding="utf-8").splitlines()]

def make_project_fixture(source, root):
    # Only Project configuration and writable directories belong to the fixture.
    root.mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "README.md"):
        shutil.copyfile(source / name, root / name)
    for name in ("tasks", "docs/designs", "model", "infra", "tests/scenarios", "tests/results"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "docs/system-overview.md").write_text("# Fixture\n", encoding="utf-8")


def make_loop_fixture(scripts):
    # Keep existing orchestration outcomes at the validator boundary; import real code.
    bootstrap = f"""import sys, runpy
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, {str(SCRIPT.parent)!r})
from validation import loop, runner
from utils.script_loader import module
cli = module('blueprint-loop.py', 'fixture_loop_cli')
root = Path.cwd().resolve()
original_changed = loop.framework_changed
loop.framework_changed = lambda paths: original_changed(paths) or any(p.startswith('checks/') for p in paths)
loop.select_checks = lambda *a, **k: (sorted((root / 'checks/tests/units').glob('*.checks.py')), 'orchestration outcomes')
original_popen = loop.subprocess.Popen
def child(command, *args, **kwargs):
    if len(command) > 3 and command[1:3] == ['-X', 'utf8'] and command[3].endswith('blueprint-loop.py'):
        command = [*command[:3], str(Path(kwargs['cwd']) / 'checks/blueprint-loop.py'), *command[4:]]
    return original_popen(command, *args, **kwargs)
loop.subprocess.Popen = child

def run_validation(root, options, **kwargs):
    def report():
        try:
            runpy.run_path(str(root / 'checks/validate-blueprint.py'), run_name='__main__')
        except SystemExit as error:
            return error.code or 0
        return 0
    return SimpleNamespace(display_report=report)
runner.run_validation = run_validation
loop.authorize_full_regression = lambda root: None
raise SystemExit(cli.main())
"""
    (scripts / 'blueprint-loop.py').write_text(bootstrap, encoding='utf-8')


__all__ = ['CLI', 'MODULE', 'Path', 'SCRIPT', 'SimpleNamespace', 'annotations', 'events', 'importlib', 'io', 'json', 'make_project_fixture', 'make_loop_fixture', 'os', 'patch', 'pytest', 'read_model', 'redirect_stdout', 'run', 'shutil', 'snapshot_model', 'subprocess', 'sys', 'tasks', 'write_fixture_files', 'write_model']
