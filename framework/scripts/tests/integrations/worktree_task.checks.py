#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case
import io
from contextlib import redirect_stderr

from support.worktree_task_fixtures import *

@it_case
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
            wt.integration_task(target, state)
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


@it_case
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


@it_case
def check_incomplete_and_git_safety():
    for mode in ("running", "suspend", "unexpected-commit", "git-conflict",
                 "missing-python-setup", "missing-python-status"):
        with fixture() as root:
            target, state = start(root)
            (target / "file.txt").write_text("task\n")
            before = git(root, "rev-parse", "HEAD")
            task_head = git(target, "rev-parse", "HEAD")
            if mode == "suspend":
                tasks.suspend(target, state["task_file"], "validation/local loop failure: file.txt")
            elif mode in ("missing-python-setup", "missing-python-status"):
                finish_contract(target, state)
                _, _, path, record = wt.load(root, "example")
                if mode == "missing-python-setup":
                    record.pop("python_setup")
                else:
                    record["python_setup"].pop("status")
                wt.save(path, record)
            elif mode in ("unexpected-commit", "git-conflict"):
                finish_contract(target, state)
                if mode == "unexpected-commit":
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
    print("Incomplete/suspended/conflict guards: PASS")


@it_case
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
        assert "dirty" in result["error"] and result["commit"] is None
        retained(root, target, state, before)
        assert (root / "file.txt").read_text() == "human dirty\n" and git(root, "write-tree") == index
        assert git(target, "rev-parse", "HEAD") == state["start"]
        assert (target / "file.txt").read_text() == "task\n"
        # Human resolves their own dirty base; helper never stashes or resets it.
        git(root, "commit", "-qm", "human work")
        result = cli(root, "finalize", success=False)  # same-path rebase conflict
        assert "aborted" in result["error"] and target.exists()
    print("Dirty base/index preserved, uncommitted task retained: PASS")


@it_case
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
                import pytest
                old = result['commit']
                with pytest.raises(wt.Blocked, match='commit changed'):
                    wt.recover(root, 'example', '0' * 40, latest)
                with pytest.raises(wt.Blocked, match='base changed'):
                    wt.recover(root, 'example', old, '0' * 40)
                with pytest.raises(wt.Blocked, match='aborted'):
                    wt.recover(root, 'example', old, latest)
                assert tasks.status((target / state['task_file']).read_text()) == 'running'
                assert 'finish reviewed recovery' in cli(root, 'finalize', success=False)['error']
                assert wt.git(target, 'rebase', latest, check=False).returncode
                (target / 'file.txt').write_text('base update\ntask\n')
                git(target, 'add', 'file.txt')
                git(target, 'rebase', '--continue')
                (target / 'file.txt').write_text('dirty\n')
                with pytest.raises(wt.Blocked, match='dirty'):
                    wt.recover(root, 'example', old, latest, finish=True)
                (target / 'file.txt').write_text('base update\ntask\n')
                recovered = wt.recover(root, 'example', old, latest, finish=True)
                assert recovered['tip'] == git(target, 'rev-parse', 'HEAD')
                assert 'recovery' not in recovered
                assert recovered['start'] == state['start']
                assert wt.task_start_commit(target, state['task_file']) == latest
                finish_contract(target, state)
                assert cli(root, 'finalize')['cleaned']
                assert (root / 'file.txt').read_text() == 'base update\ntask\n'
            else:
                assert git(root, "rev-parse", "HEAD^") == latest
                assert (root / "base.txt").read_text() == "base update\n"
                assert (root / "file.txt").read_text() == "task\n"
                assert not wt.branch_exists(root, state["branch"])
    print("Latest local base/rebase abort/ff-only integration: PASS")


@it_case
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


@it_case
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


@it_case
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


@it_case
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
        from import_guard import evidence_store, write_sealed
        evidence = evidence_store(target)
        own, other = evidence / 'example.json', evidence / 'other.json'
        write_sealed(target, own, {'task': state['task_file']})
        write_sealed(target, other, {'task': 'tasks/other.md'})
        other_before = other.read_bytes()
        assert not (target / '.blueprint').exists()

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
        assert not own.exists() and other.read_bytes() == other_before
        other.unlink()
    print("Cleanup failure/retry/ignored data/merged history preserved: PASS")


@it_case
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


@it_case
def check_human_approved_validation_failure():
    approval = "Human approves commit and merge despite file.txt trailing whitespace validation failure"
    for mode in ("accepted", "running", "git-conflict", "blank"):
        with fixture() as root:
            target, state = start(root)
            (target / "file.txt").write_text("task  \n")
            before = git(root, "rev-parse", "HEAD")
            if mode != "running":
                tasks.suspend(target, state["task_file"], "Local loop failed: file.txt trailing whitespace")
            if mode == "git-conflict":
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
    print("Explicit human approval, retained FAIL/suspend, Git guards and cleanup retry: PASS")


@it_case
def check_real_loop_integration():
    # Reuse the existing minimal framework fixture, not a new completion engine.
    from support import blueprint_loop_fixtures as loop_checks
    with fixture() as root:
        loop_checks.make_framework_fixture(SCRIPT.parents[2], root)
        for name in ("docs/designs", "model", "infra", "tests/scenarios", "tests/results"):
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


@it_case
def check_final_candidate_staleness():
    from types import SimpleNamespace
    from validation import loop
    from support.import_model_fixtures import operation_fixture, operation_candidate, operation_contract
    import shutil
    for change in ('base', 'head', 'task', 'dirty', 'none'):
        with fixture() as root:
            operation_fixture(root)
            git(root, 'add', 'model', 'project.json')
            git(root, 'commit', '-qm', 'model fixture')
            with tempfile.TemporaryDirectory() as temporary:
                candidate = Path(temporary) / 'candidate'
                sources = operation_candidate(root, candidate)
                target, state = start(root, files=tuple(sorted(sources)))
                text = operation_contract()
                for heading in ('Modified files', 'Allowed paths'):
                    text += '\n## ' + heading + '\n' + ''.join('- `' + value + '`\n' for value in sorted(sources | {state['task_file']}))
                text += '\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n'
                (target / state['task_file']).write_text(text)
                for name in sources:
                    shutil.copyfile(candidate / name, target / name)
                (root / 'unrelated.txt').write_text('new base\n')
                git(root, 'add', 'unrelated.txt'); git(root, 'commit', '-qm', 'unrelated base')
                latest = git(root, 'rev-parse', 'HEAD')
                final = wt.prepare_integration(root, 'example')
                assert final.base_commit == latest and 'unrelated.txt' not in final.changed_paths
                assert not wt.changed_paths(target) and final.changed_paths == sources
                def validate(root, options, *, final_candidate):
                    assert not wt.metadata_directory(Path(state['primary'])).joinpath('lifecycle.lock').exists()
                    return 0
                with patch.object(loop, 'run_loop', side_effect=validate) as checked:
                    result = wt.validate_final_candidate(final)
                    checked.assert_called_once()
                if change == 'base':
                    (root / 'unrelated.txt').write_text('advanced\n')
                    git(root, 'add', 'unrelated.txt'); git(root, 'commit', '-qm', 'advance')
                elif change == 'head':
                    git(target, 'commit', '--allow-empty', '-qm', 'unexpected')
                elif change == 'task':
                    file = target / state['task_file']; file.write_text(file.read_text() + '\n## Goal\nchanged\n')
                elif change == 'dirty':
                    (target / 'file.txt').write_text('changed\n')
                base_head = git(root, 'rev-parse', 'HEAD')
                if change != 'none':
                    try:
                        wt.merge_validated_candidate(result)
                        raise AssertionError('stale candidate merged')
                    except ValueError:
                        retained(root, target, state, base_head)
                else:
                    assert wt.merge_validated_candidate(result)['merged'] == final.candidate_head
                    assert tasks.status((target / state['task_file']).read_text()) == 'completed'
                    assert wt.cleanup(root, 'example')['cleaned']


@it_case
def check_approved_model_reads():
    from datetime import datetime, timezone, timedelta
    import import_guard as guard
    from support.import_model_fixtures import operation_fixture
    from utils.aws_mappings import mapping_alias
    from validation_scope import active_scope
    import pytest
    approval = 'Human accepts fixture validation failure for Git integration'
    relative = 'model/stg/cde/vpc.properties'
    for mode in ('preserved', 'changed-import', 'proof', 'missing', 'tampered', 'expired',
                 'wrong-task', 'wrong-base', 'wrong-scope', 'incomplete', 'wrong-sources'):
        with fixture() as root:
            from support.it_workspace import populate
            populate('framework', root)
            operation_fixture(root)
            git(root, 'add', 'framework', 'model', 'project.json')
            git(root, 'commit', '-qm', 'synthetic Model baseline')
            target, state = start(root, files=(relative,))
            source = target / relative
            source.write_text(source.read_text() + '\n# integration fixture\n')
            if mode == 'changed-import':
                source.write_text(source.read_text().replace('10.9.0.0/16', '10.8.0.0/16'))
            importing = mode not in ('preserved', 'changed-import')
            contract = target / state['task_file']
            contract.write_text(contract.read_text().replace('`governance`', '`design`').replace('- `framework`', '- `stg/cde/vpc`'))
            if importing:
                contract = target / state['task_file']
                text = contract.read_text().replace('- Task type: `design`', '- Task type: `design`\n- Workflow: `import`')
                contract.write_text(text.replace('- `framework`', '- `stg/cde/vpc`\n- `dev/cde/vpc`'))
                with tasks.selected_task(target, state['task_file']):
                    proof = dict(version=3, task=state['task_file'], base=state['start'],
                                 scope=['stg', 'cde', 'vpc'], acquisition='fixture-receipt',
                                 sources={relative: guard.file_hash(source)}, plan='fixture-plan',
                                 complete=mode != 'incomplete', model='reflected', markdown='failed',
                                 ownedArtifacts=[], acquiredAt=datetime.now(timezone.utc).isoformat())
                    if mode == 'expired':
                        proof['acquiredAt'] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
                    if mode.startswith('wrong-'):
                        key = mode.removeprefix('wrong-')
                        proof[key] = {'task': 'tasks/other.md', 'base': 'wrong',
                            'scope': ['dev', 'cde', 'vpc'], 'sources': {relative: '0' * 64}}[key]
                    receipt = guard.proof_path(target)
                    if mode != 'missing':
                        guard.write_sealed(target, receipt, proof)
                    if mode == 'tampered':
                        receipt.write_text(receipt.read_text().replace('fixture-plan', 'modified-plan'))
            tasks.suspend(target, state['task_file'], 'Synthetic validation FAIL: properties')
            saved = (target / state['task_file']).read_bytes()
            before = git(root, 'rev-parse', 'HEAD')
            with tasks.selected_task(target, state['task_file']):
                for call in (lambda: tasks.task_path(target), lambda: active_scope(target),
                             lambda: guard.require_import_changes(target)):
                    with pytest.raises(ValueError, match='suspend task cannot execute'):
                        call()
            cli(root, 'finalize', success=False)
            with mapping_alias(SCRIPT.parents[2], target), patch.object(wt.python_env, 'runtime', return_value=(Path(sys.executable), wt.python_env.environment(Path(sys.prefix)))):
                if mode in {'preserved', 'changed-import'}:
                    # Keep the checkout for byte-for-byte status inspection, then exercise cleanup retry.
                    (target / 'secret.bin').write_text('preserve')
                    with pytest.raises(wt.Blocked, match='ignored files'):
                        wt.finalize(root, 'example', approval)
                    assert (target / state['task_file']).read_bytes() == saved
                    assert approval in git(root, 'log', '-1', '--format=%b')
                    assert (root / relative).read_bytes() == source.read_bytes()
                    (target / 'secret.bin').unlink()
                    assert wt.cleanup(root, 'example')['cleaned']
                    assert not target.exists() and not wt.branch_exists(root, state['branch'])
                else:
                    with pytest.raises(ValueError) as error:
                        wt.finalize(root, 'example', approval)
                    assert 'suspend task cannot execute' not in str(error.value)
                    retained(root, target, state, before)
                    assert git(target, 'rev-parse', 'HEAD') == state['start']
                    assert (target / state['task_file']).read_bytes() == saved
    print('Approved suspended Model comparison and sealed IMPORT evidence guards: PASS')



@it_case
def check_registered_normal_model_guard():
    import venv
    from support.import_model_fixtures import dependency_fixture
    from support.it_workspace import populate
    relative = 'model/stg/cde/service-a.properties'
    with fixture() as root:
        populate('framework', root)
        dependency_fixture(root)
        (root / '.gitignore').write_text((root / '.gitignore').read_text() + '.venv/\n')
        git(root, 'add', '.'); git(root, 'commit', '-qm', 'synthetic runtime fixture')
        target, state = start(root, files=(relative,))
        contract_path = target / state['task_file']
        text = contract_path.read_text().replace('`governance`', '`design`').replace('- `framework`', '- `stg/cde/service-a`\n- `stg/cde/service-b`')
        contract_path.write_text(text)
        directory = wt.python_env.shared_directory(root)
        directory.mkdir()
        (directory / '.blueprint-owner').write_text(str(directory))
        venv.EnvBuilder(with_pip=False).create(directory)
        interpreter = wt.python_env.python_path(directory)
        site = subprocess.run([str(interpreter), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'],
                              capture_output=True, text=True, check=True).stdout.strip()
        # Reuse installed test dependencies offline; the fixture never invokes pip/setup.
        Path(site, 'fixture-dependencies.pth').write_text('\n'.join(p for p in sys.path if p.endswith('site-packages')) + '\n')
        probe = root.parent / 'guard-probe.json'
        Path(site, 'guard_probe.py').write_text("""import sys, json, atexit, os
from pathlib import Path
counts = {}
def profile(frame, event, arg):
    if event != 'call': return
    name, file = frame.f_code.co_name, Path(frame.f_code.co_filename).name
    if file == 'worktree_task.py' and name in ('lifecycle_lock', 'finalize', 'prepare_integration', 'cleanup'):
        raise AssertionError('guard child entered lifecycle')
    if file in ('references.py', 'sources.py') and name in ('usages', '_read_model'):
        assert sys.modules['validation_cache'].memo_table() is not None
        counts[name] = counts.get(name, 0) + 1
sys.setprofile(profile)
atexit.register(lambda: Path(os.environ['GUARD_PROBE']).write_text(json.dumps(counts)))
""", encoding='utf-8')
        Path(site, 'guard-probe.pth').write_text('import guard_probe\n', encoding='utf-8')
        (directory / '.blueprint-ready').write_text(str(directory))
        state['python_setup'] = dict(status='ready', kind='shared', installed=False,
                                    interpreter=str(interpreter), bin=str(interpreter.parent))
        _, _, state_path, _ = wt.load(root, 'example')
        wt.save(state_path, state)
        (target / relative).write_text((target / relative).read_text() + '\n# ordinary save\n')
        finish_contract(target, state)
        environment = {**os.environ, 'BLUEPRINT_TASK_FILE': 'tasks/foreign.md', 'GUARD_PROBE': str(probe)}
        parent = [sys.executable, '-S', '-B', '-c',
                  'import sys, importlib.util; '
                  'assert importlib.util.find_spec("pystache") is None; '
                  'sys.path.insert(0, sys.argv.pop(1)); '
                  'import worktree_task; raise SystemExit(worktree_task.main())',
                  str(SCRIPT.parent), 'finalize', '--repository-root', str(root), '--task-id', 'example']
        result = subprocess.run(parent, cwd=root, env=environment, capture_output=True, text=True, timeout=60)
        response = json.loads(result.stdout)
        assert result.returncode == 0, response
        assert response['cleaned'] and response['merged']
        counts = json.loads(probe.read_text())
        assert counts['usages'] >= 1 and counts['_read_model'] >= 1, counts
        assert not target.exists()
        assert wt.python_env.shared_ready(directory)
        assert (root / relative).read_text().endswith('# ordinary save\n')
    print('Ordinary Model guard in registered shared venv with dependency-free parent: PASS')


def main():
    for check in (check_model_refactor_integration, check_final_candidate_staleness, check_model_operation_integration, check_success_and_empty, check_finalize_line_endings, check_incomplete_and_git_safety,
                  check_dirty_base_and_retry, check_ahead_and_rebase_conflict,
                  check_collisions_and_base_selection, check_directory_layout, check_metadata_storage,
                  check_cleanup_failure_and_retry,
                  check_merge_retry_and_commit_failure,
                  check_human_approved_validation_failure, check_approved_model_reads, check_registered_normal_model_guard, check_real_loop_integration):
        check()
    print("worktree-task: PASS (isolated lifecycle and failure retention)")


@it_case
def check_model_operation_integration():
    import shutil
    from support.import_model_fixtures import operation_fixture, operation_candidate, operation_contract
    from utils.aws_mappings import mapping_alias
    for action, corrupt, approved in (("import-merge", False, False), ("import-delete", False, False),
                                      ("import-merge", True, False), ("import-merge", False, True),
                                      ("import-delete", False, True), ("import-merge", True, True)):
        with fixture() as root:
            if approved:
                from support.it_workspace import populate
                populate("framework", root)
                git(root, "add", "framework")
            operation_fixture(root)
            git(root, "add", "model", "project.json")
            git(root, "commit", "-qm", "model fixture")
            with tempfile.TemporaryDirectory() as directory:
                candidate = Path(directory) / "candidate"
                sources = operation_candidate(root, candidate, action)
                target, state = start(root, files=tuple(sorted(sources)))
                text = operation_contract(action)
                for heading in ("Modified files", "Allowed paths"):
                    text += "\n## " + heading + "\n" + "".join("- `" + name + "`\n" for name in sorted(sources | {state['task_file']}))
                text += "\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n"
                (target / state['task_file']).write_text(text)
                tasks.refresh(target, state['task_file'])
                for name in sources:
                    shutil.copyfile(candidate / name, target / name)
                with mapping_alias(SCRIPT.parents[2], target), patch.object(wt.python_env, 'runtime', return_value=(Path(sys.executable), wt.python_env.environment(Path(sys.prefix)))):
                    if not approved:
                        finish_contract(target, state)
                    if corrupt:
                        file = target / 'model/stg/cde/vpc.properties'
                        file.write_text(file.read_text().replace('10.9.0.0/16', '10.8.0.0/16'))
                    base_head = git(root, 'rev-parse', 'HEAD')
                    if approved:
                        import pytest
                        tasks.suspend(target, state['task_file'], 'Synthetic validation FAIL')
                        if action == 'import-delete':
                            with pytest.raises(wt.Blocked, match='requires successful final candidate validation'):
                                wt.finalize(root, 'example', 'Human accepts fixture validation FAIL')
                            retained(root, target, state, base_head)
                            assert git(target, 'rev-parse', 'HEAD') == state['start']
                        elif corrupt:
                            with pytest.raises(ValueError, match='undeclared value/type'):
                                wt.finalize(root, 'example', 'Human accepts fixture validation FAIL')
                            retained(root, target, state, base_head)
                            assert git(target, 'rev-parse', 'HEAD') == state['start']
                        else:
                            assert wt.finalize(root, 'example', 'Human accepts fixture validation FAIL')['cleaned']
                        continue
                    final = wt.prepare_integration(root, 'example')
                    from import_guard import require_import_changes
                    from validation import loop
                    def validate(root, options, *, final_candidate):
                        assert not (root.parent / '.blueprint/lifecycle.lock').exists()
                        with tasks.selected_task(root, final_candidate.task_file):
                            require_import_changes(root, final_candidate.changed_paths, final_candidate=final_candidate)
                        return 0
                    with patch.object(loop, 'run_loop', side_effect=validate):
                        if corrupt:
                            try:
                                wt.validate_final_candidate(final)
                                raise AssertionError('corrupted merge was accepted')
                            except ValueError as error:
                                assert 'undeclared value/type' in str(error)
                            retained(root, target, state, base_head)
                        else:
                            result = wt.validate_final_candidate(final)
                            assert wt.merge_validated_candidate(result)['merged'] == final.candidate_head
                            assert wt.cleanup(root, 'example')['cleaned']
                            assert not target.exists()
    print('Model-only merge/delete integration and post-completion guard: PASS')


@it_case
def check_model_refactor_integration():
    from support.import_model_fixtures import dependency_fixture, dependency_refactor, dependency_contract
    from utils.aws_mappings import mapping_alias
    from model.sources import load_model
    from model import prepare_edit, publish_edit
    from model.adapters.task import edit_write_context
    import pytest
    from import_guard import require_import_changes, source_write_context
    from validation import loop
    for advance in (False, True):
        with fixture() as root, tempfile.TemporaryDirectory() as directory:
            dependency_fixture(root)
            git(root, 'add', 'model', 'project.json'); git(root, 'commit', '-qm', 'generic Model fixture')
            candidate = Path(directory) / 'candidate'
            sources = dependency_refactor(root, candidate)
            target, state = start(root, files=tuple(sorted(sources)))
            text = dependency_contract()
            for heading in ('Modified files', 'Allowed paths'):
                text += '\n## ' + heading + '\n' + ''.join('- `' + name + '`\n' for name in sorted(sources | {state['task_file']}))
            text += '\n## Validation scope\n- `dev/cde/service-a`\n- `dev/cde/service-b`\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n'
            (target / state['task_file']).write_text(text)
            tasks.refresh(target, state['task_file'])
            with mapping_alias(SCRIPT.parents[2], target), tasks.selected_task(target, state['task_file']):
                # Refactors use ordinary design publication, never intermediate operation saves.
                try:
                    with source_write_context(target, state['task_file']):
                        raise AssertionError('refactor entered intermediate operation writer')
                except ValueError as error:
                    assert 'Model-only update operation' in str(error)
                output = {target / name: (candidate / name).read_text() for name in sources}
                original = {path: path.read_bytes() for path in output}
                bad = {p: value.replace('same-name-stg', 'changed') for p, value in output.items()}
                scope = {('stg', 'cde', 'service-b')}
                with edit_write_context(target, scope, state['task_file']) as context:
                    path = next(iter(bad))
                    plan = prepare_edit(load_model(path, context.snapshot), bad, context)
                    with pytest.raises(ValueError, match='changed a saved native value'):
                        publish_edit(plan, context)
                assert all(path.read_bytes() == raw for path, raw in original.items())
                with edit_write_context(target, scope, state['task_file']) as context:
                    path = next(iter(output))
                    publish_edit(prepare_edit(load_model(path, context.snapshot), output, context), context)
                require_import_changes(target)
                assert load_model(target / 'model/stg/cde/service-b.properties').values['desired.row.002-001.value'] == 'same-name-stg'
                for identity in ('001', '999'):
                    result = subprocess.run([sys.executable, '-B', str(SCRIPT.parent / 'model/cli.py'),
                        'incoming', str(target / 'model/stg/cde/service-a.properties'), identity],
                        capture_output=True, text=True)
                    assert result.returncode == 0, result.stderr + result.stdout
                    response = json.loads(result.stdout)
                    assert response == {'status': 'complete', 'references': [], 'warnings': []}
                if advance:
                    file = root / 'model/stg/cde/service-a.properties'
                    file.write_text(file.read_text().replace('same-name-stg', 'advanced-name'))
                    git(root, 'add', file); git(root, 'commit', '-qm', 'advance producer on base')
                latest = git(root, 'rev-parse', 'HEAD')
                final = wt.prepare_integration(root, 'example')
                assert final.base_commit == latest
                calls = []
                def validate(root, options, *, final_candidate):
                    calls.append(final_candidate.candidate_head)
                    assert not (root.parent / '.blueprint/lifecycle.lock').exists()
                    with tasks.selected_task(root, final_candidate.task_file):
                        require_import_changes(root, final_candidate.changed_paths, final_candidate=final_candidate)
                    return 0
                with patch.object(loop, 'run_loop', side_effect=validate):
                    with redirect_stderr(io.StringIO()) as warnings:
                        result = wt.validate_final_candidate(final)
                    assert 'producer name/identifier differs from saved text' not in warnings.getvalue()
                    assert wt.merge_validated_candidate(result)['merged'] == final.candidate_head
                    assert wt.cleanup(root, 'example')['cleaned']
                assert calls == [final.candidate_head]
    print('Generic refactor publication and actual post-rebase candidate guard: PASS')

if __name__ == "__main__":
    main()

