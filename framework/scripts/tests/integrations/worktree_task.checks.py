#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import shutil
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import io
import venv
from contextlib import redirect_stderr

import import_guard as _imports_import_guard
import import_guard as guard
import pytest
import pytest as _imports_pytest
import support.import_model_fixtures as _imports_support_import_model_fixtures
import validation.loop as _imports_validation_loop
from deploy import handoff
from deploy_handoff import main as handoff_cli
from import_guard import require_import_changes
from model.adapters.task import edit_write_context
from model.sources import load_model
from support import blueprint_loop_fixtures as loop_checks
from support.import_model_fixtures import dependency_fixture, operation_fixture
from support.it_case_receipt import it_case
from support.worktree_task_fixtures import (
    SCRIPT,
    Path,
    cli,
    finish_contract,
    fixture,
    git,
    json,
    os,
    patch,
    retained,
    start,
    subprocess,
    sys,
    tasks,
    tempfile,
    wt,
)
from support.worktree_task_fixtures import (
    contract as contract,
)
from task_contract_core import task_digest
from utils import sealed_evidence
from utils.aws_mappings import mapping_alias
from validation import loop
from validation.findings import Findings
from validation.task import TaskValidation
from validation_scope import active_scope

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def check_sync_base_preserves_candidate():
    with fixture() as root:
        target, state = start(root, files=("file.txt",))
        old = state["start"]
        (root / "file.txt").write_text("upstream\n")
        (root / "upstream.txt").write_text("inherited\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "reviewed upstream")
        latest = git(root, "rev-parse", "HEAD")
        (target / "file.txt").write_text("upstream\nreviewed candidate\n")
        saved = wt.sync_base(target, "example", latest)
        assert (
            saved["start"] == old and saved["tip"] == saved["validation_base"] == latest
        )
        assert saved["commit"] is None and git(target, "rev-parse", "HEAD") == latest
        assert (target / "file.txt").read_text() == "upstream\nreviewed candidate\n"
        assert (target / "upstream.txt").read_text() == "inherited\n"
        assert tasks.status((target / state["task_file"]).read_text()) == "running"
        finish_contract(target, state)
        assert cli(root, "finalize")["cleaned"]


def _callback_check_deploy_workflow_cross_task_reset_rejected_initial(
    target, /, root, state
):
    return {
        "repository": str(root),
        "taskFile": state["task_file"],
        "target": target,
        "taskDigest": task_digest((root / state["task_file"]).read_text()),
        "workflow": handoff.new_workflow(),
        "states": {"Stack": {"status": "NOT_STARTED"}},
    }


@it_case
def check_deploy_workflow_cross_task_reset_rejected():
    with fixture() as primary:
        parent, parent_state = start(primary, task_id="deploy-one", files=("file.txt",))
        other, other_state = start(primary, task_id="deploy-two", files=("file.txt",))
        target = {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
        initial = _bind_framework_callback(
            _callback_check_deploy_workflow_cross_task_reset_rejected_initial, target
        )
        path = primary.parent / "original-session.json"
        original = initial(parent, parent_state)
        handoff.bind(parent, path, original)
        original["workflow"]["reserved"] = 2
        handoff.save(path, original)
        wt.bind_deploy_workflow(
            parent, path, original, Path(original["workflowBinding"]), activate=True
        )
        replacement = initial(other, other_state)
        next_path = primary.parent / "replacement-session.json"
        try:
            handoff.bind(other, next_path, replacement)
        except ValueError as error:
            assert "unfinished deploy workflow" in str(error)
        else:
            raise AssertionError("another Task reset the original workflow")
        proof = Path(original["workflowBinding"])
        retained = proof.with_name(proof.name + ".retained")
        proof.rename(retained)
        try:
            try:
                handoff.bind(other, next_path, replacement)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError(
                    "missing prior ledger became a zero-cycle workflow"
                )
        finally:
            retained.rename(proof)
        original["workflow"]["attempts"]["static-failed"] = {
            "attemptId": "static-failed",
            "stage": "STATIC_FAILED",
            "staticRuns": 3,
        }
        original["pendingRequest"] = {
            "attemptId": "static-failed",
            "requestId": "retained-pending-proof",
        }
        handoff.save(path, original)
        with tasks.selected_task(parent, parent_state["task_file"]):
            assert (
                handoff_cli(
                    [
                        "close",
                        "--repository-root",
                        str(parent),
                        "--state",
                        str(path),
                        "--authorization",
                        "fixture explicit Human termination",
                    ]
                )
                == 0
            )
        try:
            handoff.bind(other, next_path, replacement)
            wt.bind_deploy_workflow(
                other,
                next_path,
                replacement,
                Path(replacement["workflowBinding"]),
                activate=True,
            )
        except ValueError as error:
            assert "unfinished deploy workflow" in str(error)
        else:
            raise AssertionError("close must not reset unresolved history or budget")
        saved = json.loads(path.read_text())
        assert (
            saved["workflow"]["reserved"] == 2
            and saved["workflow"]["status"] == "CLOSED"
        )
        assert "pendingRequest" not in saved
        assert (
            saved["workflow"]["attempts"]["static-failed"]["closedRequest"]["requestId"]
            == "retained-pending-proof"
        )
        assert saved["workflow"]["attempts"]["static-failed"]["stage"] == "ABANDONED"


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
            result = cli(
                target, "finalize"
            )  # CLI uses the task cwd, not the helper's location.
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
                assert (
                    git(root, "log", "-1", "--format=%s")
                    == "task(example): completed task"
                )
                assert not wt.paths(root, "ls-files", "-z", "tasks")
    print("Normal/zero-change lifecycle: PASS")


@it_case
def check_finalize_line_endings():
    for content, staged, accepted in (
        (b"task\r\n", False, True),
        (b"task  \n", True, False),
    ):
        with fixture() as root:
            git(
                root,
                "config",
                "core.whitespace",
                "blank-at-eol,blank-at-eof,space-before-tab",
            )
            target, state = start(root)
            (target / "file.txt").write_bytes(content)
            if staged:
                git(target, "add", "file.txt")
            finish_contract(target, state)
            before = git(root, "rev-parse", "HEAD")
            result = cli(root, "finalize", success=accepted)
            if accepted:
                assert result["cleaned"] and (root / "file.txt").read_bytes() == content
            else:
                assert "trailing whitespace" in result["error"]
                retained(root, target, state, before)
                assert git(target, "rev-parse", "HEAD") == state["start"]
            assert (
                git(root, "config", "core.whitespace")
                == "blank-at-eol,blank-at-eof,space-before-tab"
            )


@it_case
def check_incomplete_and_git_safety():
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        before = git(root, "rev-parse", "HEAD")
        (
            Path(git(target, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD"
        ).write_text(before + "\n")
        assert (
            "unfinished Git operation" in cli(root, "finalize", success=False)["error"]
        )
        retained(root, target, state, before)
        assert git(target, "rev-parse", "HEAD") == state["start"]
        assert (target / "file.txt").read_text() == "task\n"
        cli(root, "cleanup", success=False)

    for kind, forbidden in (
        ("committed", "framework/scripts/blocked.py"),
        ("staged", "infra/template.yaml"),
        ("unstaged", ".agents/skills/update/SKILL.md"),
        ("untracked", "framework/scripts/untracked.py"),
        ("resolved", ""),
        ("unmanaged", ""),
    ):
        with fixture() as root:
            report = "issues/dev/cde/issues.md"
            for relative in (report, ".agents/skills/update/SKILL.md"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("### ec2\n1. Ordinary issue\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-qm", "remediation baseline")
            if kind == "unmanaged":
                target, name = root, "tasks/remediation.md"
            else:
                state = cli(root, "create", task_id="remediation")
                target, name = Path(state["worktree"]), state["task_file"]
            listed = f"- `{name}`\n- `{report}`\n"
            text = (
                "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
                "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
                "## Validation scope\n- `dev/cde/ec2`\n## Issue remediation\n- `dev/cde/ec2`\n"
                "## Modified files\n" + listed + "## Allowed paths\n" + listed
            )
            tasks.start(target, name, text)
            with tasks.selected_task(target, name):
                if kind == "unmanaged":
                    with pytest.raises(ValueError, match="managed Task start commit"):
                        tasks.complete(target, name)
                    with pytest.raises(ValueError, match="managed Task start commit"):
                        TaskValidation(target, Findings(target)).fix_baseline()
                    continue
                if kind == "resolved":
                    (target / report).write_text("未解決issueなし\n", encoding="utf-8")
                    tasks.refresh(target, name)
                    tasks.complete(target, name)
                    assert tasks.status((target / name).read_text()) == "completed"
                    continue
                path = target / forbidden
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("forbidden change\n", encoding="utf-8")
                if kind in {"staged", "committed"}:
                    git(target, "add", forbidden)
                if kind == "committed":
                    git(target, "commit", "-qm", "forbidden Framework change")
                    assert not wt.changed_paths(target)
                with pytest.raises(
                    ValueError, match="Issue remediation forbidden path"
                ):
                    tasks.complete(target, name)
                task = TaskValidation(target, Findings(target))
                task.check_task_scope()
                assert task.baseline == state["start"]
                assert any(
                    "Issue remediation forbidden path: " + forbidden in error
                    for error in task.findings.errors
                ), task.findings.errors
                assert tasks.status((target / name).read_text()) == "running"


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
        assert (root / "file.txt").read_text() == "human dirty\n" and git(
            root, "write-tree"
        ) == index
        assert git(target, "rev-parse", "HEAD") == state["start"]
        assert (target / "file.txt").read_text() == "task\n"
        # Human resolves their own dirty base; helper never stashes or resets it.
        git(root, "commit", "-qm", "human work")
        result = cli(root, "finalize", success=False)  # same-path rebase conflict
        assert "aborted" in result["error"] and target.exists()
    print("Dirty base/index preserved, uncommitted task retained: PASS")


@it_case
def check_ahead_and_rebase_conflict():
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        updated = root / "file.txt"
        updated.write_text("base update\n")
        git(root, "add", updated.name)
        git(root, "commit", "-qm", "base ahead")
        latest = git(root, "rev-parse", "HEAD")
        result = cli(root, "finalize", success=False)
        assert "aborted" in result["error"]
        retained(root, target, state, latest)
        assert git(target, "rev-parse", "HEAD") == result["commit"]
        assert (target / "file.txt").read_text() == "task\n"
        wt.idle_git(target)
        assert git(target, "status", "--porcelain") == ""
        pytest = _imports_pytest
        old = result["commit"]
        with pytest.raises(wt.Blocked, match="commit changed"):
            wt.recover(root, "example", "0" * 40, latest)
        with pytest.raises(wt.Blocked, match="base changed"):
            wt.recover(root, "example", old, "0" * 40)
        with pytest.raises(wt.Blocked, match="aborted"):
            wt.recover(root, "example", old, latest)
        assert tasks.status((target / state["task_file"]).read_text()) == "running"
        assert (
            "finish reviewed recovery" in cli(root, "finalize", success=False)["error"]
        )
        assert wt.git(target, "rebase", latest, check=False).returncode
        (target / "file.txt").write_text("base update\ntask\n")
        git(target, "add", "file.txt")
        git(target, "rebase", "--continue")
        (target / "file.txt").write_text("dirty\n")
        with pytest.raises(wt.Blocked, match="dirty"):
            wt.recover(root, "example", old, latest, finish=True)
        (target / "file.txt").write_text("base update\ntask\n")
        candidate = git(target, "rev-parse", "HEAD")
        previous_receipt = wt.load(root, "example")[3]["recovery"]
        (root / "base.txt").write_text("concurrent base advancement\n")
        git(root, "add", "base.txt")
        git(root, "commit", "-qm", "base advanced during reviewed recovery")
        advanced = git(root, "rev-parse", "HEAD")
        with pytest.raises(wt.Blocked, match="base changed"):
            wt.recover(root, "example", old, latest, finish=True)
        with pytest.raises(wt.Blocked, match="differs from expected commit"):
            wt.recover(root, "example", old, advanced, repin=True)
        repinned = wt.recover(root, "example", candidate, advanced, repin=True)
        assert repinned["recovery"]["previous"] == previous_receipt
        assert repinned["recovery"]["commit"] == candidate
        assert repinned["recovery"]["base"] == advanced
        assert git(target, "rev-parse", "HEAD") == candidate
        assert (
            "finish reviewed recovery" in cli(root, "finalize", success=False)["error"]
        )
        with pytest.raises(wt.Blocked, match="unexpected history"):
            wt.recover(root, "example", candidate, advanced, finish=True)
        git(target, "rebase", advanced)
        recovered = wt.recover(root, "example", candidate, advanced, finish=True)
        latest = advanced
        assert recovered["tip"] == git(target, "rev-parse", "HEAD")
        assert "recovery" not in recovered
        assert recovered["start"] == state["start"]
        assert wt.task_start_commit(target, state["task_file"]) == latest
        finish_contract(target, state)
        assert cli(root, "finalize")["cleaned"]
        assert (root / "file.txt").read_text() == "base update\ntask\n"


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
        assert (
            "collision" in cli(root, "create", "path-collision", success=False)["error"]
        )
        assert (path / "keep").read_text() == "human\n"
        stale = root / ".worktrees/stale"
        git(root, "worktree", "add", "--detach", stale, "HEAD")
        moved = stale.with_name("moved")
        stale.rename(moved)  # Simulate a stale Git entry without deleting its contents.
        assert "stale" in cli(root, "create", "stale", success=False)["error"]
        assert moved.exists()
        assert any(Path(e["worktree"]) == stale for e in wt.worktrees(root))


@it_case
def check_directory_layout():
    with fixture() as root:
        ignore = root / ".gitignore"
        ignore.write_text(
            ignore.read_text().replace("/.worktrees/\n", ""), encoding="utf-8"
        )
        git(root, "add", ".gitignore")
        git(root, "commit", "-qm", "missing worktree ignore")
        assert (
            "/.worktrees/ must be ignored"
            in cli(root, "create", success=False)["error"]
        )
        assert not wt.branch_exists(root, "codex/worktree/example")


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
            assert (
                "lifecycle busy" in cli(other, "setup", "two", success=False)["error"]
            )
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


def _callback_check_cleanup_failure_and_retry_deny_remove(
    real_git, /, where, *args, partial_remove=False, **kwargs
):
    if args[:2] == ("worktree", "remove"):
        if partial_remove:
            shutil.rmtree(Path(args[2]))
        raise wt.Blocked("injected cleanup failure")
    return real_git(where, *args, **kwargs)


@it_case
def check_cleanup_failure_and_retry():
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        real_git = wt.git
        deny_remove = _bind_framework_callback(
            _callback_check_cleanup_failure_and_retry_deny_remove, real_git
        )
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
        blocked = cli(root, "cleanup", success=False)
        assert "ignored files" in blocked["error"]
        assert blocked["cleanup"]["phase"] == "verify_worktree"
        assert blocked["cleanup"]["stop_reason"] == blocked["error"]
        assert (target / "secret.bin").read_bytes() == b"ignored human data"
        (target / "secret.bin").rename(root.parent / "saved-secret.bin")
        evidence_store = sealed_evidence.evidence_store
        write_sealed = sealed_evidence.write_sealed
        evidence = evidence_store(target)
        own, other = evidence / "example.json", evidence / "other.json"
        write_sealed(target, own, {"task": state["task_file"]})
        write_sealed(target, other, {"task": "tasks/other.md"})
        other_before = other.read_bytes()
        assert not (target / ".blueprint").exists()

        git(root, "branch", "feature", "HEAD^")
        git(root, "checkout", "-q", "feature")
        # Removal may succeed while branch deletion is blocked; retry from base safely.
        result = cli(target, "cleanup", success=False)
        assert "base must be checked out" in result["error"]
        assert (
            result["remaining_worktree"] is None
            and result["remaining_branch"] == state["branch"]
        )
        assert wt.branch_exists(root, state["branch"])
        git(root, "checkout", "-q", "main")
        result = cli(root, "cleanup")
        assert result["cleaned"] and git(root, "rev-parse", "HEAD") == saved["merged"]
        assert not wt.branch_exists(root, state["branch"])
        assert not own.exists() and other.read_bytes() == other_before
        other.unlink()
    with fixture() as root:
        target, state = start(root)
        other, other_state = start(root, "other")
        other_path = wt.load(root, "other")[2]
        other_before = other_path.read_bytes()
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        real_git = wt.git
        deny_remove = _bind_framework_callback(
            _callback_check_cleanup_failure_and_retry_deny_remove,
            real_git,
            partial_remove=True,
        )
        with (
            patch.object(wt, "git", side_effect=deny_remove),
            pytest.raises(wt.Blocked) as caught,
        ):
            wt.finalize(root, "example")
        assert caught.value.cleanup["phase"] == "remove_worktree"
        assert caught.value.cleanup["remaining"] == dict(
            worktree=False, git_registration=True, branch=True, task_state=True
        )
        assert not target.exists() and any(
            e.get("prunable")
            for e in wt.worktrees(root)
            if Path(e["worktree"]) == target
        )
        result = cli(root, "cleanup")
        assert result["cleaned"] and result["cleanup"]["phase"] == "complete"
        assert result["cleanup"]["remaining"] == dict(
            worktree=False, git_registration=False, branch=False, task_state=False
        )
        assert (
            not wt.branch_exists(root, state["branch"])
            and not wt.state_path(root, "example").exists()
        )
        assert (
            other.is_dir()
            and other_path.read_bytes() == other_before
            and wt.branch_exists(root, other_state["branch"])
        )
    print("Cleanup failure/retry/ignored data/merged history preserved: PASS")


def _callback_check_merge_retry_and_commit_failure_commit_hook_changes(
    real_git, target, /, where, *args, **kwargs
):
    if args[:1] == ("commit",):
        (target / "outside.txt").write_text("hook staged unrelated work\n")
        real_git(target, "add", "outside.txt")
    return real_git(where, *args, **kwargs)


def _callback_check_merge_retry_and_commit_failure_deny_merge(
    _state_check_merge_retry_and_commit_failure_505, /, where, *args, **kwargs
):
    if args[:1] == ("merge",):
        raise wt.Blocked("injected ff-only merge failure")
    return _state_check_merge_retry_and_commit_failure_505.real_git(
        where, *args, **kwargs
    )


@it_case
def check_merge_retry_and_commit_failure():
    _state_check_merge_retry_and_commit_failure_505 = _CallbackState()
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        (root / "base.txt").write_text("ahead\n")
        git(root, "add", "base.txt")
        git(root, "commit", "-qm", "ahead")
        latest = git(root, "rev-parse", "HEAD")
        _state_check_merge_retry_and_commit_failure_505.real_git = wt.git
        deny_merge = _bind_framework_callback(
            _callback_check_merge_retry_and_commit_failure_deny_merge,
            _state_check_merge_retry_and_commit_failure_505,
        )
        with patch.object(wt, "git", side_effect=deny_merge):
            try:
                wt.finalize(root, "example")
            except wt.Blocked as error:
                assert "merge failure" in str(error)
            else:
                raise AssertionError("merge failure must be reported")
        retained(root, target, state, latest)
        result = cli(root, "finalize")
        assert result["cleaned"] and result["commit"]
        assert git(root, "rev-list", "--count", "HEAD") == "3"
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task\n")
        finish_contract(target, state)
        latest = git(root, "rev-parse", "HEAD")
        _state_check_merge_retry_and_commit_failure_505.real_git = wt.git
        commit_hook_changes = _bind_framework_callback(
            _callback_check_merge_retry_and_commit_failure_commit_hook_changes,
            _state_check_merge_retry_and_commit_failure_505.real_git,
            target,
        )
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
    print("Failed merge retry and altered commit rejection: PASS")


@it_case
def check_human_approved_validation_failure():
    approval = "Human approves commit and merge despite file.txt trailing whitespace validation failure"
    with fixture() as root:
        target, state = start(root)
        (target / "file.txt").write_text("task  \n")
        tasks.suspend(
            target,
            state["task_file"],
            "Local loop failed: file.txt trailing whitespace",
        )
        cli(root, "finalize", success=False)  # No approval still blocks before commit.
        assert git(target, "rev-parse", "HEAD") == state["start"]
        (target / "secret.bin").write_bytes(b"keep suspended contract for inspection")
        result = cli(root, "finalize", success=False, approval=approval)
        assert "ignored files" in result["error"] and result["merged"]
        assert result["validation_failure_approval"] == approval
        text = (target / state["task_file"]).read_text()
        assert tasks.status(text) == "suspend" and "Local loop failed" in text
        assert (
            git(root, "log", "-1", "--format=%s")
            == "task(example): human-approved validation failure"
        )
        assert approval in git(root, "log", "-1", "--format=%b")
        assert (root / "file.txt").read_text() == "task  \n"
        (target / "secret.bin").unlink()
        assert cli(root, "cleanup")[
            "cleaned"
        ]  # Stored approval survives cleanup retry.
        assert not wt.branch_exists(root, state["branch"])


@it_case
def check_real_loop_integration():
    # Use shared Framework code with the existing synthetic Project fixture.
    with fixture() as root:
        loop_checks.make_project_fixture(SCRIPT.parents[2], root)
        for name in (
            "docs/designs",
            "model",
            "infra",
            "tests/scenarios",
            "tests/results",
        ):
            (root / name).mkdir(parents=True, exist_ok=True)
            (root / name / ".gitkeep").touch()
        git(root, "add", ".")
        git(root, "commit", "-qm", "Project fixture")
        target, state = start(root, files=("docs/system-overview.md",))
        overview = target / "docs/system-overview.md"
        overview.write_text("# Trailing whitespace  \n")
        loop = SCRIPT.with_name("blueprint-loop.py")
        environment = {
            **os.environ,
            tasks.SELECTOR: state["task_file"],
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(loop),
                "--mode",
                "task",
                "--task-file",
                state["task_file"],
            ],
            cwd=target,
            env=environment,
            capture_output=True,
            encoding="utf-8",
        )
        assert result.returncode != 0 and "FAIL" in result.stdout, (
            result.stdout + result.stderr
        )
        assert tasks.status((target / state["task_file"]).read_text()) == "suspend"
        before = git(root, "rev-parse", "HEAD")
        cli(root, "finalize", "example", success=False)
        retained(root, target, state, before)
        assert git(target, "rev-parse", "HEAD") == state["start"]


def _callback_check_final_candidate_staleness_validate(
    state, /, root, options, *, final_candidate
):
    assert (
        not wt.metadata_directory(Path(state["primary"]))
        .joinpath("lifecycle.lock")
        .exists()
    )
    return 0


@it_case
def check_final_candidate_staleness():
    operation_candidate = _imports_support_import_model_fixtures.operation_candidate
    operation_contract = _imports_support_import_model_fixtures.operation_contract
    operation_fixture = _imports_support_import_model_fixtures.operation_fixture
    with fixture() as root:
        operation_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "model fixture")
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate"
            sources = operation_candidate(root, candidate)
            target, state = start(root, files=tuple(sorted(sources)))
            text = operation_contract()
            for heading in ("Modified files", "Allowed paths"):
                text += (
                    "\n## "
                    + heading
                    + "\n"
                    + "".join(
                        "- `" + value + "`\n"
                        for value in sorted(sources | {state["task_file"]})
                    )
                )
            text += "\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n"
            (target / state["task_file"]).write_text(text)
            for name in sources:
                shutil.copyfile(candidate / name, target / name)
            (root / "unrelated.txt").write_text("new base\n")
            git(root, "add", "unrelated.txt")
            git(root, "commit", "-qm", "unrelated base")
            latest = git(root, "rev-parse", "HEAD")
            final = wt.prepare_integration(root, "example")
            assert (
                final.base_commit == latest
                and "unrelated.txt" not in final.changed_paths
            )
            assert not wt.changed_paths(target) and final.changed_paths == sources
            validate = _bind_framework_callback(
                _callback_check_final_candidate_staleness_validate, state
            )
            with patch.object(loop, "run_loop", side_effect=validate) as checked:
                result = wt.validate_final_candidate(final)
                checked.assert_called_once()
            git(target, "commit", "--allow-empty", "-qm", "unexpected")
            base_head = git(root, "rev-parse", "HEAD")
            with pytest.raises(ValueError, match="candidate/base changed"):
                wt.merge_validated_candidate(result)
            retained(root, target, state, base_head)


@it_case
def check_approved_model_reads():
    approval = "Human accepts fixture validation failure for Git integration"
    relative = "model/stg/cde/vpc.properties"
    for mode in ("changed-import", "missing"):
        with fixture() as root:
            operation_fixture(root)
            git(root, "add", "model", "project.json")
            git(root, "commit", "-qm", "synthetic Model baseline")
            target, state = start(root, files=(relative,))
            source = target / relative
            source.write_text(source.read_text() + "\n# integration fixture\n")
            if mode == "changed-import":
                source.write_text(
                    source.read_text().replace("10.9.0.0/16", "10.8.0.0/16")
                )
            importing = mode not in ("preserved", "changed-import")
            contract = target / state["task_file"]
            contract.write_text(
                contract.read_text()
                .replace("`governance`", "`design`")
                .replace("- `framework`", "- `stg/cde/vpc`")
            )
            if importing:
                contract = target / state["task_file"]
                text = contract.read_text().replace(
                    "- Task type: `design`",
                    "- Task type: `design`\n- Workflow: `import`",
                )
                contract.write_text(
                    text.replace("- `framework`", "- `stg/cde/vpc`\n- `dev/cde/vpc`")
                )
            tasks.suspend(
                target, state["task_file"], "Synthetic validation FAIL: properties"
            )
            saved = (target / state["task_file"]).read_bytes()
            before = git(root, "rev-parse", "HEAD")
            with tasks.selected_task(target, state["task_file"]):
                for call in (
                    lambda *, target=target: tasks.task_path(target),
                    lambda *, target=target: active_scope(target),
                    lambda *, target=target: guard.require_import_changes(target),
                ):
                    with pytest.raises(ValueError, match="suspend task cannot execute"):
                        call()
            cli(root, "finalize", success=False)
            with (
                mapping_alias(SCRIPT.parents[2], target),
                patch.object(
                    wt.python_env,
                    "runtime",
                    return_value=(
                        Path(sys.executable),
                        wt.python_env.environment(Path(sys.prefix)),
                    ),
                ),
            ):
                if mode in {"preserved", "changed-import"}:
                    # Keep the checkout for byte-for-byte status inspection, then exercise cleanup retry.
                    (target / "secret.bin").write_text("preserve")
                    with pytest.raises(wt.Blocked, match="ignored files"):
                        wt.finalize(root, "example", approval)
                    assert (target / state["task_file"]).read_bytes() == saved
                    assert approval in git(root, "log", "-1", "--format=%b")
                    assert (root / relative).read_bytes() == source.read_bytes()
                    (target / "secret.bin").unlink()
                    assert wt.cleanup(root, "example")["cleaned"]
                    assert not target.exists() and not wt.branch_exists(
                        root, state["branch"]
                    )
                else:
                    with pytest.raises(ValueError, match="no verified") as error:
                        wt.finalize(root, "example", approval)
                    assert "suspend task cannot execute" not in str(error.value)
                    retained(root, target, state, before)
                    assert git(target, "rev-parse", "HEAD") == state["start"]
                    assert (target / state["task_file"]).read_bytes() == saved
    print(
        "Approved suspended Model Git integration and missing IMPORT evidence rejection: PASS"
    )


@it_case
def check_registered_normal_model_guard():
    relative = "model/stg/cde/service-a.properties"
    with fixture() as root:
        dependency_fixture(root)
        (root / ".gitignore").write_text((root / ".gitignore").read_text() + ".venv/\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "synthetic runtime fixture")
        target, state = start(root, files=(relative,))
        contract_path = target / state["task_file"]
        text = (
            contract_path.read_text()
            .replace("`governance`", "`design`")
            .replace("- `framework`", "- `stg/cde/service-a`\n- `stg/cde/service-b`")
        )
        contract_path.write_text(text)
        directory = wt.python_env.shared_directory(root)
        directory.mkdir()
        (directory / ".blueprint-owner").write_text(str(directory))
        venv.EnvBuilder(with_pip=False).create(directory)
        interpreter = wt.python_env.python_path(directory)
        site = subprocess.run(
            [
                str(interpreter),
                "-c",
                'import sysconfig; print(sysconfig.get_path("purelib"))',
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        # Reuse installed test dependencies offline; the fixture never invokes pip/setup.
        Path(site, "fixture-dependencies.pth").write_text(
            "\n".join(p for p in sys.path if p.endswith("site-packages")) + "\n"
        )
        probe = root.parent / "guard-probe.json"
        Path(site, "guard_probe.py").write_text(
            """import sys, json, atexit, os
from pathlib import Path
counts = {}
def profile(frame, event, arg):
    if event != 'call': return
    name, file = frame.f_code.co_name, Path(frame.f_code.co_filename).name
    if file == 'worktree_task.py' and name in ('lifecycle_lock', 'finalize', 'prepare_integration', 'cleanup'):
        raise AssertionError('guard child entered lifecycle')
    if file in ('references.py', 'sources.py') and name in ('usages', '_read_model'):
        assert sys.modules['utils.input_cache'].memo_table() is not None
        counts[name] = counts.get(name, 0) + 1
sys.setprofile(profile)
atexit.register(lambda: Path(os.environ['GUARD_PROBE']).write_text(json.dumps(counts)))
""",
            encoding="utf-8",
        )
        Path(site, "guard-probe.pth").write_text(
            "import guard_probe\n", encoding="utf-8"
        )
        (directory / ".blueprint-ready").write_text(str(directory))
        state["python_setup"] = dict(
            status="ready",
            kind="shared",
            installed=False,
            interpreter=str(interpreter),
            bin=str(interpreter.parent),
        )
        _, _, state_path, _ = wt.load(root, "example")
        wt.save(state_path, state)
        (target / relative).write_text(
            (target / relative).read_text() + "\n# ordinary save\n"
        )
        finish_contract(target, state)
        environment = {
            **os.environ,
            "BLUEPRINT_TASK_FILE": "tasks/foreign.md",
            "GUARD_PROBE": str(probe),
        }
        parent = [
            sys.executable,
            "-S",
            "-B",
            "-c",
            "import sys, importlib.util; "
            'assert importlib.util.find_spec("pystache") is None; '
            "sys.path.insert(0, sys.argv.pop(1)); "
            "import worktree_task; raise SystemExit(worktree_task.main())",
            str(SCRIPT.parent),
            "finalize",
            "--repository-root",
            str(root),
            "--task-id",
            "example",
        ]
        result = subprocess.run(
            parent,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        response = json.loads(result.stdout)
        assert result.returncode == 0, response
        assert response["cleaned"] and response["merged"]
        counts = json.loads(probe.read_text())
        assert counts["usages"] >= 1 and counts["_read_model"] >= 1, counts
        assert not target.exists()
        assert wt.python_env.shared_ready(directory)
        assert (root / relative).read_text().endswith("# ordinary save\n")
    print(
        "Ordinary Model guard in registered shared venv with dependency-free parent: PASS"
    )


def main():
    for check in (
        check_sync_base_preserves_candidate,
        check_deploy_workflow_cross_task_reset_rejected,
        check_success_and_empty,
        check_finalize_line_endings,
        check_incomplete_and_git_safety,
        check_dirty_base_and_retry,
        check_ahead_and_rebase_conflict,
        check_collisions_and_base_selection,
        check_directory_layout,
        check_metadata_storage,
        check_cleanup_failure_and_retry,
        check_merge_retry_and_commit_failure,
        check_human_approved_validation_failure,
        check_real_loop_integration,
        check_final_candidate_staleness,
        check_approved_model_reads,
        check_registered_normal_model_guard,
        check_model_operation_integration,
        check_model_refactor_integration,
    ):
        check()
    print("worktree-task: PASS (Git integration and failure recovery)")


def _callback_check_model_operation_integration_validate(
    require_import_changes, /, root, options, *, final_candidate
):
    assert not (root.parent / ".blueprint/lifecycle.lock").exists()
    with tasks.selected_task(root, final_candidate.task_file):
        require_import_changes(
            root, final_candidate.changed_paths, final_candidate=final_candidate
        )
    return 0


@it_case
def check_model_operation_integration():
    operation_candidate = _imports_support_import_model_fixtures.operation_candidate
    operation_contract = _imports_support_import_model_fixtures.operation_contract
    operation_fixture = _imports_support_import_model_fixtures.operation_fixture
    action = "import-merge"
    with fixture() as root:
        operation_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "model fixture")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate"
            sources = operation_candidate(root, candidate, action)
            target, state = start(root, files=tuple(sorted(sources)))
            text = operation_contract(action)
            for heading in ("Modified files", "Allowed paths"):
                text += (
                    "\n## "
                    + heading
                    + "\n"
                    + "".join(
                        "- `" + name + "`\n"
                        for name in sorted(sources | {state["task_file"]})
                    )
                )
            text += "\n## Validation scope\n- `dev/cde/vpc`\n- `stg/cde/vpc`\n"
            (target / state["task_file"]).write_text(text)
            tasks.refresh(target, state["task_file"])
            for name in sources:
                shutil.copyfile(candidate / name, target / name)
            with (
                mapping_alias(SCRIPT.parents[2], target),
                patch.object(
                    wt.python_env,
                    "runtime",
                    return_value=(
                        Path(sys.executable),
                        wt.python_env.environment(Path(sys.prefix)),
                    ),
                ),
            ):
                finish_contract(target, state)
                final = wt.prepare_integration(root, "example")
                require_import_changes = _imports_import_guard.require_import_changes
                loop = _imports_validation_loop
                validate = _bind_framework_callback(
                    _callback_check_model_operation_integration_validate,
                    require_import_changes,
                )
                with patch.object(loop, "run_loop", side_effect=validate):
                    result = wt.validate_final_candidate(final)
                    assert (
                        wt.merge_validated_candidate(result)["merged"]
                        == final.candidate_head
                    )
                    assert wt.cleanup(root, "example")["cleaned"]
                    assert not target.exists()
    print("Model-only merge final-candidate integration: PASS")


def _callback_check_model_refactor_integration_validate(
    calls, /, root, options, *, final_candidate
):
    calls.append(final_candidate.candidate_head)
    assert not (root.parent / ".blueprint/lifecycle.lock").exists()
    with tasks.selected_task(root, final_candidate.task_file):
        require_import_changes(
            root, final_candidate.changed_paths, final_candidate=final_candidate
        )
    return 0


@it_case
def check_model_refactor_integration():
    dependency_contract = _imports_support_import_model_fixtures.dependency_contract
    dependency_fixture = _imports_support_import_model_fixtures.dependency_fixture
    dependency_refactor = _imports_support_import_model_fixtures.dependency_refactor

    with fixture() as root, tempfile.TemporaryDirectory() as directory:
        dependency_fixture(root)
        git(root, "add", "model", "project.json")
        git(root, "commit", "-qm", "generic Model fixture")
        candidate = Path(directory) / "candidate"
        sources = dependency_refactor(root, candidate)
        target, state = start(root, files=tuple(sorted(sources)))
        text = dependency_contract()
        for heading in ("Modified files", "Allowed paths"):
            text += (
                "\n## "
                + heading
                + "\n"
                + "".join(
                    "- `" + name + "`\n"
                    for name in sorted(sources | {state["task_file"]})
                )
            )
        text += "\n## Validation scope\n- `dev/cde/service-a`\n- `dev/cde/service-b`\n- `stg/cde/service-a`\n- `stg/cde/service-b`\n"
        (target / state["task_file"]).write_text(text)
        tasks.refresh(target, state["task_file"])
        with (
            mapping_alias(SCRIPT.parents[2], target),
            tasks.selected_task(target, state["task_file"]),
        ):
            output = {target / name: (candidate / name).read_text() for name in sources}
            scope = {("stg", "cde", "service-b")}
            with edit_write_context(target, scope, state["task_file"]) as context:
                path = next(iter(output))
                publish_edit(
                    prepare_edit(load_model(path, context.snapshot), output, context),
                    context,
                )
            require_import_changes(target)
            assert (
                load_model(target / "model/stg/cde/service-b.properties").values[
                    "desired.row.002-001.value"
                ]
                == "same-name-stg"
            )
            file = root / "model/stg/cde/service-a.properties"
            file.write_text(file.read_text().replace("same-name-stg", "advanced-name"))
            git(root, "add", file)
            git(root, "commit", "-qm", "advance producer on base")
            latest = git(root, "rev-parse", "HEAD")
            final = wt.prepare_integration(root, "example")
            assert final.base_commit == latest
            calls = []
            validate = _bind_framework_callback(
                _callback_check_model_refactor_integration_validate, calls
            )
            with patch.object(loop, "run_loop", side_effect=validate):
                with redirect_stderr(io.StringIO()) as warnings:
                    result = wt.validate_final_candidate(final)
                assert (
                    "producer name/identifier differs from saved text"
                    not in warnings.getvalue()
                )
                assert (
                    wt.merge_validated_candidate(result)["merged"]
                    == final.candidate_head
                )
                assert wt.cleanup(root, "example")["cleaned"]
            assert calls == [final.candidate_head]


if __name__ == "__main__":
    main()
