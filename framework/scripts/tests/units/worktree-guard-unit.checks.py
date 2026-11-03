#!/usr/bin/env python3
"""Ordinary integration guard runtime and pre-write boundaries, using synthetic inputs."""

import copy
import sys
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import builtins
import json
import os
import subprocess
from unittest.mock import Mock, patch

import pytest
import worktree_pr as pr
import worktree_state
import worktree_task as wt
from support.worktree_task_fixtures import contract
from utils.git_changes import GitWorkingPaths

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_registered_guard_process_missing_parent_dependency(
    real_import, /, name, *args, **kwargs
):
    if name in ("import_guard", "pystache", "yaml"):
        raise ModuleNotFoundError("parent lacks Model dependencies")
    return real_import(name, *args, **kwargs)


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("outcome", ["success", "reject", "launch", "runtime"])
def check_registered_guard_process(tmp_path, capsys, approved, outcome):
    check = TestCase()
    task = "tasks/selected.md"
    (tmp_path / "tasks").mkdir()
    (tmp_path / task).write_text(contract("selected", ["file.txt"]))
    environment = {
        **os.environ,
        "BLUEPRINT_TASK_FILE": "tasks/foreign.md",
        "GUARD_OUTCOME": outcome,
    }
    child = Mock(
        return_value=subprocess.CompletedProcess(
            [],
            int(outcome == "reject"),
            "stdout diagnostic\n",
            "guard rejection"
            if outcome == "reject"
            else "warning: synthetic reference\n",
        )
    )
    real_import = builtins.__import__
    missing_parent_dependency = _bind_framework_callback(
        _callback_check_registered_guard_process_missing_parent_dependency, real_import
    )
    with (
        patch.object(
            wt.python_env, "runtime", return_value=(Path(sys.executable), environment)
        ) as runtime,
        patch.object(wt.python_env, "setup", side_effect=AssertionError("no setup")),
        patch.object(wt.subprocess, "run", side_effect=child),
        patch("builtins.__import__", side_effect=missing_parent_dependency),
    ):
        if outcome == "runtime":
            runtime.side_effect = ValueError("stale runtime")
            with pytest.raises(ValueError, match="stale runtime"):
                wt._run_model_guard(tmp_path, task, approved)
            runtime.side_effect = None
            runtime.return_value = None
            with pytest.raises(
                wt.Blocked, match="registered Python runtime is missing"
            ):
                wt._run_model_guard(tmp_path, task, approved)
        elif outcome == "launch":
            with (
                patch.object(
                    wt.subprocess, "run", side_effect=OSError("cannot launch")
                ),
                pytest.raises(OSError),
            ):
                wt._run_model_guard(tmp_path, task, approved)
        elif outcome == "reject":
            with pytest.raises(wt.Blocked) as caught:
                wt._run_model_guard(tmp_path, task, approved)
            assert caught.value.diagnostics["returncode"] == 1
            assert caught.value.diagnostics["stdout"] == "stdout diagnostic\n"
            assert "guard rejection" in caught.value.diagnostics["stderr"]
        else:
            wt._run_model_guard(tmp_path, task, approved)
            output = capsys.readouterr()
            assert output.out == ""
            assert (
                "stdout diagnostic" in output.err
                and "warning: synthetic reference" in output.err
            )
        if outcome in ("success", "reject"):
            command = child.call_args.args[0]
            check.assertEqual(command[:3], [sys.executable, "-B", "-c"])
            check.assertEqual(
                command[4:], [task, "approved" if approved else "normal", "null"]
            )
            check.assertEqual(
                child.call_args.kwargs,
                dict(
                    cwd=tmp_path,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                ),
            )


def _callback_check_prepare_rejects_before_git_write_guard(
    changed, head, index, source, task, violation, /, *args
):
    if violation == "guard":
        raise wt.Blocked("guard rejected")
    if violation == "task-after":
        task.write_text(task.read_text() + "\nchanged task")
    if violation == "bytes-after":
        source.write_text("changed during guard")
    if violation == "head-after":
        head[0] = "unexpected"
    if violation == "paths-after":
        changed.add("foreign.txt")
    if violation == "index-after":
        index[0] = "changed index"


@pytest.mark.parametrize(
    "violation",
    [
        "head",
        "unverified",
        "committed-dirty",
        "scope",
        "operation",
        "guard",
        "task-after",
        "bytes-after",
        "head-after",
        "paths-after",
        "index-after",
    ],
)
def check_prepare_rejects_before_git_write(tmp_path, violation):
    relative = "model/dev/cde/example.properties"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("original")
    task = tmp_path / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(contract("example", [relative]).replace("`running`", "`completed`"))
    state = dict(
        task_id="example",
        task_file="tasks/example.md",
        tip="tip",
        start="tip",
        commit=None,
        verified=False,
        base="main",
    )
    changed = {relative}
    head, index = ["tip"], ["index"]
    if violation == "head":
        head[0] = "unexpected"
    if violation == "unverified":
        state["commit"] = "tip"
    if violation == "committed-dirty":
        state.update(commit="tip", verified=True)
    if violation == "scope":
        changed.add("foreign.txt")
    guard = _bind_framework_callback(
        _callback_check_prepare_rejects_before_git_write_guard,
        changed,
        head,
        index,
        source,
        task,
        violation,
    )
    with (
        patch.object(wt, "changed_paths", side_effect=lambda root: set(changed)),
        patch.object(wt, "committed_task_paths", return_value=set()),
        patch.object(wt, "integration_task"),
        patch.object(wt.tasks, "validate_contract"),
        patch.object(wt, "base_worktree"),
        patch.object(wt, "ancestor", return_value=True),
        patch.object(
            wt,
            "idle_git",
            side_effect=wt.Blocked("unfinished Git operation")
            if violation == "operation"
            else None,
        ),
        patch.object(
            wt,
            "output",
            side_effect=lambda root, *args: index[0] if args[0] == "diff" else head[0],
        ),
        patch.object(wt, "_run_model_guard", side_effect=guard) as called,
        patch.object(wt, "git", side_effect=AssertionError("Git write reached")),
    ):
        with pytest.raises(wt.Blocked):
            wt._prepare_commit(tmp_path, tmp_path / "state.json", state, tmp_path, None)
        assert called.call_count == (
            0
            if violation
            in ("head", "unverified", "committed-dirty", "scope", "operation")
            else 1
        )
    assert state["commit"] == (
        "tip" if violation in ("unverified", "committed-dirty") else None
    )


def check_cli_failure_diagnostics(tmp_path, capsys):
    error = wt.Blocked("child failed")
    error.diagnostics = dict(returncode=23, stdout="output", stderr="error")
    error.cleanup = dict(phase="remove_branch", stop_reason=str(error))
    with (
        patch.object(
            sys, "argv", ["worktree_task.py", "finalize", "--task-id", "fixture"]
        ),
        patch.object(wt, "load", return_value=(tmp_path, None, None, {})),
        patch.object(wt, "finalize", side_effect=error),
    ):
        assert wt.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked" and result["diagnostics"] == error.diagnostics
    assert result["cleanup"] == error.cleanup


def _cleanup_output(common, case, /, root, *args):
    if args[-1] == "--git-common-dir":
        return str(
            common / "foreign" if case == "common" and "--git-dir" in args else common
        )
    if "symbolic-ref" in args:
        return "refs/heads/codex/worktree/example"
    if args[-1] == "HEAD":
        return "changed" if case == "git_head" else "tip"
    if "diff-index" in args:
        if case == "index_error":
            raise wt.Blocked("cannot read index")
        return "staged\0" if case == "dirty" else ""
    raise AssertionError(args)


@pytest.mark.parametrize(
    "case",
    [
        "clean",
        "locked",
        "branch",
        "head",
        "merged",
        "unverified",
        "ambiguous",
        "missing_index",
        "index_link",
        "lock",
        "common",
        "git_head",
        "operation",
        "index_error",
        "dirty",
    ],
)
@pytest.mark.parametrize("discard", [False, True])
def check_cleanup_missing_worktree(tmp_path, case, discard):
    target = tmp_path / ".worktrees/example"
    common = tmp_path / ".git"
    directory = common / "worktrees/example"
    directory.mkdir(parents=True)
    for name, value in [
        ("gitdir", str(target / ".git") + "\n"),
        ("HEAD", "tip"),
        ("index", "index"),
    ]:
        (directory / name).write_text(value)
    state = dict(
        worktree=str(target),
        branch="codex/worktree/example",
        tip="tip",
        merged="tip",
        commit="tip",
        verified=True,
    )
    entry = dict(
        worktree=str(target),
        HEAD="tip",
        branch="refs/heads/codex/worktree/example",
        prunable="missing",
    )
    if case == "locked":
        entry["locked"] = ""
    if case in {"branch", "head"}:
        entry["HEAD" if case == "head" else "branch"] = "other"
    if case == "merged":
        state["merged"] = "other"
    if case == "unverified":
        state["verified"] = False
    if case == "ambiguous":
        duplicate = common / "worktrees/duplicate"
        duplicate.mkdir()
        (duplicate / "gitdir").write_text(str(target / ".git") + "\n")
    if case == "missing_index":
        (directory / "index").unlink()
    if case == "lock":
        (directory / "index.lock").write_text("owned by another process")
    with (
        patch.object(
            wt,
            "output",
            side_effect=_bind_framework_callback(_cleanup_output, common, case),
        ),
        patch.object(
            Path,
            "is_symlink",
            autospec=True,
            side_effect=lambda path: case == "index_link"
            and path == directory / "index",
        ),
        patch.object(
            worktree_state,
            "idle_operations",
            side_effect=wt.Blocked("unfinished operation")
            if case == "operation"
            else None,
        ) as idle,
    ):
        if (
            case == "clean"
            or discard
            and case in {"head", "merged", "unverified", "dirty", "index_error"}
        ):
            if case == "head":
                entry["HEAD"] = "tip"
            wt.cleanup_missing_worktree(tmp_path, state, entry, discard=discard)
            assert idle.call_args.kwargs["runner"].keywords == {"directory": directory}
        else:
            with pytest.raises(wt.Blocked):
                wt.cleanup_missing_worktree(tmp_path, state, entry, discard=discard)
    assert (directory / "HEAD").read_text() == "tip" and not target.exists()


@pytest.mark.parametrize(
    "case",
    [
        "unmerged",
        "rewritten",
        "branch_changed",
        "dirty",
        "setup_busy",
        "symlink",
        "locked",
        "ignored",
        "missing_branch",
    ],
)
def check_cleanup_stops_before_removal(tmp_path, case):
    target = tmp_path / ".worktrees/example"
    target.mkdir(parents=True)
    path = tmp_path / "state.json"
    path.write_text("preserve state")
    state = dict(
        task_id="example",
        worktree=str(target),
        branch="codex/worktree/example",
        base="main",
        tip="tip",
        merged=None if case == "unmerged" else "tip",
        commit="tip",
        task_file="tasks/example.md",
    )
    entry = dict(
        worktree=str(target), HEAD="tip", branch="refs/heads/codex/worktree/example"
    )
    if case == "setup_busy":
        path.with_suffix(".setup-lock").mkdir()
    with (
        patch.object(
            wt,
            "ancestor",
            side_effect=[True, False] if case == "rewritten" else None,
            return_value=True,
        ),
        patch.object(wt, "worktrees", return_value=[entry]),
        patch.object(
            wt,
            "task_worktree",
            side_effect=wt.Blocked("locked worktree") if case == "locked" else None,
            return_value=target,
        ),
        patch.object(
            Path,
            "is_symlink",
            autospec=True,
            side_effect=lambda path: case == "symlink" and path == target,
        ),
        patch.object(wt, "integration_task"),
        patch.object(wt, "cleanup_missing_worktree"),
        patch.object(
            wt, "output", return_value="changed" if case == "branch_changed" else "tip"
        ),
        patch.object(
            wt, "changed_paths", return_value={"dirty"} if case == "dirty" else set()
        ),
        patch.object(
            wt, "paths", return_value={"secret.bin"} if case == "ignored" else set()
        ),
        patch.object(wt, "branch_exists", return_value=case != "missing_branch"),
        patch.object(wt, "git") as mutate,
        pytest.raises(wt.Blocked) as caught,
    ):
        wt.cleanup_state(tmp_path, path, state)
    mutate.assert_not_called()
    details = caught.value.cleanup
    assert details["phase"] == (
        "verify_merge" if case in {"unmerged", "rewritten"} else "verify_worktree"
    )
    assert details["stop_reason"] == str(caught.value)
    assert details["remaining"] == dict(
        worktree=True,
        git_registration=True,
        branch=case != "missing_branch",
        task_state=True,
    )
    assert details["next_action"] == "resolve_stop_reason_then_retry"
    assert details["retry_command"].endswith("cleanup --task-id example")
    assert path.read_text() == "preserve state" and target.is_dir()


@pytest.mark.parametrize("command", ["cleanup", "finalize"])
def check_cleanup_preflight_diagnostics(tmp_path, capsys, command):
    state = dict(
        task_id="example",
        worktree=str(tmp_path / ".worktrees/example"),
        branch="codex/worktree/example",
        merged="tip",
    )
    path = tmp_path / "state.json"
    path.write_text("preserve")
    with (
        patch.object(
            sys, "argv", ["worktree_task.py", command, "--task-id", "example"]
        ),
        patch.object(wt, "load", return_value=(tmp_path, None, path, state)),
        patch.object(wt, command, side_effect=wt.Blocked("worktree lifecycle busy")),
        patch.object(wt, "worktrees", return_value=[]),
        patch.object(wt, "branch_exists", return_value=True),
    ):
        assert wt.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["cleanup"]["phase"] == "preflight"
    assert (
        result["cleanup"]["stop_reason"] == result["error"] == "worktree lifecycle busy"
    )
    assert result["cleanup"]["remaining"] == dict(
        worktree=False, git_registration=False, branch=True, task_state=True
    )


@pytest.mark.parametrize("directory", ["plain", "space 日本語", "line\nbreak"])
@pytest.mark.parametrize("linked", [False, True])
def check_idle_git_paths_and_state(tmp_path, directory, linked):
    working = GitWorkingPaths(frozenset({"file.txt"}), frozenset(), frozenset())
    with patch.object(
        worktree_state, "collect_working_paths", return_value=working
    ) as collect:
        changed = worktree_state.changed_paths(tmp_path)
    collect.assert_called_once_with(tmp_path, runner=worktree_state.git)
    changed.clear()
    assert working.all_paths == {"file.txt"}
    with patch.object(worktree_state, "read_paths", return_value={"file.txt"}) as read:
        assert wt.paths(tmp_path, "ls-files", "-z") == {"file.txt"}
    read.assert_called_once_with(tmp_path, "ls-files", "-z", runner=wt.git)
    with (
        patch.dict(
            os.environ, {"GIT_INDEX_FILE": "/foreign/index", "GIT_DIR": "/foreign/git"}
        ),
        patch.object(
            worktree_state.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 128, "", "broken"),
        ) as execute,
        pytest.raises(wt.Blocked, match="git diff failed: broken"),
    ):
        worktree_state.changed_paths(tmp_path)
    environment = execute.call_args.kwargs["env"]
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_INDEX_FILE" not in environment and "GIT_DIR" not in environment
    root = tmp_path / directory
    root.mkdir()
    common = tmp_path / (("linked " if linked else "") + directory + " administration")
    common.mkdir()
    state = SimpleNamespace(common=common, conflicts=False)
    runner = _bind_framework_callback(_idle_git_process, state)
    with patch.object(worktree_state.subprocess, "run", side_effect=runner):
        _check_idle_markers(root, directory, state)


def _idle_git_process(state, command, **kwargs):
    if command[1] == "rev-parse":
        names = [
            command[index + 1]
            for index, value in enumerate(command)
            if value == "--git-path"
        ]
        output = "\n".join(str(state.common / name) for name in names) + "\n"
        return subprocess.CompletedProcess(command, 0, output, "")
    if command[1:] == ["diff", "--name-only", "--diff-filter=U", "-z"]:
        output = "conflict.txt\x00" if state.conflicts else ""
        return subprocess.CompletedProcess(command, 0, output, "")
    raise AssertionError(f"unexpected Git command: {command}")


def _check_idle_markers(root, directory, state):
    names = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    )
    markers = [
        Path(wt.output(root, "rev-parse", "--path-format=absolute", "--git-path", name))
        for name in names
    ]
    with patch.object(wt, "git", wraps=wt.git) as calls:
        wt.idle_git(root)
        assert calls.call_count == (8 if "\n" in directory else 2)
    for name, marker in zip(names, markers, strict=False):
        marker.write_text("marker", encoding="utf-8")
        with pytest.raises(wt.Blocked) as caught:
            wt.idle_git(root)
        assert (
            str(caught.value) == f"unfinished Git operation: {name}; worktree retained"
        )
        marker.unlink()
        wt.idle_git(root)
    for marker in markers:
        marker.write_text("marker", encoding="utf-8")
    for name, marker in zip(names, markers, strict=False):
        with pytest.raises(wt.Blocked) as caught:
            wt.idle_git(root)
        assert (
            str(caught.value) == f"unfinished Git operation: {name}; worktree retained"
        )
        marker.unlink()
    state.conflicts = True
    with pytest.raises(
        wt.Blocked, match="^unresolved index conflicts; worktree retained$"
    ):
        wt.idle_git(root)
    markers[0].write_text("marker", encoding="utf-8")
    with pytest.raises(
        wt.Blocked, match="^unfinished Git operation: MERGE_HEAD; worktree retained$"
    ):
        wt.idle_git(root)
    markers[0].unlink()
    state.conflicts = False
    wt.idle_git(root)


def _callback_check_repin_rejects_before_state_write_output(
    base, candidate, latest, violation, /, root, *args
):
    if args[0] == "rev-parse":
        return (
            ("0" * 40 if violation == "base" else latest) if root == base else candidate
        )
    if args[1] == "--count":
        return "2" if violation == "count" else "1"
    return "a merge" if violation == "merge" else ""


@pytest.mark.parametrize(
    "violation",
    [
        "dirty",
        "suspend",
        "count",
        "merge",
        "scope",
        "history",
        "head",
        "base",
        "unverified",
        "type",
        "receipt",
        "descendant",
    ],
)
def check_repin_rejects_before_state_write(tmp_path, violation):
    old, latest, candidate = "1" * 40, "2" * 40, "3" * 40
    task = "tasks/example.md"
    text = contract("example", ["file.txt"])
    if violation == "suspend":
        text = (
            text.replace("`running`", "`suspend`") + "\n## Suspension reason\nfixture\n"
        )
    if violation == "type":
        text = text.replace("`governance`", "`migration`")
    (tmp_path / "tasks").mkdir()
    (tmp_path / task).write_text(text, encoding="utf-8")
    state = dict(
        task_file=task,
        merged=None,
        verified=violation != "unverified",
        recovery=dict(commit="4" * 40, base=old, count="1"),
    )
    if violation == "receipt":
        del state["recovery"]
    original = copy.deepcopy(state)
    base = tmp_path / "base"

    output = _bind_framework_callback(
        _callback_check_repin_rejects_before_state_write_output,
        base,
        candidate,
        latest,
        violation,
    )

    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "base_worktree", return_value=base),
        patch.object(wt, "output", side_effect=output),
        patch.object(
            wt,
            "git",
            side_effect=lambda root, *args, **kwargs: SimpleNamespace(
                returncode=int(
                    violation == "history"
                    and args[-1] == candidate
                    or violation == "descendant"
                    and args[-1] == latest
                )
            ),
        ),
        patch.object(
            wt,
            "changed_paths",
            return_value={"file.txt"} if violation == "dirty" else set(),
        ),
        patch.object(
            wt,
            "paths",
            return_value={"outside.txt"} if violation == "scope" else {"file.txt"},
        ),
        patch.object(wt, "save") as save,
    ):
        with pytest.raises(wt.Blocked):
            wt.recover(
                tmp_path,
                "example",
                "0" * 40 if violation == "head" else candidate,
                latest,
                repin=True,
            )
        save.assert_not_called()
    assert state == original


@pytest.mark.parametrize(
    "status,approval,accepted",
    [
        ("running", None, False),
        ("suspend", None, False),
        ("completed", None, True),
        ("running", "accepted failure", False),
        ("suspend", " ", False),
        ("suspend", "accepted failure", True),
    ],
)
def check_integration_status(tmp_path, status, approval, accepted):
    task = tmp_path / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(
        contract("example", ["file.txt"]).replace("`running`", "`" + status + "`")
        + (
            "\n## Suspension reason\nfixture validation failure\n"
            if status == "suspend"
            else ""
        )
    )
    with patch.object(wt, "task_start_commit", return_value="base"):
        if accepted:
            wt.integration_task(tmp_path, {"task_file": "tasks/example.md"}, approval)
        else:
            with pytest.raises(wt.Blocked):
                wt.integration_task(
                    tmp_path, {"task_file": "tasks/example.md"}, approval
                )


@pytest.mark.parametrize("setup", [None, {}])
def check_finalize_requires_setup(tmp_path, setup):
    task = tmp_path / "tasks/example.md"
    task.parent.mkdir()
    task.write_text(
        contract("example", ["file.txt"]).replace("`running`", "`completed`")
    )
    state = dict(task_file="tasks/example.md", merged=None)
    if setup is not None:
        state["python_setup"] = setup
    with (
        patch.object(wt, "integration_changed_paths", return_value={"file.txt"}),
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(
            wt,
            "_prepare_commit",
            side_effect=AssertionError("setup must precede commit"),
        ),
    ):
        with pytest.raises(wt.Blocked, match="Python setup is incomplete"):
            wt.finalize(tmp_path, "example")


@pytest.mark.parametrize(
    "explicit,remote,branches,expected",
    [
        ("master", "refs/remotes/origin/main", {"master", "main"}, "master"),
        ("", "refs/remotes/origin/release", {"release", "main"}, "release"),
        ("", "", {"main", "master"}, "main"),
        ("", "", {"master"}, "master"),
        ("missing", "", {"main"}, None),
        ("", "", {"feature"}, None),
    ],
)
def check_base_selection(tmp_path, explicit, remote, branches, expected):
    with (
        patch.object(
            wt,
            "git",
            side_effect=[
                SimpleNamespace(stdout=explicit),
                SimpleNamespace(stdout=remote),
            ],
        ),
        patch.object(
            wt, "branch_exists", side_effect=lambda root, name: name in branches
        ),
    ):
        if expected:
            assert wt.base_branch(tmp_path) == expected
        else:
            with pytest.raises(wt.Blocked):
                wt.base_branch(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        ".other/example",
        ".worktrees/other",
        ".worktrees/example/extra",
        ".git/worktrees/example",
        ".worktree/example",
    ],
)
def check_lifecycle_layout(tmp_path, relative):
    state = dict(
        task_id="example",
        branch="codex/worktree/example",
        task_file="tasks/example.md",
        primary=str(tmp_path),
        worktree=str(tmp_path / relative),
    )
    path = tmp_path / ".worktrees/.blueprint/tasks/example.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state))
    with patch.object(
        wt.worktree_state, "repository", return_value=(tmp_path, None, tmp_path)
    ):
        with pytest.raises(wt.Blocked, match="state does not match"):
            wt.load(tmp_path, "example")


@pytest.mark.parametrize(
    "relative", [".worktrees", ".worktrees/.blueprint", ".worktrees/.blueprint/tasks"]
)
def check_metadata_symlinks(tmp_path, relative):
    external = tmp_path / "external"
    external.mkdir()
    link = tmp_path / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(external, target_is_directory=True)
    with pytest.raises(wt.Blocked, match="metadata must not use symlinks"):
        wt.metadata_directory(tmp_path)
    assert link.is_symlink() and not list(external.iterdir())


@pytest.mark.parametrize(
    "pending",
    [
        "generation-only",
        "producer",
        "pendingObserved",
        "success",
        "observedError",
        "running",
        "pollError",
    ],
)
def check_checkpoint_observed_barrier(tmp_path, pending):
    handoff = wt._worktree_runtime().deploy_handoff
    request = {
        "target": {"awsAccountId": "account", "awsRegion": "region"},
        "diagnosis": {"Peer": {"inputRefs": [], "modelRefs": []}},
        "allowedPaths": [],
    }
    context = {}
    if pending == "generation-only":
        context["pendingGeneration"] = {
            "view": {
                "generated": {"originals": {"docs/designs/peer.md": None}},
                "producers": [],
            }
        }
    elif pending == "producer":
        context["generationProducers"] = {"Peer": {}}
        context["pendingGeneration"] = {
            "view": {
                "generated": {"originals": {"docs/designs/peer.md": None}},
                "producers": [],
            }
        }
    elif pending in {"pendingObserved", "observedError"}:
        context["pendingObserved"] = {
            "beforeManifest": {"model/peer.properties": "hash"},
            "evidence": {"Peer": {}},
        }
    stack_status = (
        "UPDATE_IN_PROGRESS"
        if pending in {"running", "pollError"}
        else "UPDATE_COMPLETE"
    )
    with (
        patch.object(
            handoff.worktree,
            "progress_path",
            return_value=SimpleNamespace(exists=lambda: True),
        ),
        patch.object(handoff.worktree, "require", return_value={}),
        patch.object(
            handoff.worktree, "read_progress", return_value={"runContext": context}
        ),
        patch.object(handoff, "dependency_reader", return_value=Mock()),
        patch.object(
            handoff.current_request, "location", return_value=tmp_path / "request.json"
        ),
        patch.object(
            handoff.current_state, "read", return_value={"StackStatus": stack_status}
        ),
    ):
        if pending in {"generation-only", "success"}:
            handoff.require_settled(tmp_path, request)
        else:
            with pytest.raises(handoff.Blocked):
                handoff.require_settled(tmp_path, request)


@pytest.mark.parametrize(
    "case", ["independent", "publication-overlap", "journal-active", "repair-active"]
)
def check_checkpoint_uses_scoped_barrier_under_ordered_locks(tmp_path, case):
    runtime = wt._worktree_runtime()
    handoff = runtime.deploy_handoff
    journal = handoff.operation_journal
    target = {"awsAccountId": "account", "awsRegion": "region"}
    request = {
        "repository": str(tmp_path),
        "taskFile": "tasks/deploy.md",
        "taskDigest": "digest",
        "target": target,
        "requestId": "one",
        "diagnosis": {"S3": {"inputRefs": [], "modelRefs": []}},
        "allowedPaths": ["infra/cloudformation/s3.yaml"],
    }
    store = handoff.evidence_store(tmp_path)
    request_path = store / "deploy-repair-one/request.json"
    request_path.parent.mkdir(mode=0o700)
    runtime.write_sealed(tmp_path, request_path, request)
    journal_path = tmp_path / "journal/journal.json"
    shared = "model/dev/team/kms.properties"
    publication = {
        "repository": str(tmp_path),
        "pendingGeneration": {
            "view": {
                "generated": {"outputs": {}, "originals": {shared: None}},
                "producers": [],
            }
        },
    }
    state = {"task_file": "tasks/deploy.md"}
    task = SimpleNamespace(
        text="## Task contract\n- Task status: `running`", task_digest="digest"
    )
    active = (
        journal.locked(journal_path)
        if case == "journal-active"
        else handoff.repair_lock(tmp_path)
        if case == "repair-active"
        else nullcontext()
    )
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(runtime.tasks, "read_task_snapshot", return_value=task),
        patch.object(
            runtime._imports_deploy_contracts, "task_digest", return_value="digest"
        ),
        patch.object(journal, "location", return_value=journal_path),
        patch.object(
            handoff.worktree,
            "progress_path",
            return_value=SimpleNamespace(exists=lambda: True),
        ),
        patch.object(handoff.worktree, "require", return_value={}),
        patch.object(
            handoff.worktree,
            "read_progress",
            return_value={
                "runContext": publication if case == "publication-overlap" else {}
            },
        ),
        patch.object(handoff, "dependency_reader", return_value=Mock()),
        patch.object(
            handoff.current_state,
            "read",
            return_value={"StackStatus": "UPDATE_COMPLETE"},
        ),
        patch.object(
            wt,
            "changed_paths",
            return_value={shared}
            if case == "publication-overlap"
            else {"tasks/deploy.md"},
        ),
        patch.object(
            handoff, "verify_inputs", side_effect=handoff.Blocked("past scoped barrier")
        ) as verified,
        patch.object(wt, "git") as git,
        active,
    ):
        expected = (
            "past scoped barrier"
            if case == "independent"
            else "unfinished publication"
            if case == "publication-overlap"
            else "lock busy"
        )
        with pytest.raises(handoff.Blocked, match=expected):
            runtime.deploy_checkpoint(tmp_path, "deploy", request_path)
        assert verified.called == (case == "independent")
        git.assert_not_called()
    with journal.locked(journal_path), handoff.repair_lock(tmp_path):
        pass


@pytest.mark.parametrize(
    "command",
    [
        "create",
        "setup",
        "cleanup",
        "recover",
        "repair-checkpoint",
        "repair-validate",
        "sync-base",
        "deploy-start",
        "deploy-publish",
    ],
)
def check_pr_cli_and_special_routes(tmp_path, command):
    with (
        patch.object(
            sys,
            "argv",
            ["worktree_task.py", command, "--task-id", "example", "--create-pr"],
        ),
        patch.object(wt, "load") as load,
    ):
        with pytest.raises(SystemExit) as error:
            wt.main()
        assert error.value.code == 2
        load.assert_not_called()
    for special in ("deployIdentity", "deployRepair", "merged"):
        state = {"merged": None, special: "present"}
        with (
            patch.object(
                wt,
                "load",
                return_value=(tmp_path, None, tmp_path / "state.json", state),
            ),
            patch.object(wt, "module") as module,
            patch.object(wt, "git") as git,
        ):
            with pytest.raises(wt.Blocked, match="Deploy, repair or merged"):
                wt.finalize(tmp_path, "example", create_pr=True)
            module.assert_not_called()
            git.assert_not_called()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/team/repo.git", ("github.com", "team/repo")),
        ("git@github.com:team/repo.git", ("github.com", "team/repo")),
        ("ssh://git@ghe.example/team/repo", ("ghe.example", "team/repo")),
        ("https://github.com/team/repo/", ("github.com", "team/repo")),
        ("https://token@github.com/team/repo", None),
        ("https://github.com/team/repo?token=secret", None),
        ("/tmp/remote", None),
        ("-evil", None),
    ],
)
def check_pr_repository_url(url, expected):
    if expected:
        assert pr.repository_identity(url) == expected
    else:
        with pytest.raises(wt.Blocked, match="URL without credentials"):
            pr.repository_identity(url)


@pytest.mark.parametrize(
    "failure", ["none", "urls", "rewrite", "auth", "repository", "permission"]
)
def check_pr_remote_identity(tmp_path, failure):
    url = "https://github.com/team/repo.git"
    info = {
        "url": "https://github.com/team/repo",
        "nameWithOwner": "team/repo",
        "viewerPermission": "WRITE",
    }
    if failure == "repository":
        info["nameWithOwner"] = "other/repo"
    if failure == "permission":
        info["viewerPermission"] = "READ"
    with (
        patch.object(
            wt,
            "output",
            side_effect=[url, url + ("\nother" if failure == "urls" else "")],
        ),
        patch.object(
            wt,
            "git",
            return_value=SimpleNamespace(returncode=0 if failure == "rewrite" else 1),
        ),
        patch.object(
            pr,
            "gh",
            side_effect=wt.Blocked("auth failure")
            if failure == "auth"
            else ["", json.dumps(info)],
        ),
    ):
        if failure == "none":
            assert pr.remote_identity(tmp_path)["repository"] == "team/repo"
        else:
            with pytest.raises(wt.Blocked):
                pr.remote_identity(tmp_path)


def _pr_publication():
    return dict(
        status="PREPARED",
        base="main",
        head="codex/worktree/example",
        baseCommit="base",
        candidate="candidate",
        remoteUrl="https://github.com/team/repo.git",
        repository="team/repo",
        host="github.com",
    )


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "closed",
        "merged",
        "base",
        "head",
        "sha",
        "fork",
        "url",
        "number",
        "missing",
        "multiple",
    ],
)
def check_pr_existing_identity(tmp_path, change):
    publication = _pr_publication()
    item = dict(
        number=7,
        url="https://github.com/team/repo/pull/7",
        state="OPEN",
        baseRefName="main",
        headRefName=publication["head"],
        headRefOid="candidate",
        isCrossRepository=False,
    )
    if change in {"closed", "merged"}:
        item["state"] = change.upper()
    for value, key in (
        ("base", "baseRefName"),
        ("head", "headRefName"),
        ("sha", "headRefOid"),
        ("url", "url"),
    ):
        if change == value:
            item[key] = "other"
    if change == "fork":
        item["isCrossRepository"] = True
    if change in {"number", "missing"}:
        publication["number"] = 8
    items = [] if change == "missing" else [item] * (2 if change == "multiple" else 1)
    with patch.object(pr, "gh", side_effect=[json.dumps(items), json.dumps(item)]):
        if change == "none":
            assert pr.existing_pr(tmp_path, publication) == item
        else:
            with pytest.raises(wt.Blocked):
                pr.existing_pr(tmp_path, publication)


@pytest.mark.parametrize("change", ["none", "api", "git"])
def check_pr_remote_base(tmp_path, change):
    publication = _pr_publication()
    with (
        patch.object(
            pr,
            "gh",
            return_value=json.dumps(
                {"commit": {"sha": "drift" if change == "api" else "base"}}
            ),
        ),
        patch.object(
            pr,
            "remote_heads",
            return_value={"refs/heads/main": "drift" if change == "git" else "base"},
        ),
    ):
        if change == "none":
            assert pr.remote_base(tmp_path, publication) is None
        else:
            with pytest.raises(wt.Blocked, match="base differs"):
                pr.remote_base(tmp_path, publication)
    api_base = "a" * 40
    remote_base = "b" * 40 if change == "git" else api_base
    with (
        patch.object(pr, "gh", return_value=json.dumps({"commit": {"sha": api_base}})),
        patch.object(pr, "remote_heads", return_value={"refs/heads/main": remote_base}),
    ):
        if change == "git":
            with pytest.raises(wt.Blocked, match="references differ"):
                pr.update_refs(tmp_path, publication)
        else:
            assert pr.update_refs(tmp_path, publication) == (api_base, None)
    _check_pr_integration_guard(
        tmp_path, {"none": "rewrite", "api": "conflict", "git": "fetch"}[change]
    )


def _pr_integration_git(failure, root, *args, **kwargs):
    failed = (failure == "rewrite" and "--is-ancestor" in args) or (
        failure == "conflict" and "merge-tree" in args
    )
    return SimpleNamespace(returncode=int(failed), stdout="", stderr="")


def _check_pr_integration_guard(tmp_path, failure):
    text = contract("example", ["file.txt"])
    base, candidate, old = "a" * 40, "b" * 40, "c" * 40
    publication = dict(_pr_publication(), baseCommit=old)
    state = dict(
        task_id="example",
        task_file="tasks/example.md",
        prPublication=publication,
        prUpdate=dict(
            status="PREPARED",
            candidate=candidate,
            previousCandidate=old,
            taskHash=pr.hashlib.sha256(text.encode()).hexdigest(),
        ),
    )

    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(pr, "update_snapshot", return_value=(tmp_path, text)),
        patch.object(pr, "update_refs", return_value=(base, old)),
        patch.object(pr, "existing_pr"),
        patch.object(wt.python_env, "runtime", return_value=(Path(sys.executable), {})),
        patch.object(
            wt,
            "git",
            side_effect=_bind_framework_callback(_pr_integration_git, failure),
        ),
        patch.object(
            wt, "output", return_value="d" * 40 if failure == "fetch" else base
        ),
        patch.object(pr, "validate_snapshot") as validator,
    ):
        with pytest.raises(wt.Blocked):
            pr.validate_update(tmp_path, "example")
        validator.assert_not_called()


@pytest.mark.parametrize(
    "change", ["none", "head", "commit", "base", "dirty", "task", "mode", "state"]
)
def check_pr_candidate_identity(tmp_path, change):
    text = contract("example", ["file.txt"]).replace("`running`", "`completed`")
    publication = _pr_publication()
    publication["taskHash"] = pr.hashlib.sha256(text.encode("utf-8")).hexdigest()
    state = dict(
        task_id="example",
        task_file="tasks/example.md",
        integrationMode="pr",
        branch=publication["head"],
        base="main",
        merged=None,
        tip="candidate",
        commit="candidate",
        verified=True,
        prPublication=publication,
    )
    if change == "commit":
        state["commit"] = "other"
    if change == "mode":
        state["integrationMode"] = "merge"
    path = tmp_path / "state.json"
    with (
        patch.object(
            wt,
            "load",
            return_value=(tmp_path, None, path, {} if change == "state" else state),
        ),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "base_worktree", return_value=tmp_path / "base"),
        patch.object(
            wt.tasks,
            "read_task_snapshot",
            return_value=SimpleNamespace(
                text=text + ("edit" if change == "task" else "")
            ),
        ),
        patch.object(
            wt,
            "output",
            side_effect=[
                "other" if change == "head" else "candidate",
                "other" if change == "base" else "base",
            ],
        ),
        patch.object(
            wt,
            "changed_paths",
            return_value={"file.txt"} if change == "dirty" else set(),
        ),
        patch.object(wt, "integration_task") as integration,
    ):
        if change == "none":
            assert pr.check_candidate(tmp_path, path, state) == (tmp_path, text)
            integration.assert_called_once()
        else:
            with pytest.raises(wt.Blocked, match="changed"):
                pr.check_candidate(tmp_path, path, state)


@pytest.mark.parametrize(
    "failure", ["collision", "missing", "auth", "api", "late-collision"]
)
def check_pr_publication_prewrite(tmp_path, failure):
    publication = _pr_publication()
    if failure == "missing":
        publication["status"] = "PUSHED"
    state = dict(task_id="example", prPublication=publication)
    identity = {key: publication[key] for key in ("remoteUrl", "repository", "host")}
    with (
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(pr, "check_candidate", return_value=(tmp_path, "task")),
        patch.object(
            pr,
            "remote_identity",
            side_effect=wt.Blocked("auth") if failure == "auth" else None,
            return_value=identity,
        ),
        patch.object(pr, "record"),
        patch.object(
            pr,
            "remote_base",
            side_effect=wt.Blocked("API unavailable")
            if failure == "api"
            else [None, "foreign"]
            if failure == "late-collision"
            else None,
            return_value="foreign" if failure == "collision" else None,
        ),
        patch.object(wt, "git") as git,
        patch.object(pr, "existing_pr", return_value=None) as existing,
    ):
        with pytest.raises(wt.Blocked):
            pr.publish(tmp_path, tmp_path / "state.json", state)
        git.assert_not_called()
        if failure == "late-collision":
            existing.assert_called_once()
        else:
            existing.assert_not_called()


@pytest.mark.parametrize("failure", ["none", "exit", "timeout"])
def check_pr_gh_noninteractive(tmp_path, failure):
    with patch.object(
        pr.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired("gh", 60)
        if failure == "timeout"
        else None,
        return_value=SimpleNamespace(
            returncode=1 if failure == "exit" else 0,
            stdout="{}",
            stderr="sensitive credential",
        ),
    ) as run:
        if failure == "none":
            assert pr.gh(tmp_path, "github.com", "repo", "view") == "{}"
            arguments, options = run.call_args
            assert arguments[0] == ["gh", "repo", "view"]
            assert options["env"]["GH_PROMPT_DISABLED"] == "1"
            assert options["timeout"] == 60 and "shell" not in options
        else:
            with pytest.raises(wt.Blocked) as error:
                pr.gh(tmp_path, "github.com", "auth", "status")
            assert "sensitive" not in str(error.value)


def check_pr_lock_and_mode_retention(tmp_path):
    path = tmp_path / "task.json"
    with pr.publication_lock(path):
        with pytest.raises(wt.Blocked, match="busy"):
            with pr.publication_lock(path):
                pytest.fail("double publisher")
    assert path.with_suffix(".pr-lock").is_file()
    path.with_suffix(".tmp").symlink_to(tmp_path / "foreign")
    with pytest.raises(wt.Blocked, match="redirected"):
        with pr.publication_lock(path):
            pytest.fail("redirected metadata")
    path.with_suffix(".tmp").unlink()
    state = {"merged": None, "commit": None, "integrationMode": "pr"}
    with (
        patch.object(wt, "load", return_value=(tmp_path, None, path, state)),
        patch.object(wt, "_finalize") as finalize,
    ):
        with pytest.raises(wt.Blocked, match="--create-pr"):
            wt.finalize(tmp_path, "example")
        finalize.assert_not_called()
    with pytest.raises(wt.Blocked, match="successful merge"):
        wt.cleanup_state(tmp_path, path, state)


def check_pr_existing_hook_is_preserved(tmp_path):
    hook = tmp_path / "pre-push"
    hook.write_text("Human hook\n", encoding="utf-8")
    with (
        patch.object(wt, "output", return_value=str(hook)),
        patch.object(wt, "git") as git,
    ):
        with pytest.raises(wt.Blocked, match="never replaces"):
            pr.push_candidate(tmp_path, _pr_publication())
        git.assert_not_called()
    assert hook.read_text(encoding="utf-8") == "Human hook\n"


def check_pr_git_deadline(tmp_path):
    with (
        patch.object(wt, "output", return_value=str(tmp_path / "no-hook")),
        patch.object(
            wt, "git", side_effect=subprocess.TimeoutExpired("git sensitive", 60)
        ) as git,
    ):
        for operation in (pr.remote_heads, pr.push_candidate):
            with pytest.raises(wt.Blocked) as error:
                operation(tmp_path, _pr_publication())
            assert "sensitive" not in str(error.value)
            assert git.call_args.kwargs["timeout"] == 60
            assert "core.sshCommand=ssh -o BatchMode=yes" in git.call_args.args


@pytest.mark.parametrize(
    "failure", ["ignored", "state", "branch", "path", "registered", "repair-child"]
)
def check_create_refusals_before_mutation(tmp_path, failure):
    check = TestCase()
    root = tmp_path / "primary"
    root.mkdir()
    target = root / ".worktrees/example"
    state_path = tmp_path / "state.json"
    if failure == "state":
        state_path.write_bytes(b"preserve state")
    if failure == "path":
        target.mkdir(parents=True)
        (target / "keep").write_bytes(b"human data")
    with (
        patch.object(wt, "repository", return_value=(root, root / ".git", root)),
        patch.object(wt, "state_path", return_value=state_path),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt, "base_branch", return_value="main"),
        patch.object(wt, "branch_exists", return_value=failure == "branch"),
        patch.object(
            wt,
            "worktrees",
            return_value=[dict(worktree=str(target), prunable="stale")]
            if failure == "registered"
            else [],
        ),
        patch.object(
            wt,
            "git",
            return_value=subprocess.CompletedProcess(
                [], int(failure == "ignored"), "", ""
            ),
        ) as git,
        patch.object(wt, "setup") as setup,
        patch.object(
            wt,
            "deploy_request",
            return_value=(
                root,
                state_path,
                {"iacRepair": {"childTask": "other"}},
                {"repository": str(root), "taskFile": "tasks/parent.md"},
            ),
        ),
        patch.object(
            wt.tasks,
            "read_task_snapshot",
            return_value=SimpleNamespace(
                text="## Task contract\n- Task status: `suspend`\n## Suspension reason\nAuthorized child repair\n"
            ),
        ),
    ):
        with pytest.raises(
            wt.Blocked, match="ignored|collision|another implement child"
        ):
            wt.create(
                root,
                "example",
                tmp_path / "request.json" if failure == "repair-child" else None,
            )
    setup.assert_not_called()
    check.assertEqual(git.call_count, 1)
    check.assertEqual(
        state_path.read_bytes() if state_path.exists() else None,
        b"preserve state" if failure == "state" else None,
    )
    if failure == "path":
        check.assertEqual((target / "keep").read_bytes(), b"human data")


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "locked", "prunable", "dirty", "operation"]
)
def check_base_worktree_refusals(tmp_path, failure):
    entries = [dict(branch="refs/heads/main", worktree=str(tmp_path))]
    if failure == "missing":
        entries = []
    elif failure == "duplicate":
        entries *= 2
    elif failure in ("locked", "prunable"):
        entries[0][failure] = "retain"
    original = copy.deepcopy(entries)
    with (
        patch.object(wt, "worktrees", return_value=entries),
        patch.object(
            wt,
            "idle_git",
            side_effect=wt.Blocked("operation in progress")
            if failure == "operation"
            else None,
        ),
        patch.object(
            wt,
            "git",
            return_value=subprocess.CompletedProcess(
                [], 0, "dirty" if failure == "dirty" else "", ""
            ),
        ),
    ):
        with pytest.raises(wt.Blocked, match="available worktree|dirty|operation"):
            wt.base_worktree(tmp_path, {"base": "main"})
    TestCase().assertEqual(entries, original)


def _commit_git(trace, where, *args, **kwargs):
    trace.commands.append(args)
    if (
        "diff" in args
        and "--check" in args
        and trace.failure in ("whitespace", "staged-whitespace")
        and ("--cached" in args) == (trace.failure == "staged-whitespace")
    ):
        raise subprocess.CalledProcessError(
            2, ["git", *args], stderr="trailing whitespace"
        )
    if args[0] == "commit":
        if trace.failure == "commit":
            raise subprocess.CalledProcessError(
                1, ["git", *args], stderr="commit failed"
            )
        trace.head, trace.dirty = "commit", False
    if "rebase" in args and "--abort" not in args:
        if trace.failure == "rebase":
            return subprocess.CompletedProcess([], 1, "", "conflict")
        trace.head = "rebased"
        trace.dirty = trace.failure == "dirty-rebase"
    return subprocess.CompletedProcess([], 0, "", "")


def _commit_output(trace, base, where, *args, **kwargs):
    if args == ("write-tree",):
        return "tree"
    if args == ("rev-parse", "HEAD^{tree}"):
        return "changed-tree" if trace.failure == "altered-commit" else "tree"
    if args == ("rev-parse", "HEAD^"):
        return "tip"
    if args[0] == "rev-parse" and args[1].startswith("refs/heads/"):
        return "latest"
    if where == base:
        return "advanced" if trace.failure == "base-advance" else "latest"
    return trace.head


@pytest.mark.parametrize(
    "failure",
    [
        "commit",
        "altered-commit",
        "rebase",
        "dirty-rebase",
        "base-advance",
        "rewritten",
        "whitespace",
        "staged-whitespace",
    ],
)
def check_commit_and_rebase_failure_retention(tmp_path, failure):
    check = TestCase()
    base, target = tmp_path / "base", tmp_path / "task"
    base.mkdir()
    (target / "tasks").mkdir(parents=True)
    (target / "tasks/example.md").write_text(
        contract("example", ["file.txt"]).replace("`running`", "`completed`"),
        encoding="utf-8",
    )
    source = target / "file.txt"
    source.write_bytes(b"candidate bytes")
    state = dict(
        task_id="example",
        task_file="tasks/example.md",
        base="main",
        start="start",
        tip="tip",
        commit=None,
        verified=False,
    )
    trace = SimpleNamespace(
        failure=failure,
        head="tip",
        dirty=failure
        in ("commit", "altered-commit", "whitespace", "staged-whitespace"),
        commands=[],
    )
    with (
        patch.object(
            wt,
            "changed_paths",
            side_effect=lambda root: {"file.txt"} if trace.dirty else set(),
        ),
        patch.object(wt, "integration_changed_paths", return_value={"file.txt"}),
        patch.object(wt, "_commit_preconditions", return_value="tip"),
        patch.object(wt, "base_worktree", return_value=base),
        patch.object(wt, "ancestor", return_value=failure != "rewritten"),
        patch.object(wt, "paths", return_value={"file.txt"}),
        patch.object(
            wt,
            "output",
            side_effect=_bind_framework_callback(_commit_output, trace, base),
        ),
        patch.object(
            wt, "git", side_effect=_bind_framework_callback(_commit_git, trace)
        ),
        patch.object(wt, "save"),
    ):
        with pytest.raises((wt.Blocked, subprocess.CalledProcessError)):
            wt._prepare_commit(base, tmp_path / "state.json", state, target, None)
    check.assertEqual(source.read_bytes(), b"candidate bytes")
    check.assertFalse(any(args[0] == "merge" for args in trace.commands))
    if failure == "rebase":
        check.assertIn(("rebase", "--abort"), trace.commands)
        check.assertEqual(state["tip"], "tip")
    if failure == "altered-commit":
        check.assertEqual(state["commit"], "commit")
        check.assertFalse(state["verified"])


def _cleanup_operation(trace, target, root, *args, **kwargs):
    if args[:2] == ("worktree", "remove"):
        if trace.failure == "remove_worktree":
            raise OSError("remove worktree failure")
        target.rmdir()
        trace.removed = True
    elif args[:2] == ("branch", "-D"):
        if trace.failure == "remove_branch":
            raise OSError("remove branch failure")
        trace.branch_removed = True
    else:
        raise AssertionError(f"unexpected cleanup mutation: {args}")
    return subprocess.CompletedProcess([], 0, "", "")


def _cleanup_unlink(trace, state_path, original, path, *args, **kwargs):
    if trace.failure == "remove_state" and path == state_path:
        raise OSError("remove state failure")
    return original(path, *args, **kwargs)


@pytest.mark.parametrize(
    "failure",
    ["remove_worktree", "remove_branch", "remove_import_proof", "remove_state"],
)
def check_cleanup_operation_failure_and_retry(tmp_path, failure):
    check = TestCase()
    target = tmp_path / ".worktrees/example"
    target.mkdir(parents=True)
    path = tmp_path / "state.json"
    path.write_bytes(b"preserve state")
    state = dict(
        task_id="example",
        worktree=str(target),
        branch="codex/worktree/example",
        base="main",
        tip="tip",
        merged="tip",
        commit="tip",
        task_file="tasks/example.md",
    )
    entry = dict(
        worktree=str(target), HEAD="tip", branch="refs/heads/codex/worktree/example"
    )
    trace = SimpleNamespace(failure=failure, removed=False, branch_removed=False)
    with (
        patch.object(wt, "ancestor", return_value=True),
        patch.object(
            wt, "worktrees", side_effect=lambda root: [] if trace.removed else [entry]
        ),
        patch.object(wt, "task_worktree", return_value=target),
        patch.object(wt, "deploy_cleanup_task", return_value=None),
        patch.object(wt, "cleanup_missing_worktree"),
        patch.object(wt, "integration_task"),
        patch.object(wt, "output", return_value="tip"),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(wt, "paths", return_value=set()),
        patch.object(
            wt, "branch_exists", side_effect=lambda *args: not trace.branch_removed
        ),
        patch.object(wt, "base_worktree", return_value=tmp_path),
        patch.object(
            wt,
            "git",
            side_effect=_bind_framework_callback(_cleanup_operation, trace, target),
        ),
        patch.object(
            wt,
            "discard_import_proof",
            side_effect=OSError("proof failure")
            if failure == "remove_import_proof"
            else None,
        ) as proof,
        patch.object(
            Path,
            "unlink",
            autospec=True,
            side_effect=_bind_framework_callback(
                _cleanup_unlink, trace, path, Path.unlink
            ),
        ),
    ):
        with pytest.raises(OSError) as caught:
            wt.cleanup_state(tmp_path, path, state)
        check.assertEqual(caught.value.cleanup["phase"], failure)
        check.assertEqual(path.read_bytes(), b"preserve state")
        check.assertEqual(state["merged"], "tip")
        trace.failure = None
        proof.side_effect = None
        check.assertTrue(wt.cleanup_state(tmp_path, path, state)["cleaned"])
    check.assertFalse(path.exists())
    check.assertTrue(trace.removed and trace.branch_removed)


def _recovery_output(trace, base, where, *args, **kwargs):
    if args[:2] == ("rev-parse", "HEAD"):
        return trace.base if where == base else trace.head
    if args[:2] == ("rev-list", "--count"):
        return "1"
    if args[:2] == ("rev-list", "--merges"):
        return ""
    raise AssertionError(f"unexpected recovery read: {args}")


@pytest.mark.parametrize(
    "approval", [None, "Human accepts the fixture validation failure"]
)
@pytest.mark.parametrize("repin", [False, True])
def check_reviewed_recovery_transitions(tmp_path, approval, repin):
    check = TestCase()
    old, base, reviewed = "1" * 40, "2" * 40, "3" * 40
    target, primary = tmp_path / "task", tmp_path / "primary"
    (target / "tasks").mkdir(parents=True)
    text = contract("example", ["file.txt"])
    text = text.replace("`running`", "`suspend`" if approval else "`completed`")
    if approval:
        text += "\n## Suspension reason\nsynthetic accepted failure\n"
    task = target / "tasks/example.md"
    task.write_text(text, encoding="utf-8")
    state = dict(
        task_file="tasks/example.md",
        task_id="example",
        start="0" * 40,
        tip=old,
        commit=old,
        merged=None,
        verified=True,
    )
    if approval:
        state["validation_failure_approval"] = approval
    trace = SimpleNamespace(base=base, head=old)
    path = tmp_path / "state.json"
    with (
        patch.object(wt, "load", return_value=(primary, None, path, state)),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(wt, "task_worktree", return_value=target),
        patch.object(wt, "base_worktree", return_value=primary),
        patch.object(
            wt,
            "output",
            side_effect=_bind_framework_callback(_recovery_output, trace, primary),
        ),
        patch.object(
            wt, "git", return_value=subprocess.CompletedProcess([], 0, "", "")
        ),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(wt, "paths", return_value={"file.txt"}),
        patch.object(wt, "save") as save,
        patch.object(
            wt,
            "_prepare_commit",
            side_effect=wt.Blocked(
                "rebase failed and was aborted; human review required"
            ),
        ),
    ):
        with pytest.raises(wt.Blocked, match="aborted"):
            wt.recover(primary, "example", old, base)
        original = copy.deepcopy(state["recovery"])
        check.assertEqual(
            (original["commit"], original["base"], original["count"]), (old, base, "1")
        )
        trace.head = reviewed
        if repin:
            trace.base = "4" * 40
            wt.recover(primary, "example", reviewed, trace.base, repin=True)
            check.assertEqual(state["recovery"]["previous"], original)
            old, base = reviewed, trace.base
            trace.head = "5" * 40
        wt.recover(primary, "example", old, base, finish=True)
    check.assertNotIn("recovery", state)
    check.assertEqual(
        (state["tip"], state["commit"], state["validation_base"]),
        (trace.head, trace.head, base),
    )
    check.assertEqual(
        wt.tasks.status(task.read_text(encoding="utf-8")),
        "suspend" if approval else "running",
    )
    check.assertEqual(state.get("validation_failure_approval"), approval)
    check.assertEqual(save.call_count, 3 if repin else 2)


@pytest.mark.parametrize(
    "result", [None, SimpleNamespace(returncode=0), wt._ValidatedCandidate(None, 1)]
)
def check_failed_validation_cannot_merge(result):
    with patch.object(wt, "load") as load, pytest.raises(wt.Blocked, match="no merge"):
        wt.merge_validated_candidate(result)
    load.assert_not_called()


def _pr_resume_head(trace, target, publication):
    return publication["candidate"] if trace.pushed else None


def _pr_resume_existing(trace, target, publication, *, heads=None):
    if heads is not None:
        TestCase().assertIn(publication["candidate"], heads)
    return (
        dict(url="https://github.com/team/repo/pull/7", number=7, state="OPEN")
        if trace.created
        else None
    )


def _pr_resume_push(trace, target, publication):
    trace.pushed = True
    trace.pushes += 1
    if trace.failure == "push" and not trace.failed:
        trace.failed = True
        raise wt.Blocked("lost push response")


def _pr_resume_gh(trace, target, host, *args):
    TestCase().assertEqual(args[:2], ("pr", "create"))
    trace.created = True
    trace.creates += 1
    if trace.failure == "create" and not trace.failed:
        trace.failed = True
        raise wt.Blocked("lost create response")
    return "https://github.com/team/repo/pull/7"


def _pr_resume_save(trace, path, state):
    if (
        trace.failure == "save"
        and not trace.failed
        and state["prPublication"]["status"] == "OPEN"
    ):
        trace.failed = True
        raise OSError("state save failed")
    trace.saved.append(copy.deepcopy(state))


@pytest.mark.parametrize("failure", ["push", "create", "save"])
def check_pr_intent_reconciles_without_duplicate_publication(tmp_path, failure):
    check = TestCase()
    publication = _pr_publication()
    state = dict(task_id="example", prPublication=publication)
    trace = SimpleNamespace(
        failure=failure,
        pushed=False,
        created=False,
        failed=False,
        pushes=0,
        creates=0,
        saved=[],
    )
    identity = {key: publication[key] for key in ("remoteUrl", "repository", "host")}
    with (
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(pr, "check_candidate", return_value=(tmp_path, "Task")),
        patch.object(pr, "remote_identity", return_value=identity),
        patch.object(
            pr,
            "remote_base",
            side_effect=_bind_framework_callback(_pr_resume_head, trace),
        ),
        patch.object(
            pr,
            "existing_pr",
            side_effect=_bind_framework_callback(_pr_resume_existing, trace),
        ),
        patch.object(
            pr,
            "push_candidate",
            side_effect=_bind_framework_callback(_pr_resume_push, trace),
        ),
        patch.object(
            pr, "gh", side_effect=_bind_framework_callback(_pr_resume_gh, trace)
        ),
        patch.object(
            wt, "save", side_effect=_bind_framework_callback(_pr_resume_save, trace)
        ),
    ):
        with pytest.raises((wt.Blocked, OSError)):
            pr.publish(tmp_path, tmp_path / "state.json", state)
        state = copy.deepcopy(trace.saved[-1])
        check.assertTrue(state["prPublication"]["pushIntent"])
        result = pr.publish(tmp_path, tmp_path / "state.json", state)
    check.assertEqual(result["prPublication"]["status"], "OPEN")
    check.assertEqual((trace.pushes, trace.creates), (1, 1))


def check_lifecycle_lock_refuses_busy(tmp_path):
    check = TestCase()
    with wt.lifecycle_lock(tmp_path):
        lock = wt.metadata_directory(tmp_path) / "lifecycle.lock"
        with pytest.raises(wt.Blocked, match="lifecycle busy"):
            with wt.lifecycle_lock(tmp_path):
                pytest.fail("concurrent lifecycle entered")
        check.assertTrue(lock.is_dir())
    check.assertFalse(lock.exists())


@pytest.mark.parametrize(
    "failure", ["empty", "unverified", "head", "dirty", "base", "merged", "prior"]
)
def check_pr_prepare_refuses_unvalidated_candidate(tmp_path, failure):
    publication = _pr_publication()
    state = dict(
        task_file="tasks/example.md",
        branch=publication["head"],
        base="main",
        tip="candidate",
        merged="candidate" if failure == "merged" else None,
        verified=failure != "unverified",
    )
    if failure == "prior":
        state["prPublication"] = publication
    with (
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "integration_task"),
        patch.object(
            wt, "paths", return_value=set() if failure == "empty" else {"file.txt"}
        ),
        patch.object(
            wt,
            "output",
            side_effect=[
                "other" if failure == "head" else "candidate",
                "other" if failure == "base" else "base",
            ],
        ),
        patch.object(wt, "base_worktree", return_value=tmp_path / "base"),
        patch.object(
            wt, "changed_paths", return_value={"dirty"} if failure == "dirty" else set()
        ),
        patch.object(wt, "save") as save,
    ):
        with pytest.raises(wt.Blocked, match="empty|changed|unverified"):
            pr.prepare(tmp_path, tmp_path / "state.json", state, "base", "candidate")
    save.assert_not_called()


def _repair_merge_output(trace, child, parent, target, *args):
    if target == parent:
        return trace["head"]
    values = {
        ("rev-parse", "HEAD"): "commit",
        ("rev-parse", "HEAD^"): "parent",
        ("rev-parse", "HEAD^{tree}"): "tree",
        ("log", "-1", "--format=%s"): "message",
    }
    return values.get(args, "blob")


def _repair_merge_git(trace, failure, parent, target, *args, **kwargs):
    if target == parent and args[:2] == ("merge", "--ff-only"):
        if failure == "before" and not trace["raised"]:
            trace["raised"] = True
            raise OSError("merge transport")
        trace["head"] = "commit"
        trace["merges"] += 1
        if failure == "after" and not trace["raised"]:
            trace["raised"] = True
            raise OSError("merge transport")


def _repair_saved(saved, path, state):
    saved[path] = copy.deepcopy(state)


@pytest.mark.parametrize("failure", ["before", "after"])
def check_repair_merge_intent_reconciles_once(tmp_path, failure):
    check = TestCase()
    runtime = wt._worktree_runtime()
    handoff = runtime._imports_deploy_handoff
    parent, child = tmp_path / "parent", tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    (child / "input.yaml").write_bytes(b"new")
    path, parent_path = tmp_path / "child.json", tmp_path / "parent.json"
    text = "## Task contract\n- Task status: `completed`\n"
    request = dict(
        requestId="request",
        requestPath=str(tmp_path / "request.json"),
        repository=str(parent),
        taskFile="tasks/deploy.md",
        taskDigest="digest",
        parentTip="parent",
        allowedPaths=["input.yaml"],
    )
    state = dict(
        task_file="tasks/child.md",
        deployRepair=request["requestPath"],
        deployValidation=str(tmp_path / "validation.json"),
        deployCommitIntent=dict(parent="parent", tree="tree", message="message"),
    )
    parent_state = {}
    validation = dict(
        requestId="request",
        contract=runtime.tasks.set_status(text, "running"),
        snapshot={},
    )
    saved, trace = {}, dict(head="parent", merges=0, raised=False)
    with (
        patch.object(
            wt, "load", side_effect=lambda *args: (parent, "child", path, state)
        ),
        patch.object(wt, "task_worktree", return_value=child),
        patch.object(
            wt,
            "deploy_request",
            side_effect=lambda *args: (parent, parent_path, parent_state, request),
        ),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(handoff, "locked", return_value=nullcontext()),
        patch.object(
            runtime.tasks,
            "read_task_snapshot",
            return_value=SimpleNamespace(
                text="## Task contract\n- Task status: `suspend`\n## Suspension reason\nAuthorized child repair\n"
            ),
        ),
        patch.object(wt, "integration_task"),
        patch.object(wt, "deploy_child_contract", return_value=text),
        patch.object(runtime, "read_sealed", return_value=validation),
        patch.object(runtime, "write_sealed") as seal,
        patch.object(wt, "deploy_snapshot", return_value={}),
        patch.object(handoff, "verify_inputs") as verify,
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(wt, "paths", return_value={"input.yaml"}),
        patch.object(
            wt,
            "output",
            side_effect=_bind_framework_callback(
                _repair_merge_output, trace, child, parent
            ),
        ),
        patch.object(
            wt,
            "git",
            side_effect=_bind_framework_callback(
                _repair_merge_git, trace, failure, parent
            ),
        ),
        patch.object(
            wt, "save", side_effect=_bind_framework_callback(_repair_saved, saved)
        ),
        patch.object(
            runtime,
            "_imports_deploy_contracts",
            SimpleNamespace(
                sha=runtime._imports_deploy_contracts.sha,
                subprocess_bytes=Mock(return_value=b"old"),
            ),
        ),
    ):
        with pytest.raises(OSError, match="merge transport"):
            runtime.deploy_finalize(child, "child")
        check.assertIn("deployIntegrationIntent", saved[parent_path])
        state = copy.deepcopy(saved[path])
        parent_state = copy.deepcopy(saved[parent_path])
        result = runtime.deploy_finalize(child, "child")
    check.assertEqual(trace["merges"], 1)
    check.assertEqual(result["merged"], "commit")
    check.assertEqual(parent_state["tip"], "commit")
    check.assertEqual(verify.call_args_list[0].kwargs["child_paths"], ())
    check.assertEqual(verify.call_args_list[1].kwargs["child_paths"], ["input.yaml"])
    seal.assert_called_once()


@pytest.mark.parametrize("failure", ["validator", "inputs", "contract", "limit"])
def check_repair_static_failure_preserves_inputs(tmp_path, failure):
    check = TestCase()
    runtime = wt._worktree_runtime()
    handoff = runtime._imports_deploy_handoff
    request = dict(
        requestPath=str(tmp_path / "request.json"),
        parentTip="parent",
        allowedPaths=["input.yaml"],
    )
    text = "## Task contract\n- Task status: `running`\n"
    state = dict(
        task_file="tasks/child.md",
        deployRepair=request["requestPath"],
        start="parent",
        tip="parent",
        repairStaticRuns=3 if failure == "limit" else 0,
    )
    source = tmp_path / "input.yaml"
    source.write_bytes(b"approved bytes")
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, "child", tmp_path / "state.json", state)
        ),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(
            wt,
            "deploy_request",
            return_value=(tmp_path, tmp_path / "parent.json", {}, request),
        ),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(handoff, "locked", return_value=nullcontext()),
        patch.object(wt, "deploy_child_contract", return_value=text),
        patch.object(wt, "output", return_value="parent"),
        patch.object(handoff, "verify_inputs"),
        patch.object(
            wt,
            "deploy_snapshot",
            side_effect=[{}, {"changed": True} if failure == "inputs" else {}],
        ),
        patch.object(wt, "save"),
        patch.object(runtime.python_env, "runtime", return_value=(sys.executable, {})),
        patch.object(
            runtime.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], int(failure == "validator"), "output", "error"
            ),
        ) as run,
        patch.object(
            runtime.tasks,
            "read_task_snapshot",
            return_value=SimpleNamespace(
                text=text + "# changed" if failure == "contract" else text
            ),
        ),
        patch.object(runtime.tasks, "suspend") as suspend,
        patch.object(runtime, "write_sealed") as seal,
    ):
        with pytest.raises(wt.Blocked, match="static"):
            runtime.deploy_validate(tmp_path, "child", Path(request["requestPath"]))
    check.assertEqual(source.read_bytes(), b"approved bytes")
    check.assertEqual(state["repairStaticRuns"], 3 if failure == "limit" else 1)
    check.assertEqual(run.call_count, int(failure != "limit"))
    check.assertEqual(suspend.call_count, int(failure != "limit"))
    seal.assert_not_called()


@pytest.mark.parametrize("draft", [False, True])
def check_pr_draft_and_closed_state(tmp_path, draft):
    publication = _pr_publication()
    item = dict(
        number=7,
        url="https://github.com/team/repo/pull/7",
        state="MERGED",
        isDraft=draft,
        baseRefName="main",
        headRefName=publication["head"],
        headRefOid="candidate",
        isCrossRepository=False,
    )
    assert "isDraft" in pr.PR_FIELDS.split(",")
    with patch.object(pr, "gh", side_effect=[json.dumps([item]), json.dumps(item)]):
        assert (
            pr.existing_pr(tmp_path, publication, states=("MERGED",))["isDraft"]
            is draft
        )


@pytest.mark.parametrize(
    "published,descendant,changed",
    [(None, True, False), ("old", True, True), ("old", False, False)],
)
def check_pr_update_commit_boundary(tmp_path, published, descendant, changed):
    state = dict(
        tip="old",
        commit="old",
        verified=True,
        branch="codex/worktree/example",
        task_file="tasks/example.md",
    )
    text = contract("example", ["file.txt"])
    with (
        patch.object(wt, "idle_git"),
        patch.object(wt.tasks, "validate_contract"),
        patch.object(wt, "output", return_value="new"),
        patch.object(wt, "ancestor", return_value=descendant),
    ):
        if published and descendant:
            assert (
                wt._commit_preconditions(
                    tmp_path,
                    state,
                    {"file.txt"} if changed else set(),
                    text,
                    None,
                    scope_paths={"file.txt"},
                    published_head=published,
                )
                == "new"
            )
        else:
            with pytest.raises(wt.Blocked):
                wt._commit_preconditions(
                    tmp_path,
                    state,
                    set(),
                    text,
                    None,
                    scope_paths={"file.txt"},
                    published_head=published,
                )


@pytest.mark.parametrize(
    "arguments,valid",
    [
        (["finalize", "--task-id", "example", "--create-pr", "--draft"], True),
        (["finalize", "--task-id", "example", "--draft"], False),
        (["cleanup", "--task-id", "example", "--draft"], False),
        (["branches"], True),
        (["branch-delete", "--branch", "codex/worktree/example"], True),
        (["branch-delete"], False),
        (["pr-close", "--pr", "7"], True),
        (["pr-close"], False),
        (["pr-update", "--task-id", "example", "--create-pr"], False),
    ],
)
def check_pr_lifecycle_cli(tmp_path, capsys, arguments, valid):
    with (
        patch.object(sys, "argv", ["worktree_task.py", *arguments]),
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", {})
        ),
        patch.object(wt, "finalize", return_value={}) as finalize,
        patch.object(wt, "branches", return_value={}),
        patch.object(wt, "delete_branch", return_value={}),
        patch.object(pr, "close_existing", return_value={}),
    ):
        if valid:
            assert wt.main() == 0
            if arguments[0] == "finalize":
                assert finalize.call_args.kwargs["draft"] is True
        else:
            with pytest.raises(SystemExit) as error:
                wt.main()
            assert error.value.code == 2
    capsys.readouterr()


@pytest.mark.parametrize(
    "failure",
    [
        "unchanged",
        "remote-head",
        "validation",
        "validation-detail",
        "validated-edit",
        "suspended",
        "stale-base",
        "push-third",
        "hash-changed",
        "legacy-review",
        "legacy-stale",
        "published-valid",
        "published-unverified",
    ],
)
def check_pr_update_failure_retains_candidate(tmp_path, failure):
    if failure in {
        "legacy-review",
        "legacy-stale",
        "published-valid",
        "published-unverified",
    }:
        _check_pr_update_published_recovery(tmp_path, failure)
        return
    publication = dict(_pr_publication(), number=7)
    state = dict(
        task_id="example",
        task_file="tasks/example.md",
        integrationMode="pr",
        merged=None,
        prPublication=publication,
        tip="candidate",
        commit="candidate",
        verified=True,
    )
    text = contract("example", ["file.txt"])
    if failure == "suspended":
        text = (
            text.replace("`running`", "`suspend`")
            + "\n## Suspension reason\n\n    validation failed\n"
        )
    if failure in {
        "validation",
        "validation-detail",
        "validated-edit",
        "suspended",
        "stale-base",
        "push-third",
        "hash-changed",
    }:
        publication["candidate"] = "old"
        state["prUpdate"] = dict(
            status="VALIDATED"
            if failure in {"validated-edit", "stale-base", "push-third", "hash-changed"}
            else "PREPARED",
            previousCandidate="old",
            candidate="candidate",
            taskHash=pr.hashlib.sha256(text.encode()).hexdigest()
            if failure == "stale-base"
            else "hash",
            baseCommit="base",
            integrationTree="a" * 40,
            validation="PASS",
            pushIntent=failure == "push-third",
        )
    path = tmp_path / "state.json"
    with (
        patch.object(wt, "load", return_value=(tmp_path, None, path, state)),
        patch.object(pr, "publication_lock", return_value=nullcontext()),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(pr, "remote_identity", return_value={}),
        patch.object(pr, "existing_pr"),
        patch.object(
            pr,
            "remote_heads",
            return_value={"refs/heads/" + publication["head"]: "foreign"},
        ),
        patch.object(
            pr,
            "update_refs",
            return_value=(
                "new-base" if failure == "stale-base" else "base",
                "foreign" if failure in {"remote-head", "push-third"} else "candidate",
            ),
        ),
        patch.object(wt, "task_worktree", return_value=tmp_path),
        patch.object(wt, "output", return_value="candidate"),
        patch.object(
            wt,
            "changed_paths",
            return_value={"file.txt"} if failure == "validated-edit" else set(),
        ),
        patch.object(
            wt.tasks, "read_task_snapshot", return_value=SimpleNamespace(text=text)
        ),
        patch.object(wt, "save"),
        patch.object(pr, "save_update"),
        patch.object(wt.python_env, "runtime", return_value=(Path(sys.executable), {})),
        patch.object(
            pr.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [],
                2,
                "case-id",
                (
                    'PR_VALIDATOR_DIAGNOSTICS={"returncode": 7, "stdout": "validator output", "stderr": "specific reason"}\n'
                    if failure == "validation-detail"
                    else "validation diagnostic"
                ),
            ),
        ) as child,
        patch.object(pr, "push_candidate") as push,
    ):
        with pytest.raises(wt.Blocked) as error:
            pr.update(tmp_path, "example")
        push.assert_not_called()
        if failure in {"validation", "validation-detail"}:
            assert error.value.diagnostics == (
                dict(returncode=7, stdout="validator output", stderr="specific reason")
                if failure == "validation-detail"
                else dict(
                    returncode=2, stdout="case-id", stderr="validation diagnostic"
                )
            )
            assert state["prUpdate"]["status"] == "PREPARED"
            assert "validate_update" in child.call_args.args[0][3]
        else:
            child.assert_not_called()
            if failure in {"unchanged", "remote-head"}:
                assert "prUpdate" not in state
            if failure == "suspended":
                assert "`suspend`" in text
            if failure == "stale-base":
                assert state["prUpdate"]["validation"] == "STALE"
                assert state["prUpdate"]["status"] == "PREPARED"


def _check_pr_update_published_recovery(tmp_path, failure):
    status, validation, confirmed = {
        "legacy-review": ("PUBLISHED_REVIEW", "STALE", True),
        "legacy-stale": ("PREPARED", "STALE", True),
        "published-valid": ("VALIDATED", "PASS", False),
        "published-unverified": ("VALIDATED", "PASS", False),
    }[failure]
    valid = failure != "published-unverified"
    old, candidate, base = "a" * 40, "b" * 40, "c" * 40
    publication = dict(
        _pr_publication(), number=7, candidate=candidate if confirmed else old
    )
    intent = dict(
        status=status,
        validation=validation,
        pushConfirmed=confirmed,
        pushIntent=True,
        candidate=candidate,
        previousCandidate=old,
        baseCommit=base,
        integrationTree="d" * 40 if valid else "",
        taskHash="e" * 64,
    )
    state = dict(
        task_id="example",
        integrationMode="pr",
        merged=None,
        prPublication=publication,
        prUpdate=intent,
    )
    with (
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", state)
        ),
        patch.object(pr, "publication_lock", return_value=nullcontext()),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(pr, "remote_identity", return_value={}),
        patch.object(
            pr,
            "remote_heads",
            return_value={"refs/heads/" + publication["head"]: candidate},
        ),
        patch.object(pr, "existing_pr"),
        patch.object(wt, "save"),
        patch.object(pr, "push_candidate") as push,
        patch.object(pr, "update_snapshot") as snapshot,
    ):
        if valid:
            result = pr.update(tmp_path, "example")
            assert "prUpdate" not in result
            assert (
                publication["publishedHead"] == candidate
                and publication["baseCommit"] == base
            )
        else:
            with pytest.raises(wt.Blocked, match="lacks validated"):
                pr.update(tmp_path, "example")
        push.assert_not_called()
        snapshot.assert_not_called()


def _pr_merge_response(publication, merged, *_args):
    if merged:
        publication.update(state="MERGED", mergeCommit=dict(oid="a" * 40))
    raise wt.Blocked("uncertain merge response")


@pytest.mark.parametrize("merged", [False, True])
def check_pr_merge_response_is_reconciled_without_repeating(tmp_path, merged):
    check = TestCase()
    publication = dict(_pr_publication(), number=7)
    state = dict(integrationMode="pr", merged=None, prPublication=publication)
    record = dict(state="OPEN", number=7, isDraft=False)
    path = tmp_path / "state.json"
    with (
        patch.object(wt, "load", return_value=(tmp_path, None, path, state)),
        patch.object(pr, "publication_lock", return_value=nullcontext()),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(pr, "remote_identity", return_value={}),
        patch.object(pr, "existing_pr", return_value=record),
        patch.object(wt, "save"),
        patch.object(
            pr,
            "gh",
            side_effect=_bind_framework_callback(_pr_merge_response, record, merged),
        ) as gh,
        patch.object(wt, "cleanup_state", return_value="cleaned") as cleanup,
    ):
        with pytest.raises(wt.Blocked, match="uncertain merge"):
            pr.operate(tmp_path, "example", "pr-merge")
        check.assertTrue(publication["mergeIntent"])
        check.assertEqual(
            pr.operate(tmp_path, "example", "pr-status"), "cleaned" if merged else state
        )
        gh.assert_called_once()
        check.assertEqual(cleanup.call_count, int(merged))
        check.assertEqual(state["merged"], "a" * 40 if merged else None)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
