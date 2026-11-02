#!/usr/bin/env python3
"""Offline integration through the official IT runner."""

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import subprocess
from contextlib import contextmanager

import import_guard
import model.importing.evidence as import_evidence
from support.import_model_fixtures import fixture as import_fixture
from support.import_model_fixtures import (
    logs_edit,
    m,
    review_fixture,
)
from support.model_v2_fixtures import import_publication_case
from support.repository_fixtures import fixture as repository_fixture
from support.repository_fixtures import git, start

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def fixture(root):
    path = import_fixture(root)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Import seed",
    )
    return path


def check_cross_process_evidence(tmp_path):
    root = tmp_path / "case"
    fixture(root)
    scripts = m.ROOT / "framework/scripts"
    setup = f"import sys; sys.path[:0] = [{str(scripts)!r}, {str(scripts / 'tests')!r}]; from pathlib import Path; from support.import_model_fixtures import m, aws; "
    acquire_code = (
        setup
        + f"import json; print(json.dumps(m.acquire(Path({str(root)!r}), 'dev', 'cloudwatch-logs', 'cde', cli_runner=aws(changed=True), resource_types=['Logs.LogGroup'])))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", acquire_code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    acquired = json.loads(completed.stdout)
    logs_edit(root, acquired)
    review_fixture(root, acquired)
    # Run the real CLI parser/entrypoint in an unpatched child, with no Host adapter.
    command = [
        sys.executable,
        "-B",
        str(scripts / "model/cli.py"),
        "import",
        "publish",
        "--repository-root",
        str(root),
        "--environment",
        "dev",
        "--service",
        "cloudwatch-logs",
        "--target",
        "cde",
        "--evidence",
        acquired["evidence"],
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", check=True
    )
    report = json.loads(result.stdout)
    assert report["model"] == "reflected" and report["markdown"] == "generated"
    assert import_evidence.read_proof(root)["complete"]
    # The ignored completion receipt contains hashes, not captured configuration values.
    assert '"retentionInDays"' not in import_guard.proof_path(root).read_text(
        encoding="utf-8"
    )


def _git_publication_workspace_begin(root, relative):
    git(root, "add", "model", "project.json")
    git(root, "commit", "-qm", "synthetic properties Import")
    return start(root, files=(relative.as_posix(),))


def _git_publication_workspace_advance(target):
    git(target, "commit", "--allow-empty", "-qm", "changed HEAD")


@contextmanager
def git_publication_workspace():
    with repository_fixture() as root:
        begin = _git_publication_workspace_begin
        advance = _git_publication_workspace_advance
        yield root, begin, advance


def check_properties_import_git_boundary(monkeypatch):
    import_publication_case(
        monkeypatch, subprocess_cli=True, workspace=git_publication_workspace
    )


def check_cli_help_entrypoints():
    scripts = Path(__file__).resolve().parents[2]
    direct = subprocess.run(
        [sys.executable, "-B", str(scripts / "model/cli.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    imported = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; sys.argv[0] = 'cli.py'; from model.cli import main; main(['--help'])",
        ],
        cwd=scripts,
        capture_output=True,
        text=True,
        check=True,
    )
    TestCase().assertTrue(direct.stdout == imported.stdout)
    module = subprocess.run(
        [sys.executable, "-B", "-m", "model.cli", "--help"],
        cwd=scripts,
        capture_output=True,
        text=True,
        check=True,
    )
    TestCase().assertTrue(module.stdout == "")


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
