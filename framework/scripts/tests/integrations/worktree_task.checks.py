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
from import_guard import require_import_changes
from model.adapters.task import edit_write_context
from model.format import serialize
from model.identity import allocate
from model.importing import cli as import_cli
from model.sources import load_model
from support import blueprint_loop_fixtures as loop_checks
from support.import_model_fixtures import (
    VPC_ID,
    aws,
    correspondence,
    dependency_fixture,
    exclusions,
    operation_fixture,
    publish_fixture,
    reference_fields,
    resource_values,
    service_values,
    stage,
)
from support.import_model_fixtures import (
    fixture as import_fixture,
)
from support.it_case_receipt import it_case
from support.model_sources import write_model
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
from utils import sealed_evidence
from utils.aws_mappings import mapping_alias
from validation import loop
from validation_scope import active_scope

from model import prepare_edit, publish_edit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _check_import_completion_and_approved_integration():
    for suspended in (False, True):
        with fixture() as root:
            import_fixture(root, "vpc", register=False, focused=True)
            consumer = service_values("vpc-endpoint", ["EC2.VPCEndpoint"])
            consumer.update(
                resource_values(
                    "001",
                    "EC2.VPCEndpoint",
                    "endpoint",
                    "IMPORT",
                    [("VpcId", "[001](vpc.md#vpc-main)")],
                )
            )
            consumer.update(
                reference_fields(
                    "vpc",
                    "desired.row.001-001.value",
                    "[001](vpc.md#vpc-main)",
                    "dev/cde/vpc/001",
                    kind="EC2.VPC",
                    mode="link",
                )
            )
            write_model(root / "model/dev/cde/vpc-endpoint.properties", consumer)
            git(root, "add", "model", "project.json")
            git(root, "commit", "-qm", "Import fixture")
            relative = "model/dev/cde/vpc.properties"
            design = "docs/designs/dev/cde/vpc.md"
            foreign_view = "docs/designs/dev/cde/vpc-endpoint.md"
            target, state = start(root, files=(relative, design, foreign_view))
            name = state["task_file"]
            contract = target / name
            contract.write_text(
                contract.read_text()
                .replace("`governance`", "`design`")
                .replace(
                    "- Task status:",
                    "- Workflow: `import`\n- IMPORT target: `dev/cde/vpc`\n- Task status:",
                )
                .replace("- `framework`", "- `dev/cde/vpc`")
            )
            path = target / relative
            with (
                mapping_alias(SCRIPT.parents[2], target),
                tasks.selected_task(target, name),
            ):
                before = load_model(path)
                cli = aws("vpc", changed=True)
                identity = "subnet-managed-new"
                cli.responses["ec2", "describe-subnets"]["Subnets"].append(
                    {
                        "SubnetId": identity,
                        "VpcId": VPC_ID,
                        "CidrBlock": "10.11.0.0/26",
                        "AvailabilityZone": "ap-northeast-1a",
                        "MapPublicIpOnLaunch": False,
                        "Tags": [{"Key": "Name", "Value": "audit-private-1a"}],
                    }
                )
                acquired = import_cli.acquire(
                    target, "dev", "vpc", "cde", cli_runner=cli
                )
                values = dict(before.authoritative)
                for key, value in before.authoritative.items():
                    if key.startswith(
                        (
                            "desired.resource.002.",
                            "display.resource.002.",
                            "desired.row.002-",
                            "observed.row.002-",
                        )
                    ):
                        values[key.replace(".002", ".009", 1)] = value
                del values["desired.resource.009.logicalId"]
                values = allocate(values, ["009"])
                values.update(
                    {
                        "desired.resource.009.anchor": "vpc-managed-009",
                        "desired.row.009-001.value": "[009](#vpc-managed-009)",
                        "observed.row.009-001.value": identity,
                        "desired.row.009-003.value": "`10.11.0.0/26`",
                        "desired.row.009-004.value": "`audit-private-1a`",
                    }
                )
                selected = [correspondence(acquired, identity, "009")]
                stage(
                    target,
                    acquired,
                    {relative: serialize(values)},
                    selected,
                    exclusions(acquired, selected),
                )
                assert publish_fixture(target, acquired, "vpc")["model"] == "reflected"
                candidate = path.read_bytes()
                path.write_bytes(candidate + b"\n# tampered\n")
                with pytest.raises(
                    ValueError, match="differs from acquired change plan"
                ):
                    tasks.complete(target, name)
                path.write_bytes(candidate)
                consumer_path = target / "model/dev/cde/vpc-endpoint.properties"
                consumer_before = consumer_path.read_bytes()
                consumer_path.write_bytes(consumer_before + b"\n# unauthorized\n")
                with pytest.raises(
                    ValueError, match="outside task scope|Modified files"
                ):
                    tasks.complete(target, name)
                consumer_path.write_bytes(consumer_before)
                if suspended:
                    tasks.suspend(target, name, "Synthetic validation failure")
                    approval = "Human accepts synthetic validation failure"
                    with pytest.raises(wt.Blocked, match="task must be completed"):
                        wt.finalize(root, "example")
                    assert tasks.status(contract.read_text()) == "suspend"
                else:
                    tasks.complete(target, name)
                    approval = None
                with patch.object(
                    wt.python_env,
                    "runtime",
                    return_value=(
                        Path(sys.executable),
                        wt.python_env.environment(Path(sys.prefix)),
                    ),
                ):
                    saved = contract.read_text()
                    contract.write_text(
                        saved.replace(
                            "exists:" + relative, "exists:missing-required.txt"
                        )
                    )
                    with pytest.raises(wt.Blocked, match="required path missing"):
                        wt.finalize(root, "example", approval)
                    assert target.exists() and tasks.status(contract.read_text()) == (
                        "suspend" if suspended else "completed"
                    )
                    contract.write_text(saved)
                    foreign = target / foreign_view
                    foreign.parent.mkdir(parents=True, exist_ok=True)
                    foreign.write_text("unauthorized view")
                    with pytest.raises(wt.Blocked, match="outside selected"):
                        wt.finalize(root, "example", approval)
                    assert target.exists() and contract.read_text() == saved
                    foreign.unlink()
                    result = wt.finalize(root, "example", approval)
                assert result["cleaned"]
                assert (root / relative).read_bytes() == candidate
                if suspended:
                    assert approval in git(root, "log", "-1", "--format=%b")


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


@it_case
def check_old_workflow_registry_is_ignored():
    with fixture() as primary:
        directory = wt.metadata_directory(primary) / "deploy-workflows"
        directory.mkdir(parents=True)
        retained = directory / "old.json"
        retained.write_text('{"workflowId":"old","status":"unfinished"}')
        target, state = start(primary, task_id="new-deploy", files=("file.txt",))
        assert target.is_dir() and state["task_id"] == "new-deploy"
        assert retained.read_text() == '{"workflowId":"old","status":"unfinished"}'


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
    _check_normal_model_final_candidate()
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


def _callback_normal_model_candidate(mode, /, root, options, *, final_candidate):
    assert tasks.status((root / final_candidate.task_file).read_text()) == "running"
    with tasks.selected_task(root, final_candidate.task_file):
        require_import_changes(
            root, final_candidate.changed_paths, final_candidate=final_candidate
        )
    return 1 if mode == "fail" else 0


def _check_normal_model_final_candidate():
    relative = "model/stg/cde/service-a.properties"
    for mode in ("pass", "fail", "head", "base", "task"):
        with fixture() as root:
            dependency_fixture(root)
            git(root, "add", "model", "project.json")
            git(root, "commit", "-qm", "Model fixture")
            target, state = start(root, files=(relative,))
            task = target / state["task_file"]
            text = (
                task.read_text()
                .replace("`governance`", "`design`")
                .replace(
                    "- Task status:",
                    "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n- Task status:",
                )
                .replace(
                    "- `framework`", "- `stg/cde/service-a`\n- `stg/cde/service-b`"
                )
            )
            task.write_text(text)
            source = target / relative
            source.write_text(source.read_text() + "\n# ordinary correction\n")
            (root / "upstream.txt").write_text("latest\n")
            git(root, "add", "upstream.txt")
            git(root, "commit", "-qm", "advance base")
            latest = git(root, "rev-parse", "HEAD")
            with mapping_alias(SCRIPT.parents[2], target):
                candidate = wt.prepare_integration(root, "example")
                assert candidate.base_commit == latest
                assert wt.task_start_commit(target, state["task_file"]) == latest
                assert wt.committed_task_paths(target, state["task_file"]) == {relative}
                assert tasks.final_model_task(
                    text, wt.integration_changed_paths(target, state["task_file"])
                )
                if mode == "pass":
                    # Resume the retained rebased candidate through the normal Scope preflight.
                    tasks.suspend(
                        target, state["task_file"], "reviewed integration interruption"
                    )
                    tasks.resume(target, state["task_file"])
                    resumed = wt.prepare_integration(root, "example")
                    assert resumed.candidate_head == candidate.candidate_head
                    assert resumed.base_commit == candidate.base_commit
                    assert resumed.changed_paths == candidate.changed_paths
                    candidate = resumed
                validate = _bind_framework_callback(
                    _callback_normal_model_candidate, mode
                )
                with patch.object(loop, "run_loop", side_effect=validate) as checked:
                    result = wt.validate_final_candidate(candidate)
                    checked.assert_called_once()
                if mode == "head":
                    git(target, "commit", "--allow-empty", "-qm", "changed")
                elif mode == "base":
                    git(root, "commit", "--allow-empty", "-qm", "changed")
                elif mode == "task":
                    task.write_text(text + "\nChanged after validation\n")
                if mode != "pass":
                    with pytest.raises(ValueError):
                        wt.merge_validated_candidate(result)
                    assert target.is_dir()
                    assert git(root, "rev-parse", "HEAD") != candidate.candidate_head
                else:
                    assert (
                        wt.merge_validated_candidate(result)["merged"]
                        == candidate.candidate_head
                    )
                    assert tasks.status(task.read_text()) == "completed"
                    assert git(root, "rev-parse", "HEAD") == candidate.candidate_head
                    assert wt.cleanup(root, "example")["cleaned"]


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
                    "- Task type: `design`\n- Workflow: `import`\n- IMPORT target: `stg/cde/vpc`",
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
    _check_import_completion_and_approved_integration()
    print(
        "Approved suspended Model Git integration and missing IMPORT evidence rejection: PASS"
    )


@it_case
def check_registered_normal_model_guard():
    relative = "model/stg/cde/service-a.properties"
    with fixture() as root:
        dependency_fixture(root)
        # Requirements select local definitions, so provision the complete Framework.
        shutil.copytree(
            Path(wt.__file__).resolve().parents[1],
            root / "framework",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        requirements = root / wt.python_env.REQUIREMENTS
        requirements.write_text("", encoding="utf-8")
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
    if file in ('references.py', 'sources.py') and name in ('usages', '_read_model', 'raw_model'):
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
        (directory / wt.python_env.APPLIED).write_text(
            wt.python_env.hashlib.sha256(requirements.read_bytes()).hexdigest(),
            encoding="utf-8",
        )
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
        assert counts.get("usages", 0) == 0 and counts["raw_model"] >= 1, counts
        assert not target.exists()
        assert wt.python_env.shared_ready(directory)
        assert (root / relative).read_text().endswith("# ordinary save\n")
    print(
        "Ordinary Model guard in registered shared venv with dependency-free parent: PASS"
    )


def main():
    for check in (
        check_sync_base_preserves_candidate,
        check_old_workflow_registry_is_ignored,
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
        check_framework_final_candidate,
    ):
        check()
    print("worktree-task: PASS (Git integration and failure recovery)")


@it_case
def check_framework_final_candidate():
    relative = ".github/workflows/framework-it.yml"
    for success in (False, True):
        with fixture() as root:
            loop_checks.make_project_fixture(SCRIPT.parents[2], root)
            shutil.copytree(
                SCRIPT.parents[1],
                root / "framework",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            for directory in (
                "docs/designs",
                "infra",
                "tests/scenarios",
                "tests/results",
            ):
                (root / directory / ".gitkeep").touch()
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text("name: Framework IT\n")
            git(root, "add", ".")
            git(root, "commit", "-qm", "synthetic Framework fixture")
            target, state = start(root, files=(relative,))
            source = target / relative
            source.write_text(source.read_text() + "\nTask correction\n")
            if not success:
                task = target / state["task_file"]
                task.write_text(
                    task.read_text().replace(f"exists:{relative}", f"absent:{relative}")
                )
            # Advance the base with a path outside the Task's declarations.
            (root / "upstream.txt").write_text("inherited base\n")
            git(root, "add", "upstream.txt")
            git(root, "commit", "-qm", "advance Framework base")
            latest = git(root, "rev-parse", "HEAD")
            candidate = wt.prepare_integration(root, "example")
            assert candidate.scope == frozenset() and candidate.changed_paths == {
                relative
            }
            assert not (target / "project.json").exists()
            assert tasks.status((target / state["task_file"]).read_text()) == "running"
            with patch(
                "model.sources.raw_model",
                side_effect=AssertionError("Framework must not load Models"),
            ):
                result = wt.validate_final_candidate(candidate)
            if success:
                assert result.returncode == 0
                merged = wt.merge_validated_candidate(result)
                assert (
                    merged["merged"]
                    == candidate.candidate_head
                    == git(root, "rev-parse", "HEAD")
                )
                assert (
                    tasks.status((target / state["task_file"]).read_text())
                    == "completed"
                )
                assert wt.cleanup(root, "example")["cleaned"]
                assert not target.exists()
            else:
                assert result.returncode != 0
                with pytest.raises(wt.Blocked, match="no merge"):
                    wt.merge_validated_candidate(result)
                retained(root, target, state, latest)
                assert git(target, "rev-parse", "HEAD") == candidate.candidate_head
                assert (
                    tasks.status((target / state["task_file"]).read_text()) == "suspend"
                )


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
