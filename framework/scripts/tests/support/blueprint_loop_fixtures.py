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
from design.policy_tables import rendered_design
from model.files import read_model
from model.render import markdown_for
from model.sources import load_model
from support.it_workspace import populate
from support.model_sources import snapshot_model, write_fixture_files, write_model
from support.pytest_cli import run
from utils.script_loader import module
from validation import loop as MODULE

from model import dependency_index

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = Path(__file__).resolve().parents[2] / "blueprint-loop.py"


CLI = module("blueprint-loop.py", "blueprint_loop_cli")


def events(directory):
    return [
        json.loads(line)
        for line in (directory / "timing.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def make_project_fixture(source, root):
    # Only Project configuration and writable directories belong to the fixture.
    root.mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "README.md"):
        shutil.copyfile(source / name, root / name)
    for name in (
        "tasks",
        "docs/designs",
        "model",
        "infra",
        "tests/scenarios",
        "tests/results",
    ):
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
    (scripts / "blueprint-loop.py").write_text(bootstrap, encoding="utf-8")


__all__ = [
    "CLI",
    "MODULE",
    "Path",
    "SCRIPT",
    "SimpleNamespace",
    "annotations",
    "events",
    "importlib",
    "io",
    "json",
    "make_project_fixture",
    "make_loop_fixture",
    "os",
    "patch",
    "pytest",
    "read_model",
    "redirect_stdout",
    "run",
    "shutil",
    "snapshot_model",
    "subprocess",
    "sys",
    "tasks",
    "write_fixture_files",
    "write_model",
]


def make_service_loop_fixture(root):
    """Independent copy of the official, already consistent Model/Design seed."""
    make_project_fixture(SCRIPT.parents[2], root)
    populate("generated_policy", root)
    (root / "infra/cloudformation/parameters/dev/123456789012").mkdir(
        parents=True, exist_ok=True
    )
    (root / ".gitignore").write_text("tasks/**\n", encoding="utf-8")
    model = root / "model/dev/123456789012/iam.properties"
    design = root / "docs/designs/dev/123456789012/iam.md"
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=root,
        check=True,
    )
    name = "tasks/example.md"
    paths = [
        name,
        model.relative_to(root).as_posix(),
        design.relative_to(root).as_posix(),
    ]
    listed = "\n".join(f"- `{path}`" for path in paths)
    tasks.start(
        root,
        name,
        f"""## Task contract
- Task type: `design`
- Task status: `running`
## Validation scope
- `dev/123456789012/iam`
## Required changes
- [R1] 権限の説明を更新する。
## Acceptance checks
- [R1] `changed:{paths[1]}`
- [R1] `changed:{paths[2]}`
## Modified files
{listed}
## Allowed paths
{listed}
""",
    )
    values = dict(load_model(model).authoritative)
    values["display.resource.001.comment"] = "実行権限の説明を更新"
    write_model(model, values)
    design.write_text(
        markdown_for(design, load_model(model).values, root), encoding="utf-8"
    )
    design.write_text(rendered_design(design), encoding="utf-8")
    dependency_index.rebuild(root)
    return model
