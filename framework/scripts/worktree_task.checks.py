#!/usr/bin/env python3
"""Real temporary Git repositories exercise worktree lifecycle and failure retention."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import task_contract as tasks
import worktree_task as wt


SCRIPT = Path(__file__).with_name("worktree_task.py")


def git(root, *args):
    return wt.output(root, *args)


def contract(task_id, files):
    name = f"tasks/{task_id}.md"
    listed = "\n".join(f"- `{path}`" for path in [name, *files])
    return f"""# Task
## Task contract
- Task type: `governance`
- Task status: `running`
## Validation scope
- `framework`
## Required changes
- [R1] Fixture change
## Acceptance checks
- [R1] `exists:{files[0]}`
## Modified files
{listed}
## Allowed paths
{listed}
"""


@contextmanager
def fixture(branch="main"):
    with tempfile.TemporaryDirectory(prefix="worktree-check-") as directory:
        root = Path(directory).resolve() / "repository"
        root.mkdir()
        git(root, "init", "-q", "-b", branch)
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "config", "commit.gpgsign", "false")
        (root / ".gitignore").write_text("tasks/**\n/.worktrees/\n__pycache__\nsecret.bin\n", encoding="utf-8")
        (root / "file.txt").write_text("original\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-qm", "fixture")
        yield root


def cli(root, command, task_id="example", success=True):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0"}
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), command,
                             "--repository-root", str(root), "--task-id", task_id],
                            cwd=root, env=environment, capture_output=True, encoding="utf-8")
    data = json.loads(result.stdout)
    assert result.returncode == (0 if success else 1), result.stdout + result.stderr
    assert data["status"] == ("ok" if success else "blocked"), data
    return data


def start(root, task_id="example", files=("file.txt",)):
    state = cli(root, "create", task_id)
    target = Path(state["worktree"])
    tasks.start(target, state["task_file"], contract(task_id, files))
    return target, state


def finish_contract(target, state):
    tasks.complete(target, state["task_file"])


def retained(root, target, state, base_head):
    assert git(root, "rev-parse", f"refs/heads/{state['base']}") == base_head
    assert target.is_dir() and wt.branch_exists(root, state["branch"])
    assert any(e.get("branch") == f"refs/heads/{state['branch']}" for e in wt.worktrees(root))


def check_success_and_empty():
    for empty in (False, True):
        with fixture() as root:
            before = git(root, "rev-parse", "HEAD")
            target, state = start(root, files=("file.txt", "追加 file.txt"))
            if not empty:
                (target / "file.txt").write_text("task\n", encoding="utf-8")
                (target / "追加 file.txt").write_text("new\n", encoding="utf-8")
            else:
                (target / "file.txt").write_text("staged, then canceled\n")
                git(target, "add", "file.txt")
                (target / "file.txt").write_text("original\n")
            finish_contract(target, state)
            result = cli(target, "finalize")  # CLI uses the task cwd, not the helper's location.
            assert result["cleaned"] and not target.exists()
            assert not wt.branch_exists(root, state["branch"])
            assert git(root, "status", "--porcelain") == ""
            assert git(root, "rev-list", "--count", "HEAD") == ("1" if empty else "2")
            assert bool(result["commit"]) != empty
            if empty:
                assert git(root, "rev-parse", "HEAD") == before
            else:
                assert (root / "file.txt").read_text() == "task\n"
                assert (root / "追加 file.txt").read_text() == "new\n"
                assert git(root, "log", "-1", "--format=%s") == "task(example): completed task"
                assert not wt.paths(root, "ls-files", "-z", "tasks")
    print("Normal/zero-change lifecycle: PASS")


def check_incomplete_and_ownership():
    for mode in ("running", "suspend", "deferred", "outside", "foreign", "unexpected-commit", "git-conflict"):
        with fixture() as root:
            target, state = start(root)
            (target / "file.txt").write_text("task\n")
            before = git(root, "rev-parse", "HEAD")
            task_head = git(target, "rev-parse", "HEAD")
            if mode == "suspend":
                tasks.suspend(target, state["task_file"], "validation/local loop failure: file.txt")
            elif mode == "deferred":
                path = target / state["task_file"]
                text = path.read_text().replace("- Task status: `running`", "- Task status: `completed`")
                text = text.replace("## Active files\n\n- `file.txt`\n", "## Active files\n\n")
                path.write_text(text.replace("## Deferred files\n", "## Deferred files\n\n- `file.txt`\n"))
            elif mode in ("outside", "foreign", "unexpected-commit", "git-conflict"):
                finish_contract(target, state)
                if mode == "outside":
                    (target / "outside.txt").write_text("other task\n")
                    git(target, "add", "outside.txt")
                elif mode == "foreign":
                    path = target / state["task_file"]
                    path.write_text(tasks.bind_worktree(root, path.read_text()))
                elif mode == "unexpected-commit":
                    git(target, "add", "file.txt")
                    git(target, "commit", "-qm", "manual commit")
                    task_head = git(target, "rev-parse", "HEAD")
                else:
                    (Path(git(target, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD").write_text(before + "\n")
            cli(root, "finalize", success=False)
            retained(root, target, state, before)
            assert git(target, "rev-parse", "HEAD") == task_head, mode
            assert (target / "file.txt").read_text() == "task\n"
            cli(root, "cleanup", success=False)
    print("Incomplete/suspended/Deferred/foreign/outside-task/conflict guards: PASS")


def check_dirty_base_and_retry():
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        before = git(root, "rev-parse", "HEAD")
        (root / "file.txt").write_text("human dirty\n")
        git(root, "add", "file.txt")
        index = git(root, "write-tree")
        result = cli(root, "finalize", success=False)
        assert "dirty" in result["error"] and result["commit"]
        retained(root, target, state, before)
        assert (root / "file.txt").read_text() == "human dirty\n" and git(root, "write-tree") == index
        assert git(target, "rev-parse", "HEAD") == result["commit"]
        # Human resolves their own dirty base; helper never stashes or resets it.
        git(root, "commit", "-qm", "human work")
        result = cli(root, "finalize", success=False)  # same-path rebase conflict
        assert "aborted" in result["error"] and target.exists()
    print("Dirty base/index preserved, committed task retained: PASS")


def check_ahead_and_rebase_conflict():
    for conflict in (False, True):
        with fixture() as root:
            target, state = start(root)
            (target / "file.txt").write_text("task\n")
            finish_contract(target, state)
            updated = root / ("file.txt" if conflict else "base.txt")
            updated.write_text("base update\n")
            git(root, "add", updated.name)
            git(root, "commit", "-qm", "base ahead")
            latest = git(root, "rev-parse", "HEAD")
            result = cli(root, "finalize", success=not conflict)
            if conflict:
                assert "aborted" in result["error"]
                retained(root, target, state, latest)
                assert git(target, "rev-parse", "HEAD") == result["commit"]
                assert (target / "file.txt").read_text() == "task\n"
                wt.idle_git(target)
                assert git(target, "status", "--porcelain") == ""
            else:
                assert git(root, "rev-parse", "HEAD^") == latest
                assert (root / "base.txt").read_text() == "base update\n"
                assert (root / "file.txt").read_text() == "task\n"
                assert not target.exists() and not wt.branch_exists(root, state["branch"])
    print("Latest local base/rebase abort/ff-only integration: PASS")


def check_collisions_and_base_selection():
    with fixture() as root:
        git(root, "branch", "codex/worktree/example")
        before = git(root, "rev-parse", "codex/worktree/example")
        assert "collision" in cli(root, "create", success=False)["error"]
        assert git(root, "rev-parse", "codex/worktree/example") == before
        path = root / ".worktrees/path-collision"
        path.mkdir(parents=True)
        (path / "keep").write_text("human\n")
        assert "collision" in cli(root, "create", "path-collision", success=False)["error"]
        assert (path / "keep").read_text() == "human\n"
        stale = root / ".worktrees/stale"
        git(root, "worktree", "add", "--detach", stale, "HEAD")
        moved = stale.with_name("moved")
        stale.rename(moved)  # Simulate a stale Git entry without deleting its contents.
        assert "stale" in cli(root, "create", "stale", success=False)["error"]
        assert moved.exists()
        assert any(Path(e["worktree"]) == stale for e in wt.worktrees(root))
    with fixture("master") as root:
        assert wt.base_branch(root) == "master"
        git(root, "branch", "main")
        assert wt.base_branch(root) == "main"
        git(root, "config", "blueprint.baseBranch", "master")
        assert wt.base_branch(root) == "master"
        git(root, "config", "blueprint.baseBranch", "missing")
        assert "does not exist" in cli(root, "create", success=False)["error"]
        assert not wt.branch_exists(root, "missing")
    with fixture("feature") as root:
        assert "no configured base" in cli(root, "create", success=False)["error"]
    print("Branch/path/stale collisions and configured/main/master base: PASS")


def check_cleanup_failure_and_retry():
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        real_git = wt.git
        def deny_remove(where, *args, **kwargs):
            if args[:2] == ("worktree", "remove"):
                raise wt.Blocked("injected cleanup failure")
            return real_git(where, *args, **kwargs)
        with patch.object(wt, "git", side_effect=deny_remove):
            try:
                wt.finalize(root, "example")
            except wt.Blocked as error:
                assert "cleanup failure" in str(error)
            else:
                raise AssertionError("cleanup failure must be reported")
        saved = wt.load(root, "example")[3]
        assert saved["merged"] and git(root, "rev-parse", "HEAD") == saved["commit"]
        assert target.exists() and wt.branch_exists(root, state["branch"])
        (target / "secret.bin").write_bytes(b"ignored human data")
        assert "ignored files" in cli(root, "cleanup", success=False)["error"]
        assert (target / "secret.bin").read_bytes() == b"ignored human data"
        (target / "secret.bin").rename(root.parent / "saved-secret.bin")
        git(root, "branch", "feature", "HEAD^")
        git(root, "checkout", "-q", "feature")
        # Removal may succeed while branch deletion is blocked; retry from base safely.
        result = cli(target, "cleanup", success=False)
        assert "base must be checked out" in result["error"]
        assert result["remaining_worktree"] is None and result["remaining_branch"] == state["branch"]
        assert not target.exists() and wt.branch_exists(root, state["branch"])
        git(root, "checkout", "-q", "main")
        result = cli(root, "cleanup")
        assert result["cleaned"] and git(root, "rev-parse", "HEAD") == saved["merged"]
        assert not wt.branch_exists(root, state["branch"])
    print("Cleanup failure/retry/ignored data/merged history preserved: PASS")


def check_merge_retry_and_commit_failure():
    for empty in (False, True):
        with fixture() as root:
            target, state = start(root)
            if not empty:
                (target / "file.txt").write_text("task\n")
            finish_contract(target, state)
            (root / "base.txt").write_text("ahead\n")
            git(root, "add", "base.txt")
            git(root, "commit", "-qm", "ahead")
            latest = git(root, "rev-parse", "HEAD")
            real_git = wt.git
            def deny_merge(where, *args, **kwargs):
                if args[:1] == ("merge",):
                    raise wt.Blocked("injected ff-only merge failure")
                return real_git(where, *args, **kwargs)
            with patch.object(wt, "git", side_effect=deny_merge):
                try:
                    wt.finalize(root, "example")
                except wt.Blocked as error:
                    assert "merge failure" in str(error)
                else:
                    raise AssertionError("merge failure must be reported")
            retained(root, target, state, latest)
            result = cli(root, "finalize")
            assert result["cleaned"] and bool(result["commit"]) != empty
            assert git(root, "rev-list", "--count", "HEAD") == ("2" if empty else "3")
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        latest = git(root, "rev-parse", "HEAD")
        real_git = wt.git
        def commit_hook_changes(where, *args, **kwargs):
            if args[:1] == ("commit",):
                (target / "outside.txt").write_text("hook staged unrelated work\n")
                real_git(target, "add", "outside.txt")
            return real_git(where, *args, **kwargs)
        with patch.object(wt, "git", side_effect=commit_hook_changes):
            try:
                wt.finalize(root, "example")
            except wt.Blocked as error:
                assert "commit differs" in str(error)
            else:
                raise AssertionError("changed commit must never reach base")
        retained(root, target, state, latest)
        assert "verification failed" in cli(root, "finalize", success=False)["error"]
        retained(root, target, state, latest)
    print("Failed merge retries, zero-change rebase, altered commit rejection: PASS")


def check_real_loop_integration():
    # Reuse the existing minimal framework fixture, not a new completion engine.
    spec = importlib.util.spec_from_file_location("loop_checks", SCRIPT.with_name("blueprint-loop.checks.py"))
    loop_checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop_checks)
    with fixture() as root:
        loop_checks.make_framework_fixture(SCRIPT.parents[2], root)
        for name in ("docs/designs", "model", "infra", "tests/scenarios", "tests/results"):
            (root / name / ".gitkeep").touch()
        # This fixture tests the real child loop, not recursively the entire regression.
        for path in (root / "framework/scripts").glob("*.checks.py"):
            path.unlink()
        git(root, "add", ".")
        git(root, "commit", "-qm", "framework fixture")
        target, state = start(root, files=("docs/system-overview.md",))
        overview = target / "docs/system-overview.md"
        overview.write_text("# Fixture changed\n")
        loop = target / "framework/scripts/blueprint-loop.py"
        environment = {**os.environ, tasks.SELECTOR: state["task_file"], "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-B", str(loop), "--mode", "task", "--task-file", state["task_file"]],
                                cwd=target, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Blueprint local loop: PASS" in result.stdout
        finish_contract(target, state)
        cli(root, "finalize")
        assert (root / "docs/system-overview.md").read_text() == "# Fixture changed\n"
        target, state = start(root, "failed-loop", files=("docs/system-overview.md",))
        (target / "docs/system-overview.md").write_text("# Trailing whitespace  \n")
        result = subprocess.run([sys.executable, "-B", str(target / "framework/scripts/blueprint-loop.py"),
                                 "--mode", "task", "--task-file", state["task_file"]],
                                cwd=target, env=environment, capture_output=True, encoding="utf-8")
        assert result.returncode != 0 and "FAIL" in result.stdout, result.stdout + result.stderr
        assert tasks.status((target / state["task_file"]).read_text()) == "suspend"
        before = git(root, "rev-parse", "HEAD")
        cli(root, "finalize", "failed-loop", success=False)
        retained(root, target, state, before)
        assert git(target, "rev-parse", "HEAD") == state["start"]
    print("Real Task Contract + child local loop success/failure integration: PASS")


def main():
    for check in (check_success_and_empty, check_incomplete_and_ownership,
                  check_dirty_base_and_retry, check_ahead_and_rebase_conflict,
                  check_collisions_and_base_selection, check_cleanup_failure_and_retry,
                  check_merge_retry_and_commit_failure,
                  check_real_loop_integration):
        check()
    print("worktree-task: PASS (isolated lifecycle and failure retention)")


if __name__ == "__main__":
    main()
