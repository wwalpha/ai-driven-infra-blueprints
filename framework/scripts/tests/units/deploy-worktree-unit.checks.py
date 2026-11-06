"""Deploy-only snapshot, ownership, progress and Git failure boundaries without Git fixtures."""

import copy
import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import worktree_checkpoint as checkpoints
import worktree_state as ws
from deploy import (
    controller,
    guards,
    inputs,
    operation_journal,
    run_context,
    worktree,
)
from deploy import git_publication as publication
from deploy import progress as deploy_progress
from support.pytest_cli import run
from task_contract_core import task_digest
from utils.cloudformation.inputs import Blocked as DeployBlocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_source_scope_shares_deploy_baseline(tmp_path, monkeypatch):
    start = Mock(return_value="start")
    observation = Mock()
    findings = SimpleNamespace(errors=[])
    task = Mock()
    monkeypatch.setattr(publication.ws, "deploy_start_commit", start)
    monkeypatch.setattr(publication, "require_observation_delta", observation)
    monkeypatch.setattr(publication, "Findings", Mock(return_value=findings))
    factory = Mock(return_value=task)
    monkeypatch.setattr(publication, "TaskValidation", factory)
    publication.check_scope_in_process(tmp_path, "tasks/deploy.md")
    start.assert_called_once_with(tmp_path, "tasks/deploy.md", required=True)
    observation.assert_called_once_with(tmp_path, "start")
    factory.assert_called_once_with(tmp_path, findings, contract_file="tasks/deploy.md")
    TestCase().assertEqual((task.baseline, task.baseline_fixed), ("start", True))
    task.check_task_scope.assert_called_once()
    task.check_task_type_requirements.assert_called_once()
    findings.errors.append("outside scope")
    with pytest.raises(ValueError, match="outside scope"):
        publication.check_scope_in_process(tmp_path, "tasks/deploy.md")


def check_zero_delta_checkpoint_returns_head(tmp_path, monkeypatch):
    snapshot = SimpleNamespace(raw=b"task")
    monkeypatch.setattr(
        publication.tasks, "read_task_snapshot", lambda *a, **k: snapshot
    )
    monkeypatch.setattr(publication.worktree, "require", lambda *a: None)
    monkeypatch.setattr(publication.wt, "changed_paths", lambda root: set())
    output = Mock(return_value="existing-head")
    git = Mock()
    monkeypatch.setattr(publication.wt, "output", output)
    monkeypatch.setattr(publication.wt, "git", git)
    monkeypatch.setattr(
        publication.contracts, "validation_snapshot", Mock(return_value={})
    )
    scope = Mock()
    guard = Mock()
    monkeypatch.setattr(publication, "check_scope", scope)
    monkeypatch.setattr(publication.wt, "_run_model_guard", guard)
    preflight = {
        "task": b"task",
        "head": "existing-head",
        "index": "existing-head",
        "changed": set(),
        "candidate": {},
    }
    TestCase().assertEqual(
        publication.checkpoint(
            tmp_path,
            tmp_path / "state",
            {"task_file": "tasks/deploy.md"},
            preflight=preflight,
        ),
        "existing-head",
    )
    scope.assert_not_called()
    guard.assert_not_called()


@pytest.mark.parametrize("problem", ["task", "head", "index", "candidate", "paths"])
def check_preflight_change_blocks_checkpoint(tmp_path, monkeypatch, problem):
    snapshot = SimpleNamespace(raw=b"task")
    changed = {"model/a.properties"}
    path = tmp_path / "model/a.properties"
    path.parent.mkdir()
    path.write_text("observed", encoding="utf-8")
    preflight = {
        "task": b"other" if problem == "task" else b"task",
        "head": "other" if problem == "head" else "head",
        "index": "other" if problem == "index" else "index",
        "candidate": {"model/a.properties": "other"} if problem == "candidate" else {},
        "changed": set() if problem == "paths" else changed,
    }
    monkeypatch.setattr(
        publication.tasks, "read_task_snapshot", Mock(return_value=snapshot)
    )
    monkeypatch.setattr(publication.worktree, "require", Mock())
    monkeypatch.setattr(publication.wt, "changed_paths", Mock(return_value=changed))
    monkeypatch.setattr(publication.wt, "output", Mock(side_effect=["head", "index"]))
    monkeypatch.setattr(
        publication.contracts, "validation_snapshot", Mock(return_value={})
    )
    scope = Mock()
    guard = Mock()
    monkeypatch.setattr(publication, "check_scope", scope)
    monkeypatch.setattr(publication.wt, "_run_model_guard", guard)
    with pytest.raises(ValueError, match="changed during preflight"):
        publication.checkpoint(
            tmp_path,
            tmp_path / "state",
            {"task_file": "tasks/deploy.md"},
            preflight=preflight,
        )
    scope.assert_not_called()
    guard.assert_not_called()


def check_outside_change_blocks_snapshot_checkpoint(tmp_path, monkeypatch):
    target = tmp_path / "deploy"
    target.mkdir()
    readme = target / "README.md"
    readme.write_text("foreign change\n")
    before = {"model/a.properties": "old"}
    after = {"model/a.properties": "new"}
    state = {"deployCheckpoints": {}, "task_file": "tasks/deploy.md"}
    context = {"checkpointPending": {"stacks": ["A"], "before": before, "after": after}}
    backend = SimpleNamespace(
        root=target, run_context=context, states={"A": {"observedSynced": True}}
    )
    monkeypatch.setattr(
        checkpoints.wt, "load", lambda *a: (tmp_path, None, tmp_path / "state", state)
    )
    monkeypatch.setattr(checkpoints.wt, "lifecycle_lock", lambda *a: nullcontext())
    monkeypatch.setattr(checkpoints.worktree, "require", lambda *a: state)
    monkeypatch.setattr(checkpoints.contracts, "validation_snapshot", lambda *a: after)
    monkeypatch.setattr(
        checkpoints.wt, "changed_paths", lambda *a: {"model/a.properties", "README.md"}
    )
    git = Mock()
    monkeypatch.setattr(checkpoints.wt, "git", git)
    with pytest.raises(ValueError, match="outside synchronized Model/views"):
        checkpoints.snapshot_checkpoint(backend, ["A"])
    assert readme.read_text() == "foreign change\n"
    assert state["deployCheckpoints"] == {}
    assert context["checkpointPending"]["after"] == after
    git.assert_not_called()


def task(root):
    text = "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Infrastructure phase: `deploy`\n"
    return SimpleNamespace(
        name="tasks/deploy.md", text=text, task_digest=task_digest(text)
    )


def _callback_snapshot_git(replies, /, root, *args, **kwargs):
    reply = replies.get((root, *args), replies.get(args))
    assert reply is not None, args
    if isinstance(reply, Exception):
        raise reply
    return SimpleNamespace(stdout=reply, returncode=0)


@pytest.mark.parametrize(
    "problem",
    [
        None,
        "head",
        "ancestry",
        "owner",
        "merged",
        "branch",
        "missing",
        "locked",
        "stale",
        "setup",
        "digest",
        "lifecycle",
        "conflict",
        "operation",
        "git",
        "checkpoint",
        "checkpoint-parent",
        "checkpoint-tree",
        "checkpoint-message",
        "repository-lines",
    ],
)
def check_snapshot_ignores_base_history(tmp_path, monkeypatch, problem):
    primary = tmp_path / "primary"
    root = primary / ".worktrees/deploy"
    root.mkdir(parents=True)
    snapshot = task(root)
    meta = ws.state_path(primary, "deploy")
    meta.parent.mkdir(parents=True)
    state = dict(
        task_id="deploy",
        task_file=snapshot.name,
        primary=str(primary),
        branch="codex/worktree/deploy",
        worktree=str(root),
        start="snapshot",
        tip="tip",
        merged=None,
        python_setup={"status": "ready"},
        deployIdentity={"taskDigest": snapshot.task_digest},
    )
    common = primary / ".git"
    directory = common / "worktrees/deploy"
    directory.mkdir(parents=True)
    gitfile = root / ".git"
    gitfile.write_text(f"gitdir: {directory}\n")
    (directory / "gitdir").write_text(str(gitfile))
    ref = "refs/heads/" + state["branch"]
    replies = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-bare-repository"): "false",
        ("rev-parse", "--path-format=absolute", "--git-common-dir"): str(
            primary / ".git"
        ),
        ("rev-parse", "--verify", "snapshot^{commit}"): "snapshot",
        ("rev-parse", "HEAD"): "tip",
        ("rev-parse", "--absolute-git-dir"): str(directory),
        ("symbolic-ref", "HEAD"): ref,
        ("rev-parse", "--verify", "HEAD^{commit}"): "tip",
        ("rev-parse", "--verify", ref + "^{commit}"): "tip",
        ("merge-base", "--is-ancestor", "snapshot", "tip"): "",
        ("diff", "--name-only", "--diff-filter=U", "-z"): "",
    }
    repository_command = (
        "rev-parse",
        "--show-toplevel",
        "--is-bare-repository",
        "--path-format=absolute",
        "--git-common-dir",
    )
    replies[repository_command] = "\n".join((str(root), "false", str(common)))
    replies[(primary, *repository_command)] = "\n".join((str(primary), "false", str(common)))
    if problem == "repository-lines":
        replies[repository_command] = "ambiguous\npath\nfalse\ncommon"
    names = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    )
    replies[
        (
            "rev-parse",
            "--path-format=absolute",
            *[a for n in names for a in ("--git-path", n)],
        )
    ] = "\n".join(str(root / n) for n in names)
    if problem == "owner":
        state["worktree"] += "-other"
    elif problem == "merged":
        state["merged"] = "published"
    elif problem == "branch":
        replies[("symbolic-ref", "HEAD")] = "refs/heads/other"
    elif problem == "missing":
        gitfile.unlink()
    elif problem == "locked":
        (directory / "locked").touch()
    elif problem == "stale":
        (directory / "gitdir").write_text(str(primary / "wrong"))
    elif problem == "setup":
        state["python_setup"]["status"] = "failed"
    elif problem == "digest":
        state["deployIdentity"]["taskDigest"] = "changed"
    elif problem == "lifecycle":
        state["branch"] = "other"
    elif problem == "head":
        replies[("rev-parse", "HEAD")] = "unexpected"
    elif problem in {"ancestry", "git"}:
        key = (
            ("merge-base", "--is-ancestor", "snapshot", "tip")
            if problem == "ancestry"
            else ("rev-parse", "HEAD")
        )
        replies[key] = ws.Blocked("git verification failed")
    elif problem == "conflict":
        replies[("diff", "--name-only", "--diff-filter=U", "-z")] = "conflict\0"
    elif problem == "operation":
        (root / "MERGE_HEAD").touch()
    elif problem and problem.startswith("checkpoint"):
        state["deployCheckpointIntent"] = {
            "head": "tip",
            "tree": "tree",
            "message": "checkpoint",
        }
        replies.update(
            {
                ("rev-parse", "HEAD"): "checkpoint",
                ("rev-parse", "HEAD^"): "wrong"
                if problem == "checkpoint-parent"
                else "tip",
                ("rev-parse", "HEAD^{tree}"): "wrong"
                if problem == "checkpoint-tree"
                else "tree",
                ("log", "-1", "--format=%s"): "wrong"
                if problem == "checkpoint-message"
                else "checkpoint",
                ("merge-base", "--is-ancestor", "snapshot", "checkpoint"): "",
            }
        )
    meta.write_text(json.dumps(state), encoding="utf-8")
    git = Mock(side_effect=partial(_callback_snapshot_git, replies))
    monkeypatch.setattr(ws, "git", git)
    if problem not in {None, "checkpoint", "repository-lines"}:
        with pytest.raises(ValueError):
            worktree.require(root, snapshot)
    else:
        assert worktree.require(root, snapshot) == state
        assert all(call.args[1:3] != ("worktree", "list") for call in git.call_args_list)
        if problem is None:
            replies[("rev-parse", "HEAD")] = "unexpected"
            with pytest.raises(ValueError, match="HEAD"):
                worktree.require(root, snapshot)
            replies[("rev-parse", "HEAD")] = "tip"
            gitfile.unlink()
            with pytest.raises(ValueError, match="missing"):
                worktree.require(root, snapshot)
            gitfile.write_text(f"gitdir: {directory}\n")
        # A later operation rereads lifecycle bytes rather than reusing authorization.
        state["merged"] = "published"
        meta.write_text(json.dumps(state), encoding="utf-8")
        with pytest.raises(ValueError, match="merged"):
            worktree.require(root, snapshot)
    assert all("refs/heads/main" not in str(call) for call in git.call_args_list)


@pytest.mark.parametrize("operation", sorted(guards.MUTATIONS))
def check_unmanaged_mutation_is_rejected(tmp_path, monkeypatch, operation):
    snapshot = task(tmp_path)
    monkeypatch.setattr(worktree.tasks, "task_snapshot", Mock(return_value=snapshot))
    monkeypatch.setattr(
        ws,
        "deploy_task_state",
        Mock(side_effect=ws.Blocked("registered managed worktree required")),
    )
    monkeypatch.setattr(guards, "task_reads", Mock(return_value=nullcontext()))
    monkeypatch.setattr(
        controller._imports_utils_aws_client,
        "connection_context",
        Mock(return_value=None),
    )
    runtime = controller.create_runtime(
        tmp_path,
        "dev",
        "target",
        {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
    )
    runtime.guard = Mock(wraps=runtime.guard)
    runtime.timing = Mock()
    with pytest.raises(DeployBlocked, match="validated controller Task"):
        guards.call(runtime, "cloudformation", operation, {})
    runtime.guard.assert_called_once()
    runtime.timing.phase.assert_not_called()


@pytest.mark.parametrize("problem", [None, "setup", "contract"])
def check_managed_task_authority(tmp_path, monkeypatch, problem):
    snapshot = task(tmp_path)
    state = {
        "worktree": str(tmp_path),
        "python_setup": {"status": "failed" if problem == "setup" else "ready"},
        "deployIdentity": {
            "taskDigest": "changed" if problem == "contract" else snapshot.task_digest
        },
    }
    monkeypatch.setattr(ws, "deploy_task_state", Mock(return_value=("snapshot", state)))
    if problem:
        with pytest.raises(ValueError):
            worktree.require(tmp_path, snapshot)
    else:
        assert worktree.require(tmp_path, snapshot) is state


@pytest.mark.parametrize(
    "problem", ["task", "status", "account", "scope", "target", "input", "ownership"]
)
def check_mutation_rechecks_live_authority(tmp_path, monkeypatch, problem):
    snapshot = task(tmp_path)
    snapshot.status = "running"
    snapshot.text += "- AWS API execution: `allowed`\n- Deploy/apply: `allowed`\n- Target environment: `dev`\n- Target AWS account: `123456789012`\n- Deployment scope: `A`\n"
    target = {"awsAccountId": "123456789012"}
    context = SimpleNamespace(load_target=Mock(return_value=target))
    args = SimpleNamespace(
        stack=["A"], environment="dev", alias=None, aws_account_id="123456789012"
    )
    run = {
        "taskDigest": snapshot.task_digest,
        "consumedInputs": {"infra/a.yaml": "hash"},
    }
    runtime = SimpleNamespace(
        root=tmp_path,
        file_digest=Mock(return_value="hash"),
        timing=SimpleNamespace(phase=Mock(return_value=nullcontext())),
        connection=None,
    )
    runtime.guard = partial(
        run_context._callback_run_guard,
        args,
        runtime,
        context,
        tmp_path,
        target,
        run,
        target,
    )
    require = Mock(return_value={})
    monkeypatch.setattr(worktree, "require", require)
    monkeypatch.setattr(run_context, "task_snapshot", Mock(return_value=snapshot))
    mutation = Mock(return_value={})
    monkeypatch.setattr(guards.SERVICES["s3"], "put_object", mutation)
    guards.call(runtime, "s3", "put_object", {})
    if problem == "task":
        snapshot.task_digest = "changed"
    elif problem == "status":
        snapshot.status = "suspend"
    elif problem == "account":
        snapshot.text = snapshot.text.replace("123456789012", "999999999999")
    elif problem == "scope":
        args.stack = ["other"]
    elif problem == "target":
        context.load_target.return_value = {"awsAccountId": "other"}
    elif problem == "input":
        runtime.file_digest.return_value = "changed"
    else:
        snapshot.text = snapshot.text.replace("- Deploy/apply: `allowed`", "- Deploy/apply: `forbidden`")
    with pytest.raises((ValueError, run_context.Blocked)):
        guards.call(runtime, "s3", "put_object", {})
    assert mutation.call_count == 1
    require.assert_not_called()






@pytest.fixture
def checkpoint_evidence(tmp_path, monkeypatch):
    unit = {"name": "A", "template": "a.yaml", "parameters": "a.json"}
    identity = {
        "taskFile": "tasks/deploy.md",
        "taskDigest": "task",
        "target": {},
        "environment": "dev",
        "stacks": ["A"],
        "snapshot": "start",
    }
    manifest = {}
    for path in inputs.deployment_input_paths(tmp_path, "dev", "app", {}, [unit]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("immutable input", encoding="utf-8")
        manifest[path.relative_to(tmp_path).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    digest = inputs.fingerprint(list(manifest.values()))
    state = {
        "task_id": "deploy",
        "task_file": "tasks/deploy.md",
        "tip": "checkpoint",
        "branch": "codex/worktree/deploy",
        "base": "main",
        "deployIdentity": identity,
        "deployCheckpoints": {
            "A": {
                "commit": "checkpoint",
                "tree": "tree",
                "identity": identity,
                "taskDigest": "task",
                "inputDigest": digest,
                "inputs": manifest,
                "unit": unit,
                "stackId": "stack-a",
                "stackStatus": "CREATE_COMPLETE",
                "coverage": {"ResourceA": {"status": "MATCHED"}},
                "services": ["ec2"],
            }
        },
    }
    progress = {
        "identity": identity,
        "runContext": {
            "stepUnits": [unit],
            "directory": "app",
            "states": {
                "A": {
                    "status": "SUCCESS",
                    "observedSynced": True,
                    "stackId": "stack-a",
                    "stackStatus": "CREATE_COMPLETE",
                    "observedCoverage": {"ResourceA": {"status": "MATCHED"}},
                    "observedServices": ["ec2"],
                }
            },
            "inputDigests": {"A": digest},
        },
    }
    monkeypatch.setattr(publication.wt, "ancestor", Mock(return_value=True))
    monkeypatch.setattr(publication.wt, "output", Mock(return_value="tree"))
    monkeypatch.setattr(
        publication.ws, "subprocess_bytes", Mock(return_value=b"immutable input")
    )
    monkeypatch.setattr(publication.wt, "base_worktree", Mock(return_value=tmp_path))
    return state, progress


@pytest.mark.parametrize(
    "problem",
    [None, "receipt", "commit", "target", "unit", "digest", "input", "tree", "aws"],
)
def check_publication_requires_exact_saved_checkpoint(
    tmp_path, monkeypatch, checkpoint_evidence, problem
):
    state, progress = checkpoint_evidence
    entry = state["deployCheckpoints"]["A"]
    if problem == "receipt":
        state["deployCheckpoints"] = {}
    elif problem == "commit":
        state["tip"] = "unverified-commit"
    elif problem == "target":
        entry["identity"] = {**entry["identity"], "target": {"awsAccountId": "other"}}
    elif problem == "unit":
        entry["unit"] = {"name": "other"}
    elif problem == "digest":
        entry["inputDigest"] = "other"
    elif problem == "input":
        (tmp_path / next(iter(entry["inputs"]))).write_text("changed", encoding="utf-8")
    elif problem == "tree":
        entry["tree"] = "other"
    elif problem == "aws":
        progress["runContext"]["states"]["A"]["status"] = "RUNNING"
    if problem and problem != "aws":
        with pytest.raises(ValueError):
            publication.checkpoint_source(tmp_path, state, progress)
    else:
        assert publication.checkpoint_source(tmp_path, state, progress) == "checkpoint"








def check_claim_input_hash_still_blocks(tmp_path):
    source = tmp_path / "infra/template.yaml"
    source.parent.mkdir()
    source.write_text("Resources: {}")
    context = {
        "inputIdentities": {"infra/template.yaml": run_context.file_revision(source)},
        "inputDigests": {"A": "old"},
    }
    backend = SimpleNamespace(
        phase="update",
        deployment_input_paths=Mock(return_value=[source]),
        input_digest=Mock(return_value="changed"),
    )
    with pytest.raises(run_context.Blocked, match="IaC changed"):
        run_context._callback_claim_inputs(
            tmp_path, context, backend, Mock(), {"name": "A"}
        )




def progress_backend(root, context):
    identity = dict(
        taskFile="tasks/deploy.md",
        taskDigest="digest",
        target={},
        environment="dev",
        stacks=["A"],
        snapshot="fixed",
    )
    context.update(
        {
            key: identity[key]
            for key in ("taskFile", "taskDigest", "target", "environment")
        }
    )
    context["repository"] = str(root)
    context.setdefault("consumedInputs", {})
    context.setdefault("stepUnits", [{"name": "A"}])
    return SimpleNamespace(
        root=root,
        phase="deploy",
        run_context=context,
        progress_identity=identity,
        progress_root=root.resolve(),
        progress_directory=context.get("directory"),
        progress_destination=deploy_progress.progress_path(root, create=True),
    )


def check_progress_uses_fixed_identity_without_git(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    first = deploy_progress.progress_path(isolated, "tasks/first.md", create=True)
    second = deploy_progress.progress_path(isolated, "tasks/second.md", create=True)
    legacy = deploy_progress.progress_path(isolated, create=True)
    assert first != second and legacy not in {first, second}
    assert first.parent == operation_journal.location(isolated, "tasks/first.md").parent
    identity = {"taskFile": "tasks/first.md", "taskDigest": "digest", "target": {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}, "environment": "dev", "stacks": ["A"]}
    backend = progress_backend(isolated, {"states": {"A": {"status": "RUNNING", "clientToken": "token"}}, "inputDigests": {}})
    backend.progress_identity = identity
    backend.run_context.update(identity)
    backend.progress_task_file = identity["taskFile"]
    backend.progress_destination = first
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    legacy.write_text("legacy", encoding="utf-8")
    with operation_journal.locked(first), operation_journal.locked(second):
        with pytest.raises(DeployBlocked, match="lock busy"):
            with operation_journal.locked(first):
                pass
    assert deploy_progress.read_progress(isolated, {"deployIdentity": identity}, identity["taskFile"])["runContext"]["states"]["A"]["clientToken"] == "token"
    assert legacy.read_text(encoding="utf-8") == "legacy"
    assert not second.exists()


    context = {"states": {"A": {"status": "RUNNING"}}, "inputDigests": {}}
    backend = progress_backend(tmp_path, context)
    with (
        patch.object(ws, "git", side_effect=AssertionError("unexpected Git")),
        patch.object(worktree, "require", side_effect=ws.Blocked("worktree changed")),
    ):
        deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
        context["states"]["A"]["status"] = "SUCCESS"
        deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
        with pytest.raises(ws.Blocked, match="worktree changed"):
            worktree.require(tmp_path)
    assert (
        deploy_progress.read_progress(tmp_path, {"deployIdentity": backend.progress_identity})[
            "runContext"
        ]["states"]["A"]["status"]
        == "SUCCESS"
    )
    context["taskDigest"] = "other"
    with pytest.raises(ValueError, match="fixed identity"):
        deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    assert (
        deploy_progress.read_progress(tmp_path, {"deployIdentity": backend.progress_identity})[
            "runContext"
        ]["states"]["A"]["status"]
        == "SUCCESS"
    )


def check_progress_preserves_success_and_omits_unowned_fields(tmp_path, monkeypatch):
    context = {
        "states": {
            "A": {
                "status": "SUCCESS",
                "observedSynced": True,
                "clientToken": "original",
                "arbitrary": "must not persist",
            }
        },
        "inputDigests": {"A": "hash"},
    }
    backend = progress_backend(tmp_path, context)
    state = {"deployIdentity": backend.progress_identity}
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    context["states"]["A"] = {"status": "NOT_STARTED"}
    context["inputDigests"] = {}
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    progress = deploy_progress.read_progress(tmp_path, state)
    TestCase().assertEqual(
        progress["runContext"]["states"]["A"], {"status": "NOT_STARTED"}
    )
    TestCase().assertEqual(progress["runContext"]["inputDigests"], {})
    TestCase().assertNotIn("arbitrary", progress["runContext"]["states"]["A"])


@pytest.mark.parametrize(
    "changed", ["account", "region", "stack", "contract", "snapshot"]
)
def check_reuse_keeps_exact_identity(tmp_path, monkeypatch, changed):
    snapshot = task(tmp_path)
    state = {"task_id": "deploy", "start": "snapshot"}
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(
        ws, "load", Mock(return_value=(tmp_path, None, tmp_path / "state.json", state))
    )
    monkeypatch.setattr(
        worktree.wt, "lifecycle_lock", Mock(side_effect=lambda root: nullcontext())
    )
    saved = Mock()
    monkeypatch.setattr(worktree.wt, "save", saved)
    target, stacks = (
        {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
        ["A"],
    )
    worktree.bind(tmp_path, snapshot, target, "dev", stacks)
    target = dict(target)
    if changed == "account":
        target["awsAccountId"] = "999999999999"
    elif changed == "region":
        target["awsRegion"] = "us-east-1"
    elif changed == "stack":
        stacks = ["B"]
    elif changed == "contract":
        snapshot.task_digest = "changed"
    else:
        state["start"] = "new-snapshot"
    with pytest.raises(ValueError, match="identity changed"):
        worktree.bind(tmp_path, snapshot, target, "dev", stacks)
    saved.assert_called_once()




def check_progress_has_one_mutable_context_and_preserves_recovery(tmp_path):
    context = {
        "states": {
            "A": {
                "status": "SETTLED",
                "attemptResult": "UNKNOWN",
            }
        },
        "inputDigests": {"A": "fixed"},
        "pendingObserved": {
            "evidence": {"A": {"original": "before"}},
            "candidate": "after",
        },
        "pendingGeneration": {"ec2": {"candidate": "view", "producers": ["A"]}},
        "checkpointPending": {
            "stacks": ["A"],
            "before": {"model": "before"},
            "after": {"model": "after"},
            "final": {"taskBefore": "running", "taskAfter": "completed"},
        },
        "generationError": "failed generation",
        "snapshotValidation": "FAIL",
        "deployResult": "FAIL",
        "gitPublication": {"status": "stale"},
    }
    backend = progress_backend(tmp_path, context)
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    saved = deploy_progress.read_progress(
        tmp_path, {"deployIdentity": backend.progress_identity}
    )
    assert set(saved) == {"identity", "runContext"}
    assert "gitPublication" not in saved["runContext"]
    for key in (
        "states",
        "inputDigests",
        "pendingObserved",
        "pendingGeneration",
        "checkpointPending",
        "generationError",
        "snapshotValidation",
        "deployResult",
    ):
        assert saved["runContext"][key] == context[key]
    for key in ("pendingObserved", "pendingGeneration", "checkpointPending"):
        assert isinstance(saved["runContext"][key], dict)


@pytest.mark.parametrize(
    "damage",
    [
        "context",
        "states",
        "inputDigests",
        "consumedInputs",
        "stepUnits",
        "pendingObserved",
    ],
)
def check_corrupt_progress_is_never_empty_success(tmp_path, damage):
    backend = progress_backend(
        tmp_path,
        {"states": {"A": {"status": "FAILED"}}, "inputDigests": {"A": "fixed"}},
    )
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    saved = deploy_progress.read_progress(
        tmp_path, {"deployIdentity": backend.progress_identity}
    )
    if damage == "context":
        saved.pop("runContext")
    elif damage == "pendingObserved":
        saved["runContext"][damage] = True
    else:
        saved["runContext"].pop(damage)
    deploy_progress.write_sealed(tmp_path, backend.progress_destination, saved)
    with pytest.raises(ValueError, match="incomplete or corrupt"):
        deploy_progress.read_progress(tmp_path, {"deployIdentity": backend.progress_identity})




def check_missing_progress_with_saved_checkpoint_is_not_a_fresh_run(tmp_path):
    with pytest.raises(ValueError, match="progress is missing"):
        deploy_progress.read_progress(
            tmp_path, {"deployCheckpoints": {"A": {"commit": "saved"}}}
        )


def check_final_source_uses_fixed_inputs_without_intermediate_receipts(
    tmp_path, monkeypatch, checkpoint_evidence
):
    state, progress = checkpoint_evidence
    task_before = task(tmp_path)
    snapshot = SimpleNamespace(
        text=publication.tasks.set_status(task_before.text, "completed"),
        status="completed",
        task_digest=task_before.task_digest,
    )
    state["deployIdentity"]["taskDigest"] = snapshot.task_digest
    state["deployPublication"] = {
        "finalCandidate": {
            "source": state["tip"],
            "tree": "tree",
            "taskBefore": task_before.text,
            "taskAfter": snapshot.text,
        }
    }
    progress["runContext"]["consumedInputs"] = dict(
        state["deployCheckpoints"]["A"]["inputs"]
    )
    state["deployCheckpoints"] = {}
    monkeypatch.setattr(
        publication.tasks, "read_task_snapshot", Mock(return_value=snapshot)
    )
    assert publication.checkpoint_source(tmp_path, state, progress) == state["tip"]
    progress["runContext"]["consumedInputs"].clear()
    with pytest.raises(ValueError, match="manifest changed"):
        publication.checkpoint_source(tmp_path, state, progress)






def atomic_test_save(tmp_path, progress, state, request, saves):
    deploy_progress.write_sealed(tmp_path, progress, state)
    saves.append(
        (
            json.loads(request.read_text()) if request.exists() else None,
            json.loads(json.dumps(state)),
        )
    )


def atomic_test_transport(
    calls, request, missing_stack, stack, _runtime, _service, operation, arguments
):
    calls.append((operation, dict(arguments), json.loads(request.read_text())))
    return (
        {"StackId": None if missing_stack else stack}
        if operation == "create_change_set"
        else {}
    )






def _checkpoint_output(trace, root, *args):
    if args == ("write-tree",) or args == ("rev-parse", "HEAD^{tree}"):
        return "tree"
    if args == ("rev-parse", "HEAD^"):
        return "old"
    if args == ("rev-parse", "HEAD"):
        return trace.head
    raise AssertionError(f"unexpected checkpoint read: {args}")


def _checkpoint_git(trace, root, *args, **kwargs):
    if args[0] == "commit":
        if trace.failure == "before-commit" and not trace.failed:
            trace.failed = True
            raise OSError("interrupted before commit")
        trace.head, trace.changed = "new", set()
        trace.commits += 1
        if trace.failure == "after-commit" and not trace.failed:
            trace.failed = True
            raise OSError("interrupted after commit")
    return subprocess.CompletedProcess([], 0, "", "")


def _checkpoint_save(trace, path, state):
    if (
        trace.failure == "receipt-save"
        and not trace.failed
        and "deployCheckpointIntent" not in state
    ):
        trace.failed = True
        raise OSError("interrupted receipt save")
    trace.saved.append(copy.deepcopy(state))
    if trace.failure == "intent-save" and not trace.failed:
        trace.failed = True
        raise OSError("interrupted intent acknowledgement")


@pytest.mark.parametrize(
    "failure", ["before-commit", "after-commit", "intent-save", "receipt-save"]
)
def check_saved_checkpoint_intent_reconciles_once(tmp_path, monkeypatch, failure):
    check = TestCase()
    relative = "model/a.properties"
    source = tmp_path / relative
    source.parent.mkdir()
    source.write_bytes(b"adopted observations")
    state = dict(task_file="tasks/deploy.md", task_id="deploy", tip="old")
    trace = SimpleNamespace(
        failure=failure,
        failed=False,
        head="old",
        changed={relative},
        commits=0,
        saved=[],
    )
    snapshot = SimpleNamespace(raw=b"task")
    monkeypatch.setattr(
        publication.tasks, "read_task_snapshot", Mock(return_value=snapshot)
    )
    monkeypatch.setattr(publication.worktree, "require", Mock())
    monkeypatch.setattr(publication, "output_changes", lambda *a: set(trace.changed))
    monkeypatch.setattr(
        publication.contracts,
        "validation_snapshot",
        Mock(return_value={relative: "adopted"}),
    )
    monkeypatch.setattr(publication.wt, "output", partial(_checkpoint_output, trace))
    monkeypatch.setattr(publication.wt, "git", partial(_checkpoint_git, trace))
    monkeypatch.setattr(publication.wt, "save", partial(_checkpoint_save, trace))
    preflight = dict(
        task=b"task",
        head="old",
        index="tree",
        changed={relative},
        candidate={relative: "adopted"},
    )
    with pytest.raises(OSError, match="interrupted"):
        publication.checkpoint(
            tmp_path, tmp_path / "state.json", state, preflight=preflight
        )
    state = copy.deepcopy(trace.saved[-1])
    check.assertIn("deployCheckpointIntent", state)
    preflight.update(head=trace.head, changed=set(trace.changed))
    check.assertEqual(
        publication.checkpoint(
            tmp_path, tmp_path / "state.json", state, preflight=preflight
        ),
        "new",
    )
    check.assertEqual(trace.commits, 1)
    check.assertNotIn("deployCheckpointIntent", state)
    check.assertEqual(state["tip"], "new")
    check.assertEqual(source.read_bytes(), b"adopted observations")


def _final_checkpoint_output(trace, root, *args):
    return trace.head if args == ("rev-parse", "HEAD") else trace.index


def _final_checkpoint_change(trace, failure, metadata, root, tree, head, candidate):
    if failure == "validation":
        raise ValueError("candidate validation failed")
    if failure == "task":
        trace.task = replace(trace.task, raw=b"external Task bytes")
    elif failure in ("input", "candidate"):
        trace.snapshot[
            "infra/parameters.json" if failure == "input" else "model/a.properties"
        ] = "external"
    elif failure == "head":
        trace.head = "external"
    elif failure == "index":
        trace.index = "external"
    else:
        metadata.write_text(
            json.dumps({"deployCheckpointIntent": {"foreign": True}}), encoding="utf-8"
        )


@pytest.mark.parametrize(
    "failure", ["task", "input", "candidate", "head", "index", "intent", "validation"]
)
def check_final_checkpoint_rejects_changes_before_adoption(
    tmp_path, monkeypatch, failure
):
    check = TestCase()
    name = "tasks/deploy.md"
    text = task(tmp_path).text
    source = tmp_path / name
    source.parent.mkdir()
    source.write_text(text, encoding="utf-8")
    snapshot = publication.tasks.TaskSnapshot(
        name,
        tmp_path,
        source,
        text,
        text.encode(),
        hashlib.sha256(text.encode()).hexdigest(),
        (None, None),
    )
    after = {"model/a.properties": "new", "infra/parameters.json": "fixed"}
    pending = dict(
        stacks=["A"],
        before={**after, "model/a.properties": "old"},
        after=dict(after),
        final=dict(
            taskBefore=text, taskAfter=publication.tasks.set_status(text, "completed")
        ),
    )
    state = dict(
        task_file=name,
        tip="head",
        deployIdentity=dict(stacks=["A"], taskDigest=snapshot.task_digest),
    )
    metadata = tmp_path / "state.json"
    metadata.write_text("{}", encoding="utf-8")
    trace = SimpleNamespace(
        task=snapshot, head="head", index="index", snapshot=dict(after)
    )
    backend = SimpleNamespace(
        root=tmp_path,
        run_context={"checkpointPending": pending},
        states={"A": {"status": "SUCCESS"}},
        target={},
        save=Mock(),
        guard=Mock(),
    )
    monkeypatch.setattr(
        checkpoints.tasks, "read_task_snapshot", lambda *a, **k: trace.task
    )
    monkeypatch.setattr(checkpoints.completion, "final_blockers", Mock(return_value=[]))
    monkeypatch.setattr(
        checkpoints.contracts, "validation_snapshot", lambda *a: dict(trace.snapshot)
    )
    monkeypatch.setattr(
        publication, "output_changes", Mock(return_value={"model/a.properties"})
    )
    monkeypatch.setattr(
        checkpoints.wt, "output", partial(_final_checkpoint_output, trace)
    )
    monkeypatch.setattr(publication, "final_tree", Mock(return_value="tree"))
    monkeypatch.setattr(
        publication,
        "validate_candidate",
        partial(_final_checkpoint_change, trace, failure, metadata),
    )
    with (
        patch.object(checkpoints.tasks, "atomic_files") as adopt,
        patch.object(publication, "checkpoint") as commit,
    ):
        with pytest.raises(
            ValueError, match="changed during validation|candidate validation failed"
        ):
            checkpoints.final_checkpoint(backend, tmp_path, metadata, state, pending)
    adopt.assert_not_called()
    commit.assert_not_called()
    check.assertEqual(source.read_text(encoding="utf-8"), text)
    check.assertNotIn("validated", pending["final"])
    check.assertEqual(backend.run_context["snapshotValidation"], "FAIL")


def _publication_output(trace, root, *args):
    return "index" if args == ("write-tree",) else "merged" if trace.merged else "base"


def _publication_merge(trace, root, *args, **kwargs):
    TestCase().assertEqual(args[:2], ("merge", "--ff-only"))
    if trace.failure == "before-merge" and not trace.failed:
        trace.failed = True
        raise OSError("interrupted before merge")
    trace.merged = True
    trace.merges += 1
    if trace.failure == "after-merge" and not trace.failed:
        trace.failed = True
        raise OSError("interrupted after merge")
    return subprocess.CompletedProcess([], 0, "", "")


def _publication_save(trace, path, state):
    if trace.failure == "receipt" and not trace.failed:
        trace.failed = True
        raise OSError("interrupted publication receipt")
    trace.saved = copy.deepcopy(state)




@pytest.mark.parametrize("status", ["SUCCESS", "FAILED", "SETTLED", "NOT_STARTED"])
def check_checkpoint_receipt_preserves_terminal_facts(tmp_path, monkeypatch, status):
    relative = "infra/parameters.json"
    unit = dict(name="A", deployOrder=1)
    state = dict(deployIdentity={"taskDigest": "task"})
    saved = dict(
        status=status,
        stackId="stack-id",
        stackStatus="UPDATE_COMPLETE",
        observedCoverage={"row": "known"},
        observedServices=["vpc"],
    )
    backend = SimpleNamespace(
        root=tmp_path,
        states={"A": saved},
        run_context=dict(
            stepUnits=[unit],
            consumedInputs={relative: "hash"},
            taskDigest="task",
            inputDigests={"A": "digest"},
        ),
        deployment_input_paths=lambda units: [tmp_path / relative],
    )
    monkeypatch.setattr(checkpoints.wt, "output", Mock(return_value="tree"))
    receipt = checkpoints.checkpoint_receipt(backend, state, "A", "commit")
    TestCase().assertEqual(
        (receipt["deployStatus"], receipt["stackStatus"], receipt["stackId"]),
        (status, "UPDATE_COMPLETE", "stack-id"),
    )
    TestCase().assertEqual(receipt["inputs"], {relative: "hash"})
    saved["observedCoverage"]["row"] = "changed"
    TestCase().assertEqual(receipt["coverage"], {"row": "known"})


def _resolution_command(command, **kwargs):
    return subprocess.CompletedProcess(
        command, 0, "resolved-tree" if command[1] == "write-tree" else "oid", ""
    )




def _conflict_publication_output(trace, primary, root, *args):
    if root == primary:
        return trace["head"]
    if args == ("write-tree",):
        return "index"
    if args[:1] == ("commit-tree",):
        return "candidate"
    return "source" if args == ("rev-parse", "HEAD") else "base-tree"


def _conflict_publication_git(trace, primary, root, *args, **kwargs):
    if args[0] == "merge-tree":
        return subprocess.CompletedProcess(
            [], 1, "conflict-tree\0model/dev/team/ec2.properties\0\0", ""
        )
    if root == primary and args[:2] == ("merge", "--ff-only"):
        trace["head"] = args[-1]
        trace["merges"] += 1
    return subprocess.CompletedProcess([], 0, "", "")




if __name__ == "__main__":
    raise SystemExit(run(__file__))
