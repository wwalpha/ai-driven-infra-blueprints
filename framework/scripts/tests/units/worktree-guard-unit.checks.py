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
from validation import loop

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_registered_guard_process_missing_parent_dependency(
    real_import, /, name, *args, **kwargs
):
    if name in ("import_guard", "pystache", "yaml"):
        raise ModuleNotFoundError("parent lacks Model dependencies")
    return real_import(name, *args, **kwargs)


@pytest.mark.parametrize("outcome", ["success", "reject", "launch", "runtime"])
def check_registered_guard_process(tmp_path, capsys, outcome):
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
                wt._run_model_guard(tmp_path, task)
            runtime.side_effect = None
            runtime.return_value = None
            with pytest.raises(
                wt.Blocked, match="registered Python runtime is missing"
            ):
                wt._run_model_guard(tmp_path, task)
        elif outcome == "launch":
            with (
                patch.object(
                    wt.subprocess, "run", side_effect=OSError("cannot launch")
                ),
                pytest.raises(OSError),
            ):
                wt._run_model_guard(tmp_path, task)
        elif outcome == "reject":
            with pytest.raises(wt.Blocked) as caught:
                wt._run_model_guard(tmp_path, task)
            assert caught.value.diagnostics["returncode"] == 1
            assert caught.value.diagnostics["stdout"] == "stdout diagnostic\n"
            assert "guard rejection" in caught.value.diagnostics["stderr"]
        else:
            wt._run_model_guard(tmp_path, task)
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
                command[4:], [task, "null"]
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
            wt._prepare_commit(tmp_path, tmp_path / "state.json", state, tmp_path)
        assert called.call_count == (
            0
            if violation
            in ("head", "unverified", "committed-dirty", "scope", "operation")
            else 1
        )
    assert state["commit"] == (
        "tip" if violation in ("unverified", "committed-dirty") else None
    )


@pytest.mark.parametrize("args", [
    ["branches"],
    ["recover", "--task-id", "example"],
    ["pr-retry-create", "--task-id", "example"],
    ["finalize", "--task-id", "example", "--finish-recovery"],
    ["finalize", "--task-id", "example", "--repin-recovery"],
    ["finalize", "--task-id", "example", "--expected-task-base", "base"],
    ["finalize", "--task-id", "example", "--human-approved-validation-failure", "approval"],
    ["create", "--task-id", "example"],
    ["deploy-start", "--task-name", "example"],
    ["finalize", "--task-name", "example"],
])
def check_removed_lifecycle_cli(args):
    with patch.object(sys, "argv", ["worktree_task.py", *args]), pytest.raises(SystemExit) as error:
        wt.main()
    assert error.value.code == 2


def check_creation_failure_reports_retained_task(tmp_path, capsys):
    creation = {
        "task_name": "example", "task_id": "example-000000",
        "primary": str(tmp_path), "worktree": str(tmp_path / "retained"),
        "branch": "codex/worktree/example-000000", "task_file": "tasks/example-000000.md",
    }
    Path(creation["worktree"]).mkdir()
    error = wt.Blocked("failed to save lifecycle")
    error.creation = creation
    with (
        patch.object(sys, "argv", ["worktree_task.py", "create", "--task-name", "example"]),
        patch.object(wt, "create", side_effect=error) as create,
        patch.object(wt, "load", side_effect=wt.Blocked("missing lifecycle")),
        patch.object(wt, "branch_exists", return_value=True),
    ):
        assert wt.main() == 1
    assert create.call_count == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked" and output["error"] == str(error)
    assert output["task_id"] == creation["task_id"]
    assert output["remaining_worktree"] == creation["worktree"]
    assert output["remaining_branch"] == creation["branch"]


def check_integration_failure_preserves_running_task(tmp_path):
    task = "tasks/example.md"
    (tmp_path / "tasks").mkdir()
    text = contract("example", ["file.txt"])
    (tmp_path / task).write_text(text)
    change = tmp_path / "file.txt"
    change.write_text("retain candidate")
    candidate = wt.FinalCandidate(tmp_path, tmp_path, task, text, "base", "head", frozenset({"file.txt"}), frozenset())
    with (
        patch.object(wt, "prepare_integration", return_value=candidate),
        patch.object(wt, "changed_paths", return_value=set()),
        patch.object(wt, "output", return_value="head"),
        patch.object(loop, "task_path", side_effect=ValueError("validation preflight failed")),
        patch.object(loop, "suspend_selected") as suspend_selected,
        patch.object(wt.tasks, "suspend") as suspend,
        pytest.raises(wt.Blocked, match="validation preflight failed"),
    ):
        wt._integrate_model(tmp_path, "example")
    suspend.assert_not_called()
    suspend_selected.assert_not_called()
    assert (tmp_path / task).read_text() == text
    assert change.read_text() == "retain candidate"


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


@pytest.mark.parametrize("discard", [False, True])
def check_cleanup_missing_worktree(tmp_path, discard):
    target = tmp_path / ".worktrees/example"
    state = dict(worktree=str(target), branch="codex/worktree/example",
                 base="main", merged="tip", commit="tip")
    path = tmp_path / "example.json"
    path.write_text("retained")
    with (
        patch.object(wt, "ancestor", return_value=True),
        patch.object(wt, "branch_exists", return_value=True),
        patch.object(wt, "git") as git,
        pytest.raises(wt.Blocked, match="exact Git registration") as caught,
    ):
        wt.cleanup_state(tmp_path, path, state, discard=discard)
    git.assert_not_called()
    assert caught.value.cleanup["remaining"]["git_registration"] is None
    assert path.read_text() == "retained"


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
    for name in ("HEAD", "index"):
        (target / name).touch()
    if case == "setup_busy":
        path.with_suffix(".setup-lock").mkdir()
    with (
        patch.object(
            wt,
            "ancestor",
            side_effect=[True, False] if case == "rewritten" else None,
            return_value=True,
        ),
        patch.object(worktree_state, "_repository_identity", return_value=(tmp_path, tmp_path / ".git")),
        patch.object(worktree_state, "task_git_directory", return_value=target),
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
            wt, "output", side_effect=lambda root, *args: str(target)
            if args[0] == "for-each-ref" else
            "changed" if case == "branch_changed" else
            (_ for _ in ()).throw(wt.Blocked("missing branch")) if case == "missing_branch" else "tip"
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
        patch.object(wt, "branch_exists", return_value=True),
    ):
        assert wt.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["cleanup"]["phase"] == "preflight"
    assert (
        result["cleanup"]["stop_reason"] == result["error"] == "worktree lifecycle busy"
    )
    assert result["cleanup"]["remaining"] == dict(
        worktree=False, git_registration=None, branch=True, task_state=True
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


@pytest.mark.parametrize("status", ["running", "suspend", "completed"])
def check_integration_status(tmp_path, status):
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
        if status == "completed":
            wt.integration_task(tmp_path, {"task_file": "tasks/example.md"})
        else:
            with pytest.raises(wt.Blocked):
                wt.integration_task(
                    tmp_path, {"task_file": "tasks/example.md"}
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
        "taskFile": "tasks/deploy.md",
        "taskDigest": "digest",
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
            handoff.deploy_progress,
            "progress_path",
            return_value=SimpleNamespace(exists=lambda: True),
        ),
        patch.object(handoff, "task_snapshot", return_value=SimpleNamespace(task_digest="digest")),
        patch.object(
            handoff.deploy_progress, "read_task", return_value={"runContext": context}
        ),
        patch.object(handoff, "dependency_reader", return_value=Mock()),
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
    "case", ["independent", "publication-overlap", "repair-active"]
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
            handoff.deploy_progress,
            "progress_path",
            return_value=SimpleNamespace(exists=lambda: True),
        ),
        patch.object(handoff, "task_snapshot", return_value=SimpleNamespace(task_digest="digest")),
        patch.object(
            handoff.deploy_progress,
            "read_task",
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


@pytest.mark.parametrize("change", ["none", "api", "git", "missing"])
def check_pr_remote_base(tmp_path, change):
    publication = _pr_publication()
    api_base = "b" * 40 if change == "api" else "a" * 40
    git_base = "b" * 40 if change == "git" else "a" * 40
    refs = {} if change == "missing" else {"refs/heads/main": git_base}
    with (
        patch.object(pr, "gh", return_value=json.dumps({"commit": {"sha": api_base}})),
        patch.object(pr, "remote_heads", return_value=refs),
    ):
        if change == "missing":
            with pytest.raises(wt.Blocked):
                pr.remote_base(tmp_path, publication)
            with pytest.raises(wt.Blocked):
                pr.update_refs(tmp_path, publication)
        else:
            assert pr.remote_base(tmp_path, publication) is None
            if change in {"api", "git"}:
                with pytest.raises(wt.Blocked):
                    pr.update_refs(tmp_path, publication)
            else:
                assert pr.update_refs(tmp_path, publication) == (api_base, None)


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "head",
        "commit",
        "base",
        "dirty",
        "task",
        "mode",
        "state",
        "worktree",
        "operation",
        "repository",
        "redirect",
    ],
)
def check_pr_candidate_identity(tmp_path, change):
    text = contract("example", ["file.txt"]).replace("`running`", "`completed`")
    publication = _pr_publication()
    publication["taskHash"] = pr.hashlib.sha256(text.encode("utf-8")).hexdigest()
    state = dict(
        task_id="example",
        primary=str(tmp_path),
        worktree=str(tmp_path),
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
            wt.worktree_state,
            "load_candidate",
            return_value=(tmp_path, None, path, {} if change == "state" else state),
        ),
        patch.object(
            wt,
            "task_worktree",
            side_effect=wt.Blocked("worktree changed")
            if change in {"worktree", "operation", "repository", "redirect"}
            else None,
            return_value=tmp_path,
        ),
        patch.object(wt, "base_worktree", return_value=tmp_path / "base"),
        patch.object(
            wt.tasks,
            "read_task_snapshot",
            return_value=SimpleNamespace(
                text=text + ("edit" if change == "task" else "")
            ),
        ) as snapshot,
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
        if change in {"none", "base"}:
            assert pr.check_candidate(tmp_path, path, state) == (tmp_path, text)
            integration.assert_called_once()
        else:
            with pytest.raises(wt.Blocked, match="changed|another repository"):
                pr.check_candidate(tmp_path, path, state)
            if change in {"state", "repository", "redirect"}:
                snapshot.assert_not_called()


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


@pytest.mark.parametrize("failure", ["none", "exit", "api", "timeout"])
def check_pr_gh_noninteractive(tmp_path, failure):
    with patch.object(
        pr.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired("gh", 60)
        if failure == "timeout"
        else None,
        return_value=SimpleNamespace(
            returncode=1 if failure in {"exit", "api"} else 0,
            stdout="{}",
            stderr="sensitive credential (HTTP 422)"
            if failure == "api"
            else "sensitive credential",
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
            if failure == "api":
                assert "HTTP 422" in str(error.value)
            if failure == "exit":
                assert "exit 1" in str(error.value)


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


def _creation_git(failure, target, /, root, *args, **kwargs):
    assert args[:2] != ("worktree", "list")
    if args[0] == "check-ignore":
        return subprocess.CompletedProcess(args, int(failure == "ignored"), "", "")
    if args[:2] == ("worktree", "add") and str(target) in args:
        if failure == "registered":
            return subprocess.CompletedProcess(args, 128, "", f"fatal: '{target}' is a missing but already registered worktree;")
        if failure == "git":
            return subprocess.CompletedProcess(args, 128, "", "Permission denied")
    return subprocess.CompletedProcess(args, 0, "", "")


@pytest.mark.parametrize("failure", ["ignored", "state", "publication-lock", "branch", "path", "contract", "registered", "git", "all"])
def check_create_refusals_before_mutation(tmp_path, failure):
    target = tmp_path / ".worktrees/example-000000"
    state_path = wt.state_path(tmp_path, "example-000000")
    collision = {
        "state": state_path,
        "publication-lock": state_path.with_suffix(".pr-lock"),
        "path": target / "keep",
        "contract": tmp_path / "tasks/example-000000.md",
    }.get(failure)
    if collision:
        collision.parent.mkdir(parents=True)
        collision.write_bytes(b"preserve bytes")

    with (
        patch.object(wt, "repository", return_value=(tmp_path, tmp_path / ".git", tmp_path)),
        patch.object(wt, "base_branch", return_value="main"),
        patch.object(wt, "output", side_effect=lambda root, *args: "start" if args[0] == "rev-parse" else ""),
        patch.object(wt, "branch_exists", side_effect=lambda root, branch: failure == "all" or (failure == "branch" and branch.endswith("-000000"))),
        patch.object(wt, "git", side_effect=_bind_framework_callback(_creation_git, failure, target)) as git,
        patch.object(wt, "setup", side_effect=lambda root, task_id: json.loads(wt.state_path(root, task_id).read_text())) as setup,
        patch.object(wt.secrets, "randbelow", side_effect=[0] * 20 if failure == "all" else [0, 42]) as random,
    ):
        if failure in {"ignored", "git", "all"}:
            with pytest.raises(wt.Blocked, match="ignored|Permission denied|20 collisions"):
                wt.create(tmp_path, "example")
            setup.assert_not_called()
        else:
            state = wt.create(tmp_path, "example")
            assert state["task_name"] == "example"
            assert state["task_id"] == "example-000042"
        assert random.call_count == (20 if failure == "all" else 1 if failure in {"ignored", "git"} else 2)
        assert all(call.args == (1_000_000,) for call in random.call_args_list)
        assert not (tmp_path / ".worktrees/.blueprint/lifecycle.lock").exists()
        if failure == "all":
            git.assert_not_called()
    if collision:
        assert collision.read_bytes() == b"preserve bytes"


@pytest.mark.parametrize("failure", ["branch", "dirty", "operation"])
def check_base_worktree_refusals(tmp_path, failure):
    with (
        patch.object(wt, "repository", return_value=(tmp_path, tmp_path / ".git", tmp_path)),
        patch.object(wt, "output", return_value="other" if failure == "branch" else "main"),
        patch.object(
            wt, "idle_git",
            side_effect=wt.Blocked("operation in progress") if failure == "operation" else None,
        ),
        patch.object(wt, "git", return_value=subprocess.CompletedProcess([], 0, "dirty", "")),
        pytest.raises(wt.Blocked, match="primary worktree|dirty|operation"),
    ):
        wt.base_worktree(tmp_path, {"base": "main"})


def check_shared_records_reject_other_repository(tmp_path):
    with (
        patch.object(
            worktree_state,
            "_repository_identity",
            side_effect=[
                (tmp_path, tmp_path / "expected.git"),
                (tmp_path / "other", tmp_path / "other.git"),
            ],
        ),
        pytest.raises(wt.Blocked, match="another repository"),
    ):
        worktree_state.load_candidate(tmp_path, {"primary": str(tmp_path / "other")})


def check_candidate_primary_identity_is_reused(tmp_path):
    state = {"primary": str(tmp_path), "task_id": "example"}
    expected = (tmp_path, tmp_path / "git", tmp_path / "state", state)
    with (
        patch.object(
            worktree_state,
            "_repository_identity",
            return_value=(tmp_path, tmp_path / "git"),
        ) as identity,
        patch.object(worktree_state, "_load", return_value=expected),
    ):
        TestCase().assertEqual(worktree_state.load_candidate(tmp_path, state), expected)
        identity.assert_called_once_with(tmp_path)


def check_candidate_rejects_redirect_before_task_read(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(repository)], check=True, capture_output=True
    )
    target = tmp_path / "redirected"
    target.symlink_to(repository, target_is_directory=True)
    _, common = worktree_state._repository_identity(repository)
    path = tmp_path / "state.json"
    state = {"worktree": str(target), "prPublication": {}}
    with (
        patch.object(
            worktree_state,
            "load_candidate",
            return_value=(tmp_path, common, path, state),
        ),
        patch.object(wt.tasks, "read_task_snapshot") as snapshot,
        pytest.raises(wt.Blocked, match="redirected"),
    ):
        pr.check_candidate(repository, path, state)
    snapshot.assert_not_called()


@pytest.mark.parametrize("change", ["branch", "detached", "locked", "backlink", "operation"])
def check_late_task_worktree_refusals(tmp_path, change):
    target = tmp_path / ".worktrees/example"
    common = tmp_path / ".git"
    directory = common / "worktrees/example"
    target.mkdir(parents=True)
    directory.mkdir(parents=True)
    gitfile = target / ".git"
    gitfile.write_text(f"gitdir: {directory}\n")
    (directory / "gitdir").write_text(str(tmp_path if change == "backlink" else gitfile))
    if change == "locked":
        (directory / "locked").touch()
    state = {"worktree": str(target), "branch": "codex/worktree/example"}
    ref = "refs/heads/codex/worktree/example"
    with (
        patch.object(worktree_state, "_repository_identity", return_value=(target, common)),
        patch.object(worktree_state, "output", side_effect=[
            str(directory), {"branch": "refs/heads/other", "detached": ""}.get(change, ref),
            "head", "head",
        ]),
        patch.object(worktree_state, "idle_git", side_effect=wt.Blocked("operation in progress") if change == "operation" else None),
        pytest.raises(wt.Blocked, match="branch changed|locked or mismatched|operation in progress"),
    ):
        worktree_state.task_worktree(tmp_path, state)


@pytest.mark.parametrize("changed", [False, True])
def check_pr_record_update_cleanup_is_atomic(tmp_path, changed):
    state = {
        "prPublication": {"previousCandidate": "old"},
        "prUpdate": {"status": "VALIDATED"},
    }
    before = copy.deepcopy(state)
    with (
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(
            pr,
            "check_candidate",
            side_effect=wt.Blocked("changed") if changed else None,
        ),
        patch.object(wt, "save") as save,
    ):
        if changed:
            with pytest.raises(wt.Blocked, match="changed"):
                pr.record(
                    tmp_path,
                    tmp_path / "state",
                    state,
                    finish_update=True,
                    status="OPEN",
                )
            TestCase().assertEqual(state, before)
            save.assert_not_called()
        else:
            pr.record(
                tmp_path, tmp_path / "state", state, finish_update=True, status="OPEN"
            )
            TestCase().assertEqual(state, {"prPublication": {"status": "OPEN"}})
            save.assert_called_once_with(tmp_path / "state", state)


@pytest.mark.parametrize("change", ["none", "state", "path"])
def check_pr_progress_requires_matching_state(tmp_path, change):
    state = {
        "task_id": "example",
        "prPublication": {"status": "PREPARED", "pushIntent": True},
    }
    before = copy.deepcopy(state)
    path = tmp_path / "state.json"
    current = copy.deepcopy(state)
    if change == "state":
        current["prPublication"]["status"] = "OTHER"
    with (
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(
            wt,
            "load",
            return_value=(
                tmp_path,
                None,
                tmp_path / "other" if change == "path" else path,
                current,
            ),
        ),
        patch.object(wt, "save") as save,
    ):
        if change != "none":
            with pytest.raises(wt.Blocked, match="lifecycle changed"):
                pr.record(tmp_path, path, state, progress_only=True, status="PUSHED")
            TestCase().assertEqual(state, before)
            save.assert_not_called()
        else:
            pr.record(tmp_path, path, state, progress_only=True, status="PUSHED")
            TestCase().assertEqual(state["prPublication"]["status"], "PUSHED")
            save.assert_called_once_with(path, state)


@pytest.mark.parametrize("failure", [False, True])
def check_candidate_history_without_merge_base(tmp_path, failure):
    task = "tasks/example.md"
    task_path = tmp_path / task
    task_path.parent.mkdir()
    task_path.write_text("completed", encoding="utf-8")
    state = {"start": "old", "validation_base": "start", "base": "main"}
    with (
        patch.object(worktree_state, "output", return_value="start") as output,
        patch.object(
            worktree_state,
            "git",
            return_value=subprocess.CompletedProcess([], int(failure)),
        ) as git,
    ):
        if failure:
            with pytest.raises(wt.Blocked, match="ancestor"):
                worktree_state._task_history(tmp_path, task, state, merge_base=False)
        else:
            assert (
                worktree_state._task_history(tmp_path, task, state, merge_base=False)
                == "start"
            )
        output.assert_called_once()
        git.assert_called_once()
        if not failure:
            state.update(
                integrationMode="pr", prPublication={"baseCommit": "published"}
            )
            state["prUpdate"] = {"syncBase": "synced"}
            output.reset_mock()
            worktree_state._task_history(tmp_path, task, state, merge_base=False)
            output.assert_called_once_with(
                tmp_path, "rev-parse", "--verify", "synced^{commit}"
            )


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
    if args[:2] == ("merge-base", "--is-ancestor") and trace.failure == "rewritten":
        return subprocess.CompletedProcess([], 1, "", "")
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
        "base-advance",
        "rewritten",
        "whitespace",
        "staged-whitespace",
    ],
)
def check_commit_failure_retention(tmp_path, failure):
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
        start="latest",
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
        with pytest.raises((wt.Blocked, wt.NeedsSync, subprocess.CalledProcessError)):
            wt._prepare_commit(
                base, tmp_path / "state.json", state, target
            )
    check.assertEqual(source.read_bytes(), b"candidate bytes")
    check.assertFalse(any(args[0] == "merge" for args in trace.commands))
    if failure == "altered-commit":
        check.assertEqual(state["commit"], "commit")
        check.assertFalse(state["verified"])


def _cleanup_operation(trace, target, root, *args, **kwargs):
    if args[:2] == ("worktree", "remove"):
        if trace.failure == "remove_worktree":
            raise OSError("remove worktree failure")
        target.rmdir()
        trace.removed = True
        for item in trace.directory.iterdir():
            item.unlink()
        trace.directory.rmdir()
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
    ["remove_worktree", "remove_branch", "remove_state"],
)
def check_cleanup_operation_failure_retains_state(tmp_path, failure):
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
    directory = tmp_path / "registered"
    directory.mkdir()
    for name in ("HEAD", "index"):
        (directory / name).touch()
    trace = SimpleNamespace(failure=failure, removed=False, branch_removed=False, directory=directory)
    with (
        patch.object(wt, "ancestor", return_value=True),
        patch.object(worktree_state, "_repository_identity", return_value=(tmp_path, tmp_path / ".git")),
        patch.object(worktree_state, "task_git_directory", return_value=directory),
        patch.object(wt, "task_worktree", return_value=target),
        patch.object(wt, "deploy_cleanup_task", return_value=None),
        patch.object(wt, "integration_task"),
        patch.object(wt, "output", side_effect=[str(target), "tip"]),
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
        check.assertEqual(target.exists(), failure == "remove_worktree")
        check.assertEqual(trace.branch_removed, failure == "remove_state")


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
    trace.created = trace.failure != "unknown-create"
    trace.creates += 1
    if trace.failure in {"create", "unknown-create"} and not trace.failed:
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


def _pr_resume_load(trace, root, task_id):
    return root, None, root / "state.json", copy.deepcopy(trace.saved[-1])


@pytest.mark.parametrize("failure", ["push", "create", "unknown-create", "save"])
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
        patch.object(
            wt, "load", side_effect=_bind_framework_callback(_pr_resume_load, trace)
        ),
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
        if failure == "unknown-create":
            with pytest.raises(wt.Blocked, match="creation outcome is unconfirmed"):
                pr.publish(tmp_path, tmp_path / "state.json", state)
        else:
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
    "failure", ["empty", "unverified", "head", "dirty", "merged", "prior"]
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
        (["branch-delete", "--branch", "codex/worktree/example"], True),
        (["branch-delete"], False),
        (["pr-close", "--pr", "7"], True),
        (["pr-close"], False),
        (["pr-update", "--task-id", "example", "--create-pr"], False),
        (["pr-status", "--task-id", "example", "--merge-method", "squash"], False),
    ],
)
def check_pr_lifecycle_cli(tmp_path, capsys, arguments, valid):
    with (
        patch.object(sys, "argv", ["worktree_task.py", *arguments]),
        patch.object(
            wt, "load", return_value=(tmp_path, None, tmp_path / "state.json", {})
        ),
        patch.object(wt, "finalize", return_value={}) as finalize,
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
            "remote_base",
            return_value="foreign"
            if failure in {"remote-head", "push-third"}
            else "candidate",
        ),
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
        with pytest.raises(
            wt.NeedsSync if failure == "stale-base" else wt.Blocked
        ) as error:
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


@pytest.mark.parametrize(
    "selected,method",
    [(None, "squash"), ("merge", "merge"), ("squash", "squash"), ("rebase", "rebase")],
)
def check_pr_merge_methods(tmp_path, selected, method):
    publication = dict(_pr_publication(), number=7)
    state = dict(integrationMode="pr", merged=None, prPublication=publication)
    opened = dict(state="OPEN", number=7, isDraft=False)
    merged = dict(
        state="MERGED", number=7, isDraft=False, mergeCommit={"oid": "a" * 40}
    )
    path = tmp_path / "state.json"
    with (
        patch.object(wt, "load", return_value=(tmp_path, None, path, state)),
        patch.object(pr, "publication_lock", return_value=nullcontext()),
        patch.object(wt, "lifecycle_lock", return_value=nullcontext()),
        patch.object(pr, "remote_identity", return_value={}),
        patch.object(pr, "existing_pr", side_effect=[opened, merged]),
        patch.object(wt, "save"),
        patch.object(pr, "gh") as gh,
        patch.object(wt, "cleanup_state", return_value={"cleaned": True}) as cleanup,
        patch.object(wt, "module", return_value=pr),
        patch.object(
            sys,
            "argv",
            ["worktree_task.py", "pr-merge", "--task-id", "example"]
            + (["--merge-method", selected] if selected else []),
        ),
    ):
        TestCase().assertEqual(wt.main(), 0)
        gh.assert_called_once_with(
            tmp_path,
            publication["host"],
            "pr",
            "merge",
            "7",
            "--repo",
            publication["host"] + "/" + publication["repository"],
            "--" + method,
            "--match-head-commit",
            publication["candidate"],
        )
        cleanup.assert_called_once_with(tmp_path, path, state)
        TestCase().assertEqual(state["merged"], "a" * 40)


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


@pytest.mark.parametrize(
    "case", ["accepted", "no_base", "wrong_commit", "not_framework", "not_ancestor"]
)
def check_synchronized_framework_continuation_guards(tmp_path, case):
    state = {
        "tip": "candidate",
        "branch": "codex/worktree/example",
        "commit": "candidate" if case != "wrong_commit" else "other",
        "verified": True,
        "task_file": "tasks/example.md",
        "validation_base": None if case == "no_base" else "base",
    }
    changed = {"framework/example.py"}
    with (
        patch.object(wt, "idle_git"),
        patch.object(wt.tasks, "validate_contract"),
        patch.object(wt.tasks, "paths_in", return_value=changed),
        patch.object(wt.tasks, "matches", return_value=True),
        patch.object(
            wt.tasks, "final_framework_task", return_value=case != "not_framework"
        ),
        patch.object(wt, "output", return_value="candidate"),
        patch.object(wt, "ancestor", return_value=case != "not_ancestor"),
    ):
        if case == "accepted":
            TestCase().assertEqual(
                wt._commit_preconditions(
                    tmp_path, state, changed, "task", None, scope_paths=changed
                ),
                "candidate",
            )
        else:
            with pytest.raises(wt.Blocked, match="task changed after commit"):
                wt._commit_preconditions(
                    tmp_path, state, changed, "task", None, scope_paths=changed
                )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
