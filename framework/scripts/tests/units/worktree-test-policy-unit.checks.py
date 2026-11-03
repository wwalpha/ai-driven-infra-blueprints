#!/usr/bin/env python3
"""Detect direct, indirect, mocked and renamed lifecycle regressions."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import support.worktree_test_policy as policy
from support.regression_cases import _EXPECTED_UPDATE
from support.worktree_test_policy import (
    POLICY_RECEIPT,
    POLICY_TOKEN,
    SessionClassifier,
    audit,
    forbidden_process,
    ordinary_suite,
    source_snapshot,
    verified_receipt,
    violations,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "fault", ["none", "token", "root", "parent", "source", "missing", "malformed"]
)
def check_policy_receipt(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(policy, "runner_parent", lambda tests: True)
    tests = tmp_path / "tests"
    tests.mkdir()
    source = tests / "example.py"
    source.write_text("pass\n", encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    data = {
        "root": str(tests.resolve()),
        "pid": os.getppid(),
        "token": "secret",
        "snapshot": source_snapshot(tests),
    }
    if fault == "token":
        data["token"] = "other"
    elif fault == "root":
        data["root"] = str(tmp_path)
    elif fault == "parent":
        data["pid"] = -1
    receipt.write_text(json.dumps(data), encoding="utf-8")
    if fault == "source":
        source.write_text("changed = True\n", encoding="utf-8")
    elif fault == "missing":
        receipt.unlink()
    elif fault == "malformed":
        receipt.write_text("{", encoding="utf-8")
    monkeypatch.setenv(POLICY_RECEIPT, str(receipt))
    monkeypatch.setenv(POLICY_TOKEN, "secret")
    assert verified_receipt(tests) is (fault == "none")
    assert not verified_receipt(tests)


@pytest.mark.parametrize(
    "args, expected",
    [
        ([], True),
        (["--ut-only"], True),
        (["--suite", "x"], False),
        (["-c", "code"], False),
    ],
)
def check_runner_parent_identity(tmp_path, monkeypatch, args, expected):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "run_it.py").write_text("pass\n", encoding="utf-8")
    argv = [sys.executable, "-B", str(tests / "run_it.py"), *args]

    root, process, executable, cwd, command = (MagicMock() for _ in range(5))
    root.__truediv__.return_value = process
    process.__truediv__.side_effect = {
        "exe": executable,
        "cwd": cwd,
        "cmdline": command,
    }.get
    executable.resolve.return_value = Path(sys.executable).resolve()
    cwd.resolve.return_value = tmp_path
    command.read_bytes.return_value = (
        b"\0".join(os.fsencode(arg) for arg in argv) + b"\0"
    )
    monkeypatch.setattr(
        policy, "Path", lambda value: root if value == "/proc" else Path(value)
    )
    assert policy.runner_parent(tests) is expected


def check_session_classification_revalidates_changed_sources(tmp_path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    source = tests / "suite.py"
    source.write_text("def check_one(): pass\n", encoding="utf-8")
    monkeypatch.setattr(policy, "WORKTREE_CASES", {"suite.py": ("check_one",)})
    classify = Mock(wraps=policy.worktree_suite)
    monkeypatch.setattr(policy, "worktree_suite", classify)
    first = SessionClassifier()
    assert first(source, tests) and first(source, tests)
    assert classify.call_count == 1
    source.write_text("def check_other(): pass\n", encoding="utf-8")
    assert not first(source, tests)
    assert classify.call_count == 2
    second = SessionClassifier()
    assert not second(source, tests)
    assert classify.call_count == 3


def check_forged_receipt_from_non_runner(tmp_path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "example.py").write_text("pass\n", encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "root": str(tests.resolve()),
                "pid": os.getppid(),
                "token": "forged",
                "snapshot": source_snapshot(tests),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(POLICY_RECEIPT, str(receipt))
    monkeypatch.setenv(POLICY_TOKEN, "forged")
    assert not verified_receipt(tests)


@pytest.mark.parametrize("change", ["add", "delete", "edit"])
def check_policy_snapshot_tracks_sources(tmp_path, change):
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")
    before = source_snapshot(tmp_path)
    if change == "add":
        (tmp_path / "other.py").write_text("pass\n", encoding="utf-8")
    elif change == "delete":
        source.unlink()
    else:
        source.write_text("x = 1\n", encoding="utf-8")
    assert source_snapshot(tmp_path) != before


def check_repository_policy():
    assert violations(Path(__file__).resolve().parents[1]) == []


@pytest.mark.parametrize(
    "source",
    [
        "import worktree_task",
        "state = {'task_file': 'tasks/example.md', 'worktree': '/tmp/fixture', 'merged': None}",
        "from support.worktree_task_fixtures import fixture",
        "from unittest.mock import patch\npatch('worktree_state.load')",
        "import importlib\nimportlib.import_module('support.worktree_task_fixtures')",
    ],
)
def check_direct_and_indirect(tmp_path, source):
    (tmp_path / "support").mkdir()
    (tmp_path / "support/helper.py").write_text(source)
    (tmp_path / "business.py").write_text("from support.helper import fixture")
    errors = violations(tmp_path)
    assert any(
        "business.py: Worktree dependency through support.helper" in error
        for error in errors
    )
    assert any("support/helper.py: Worktree dependency" in error for error in errors)


def check_filename_grants_no_authority(tmp_path):
    (tmp_path / "worktree-renamed.checks.py").write_text(
        "import worktree_task\ndef check_business(): pass"
    )
    assert violations(tmp_path)


def check_runtime_guard(tmp_path):
    with pytest.raises(TypeError, match="session Worktree classifier"):
        with ordinary_suite(tmp_path / "business.py", tmp_path, True):
            pass
    with ordinary_suite(tmp_path / "business.py", tmp_path):
        for command in (
            ["git", "worktree", "add", "candidate"],
            ["python3", "worktree_task.py", "finalize"],
        ):
            with pytest.raises(AssertionError, match="lifecycle subprocess"):
                audit("subprocess.Popen", ("unused", command, None, None))
        with pytest.raises(AssertionError, match="lifecycle storage"):
            audit("open", (str(tmp_path / ".worktrees/.blueprint/state.json"), "w", 1))
        for command in (
            ["git", "init"],
            ["git", "commit", "-m", "fixture"],
            ["git", "diff"],
            ["git", "worktree", "list"],
        ):
            assert not forbidden_process(command)
            audit("subprocess.Popen", ("unused", command, None, None))
        audit("open", (str(tmp_path / "model.properties"), "w", 1))
        with ThreadPoolExecutor(max_workers=1) as pool:
            attempted = pool.submit(
                subprocess.run,
                ["git", "worktree", "add", str(tmp_path / "candidate")],
                cwd=tmp_path,
                capture_output=True,
            )
            with pytest.raises(AssertionError, match="lifecycle subprocess"):
                attempted.result()
        assert not (tmp_path / "candidate").exists()


def check_expected_update_has_exact_write_scope(tmp_path):
    root = tmp_path / ".worktrees/task/framework/scripts/tests/expected"
    expected = root / "example/first.yml"
    with ordinary_suite(tmp_path / "business.py", tmp_path):
        token = _EXPECTED_UPDATE.set(expected)
        try:
            audit("open", (str(expected), "w", 1))
            temporary = expected.with_suffix(".yml.tmp")
            audit("open", (str(temporary), "x", 1))
            audit("os.rename", (str(temporary), str(expected), -1, -1))
            audit("os.remove", (str(temporary), -1))
            for directory in (root, expected.parent):
                audit("os.mkdir", (str(directory), 511, -1))
            for event, args in (
                ("open", (str(expected.with_name("other.yml")), "w", 1)),
                ("open", (str(root.parent / "conftest.py"), "w", 1)),
                ("open", (str(tmp_path / ".worktrees/.blueprint/state.json"), "w", 1)),
                ("os.mkdir", (str(root.parent), 511, -1)),
                ("open", (str(expected.with_name("other.yml.tmp")), "x", 1)),
                (
                    "os.rename",
                    (str(temporary), str(expected.with_name("other.yml")), -1, -1),
                ),
                ("os.rename", (str(expected), str(temporary), -1, -1)),
                ("os.remove", (str(expected), -1)),
                ("os.remove", (str(expected), -1)),
                (
                    "os.rename",
                    (str(expected), str(expected.with_name("other.yml")), -1, -1),
                ),
            ):
                with pytest.raises(AssertionError, match="lifecycle storage"):
                    audit(event, args)
            with pytest.raises(AssertionError, match="lifecycle subprocess"):
                audit(
                    "subprocess.Popen",
                    ("unused", ["git", "worktree", "add", "x"], None, None),
                )
        finally:
            _EXPECTED_UPDATE.reset(token)
        with pytest.raises(AssertionError, match="lifecycle storage"):
            audit("open", (str(expected), "w", 1))


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
