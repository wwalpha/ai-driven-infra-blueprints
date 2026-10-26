#!/usr/bin/env python3
"""Ordinary integration guard runtime and pre-write boundaries, using synthetic inputs."""

import copy
import sys
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import builtins
import json
import os
import subprocess
from unittest.mock import patch

import pytest
import worktree_state
import worktree_task as wt
from support.worktree_task_fixtures import contract
from utils.git_changes import GitWorkingPaths

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_registered_guard_process_child(
    guard_source, real_run, /, command, **kwargs
):
    command = list(command)
    at = command.index("-c") + 1
    command[at] = (
        f'import sys, types; sys.path.insert(0, {str(Path(wt.__file__).parent)!r}); stub = types.ModuleType("import_guard"); '
        + "exec("
        + repr(guard_source)
        + ", stub.__dict__); "
        + 'sys.modules["import_guard"] = stub; '
        + command[at]
    )
    return real_run(command, **kwargs)


def _callback_check_registered_guard_process_missing_parent_dependency(
    real_import, /, name, *args, **kwargs
):
    if name in ("import_guard", "pystache", "yaml"):
        raise ModuleNotFoundError("parent lacks Model dependencies")
    return real_import(name, *args, **kwargs)


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("outcome", ["success", "reject", "launch", "runtime"])
def check_registered_guard_process(tmp_path, capsys, approved, outcome):
    task = "tasks/selected.md"
    (tmp_path / "tasks").mkdir()
    (tmp_path / task).write_text(contract("selected", ["file.txt"]))
    guard_source = """import sys, os
from pathlib import Path
import task_contract as tasks
def require_import_changes(root, **kwargs):
    assert root == Path.cwd()
    assert tasks.contract_path(root).relative_to(root).as_posix() == sys.argv[1]
    assert kwargs == ({'contract_file': sys.argv[1]} if sys.argv[2] == 'approved' else {})
    print('stdout diagnostic')
    print('warning: synthetic reference', file=sys.stderr)
    if os.environ['GUARD_OUTCOME'] == 'reject':
        raise ValueError('guard rejection')
"""
    environment = {
        **os.environ,
        "BLUEPRINT_TASK_FILE": "tasks/foreign.md",
        "GUARD_OUTCOME": outcome,
    }
    real_run = wt.subprocess.run
    child = _bind_framework_callback(
        _callback_check_registered_guard_process_child, guard_source, real_run
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
def check_cleanup_missing_worktree(tmp_path, case):
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
        if case == "clean":
            wt.cleanup_missing_worktree(tmp_path, state, entry)
            assert idle.call_args.kwargs["runner"].keywords == {"directory": directory}
        else:
            with pytest.raises(wt.Blocked):
                wt.cleanup_missing_worktree(tmp_path, state, entry)
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
    wt.git(root, "init", "-q")
    wt.git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    if linked:
        target = tmp_path / ("linked " + directory)
        wt.git(root, "worktree", "add", "-qb", "linked", target)
        root = target
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
    # A real unmerged index, independent of operation markers.
    (root / "conflict.txt").write_text("conflict\n", encoding="utf-8")
    blob = wt.output(root, "hash-object", "-w", "conflict.txt")
    index = "".join(f"100644 {blob} {stage}\tconflict.txt\n" for stage in (1, 2, 3))
    subprocess.run(
        ["git", "update-index", "--index-info"],
        cwd=root,
        input=index,
        encoding="utf-8",
        check=True,
    )
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
    wt.git(root, "read-tree", "HEAD")
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
        "pendingObserved",
        "success",
        "observedError",
        "running",
        "pollError",
    ],
)
def check_checkpoint_observed_barrier(tmp_path, pending):
    handoff = wt._worktree_runtime().deploy_handoff
    journal = handoff.operation_journal
    same = pending == "generation-only"
    identities = [
        str(tmp_path / ".git"),
        str(tmp_path / (".git" if same else "other.git")),
    ]
    with patch.object(
        journal.worktree_state,
        "output",
        side_effect=OSError("missing checkout") if pending == "success" else identities,
    ):
        assert journal.same_repository(tmp_path, tmp_path / "previous") == same
    target = {"awsAccountId": "account", "awsRegion": "region"}
    request = {
        "target": target,
        "diagnosis": {"Peer": {"inputRefs": [], "modelRefs": []}},
        "allowedPaths": [],
    }
    publication = {
        "repository": str(tmp_path),
        "pendingGeneration": {
            "view": {
                "generated": {
                    "outputs": None,
                    "originals": {"docs/designs/peer.md": None},
                },
                "producers": [],
            }
        },
    }
    state = {"status": "SUCCESS", "observedSynced": True}
    if pending in {"pendingObserved", "observedError"}:
        publication["pendingObserved"] = {"stage": "PREPARED", "evidence": {"Peer": {}}}
    elif pending == "success":
        state["observedSynced"] = False
    elif pending in {"running", "pollError"}:
        state["status"] = "RUNNING"
    record = {
        "target": target,
        "publication": publication,
        "operations": {"Peer": {"state": state}},
    }
    with patch.object(journal, "read", return_value=[record]):
        if pending == "generation-only":
            handoff.require_settled(tmp_path, request)
        else:
            with pytest.raises(handoff.Blocked, match="unfinished"):
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
    records = [{"target": target, "publication": publication, "operations": {}}]
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
        patch.object(journal, "read", return_value=records),
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


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
