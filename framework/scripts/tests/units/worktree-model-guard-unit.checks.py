#!/usr/bin/env python3
"""Managed ownership, Task baseline and pre-integration rejection only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import worktree_runtime
import worktree_state
import worktree_task as wt
from support.repository_fixtures import contract as repository_contract
from support.resource_delete_fixtures import contract, fixture
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation.findings import Findings
from validation.task import TaskValidation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize("problem", ["none", "task", "root", "merged", "owner"])
def check_ownership(tmp_path, problem):
    name = "tasks/example.md"
    state = {"task_file": name, "worktree": str(tmp_path), "merged": None}
    owner = tmp_path
    if problem == "task":
        state["task_file"] = "tasks/other.md"
    elif problem == "root":
        state["worktree"] = str(tmp_path / "other")
    elif problem == "merged":
        state["merged"] = "commit"
    elif problem == "owner":
        owner = tmp_path / "other"
    with (
        patch.object(worktree_state, "load", return_value=(None, None, None, state)),
        patch.object(worktree_state, "task_worktree", return_value=owner),
    ):
        if problem == "none":
            assert worktree_state.managed_task_state(tmp_path, name) is state
        else:
            with pytest.raises(ValueError):
                worktree_state.managed_task_state(tmp_path, name)


def check_finalize_rejects_incomplete_leaves(tmp_path):
    sources = fixture(tmp_path)
    name = "tasks/parent.md"
    (tmp_path / "tasks").mkdir()
    (tmp_path / name).write_text(
        contract(sources)
        + "## Validation scope\n- `stg/cde/service-a`\n"
        + f"## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n"
    )
    state = {"task_file": name, "python_setup": {"status": "ready"}, "merged": None}
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(
            wt,
            "_prepare_commit",
            side_effect=AssertionError("incomplete leaves cannot commit"),
        ),
    ):
        with pytest.raises(wt.Blocked, match="leaves incomplete"):
            wt.prepare_integration(tmp_path, "parent")


@pytest.mark.parametrize("action", ["import-retarget", "model-delete"])
def check_model_finalize_cannot_bypass_candidate(tmp_path, action):
    state = {"task_file": "tasks/retarget.md", "task_id": "retarget"}
    task = tmp_path / state["task_file"]
    task.parent.mkdir()
    task.write_text("- Model operation: `" + action + "`\n")
    with (
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(wt, "committed_task_paths", return_value=set()),
        patch.object(
            wt.tasks, "model_operation", return_value=SimpleNamespace(action=action)
        ),
    ):
        with pytest.raises(wt.Blocked, match="successful final candidate"):
            wt._prepare_commit(
                tmp_path,
                tmp_path / "unused-state.json",
                state,
                tmp_path,
                "approval cannot bypass",
            )


def _callback_check_git_baseline_fail_closed_task(tmp_path, /):
    return TaskValidation(tmp_path, Findings(tmp_path))


def _callback_check_git_baseline_fail_closed_git(root, *args, **kwargs):
    return SimpleNamespace(
        returncode=1 if args[0] == "show-ref" else 128, stdout="", stderr="missing HEAD"
    )


def check_git_baseline_fail_closed(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/example.md").write_text(
        repository_contract("example", ["file.txt"])
    )
    task = _bind_framework_callback(
        _callback_check_git_baseline_fail_closed_task, tmp_path
    )
    with (
        patch(
            "model.importing.repository.task_start_commit", return_value="task-start"
        ),
        patch(
            "worktree_state.git", side_effect=AssertionError("managed fallback to HEAD")
        ),
    ):
        current = task()
        current.fix_baseline()
        assert current.baseline == "task-start"
    git = _callback_check_git_baseline_fail_closed_git
    with (
        patch("model.importing.repository.task_start_commit", return_value=None),
        patch("worktree_state.output", return_value="refs/heads/new"),
        patch("worktree_state.git", side_effect=git),
    ):
        current = task()
        current.fix_baseline()
        assert current.baseline_fixed and current.baseline is None
    with (
        patch(
            "model.importing.repository.task_start_commit",
            side_effect=ValueError("invalid managed state"),
        ),
        pytest.raises(ValueError, match="invalid managed state"),
    ):
        task().fix_baseline()
    with (
        patch("model.importing.repository.task_start_commit", return_value=None),
        patch("worktree_state.output", side_effect=ValueError("broken Git")),
        patch("worktree_state.git", side_effect=git),
        pytest.raises(ValueError, match="broken Git"),
    ):
        task().fix_baseline()


@pytest.mark.parametrize("change", ["base", "head", "task", "dirty", "completion"])
def check_candidate_staleness(tmp_path, change):
    target, base = tmp_path / "task", tmp_path / "base"
    target.mkdir()
    (target / "tasks").mkdir()
    name = "tasks/example.md"
    text = repository_contract("example", ["file.txt"])
    (target / name).write_text(text + ("\nchanged" if change == "task" else ""))
    candidate = wt.FinalCandidate(
        target, target, name, text, "base", "head", frozenset({"file.txt"}), frozenset()
    )
    state = dict(task_file=name, branch="task", base="main")
    result = wt._ValidatedCandidate(candidate, 0)
    heads = iter(["head", "base", "changed", "base"])
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt, "task_worktree", return_value=target),
        patch.object(wt, "base_worktree", return_value=base),
        patch.object(
            wt,
            "changed_paths",
            return_value={"file.txt"} if change == "dirty" else set(),
        ),
        patch.object(wt, "paths", return_value=set()),
        patch.object(
            wt,
            "output",
            side_effect=lambda root, *args: next(heads)
            if change == "completion"
            else (
                "changed"
                if change == "base"
                and root == base
                or change == "head"
                and root == target
                else "base"
                if root == base
                else "head"
            ),
        ),
        patch.object(
            wt, "git", side_effect=AssertionError("stale candidate must not merge")
        ),
    ):
        with pytest.raises(wt.Blocked, match="changed"):
            wt.merge_validated_candidate(result)


@pytest.mark.parametrize("kind", ["framework", "model", "missing", "empty"])
def check_final_candidate_scope(tmp_path, kind):
    name = "tasks/example.md"
    source = (
        "framework/scripts/example.py"
        if kind == "framework"
        else "model/dev/team/iam.properties"
    )
    text = repository_contract("example", [source])
    if kind != "framework":
        text = (
            text.replace("`governance`", "`design`")
            .replace(
                "- Task status:",
                "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n- Task status:",
            )
            .replace("- `framework`", "- `dev/team/iam`")
        )
    (tmp_path / "tasks").mkdir()
    (tmp_path / name).write_text(text)
    state = dict(task_file=name, merged=None, python_setup={"status": "ready"})
    scope = (
        {("dev", "team", "iam")}
        if kind == "model"
        else None
        if kind == "missing"
        else set()
    )
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "integration_changed_paths", return_value={source}),
        patch.object(wt, "_prepare_commit", return_value="base"),
        patch.object(wt, "output", return_value="head"),
        patch.object(wt, "paths", return_value={source}),
        patch.object(
            worktree_runtime._imports_validation_scope,
            "active_scope",
            return_value=scope,
        ) as selected,
    ):
        if kind in {"missing", "empty"}:
            with pytest.raises(wt.Blocked, match="explicit service scope"):
                wt.prepare_integration(tmp_path, "example")
        else:
            candidate = wt.prepare_integration(tmp_path, "example")
            assert candidate.scope == frozenset(scope)
        if kind == "framework":
            selected.assert_not_called()
        else:
            selected.assert_called_once_with(tmp_path, task_file=name)


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize(
    "outside",
    [
        "model/dev/team/other.properties",
        "infra/template.yaml",
        "framework/scripts/other.py",
    ],
)
def check_integration_detects_undeclared_paths(tmp_path, committed, outside):
    name = "tasks/example.md"
    source = "model/dev/team/iam.properties"
    text = repository_contract("example", [source])
    (tmp_path / "tasks").mkdir()
    (tmp_path / name).write_text(text)
    state = dict(task_id="example", task_file=name, commit=None)
    with (
        patch.object(
            wt,
            "changed_paths",
            return_value={source} | (set() if committed else {outside}),
        ),
        patch.object(
            wt, "committed_task_paths", return_value={outside} if committed else set()
        ),
        patch.object(wt, "idle_git"),
        patch.object(wt.tasks, "validate_contract"),
        patch.object(
            wt, "git", side_effect=AssertionError("undeclared changes cannot write")
        ),
    ):
        assert wt.integration_changed_paths(tmp_path, name) == {source, outside}
        with pytest.raises(wt.Blocked, match="outside the exact task contract"):
            wt._prepare_commit(tmp_path, tmp_path / "state.json", state, tmp_path, None)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
