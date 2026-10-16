#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.worktree_task_fixtures import *

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
            assert result["cleaned"]
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


def check_finalize_line_endings():
    for newline in (b"\n", b"\r\n"):
        for staged in (False, True):
            for suffix in (b"", b"  ", b"\t"):
                with fixture() as root:
                    git(root, "config", "core.whitespace", "blank-at-eol,blank-at-eof,space-before-tab")
                    target, state = start(root)
                    content = b"task" + suffix + newline
                    (target / "file.txt").write_bytes(content)
                    if staged:
                        git(target, "add", "file.txt")
                    finish_contract(target, state)
                    before = git(root, "rev-parse", "HEAD")
                    result = cli(root, "finalize", success=not suffix)
                    if suffix:
                        assert "trailing whitespace" in result["error"]
                        retained(root, target, state, before)
                        assert git(target, "rev-parse", "HEAD") == state["start"]
                    else:
                        assert result["cleaned"]
                        assert (root / "file.txt").read_bytes() == content
                    assert git(root, "config", "core.whitespace") == "blank-at-eol,blank-at-eof,space-before-tab"
    print("LF/CRLF integration and real trailing whitespace rejection: PASS")


def check_incomplete_and_ownership():
    for mode in ("running", "suspend", "deferred", "outside", "foreign", "unexpected-commit", "git-conflict",
                 "missing-python-setup", "missing-python-status"):
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
            elif mode in ("missing-python-setup", "missing-python-status"):
                finish_contract(target, state)
                _, _, path, record = wt.load(root, "example")
                if mode == "missing-python-setup":
                    record.pop("python_setup")
                else:
                    record["python_setup"].pop("status")
                wt.save(path, record)
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
            result = cli(root, "finalize", success=False)
            if mode in ("missing-python-setup", "missing-python-status"):
                assert "Python setup is incomplete" in result["error"], mode
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
                assert not wt.branch_exists(root, state["branch"])
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


def check_directory_layout():
    with fixture() as root:
        ignore = root / ".gitignore"
        ignore.write_text(ignore.read_text().replace("/.worktrees/\n", ""), encoding="utf-8")
        git(root, "add", ".gitignore")
        git(root, "commit", "-qm", "missing worktree ignore")
        assert "/.worktrees/ must be ignored" in cli(root, "create", success=False)["error"]
        assert not wt.branch_exists(root, "codex/worktree/example")
    with fixture() as root:
        target, state = start(root)
        _, _, path, _ = wt.load(root, "example")
        for invalid in (root / ".other/example", root / ".worktrees/other",
                        root / ".worktrees/example/extra", root / ".git/worktrees/example"):
            wt.save(path, {**state, "worktree": str(invalid)})
            assert "state does not match" in cli(root, "setup", success=False)["error"]
        wt.save(path, state)
        legacy = root / ".worktree/example"
        legacy.parent.mkdir()
        git(root, "worktree", "move", target, legacy)
        state["worktree"] = str(legacy)
        wt.save(path, state)
        for command in ("setup", "finalize", "cleanup"):
            assert "state does not match" in cli(legacy, command, success=False)["error"]
        assert legacy.is_dir() and (root / "file.txt").read_text() == "original\n"
        assert wt.branch_exists(root, state["branch"])
    print("Repo-root .worktrees creation/ignore, invalid paths and unsupported .worktree rejection: PASS")


def check_metadata_storage():
    with fixture() as root:
        target, first = start(root, "one")
        other, second = start(target, "two")
        directory = root / ".worktrees/.blueprint"
        path = directory / "tasks/one.json"
        sibling = directory / "tasks/two.json"
        assert wt.load(target, "one")[2] == path
        assert wt.load(other, "one")[2] == path
        assert json.loads(path.read_text(encoding="utf-8"))["worktree"] == str(target)
        assert sibling.is_file()
        with wt.lifecycle_lock(root):
            lock = directory / "lifecycle.lock"
            assert lock.is_dir()
            assert "lifecycle busy" in cli(other, "setup", "two", success=False)["error"]
            assert lock.is_dir()
        # Old metadata and locks neither authorize a task nor block the new lifecycle.
        old = root / ".git/blueprint-worktree-tasks/one.json"
        old.parent.mkdir()
        old.write_text("invalid old state", encoding="utf-8")
        (root / ".git/blueprint-worktree-lifecycle.lock").mkdir()
        saved = path.read_bytes()
        path.unlink()
        assert "one.json" in cli(target, "setup", "one", success=False)["error"]
        path.write_bytes(saved)
        cli(other, "setup", "one")
        sibling_before = sibling.read_bytes()
        finish_contract(target, first)
        assert cli(target, "finalize", "one")["cleaned"]
        assert sibling.read_bytes() == sibling_before and other.is_dir()
        assert old.read_text(encoding="utf-8") == "invalid old state"
        cli(root, "setup", "two")
        finish_contract(other, second)
        assert cli(root, "finalize", "two")["cleaned"]
        assert directory.is_dir()
    for relative in (".worktrees", ".worktrees/.blueprint", ".worktrees/.blueprint/tasks"):
        with fixture() as root:
            external = root.parent / "external"
            external.mkdir()
            link = root / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(external, target_is_directory=True)
            assert "metadata must not use symlinks" in cli(root, "create", success=False)["error"]
            assert not wt.branch_exists(root, "codex/worktree/example")
    print("Shared .worktrees/.blueprint state/locks, no old-location fallback, sibling retention and symlink guards: PASS")


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
        assert wt.branch_exists(root, state["branch"])
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


def check_human_approved_validation_failure():
    approval = "Human approves commit and merge despite file.txt trailing whitespace validation failure"
    for mode in ("accepted", "running", "deferred", "outside", "git-conflict", "blank"):
        with fixture() as root:
            target, state = start(root)
            (target / "file.txt").write_text("task  \n")
            before = git(root, "rev-parse", "HEAD")
            if mode != "running":
                tasks.suspend(target, state["task_file"], "Local loop failed: file.txt trailing whitespace")
            if mode == "deferred":
                path = target / state["task_file"]
                text = path.read_text().replace("## Active files\n\n- `file.txt`\n", "## Active files\n\n")
                path.write_text(text.replace("## Deferred files\n", "## Deferred files\n\n- `file.txt`\n"))
            elif mode == "outside":
                (target / "outside.txt").write_text("unrelated\n")
            elif mode == "git-conflict":
                (Path(git(target, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD").write_text(before + "\n")
            if mode != "accepted":
                cli(root, "finalize", success=False, approval=" " if mode == "blank" else approval)
                retained(root, target, state, before)
                assert git(target, "rev-parse", "HEAD") == state["start"], mode
                continue
            cli(root, "finalize", success=False)  # No approval still blocks before commit.
            assert git(target, "rev-parse", "HEAD") == state["start"]
            (target / "secret.bin").write_bytes(b"keep suspended contract for inspection")
            result = cli(root, "finalize", success=False, approval=approval)
            assert "ignored files" in result["error"] and result["merged"]
            assert result["validation_failure_approval"] == approval
            text = (target / state["task_file"]).read_text()
            assert tasks.status(text) == "suspend" and "Local loop failed" in text
            assert git(root, "log", "-1", "--format=%s") == "task(example): human-approved validation failure"
            assert approval in git(root, "log", "-1", "--format=%b")
            assert (root / "file.txt").read_text() == "task  \n"
            (target / "secret.bin").unlink()
            assert cli(root, "cleanup")["cleaned"]  # Stored approval survives cleanup retry.
            assert not wt.branch_exists(root, state["branch"])
    print("Explicit human approval, retained FAIL/suspend, scope/Deferred/Git guards and cleanup retry: PASS")


def check_real_loop_integration():
    # Reuse the existing minimal framework fixture, not a new completion engine.
    spec = importlib.util.spec_from_file_location("loop_checks", SCRIPT.parents[2] / 'framework/scripts/tests/integrations/blueprint-loop.checks.py')
    loop_checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop_checks)
    with fixture() as root:
        loop_checks.make_framework_fixture(SCRIPT.parents[2], root)
        for name in ("docs/designs", "model/parameters", "model/templates", "infra", "tests/scenarios", "tests/results"):
            (root/name).mkdir(parents=True,exist_ok=True)
            (root / name / ".gitkeep").touch()
        # This fixture tests the real child loop, not recursively the entire regression.
        for path in (root / "framework/scripts/tests").rglob("*.checks.py"):
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
        result = cli(root, "finalize", "failed-loop", approval="Human approves commit and merge despite trailing whitespace loop failure")
        assert result["cleaned"] and result["validation_failure_approval"]
        assert (root / "docs/system-overview.md").read_text() == "# Trailing whitespace  \n"
    print("Real Task Contract + child local loop success/failure/approved failure integration: PASS")


def main():
    for check in (check_success_and_empty, check_finalize_line_endings, check_incomplete_and_ownership,
                  check_dirty_base_and_retry, check_ahead_and_rebase_conflict,
                  check_collisions_and_base_selection, check_directory_layout, check_metadata_storage,
                  check_cleanup_failure_and_retry,
                  check_merge_retry_and_commit_failure,
                  check_human_approved_validation_failure, check_real_loop_integration):
        check()
    print("worktree-task: PASS (isolated lifecycle and failure retention)")


if __name__ == "__main__":
    main()

