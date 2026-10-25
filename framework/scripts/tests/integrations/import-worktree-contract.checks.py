#!/usr/bin/env python3
"""Offline integration through the official IT runner."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import socket
from contextlib import contextmanager

import import_guard
import pytest
import worktree_task as wt
from model.adapters.task import source_write_context
from model.sources import load_model
from support.import_model_fixtures import fixture as import_fixture
from support.import_model_fixtures import (
    m,
    operation_contract,
    operation_fixture,
)
from support.model_v2_fixtures import import_contract, import_publication_case
from support.worktree_task_fixtures import fixture as worktree_fixture
from support.worktree_task_fixtures import git, start

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live network forbidden")),
    )


def source_files(root):
    return {
        p.relative_to(root): p.read_bytes()
        for p in (root / "model").rglob("*")
        if p.is_file()
    }


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


def _publication_workspace_begin(root, relative):
    git(root, "add", "model", "project.json")
    git(root, "commit", "-qm", "synthetic properties Import")
    return start(root, files=(relative.as_posix(),))


def _publication_workspace_advance(target):
    git(target, "commit", "--allow-empty", "-qm", "changed HEAD")


@contextmanager
def publication_workspace():
    with worktree_fixture() as root:
        begin = _publication_workspace_begin
        advance = _publication_workspace_advance
        yield root, begin, advance


def _callback_check_import_managed_contract_boundaries_workspace_reviewed(
    review, root, /, *args, **kwargs
):
    result = review(*args, **kwargs)
    other, state = start(
        root,
        task_id="other",
        files=("model/qa-synthetic/team-a/cloudwatch-logs.properties",),
    )
    name = state["task_file"]
    (other / name).write_text(
        import_contract(name, "model/qa-synthetic/team-a/cloudwatch-logs.properties")
    )
    original = source_files(other)
    with pytest.raises(
        ValueError,
        match="original external evidence|another Task|another.*scope|acquisition",
    ):
        m.publish_acquisition(
            other, "qa-synthetic", "cloudwatch-logs", args[3], "team-a"
        )
    assert (
        source_files(other) == original and not import_guard.proof_path(other).exists()
    )
    return result


def _callback_check_import_managed_contract_boundaries_workspace(monkeypatch):
    with publication_workspace() as (root, begin, advance):
        reviewed = _bind_framework_callback(
            _callback_check_import_managed_contract_boundaries_workspace_reviewed,
            m.review_acquisition,
            root,
        )
        monkeypatch.setattr(m, "review_acquisition", reviewed)
        yield root, begin, advance


def check_import_managed_contract_boundaries(monkeypatch):
    workspace = contextmanager(
        _bind_framework_callback(
            _callback_check_import_managed_contract_boundaries_workspace, monkeypatch
        )
    )
    import_publication_case(monkeypatch, "none", workspace=workspace)


@pytest.mark.parametrize("boundary", ["none", "owner"])
def check_model_source_context_worktree_boundary(monkeypatch, boundary):
    with worktree_fixture() as root:
        operation_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "Model context baseline")
        relative = "model/stg/cde/vpc.properties"
        target, state = start(root, files=(relative,))
        name = state["task_file"]
        task = target / name
        text = operation_contract() + "\n## Validation scope\n- `stg/cde/vpc`\n"
        for heading in ("Modified files", "Allowed paths"):
            text += "\n## " + heading + "\n- `" + name + "`\n- `" + relative + "`\n"
        task.write_text(text)
        path = target / relative
        original = path.read_bytes()
        with source_write_context(target, name) as context:
            model = load_model(path, context.snapshot)
            candidate = original.decode("utf-8") + "# intermediate save\n"
            plan = prepare_edit(model, {path: candidate}, context)
            if boundary == "owner":
                invalid = dict(state, worktree=str(root))
                wt.save(wt.state_path(root, "example"), invalid)
            if boundary == "none":
                assert publish_edit(plan, context) == (path,)
                assert path.read_text() == candidate
            else:
                with pytest.raises(ValueError, match="changed|lifecycle|mismatch"):
                    publish_edit(plan, context)
                assert path.read_bytes() == original
        assert (root / relative).read_bytes() == original


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
