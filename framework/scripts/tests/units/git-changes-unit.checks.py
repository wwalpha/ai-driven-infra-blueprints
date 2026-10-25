#!/usr/bin/env python3
"""Shared Git path commands, parsing and failure boundaries; no real repository."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from utils.git_changes import collect_working_paths, read_paths, run_readonly

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_readonly_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_INDEX_FILE", "/caller/private-index")
    monkeypatch.setenv("GIT_WORK_TREE", "/caller/worktree")
    before = dict(os.environ)
    result = subprocess.CompletedProcess(["git"], 0, "日本語\r\nfile\0".encode(), b"")
    with patch("utils.git_changes.subprocess.run", return_value=result) as execute:
        assert (
            run_readonly(tmp_path, "diff", "--name-only", "-z").stdout
            == "日本語\r\nfile\0"
        )
    execute.assert_called_once_with(
        ["git", "diff", "--name-only", "-z"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert (
        dict(os.environ) == before
    )  # No env override: subprocess inherits the caller's Git settings.


@pytest.mark.parametrize(
    "output,expected",
    [
        ("", set()),
        ("\0", set()),
        (
            "空 白\0line\nbreak\0line\r\nbreak\0 trailing \0\0",
            {"空 白", "line\nbreak", "line\r\nbreak", " trailing "},
        ),
        ("same\0same\0last", {"same", "last"}),
    ],
)
def check_read_paths(tmp_path, output, expected):
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, output, ""))
    first = read_paths(tmp_path, "ls-files", "-z", runner=runner)
    assert first == expected
    first.add("local mutation")
    assert read_paths(tmp_path, "ls-files", "-z", runner=runner) == expected
    assert runner.call_args == call(tmp_path, "ls-files", "-z")


def check_working_paths(tmp_path):
    source = {"unstaged", "shared"}
    reader = Mock(side_effect=[source, {"staged", "shared"}, {"untracked", "shared"}])
    working = collect_working_paths(tmp_path, path_reader=reader)
    assert reader.call_args_list == [
        call(["diff", "--no-renames", "--name-only", "-z"]),
        call(["diff", "--cached", "--no-renames", "--name-only", "-z"]),
        call(["ls-files", "--others", "--exclude-standard", "-z"]),
    ]
    source.clear()
    assert working.unstaged == frozenset({"unstaged", "shared"})
    assert working.staged == frozenset({"staged", "shared"})
    assert working.untracked == frozenset({"untracked", "shared"})
    assert working.all_paths == frozenset({"unstaged", "staged", "untracked", "shared"})
    mutable = set(working.all_paths)
    mutable.clear()
    assert working.all_paths


def check_collection_runner(tmp_path):
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "file\0", ""))
    with patch(
        "utils.git_changes.subprocess.run", side_effect=AssertionError("default runner")
    ):
        assert collect_working_paths(tmp_path, runner=runner).all_paths == {"file"}
    assert runner.call_args_list == [
        call(tmp_path, "diff", "--no-renames", "--name-only", "-z"),
        call(tmp_path, "diff", "--cached", "--no-renames", "--name-only", "-z"),
        call(tmp_path, "ls-files", "--others", "--exclude-standard", "-z"),
    ]


@pytest.mark.parametrize("failure_at", [0, 1, 2])
@pytest.mark.parametrize("injected", [False, True])
def check_fail_closed(tmp_path, failure_at, injected):
    empty, partial, broken = (
        ("", "partial\0", "broken") if injected else (b"", b"partial\0", b"broken")
    )
    responses = [subprocess.CompletedProcess([], 0, empty, empty)] * failure_at
    responses.append(subprocess.CompletedProcess([], 128, partial, broken))
    runner = Mock(side_effect=responses) if injected else None
    with (
        patch("utils.git_changes.subprocess.run", side_effect=responses) as execute,
        pytest.raises(ValueError, match="git .* failed: broken"),
    ):
        collect_working_paths(tmp_path, runner=runner)
    assert (runner if injected else execute).call_count == failure_at + 1
    if injected:
        execute.assert_not_called()


@pytest.mark.parametrize("boundary", ["runner", "path_reader"])
@pytest.mark.parametrize(
    "error", [OSError("unavailable"), ValueError("caller failure")]
)
def check_exception_propagation(tmp_path, boundary, error):
    callback = Mock(side_effect=error)
    with pytest.raises(type(error)) as caught:
        collect_working_paths(tmp_path, **{boundary: callback})
    assert caught.value is error
    callback.assert_called_once()


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("add", "."),
        ("reset", "--hard"),
        ("write-tree",),
        ("update-index", "--refresh"),
        ("-c", "alias.paths=!touch bad", "paths"),
        ("diff", "--output=bad"),
        ("diff", "--ext-diff"),
        ("ls-files", "--with-tree=HEAD"),
    ],
)
def check_reject_mutations(tmp_path, arguments):
    runner = Mock()
    with pytest.raises(ValueError):
        run_readonly(tmp_path, *arguments, runner=runner)
    runner.assert_not_called()


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
