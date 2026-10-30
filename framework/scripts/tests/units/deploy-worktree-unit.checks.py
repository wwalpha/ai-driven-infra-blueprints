"""Deploy-only snapshot, ownership, progress and Git failure boundaries without Git fixtures."""

import copy
import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
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
from deploy import controller, guards, inputs, operation_journal, run_context, worktree
from deploy import git_publication as publication
from support.pytest_cli import run
from task_contract_core import task_digest
from utils.sealed_evidence import evidence_store as old_store

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
    assert (
        publication.checkpoint(
            tmp_path, tmp_path / "state", {"task_file": "tasks/deploy.md"}
        )
        == "existing-head"
    )
    output.assert_called_once_with(tmp_path, "rev-parse", "HEAD")
    git.assert_not_called()
    output.reset_mock()
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


@pytest.mark.parametrize("problem", ["head", "index", "candidate", "guard"])
def check_direct_checkpoint_rechecks_preflight(tmp_path, monkeypatch, problem):
    path = tmp_path / "model/a.properties"
    path.parent.mkdir()
    path.write_text("observed", encoding="utf-8")
    monkeypatch.setattr(
        publication.tasks,
        "read_task_snapshot",
        Mock(return_value=SimpleNamespace(raw=b"task")),
    )
    monkeypatch.setattr(publication.worktree, "require", Mock())
    monkeypatch.setattr(
        publication.wt, "changed_paths", Mock(return_value={"model/a.properties"})
    )
    values = [
        "head",
        "index",
        "other" if problem == "head" else "head",
        "other" if problem == "index" else "index",
    ]
    monkeypatch.setattr(publication.wt, "output", Mock(side_effect=values))
    snapshots = [
        {"model/a.properties": "before"},
        {"model/a.properties": "after" if problem == "candidate" else "before"},
    ]
    monkeypatch.setattr(
        publication.contracts, "validation_snapshot", Mock(side_effect=snapshots)
    )
    scope = Mock(
        side_effect=ValueError("Model guard failed") if problem == "guard" else None
    )
    monkeypatch.setattr(publication, "check_scope", scope)
    with pytest.raises(
        ValueError,
        match="Model guard failed"
        if problem == "guard"
        else "changed during preflight",
    ):
        publication.checkpoint(
            tmp_path, tmp_path / "state", {"task_file": "tasks/deploy.md"}
        )
    scope.assert_called_once()


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
    reply = replies[args]
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
    records = f"worktree {primary}\0HEAD main\0branch refs/heads/main\0\0"
    entry = f"worktree {root}\0HEAD tip\0branch refs/heads/{state['branch']}\0"
    replies = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--is-bare-repository"): "false",
        ("rev-parse", "--path-format=absolute", "--git-common-dir"): str(
            primary / ".git"
        ),
        ("rev-parse", "--verify", "snapshot^{commit}"): "snapshot",
        ("rev-parse", "HEAD"): "tip",
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
    replies[repository_command] = "\n".join((str(root), "false", str(primary / ".git")))
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
        entry = entry.replace(state["branch"], "other")
    elif problem == "missing":
        entry = ""
    elif problem in {"locked", "stale"}:
        entry += "locked\0" if problem == "locked" else "prunable stale\0"
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
    replies[("worktree", "list", "--porcelain", "-z")] = records + (
        entry + "\0" if entry else ""
    )
    meta.write_text(json.dumps(state), encoding="utf-8")
    git = Mock(side_effect=partial(_callback_snapshot_git, replies))
    monkeypatch.setattr(ws, "git", git)
    if problem not in {None, "checkpoint", "repository-lines"}:
        with pytest.raises(ValueError):
            worktree.require(root, snapshot)
    else:
        assert worktree.require(root, snapshot) == state
        assert git.call_count == (7 if problem is None else 10)
        assert (
            sum(call.args[1:3] == ("worktree", "list") for call in git.call_args_list)
            == 1
        )
        if problem is None:
            replies[("rev-parse", "HEAD")] = "unexpected"
            with pytest.raises(ValueError, match="HEAD"):
                worktree.require(root, snapshot)
            replies[("rev-parse", "HEAD")] = "tip"
            replies[("worktree", "list", "--porcelain", "-z")] = records
            with pytest.raises(ValueError, match="missing"):
                worktree.require(root, snapshot)
            replies[("worktree", "list", "--porcelain", "-z")] = records + entry + "\0"
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
    with pytest.raises(ValueError, match="managed worktree"):
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
        require.side_effect = ws.Blocked("worktree changed")
    with pytest.raises((ValueError, run_context.Blocked)):
        guards.call(runtime, "s3", "put_object", {})
    assert mutation.call_count == 1
    assert require.call_count == 2


def check_git_failure_preserves_stack_success(tmp_path, monkeypatch):
    states = {
        "A": {"status": "SUCCESS", "observedSynced": True},
        "B": {"status": "NOT_STARTED"},
    }
    backend = SimpleNamespace(
        root=tmp_path,
        phase="deploy",
        run_context={"taskFile": "tasks/deploy.md", "states": states},
        save=Mock(),
    )
    original = copy.deepcopy(states)
    monkeypatch.setattr(
        publication, "publish", Mock(side_effect=ValueError("base dirty"))
    )
    publication.sync(backend)
    assert backend.publication_error == "base dirty"
    assert "gitPublication" not in backend.run_context
    assert states == original
    assert not getattr(backend, "sync_failed", False)
    backend.save.assert_not_called()


@pytest.mark.parametrize(
    "digest,repair", [("hash", False), ("changed", False), ("changed", True)]
)
def check_resume_adopts_only_unchanged_successes(tmp_path, monkeypatch, digest, repair):
    saved = {
        "status": "SUCCESS",
        "observedSynced": True,
        "executionEvidence": {"clientToken": "original"},
    }
    progress = {"runContext": {"states": {"A": saved}, "inputDigests": {"A": "hash"}}}
    backend = SimpleNamespace(
        root=tmp_path,
        phase="deploy",
        run_context={},
        units=[{"name": "A"}],
        states={"A": {"status": "NOT_STARTED"}},
        claim_inputs=Mock(),
        input_digest=Mock(return_value=digest),
    )
    monkeypatch.setattr(
        worktree,
        "require",
        Mock(return_value={"iacRepair": {"commit": "verified"} if repair else {}}),
    )
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    if digest == "changed" and not repair:
        with pytest.raises(ValueError, match="input changed"):
            worktree.adopt_successes(backend)
    else:
        worktree.adopt_successes(backend)
        assert backend.states["A"] == (
            saved if digest == "hash" else {"status": "NOT_STARTED"}
        )


@pytest.mark.parametrize(
    "pending",
    [
        None,
        "pendingObserved",
        "pendingGeneration",
        "generationError",
        "checkpointPending",
        "aws",
        "request",
        "final",
        "task",
    ],
)
def check_completion_keeps_states_separate(tmp_path, monkeypatch, pending):
    snapshot = task(tmp_path)
    before = snapshot.text
    snapshot.text = publication.tasks.set_status(before, "completed")
    context = {
        "states": {
            "A": {
                "status": "FAILED",
                "observedSynced": True,
                "currentStack": {"StackStatus": "UPDATE_ROLLBACK_COMPLETE"},
            }
        },
        "snapshotValidation": "PASS",
    }
    final = {
        "source": "tip",
        "tree": "tree",
        "taskBefore": before,
        "taskAfter": snapshot.text,
    }
    state = {
        "tip": "tip",
        "deployIdentity": {"stacks": ["A"]},
        "deployPublication": {"status": "CONFLICT", "finalCandidate": final},
    }
    if pending in {"pendingObserved", "pendingGeneration", "checkpointPending"}:
        context[pending] = {"candidate": "retained"}
    elif pending == "generationError":
        context[pending] = "generation failed"
    elif pending == "aws":
        context["states"]["A"]["status"] = "RUNNING"
    elif pending == "request":
        context["states"]["A"]["requestPending"] = True
    elif pending == "final":
        state["deployPublication"].pop("finalCandidate")
    elif pending == "task":
        final["taskAfter"] += "changed authority\n"
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(
        worktree, "read_progress", Mock(return_value={"runContext": context})
    )
    monkeypatch.setattr(worktree.wt, "output", Mock(return_value="tree"))
    if pending:
        with pytest.raises(ValueError):
            worktree.require_complete(tmp_path, snapshot)
    else:
        worktree.require_complete(tmp_path, snapshot)


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
            "stepwise": True,
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


def check_final_completion_rechecks_saved_checkpoint_evidence(
    tmp_path, monkeypatch, checkpoint_evidence
):
    state, progress = checkpoint_evidence
    snapshot = task(tmp_path)
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    with pytest.raises(ValueError, match="final candidate"):
        worktree.require_complete(tmp_path, snapshot)


@pytest.mark.parametrize("mode", [True, None])
def check_stepwise_without_receipt_never_creates_checkpoint(
    tmp_path, monkeypatch, checkpoint_evidence, mode
):
    state, progress = checkpoint_evidence
    state["worktree"] = str(tmp_path)
    state["deployCheckpoints"] = {}
    if mode is None:
        progress["runContext"].pop("stepwise")
    monkeypatch.setattr(
        publication.wt,
        "load",
        Mock(return_value=(tmp_path, None, tmp_path / "state", state)),
    )
    monkeypatch.setattr(
        publication.wt, "lifecycle_lock", Mock(return_value=nullcontext())
    )
    monkeypatch.setattr(
        publication.tasks, "read_task_snapshot", Mock(return_value=task(tmp_path))
    )
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    checkpoint = Mock()
    monkeypatch.setattr(publication, "checkpoint", checkpoint)
    with pytest.raises(
        ValueError,
        match="persisted Deploy mode" if mode is None else "checkpoint evidence",
    ):
        publication.publish(tmp_path, "deploy")
    checkpoint.assert_not_called()


@pytest.mark.parametrize(
    "status", ["PENDING", "CONFLICT", "SUCCESS", "UNKNOWN", "INTENT", "CHECKPOINT"]
)
def check_publication_guidance_only_offers_proven_git_retry(
    tmp_path, monkeypatch, checkpoint_evidence, status
):
    state, progress = checkpoint_evidence
    state["deployPublication"] = {
        "status": status,
        "publishedSource": "checkpoint" if status == "SUCCESS" else "start",
        "commit": "main-commit",
        "base": "base",
        "source": "checkpoint",
        "conflicts": [{"path": "model/dev/app/ec2.properties"}],
    }
    if status == "CHECKPOINT":
        state["deployPublication"]["status"] = "PENDING"
        progress["runContext"]["checkpointPending"] = {"stacks": ["B"]}
    if status == "UNKNOWN":
        progress["runContext"].pop("stepwise")
    if status == "INTENT":
        state["deployPublication"].update(
            status="PENDING",
            intent={"source": "checkpoint", "commit": "unverified", "base": "base"},
        )
    result = publication.describe(tmp_path, state, progress)
    if status == "PENDING":
        assert result["retryable"]
        assert result["nextActions"][0]["command"][-3:] == [
            "deploy-publish",
            "--task-id",
            "deploy",
        ]
        assert result["nextActions"][0]["source"] == "checkpoint"
        assert result["checkpointRequired"] == []
    elif status == "CONFLICT":
        assert result["humanApprovalRequired"]
        assert result["nextActions"][0]["command"] is None
        assert (
            result["nextActions"][0]["conflicts"]
            == state["deployPublication"]["conflicts"]
        )
    else:
        assert not result["nextActions"] and not result["retryable"]
        assert result["status"] == (
            "PENDING" if status in {"UNKNOWN", "INTENT", "CHECKPOINT"} else "SUCCESS"
        )


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


@pytest.mark.parametrize("deleted", [False, True])
def check_conflict_records_model_values(tmp_path, monkeypatch, deleted):
    files = {
        "old": "# model-format: 2\nobserved.row.001-001.value=`before`\n",
        "main": "# model-format: 2\nobserved.row.001-001.value=`main`\n",
        "task": "# model-format: 2\nobserved.row.001-001.value=`aws`\n",
    }
    if deleted:
        files["main"] = None
    monkeypatch.setattr(
        publication, "blob", lambda root, revision, relative: files[revision]
    )
    result = publication.conflicts(
        tmp_path, "old", "main", "task", ["model/dev/a/ec2.properties"]
    )
    assert result[0]["items"] == [
        {
            "key": "observed.row.001-001.value",
            "snapshot": "`before`",
            "base": None if deleted else "`main`",
            "deployed": "`aws`",
        }
    ]


def check_startup_needs_only_standard_library():
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            f"import sys; sys.path.insert(0, {str(Path(worktree.__file__).resolve().parents[1])!r}); from deploy.worktree import start; assert 'yaml' not in sys.modules; assert 'boto3' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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
    context.setdefault("stepwise", True)
    context.setdefault("consumedInputs", {})
    context.setdefault("stepUnits", [{"name": "A"}])
    return SimpleNamespace(
        root=root,
        phase="deploy",
        run_context=context,
        progress_identity=identity,
        progress_root=root.resolve(),
        progress_directory=context.get("directory"),
        progress_destination=worktree.progress_path(root, create=True),
    )


def check_progress_uses_fixed_identity_without_git(tmp_path):
    context = {"states": {"A": {"status": "RUNNING"}}, "inputDigests": {}}
    backend = progress_backend(tmp_path, context)
    with (
        patch.object(ws, "git", side_effect=AssertionError("unexpected Git")),
        patch.object(worktree, "require", side_effect=ws.Blocked("worktree changed")),
    ):
        worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
        context["states"]["A"]["status"] = "SUCCESS"
        worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
        with pytest.raises(ws.Blocked, match="worktree changed"):
            worktree.require(tmp_path)
    assert (
        worktree.read_progress(tmp_path, {"deployIdentity": backend.progress_identity})[
            "runContext"
        ]["states"]["A"]["status"]
        == "SUCCESS"
    )
    context["taskDigest"] = "other"
    with pytest.raises(ValueError, match="fixed identity"):
        worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    assert (
        worktree.read_progress(tmp_path, {"deployIdentity": backend.progress_identity})[
            "runContext"
        ]["states"]["A"]["status"]
        == "SUCCESS"
    )


@pytest.mark.parametrize("stepwise", [False, True])
def check_progress_preserves_success_and_omits_unowned_fields(
    tmp_path, monkeypatch, stepwise
):
    context = {
        "stepwise": stepwise,
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
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    context["states"]["A"] = {"status": "NOT_STARTED"}
    context["inputDigests"] = {}
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    progress = worktree.read_progress(tmp_path, state)
    TestCase().assertEqual(
        progress["runContext"]["states"]["A"], {"status": "NOT_STARTED"}
    )
    TestCase().assertEqual(progress["runContext"]["inputDigests"], {})
    TestCase().assertNotIn("arbitrary", progress["runContext"]["states"]["A"])
    context["stepwise"] = not stepwise
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)


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


@pytest.mark.parametrize("engine", ["cloudformation", "terraform"])
def check_other_engine_retains_its_completion(tmp_path, monkeypatch, engine):
    snapshot = task(tmp_path)
    snapshot.scope = {("dev", "123456789012", "ec2")}
    monkeypatch.setattr(worktree, "require", Mock(return_value={}))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=None))
    monkeypatch.setattr(
        worktree, "load_target_directory", Mock(return_value={"iacEngine": engine})
    )
    if engine == "terraform":
        worktree.require_complete(tmp_path, snapshot)
        worktree.read_progress.assert_not_called()
    else:
        with pytest.raises(ValueError, match="no fixed identity"):
            worktree.require_complete(tmp_path, snapshot)


@pytest.mark.parametrize("kind", ["running", "observed", "generation", "failed"])
@pytest.mark.parametrize("present", [False, True])
def check_unfinished_progress_requires_original_journal(
    tmp_path, monkeypatch, kind, present
):
    saved = {
        "status": "FAILED"
        if kind == "failed"
        else "SUCCESS"
        if kind in {"observed", "generation"}
        else "RUNNING",
        "observedSynced": kind == "generation",
    }
    progress = {
        "runContext": {
            "states": {"A": saved},
            "pendingObserved": kind == "observed",
            "pendingGeneration": kind == "generation",
        }
    }
    state = {"deployIdentity": {"taskDigest": "current"}}
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    record = {
        "publication": {
            "repository": str(tmp_path),
            "taskDigest": "current",
            "pendingObserved": kind == "observed",
            "pendingGeneration": kind == "generation",
        },
        "operations": {"A": {}},
    }
    backend = SimpleNamespace(root=tmp_path, phase="deploy")
    if kind != "failed" and not present:
        with pytest.raises(ValueError, match="without its operation Journal"):
            worktree.check_pending_progress(backend, [], operation_journal.unfinished)
    else:
        worktree.check_pending_progress(
            backend, [record] if present else [], operation_journal.unfinished
        )


@pytest.mark.parametrize("legacy", [None, "{}", "{broken"])
@pytest.mark.parametrize("key", [False, True])
def check_progress_ignores_legacy_files_without_key(tmp_path, monkeypatch, legacy, key):
    old = old_store(tmp_path)
    if key:
        (old / "seal.key").write_bytes(b"broken")
    if legacy is not None:
        (old / "deploy-progress.json").write_text(legacy, encoding="utf-8")
    context = {
        "states": {"A": {"status": "SUCCESS", "observedSynced": True}},
        "inputDigests": {"A": "hash"},
    }
    backend = progress_backend(tmp_path, context)
    state = {"deployIdentity": backend.progress_identity}
    assert worktree.read_progress(tmp_path, state) is None
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    assert (
        worktree.read_progress(tmp_path, state)["runContext"]["states"]["A"]["status"]
        == "SUCCESS"
    )
    assert (
        (old / "seal.key").read_bytes() == b"broken"
        if key
        else not (old / "seal.key").exists()
    )


def check_progress_has_one_mutable_context_and_preserves_recovery(tmp_path):
    context = {
        "states": {
            "A": {
                "status": "SETTLED",
                "attemptResult": "UNKNOWN",
                "endedRequest": {"request": {"token": "original"}},
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
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    saved = worktree.read_progress(
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
        "stepwise",
        "pendingObserved",
    ],
)
def check_corrupt_progress_is_never_empty_success(tmp_path, damage):
    backend = progress_backend(
        tmp_path,
        {"states": {"A": {"status": "FAILED"}}, "inputDigests": {"A": "fixed"}},
    )
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    saved = worktree.read_progress(
        tmp_path, {"deployIdentity": backend.progress_identity}
    )
    if damage == "context":
        saved.pop("runContext")
    elif damage == "pendingObserved":
        saved["runContext"][damage] = True
    else:
        saved["runContext"].pop(damage)
    worktree.write_sealed(tmp_path, backend.progress_destination, saved)
    with pytest.raises(ValueError, match="incomplete or corrupt"):
        worktree.read_progress(tmp_path, {"deployIdentity": backend.progress_identity})


def check_git_display_uses_latest_lifecycle_without_progress_copy(
    tmp_path, monkeypatch
):
    backend = SimpleNamespace(
        root=tmp_path, phase="deploy", run_context={"taskFile": "tasks/deploy.md"}
    )
    state = {"deployPublication": {"status": "PENDING"}}
    monkeypatch.setattr(
        publication.wt, "load", Mock(side_effect=lambda *a: (None, None, None, state))
    )
    monkeypatch.setattr(
        worktree,
        "read_progress",
        Mock(return_value={"runContext": {"stepwise": False}}),
    )
    assert publication.display(backend)["status"] == "PENDING"
    state["deployPublication"] = {"status": "SUCCESS", "publishedSource": "saved"}
    assert publication.display(backend)["status"] == "SUCCESS"
    assert "gitPublication" not in backend.run_context


def check_missing_progress_with_saved_checkpoint_is_not_a_fresh_run(tmp_path):
    with pytest.raises(ValueError, match="progress is missing"):
        worktree.read_progress(
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


@pytest.mark.parametrize(
    "problem",
    [None, "missing", "changed", "tracked", "source", "digest", "publication", "tree"],
)
def check_untracked_cleanup_uses_only_published_exact_task(
    tmp_path, monkeypatch, problem
):
    before = task(tmp_path).text
    after = publication.tasks.set_status(before, "completed")
    path = tmp_path / "tasks/deploy.md"
    path.parent.mkdir()
    if problem != "missing":
        path.write_text(
            after + ("foreign change" if problem == "changed" else ""), encoding="utf-8"
        )
    final = {
        "source": "source",
        "tree": "tree",
        "taskBefore": before,
        "taskAfter": after,
    }
    state = {
        "task_file": "tasks/deploy.md",
        "tip": "source",
        "merged": "merged",
        "deployIdentity": {"taskDigest": task_digest(after)},
        "deployPublication": {
            "status": "SUCCESS",
            "publishedSource": "source",
            "commit": "merged",
            "finalCandidate": final,
        },
    }
    if problem == "source":
        final["source"] = "other"
    elif problem == "digest":
        state["deployIdentity"]["taskDigest"] = "other"
    elif problem == "publication":
        state["deployPublication"]["status"] = "PENDING"
    elif problem == "tree":
        final["tree"] = "other"
    monkeypatch.setattr(
        publication.wt,
        "paths",
        Mock(return_value={"tasks/deploy.md"} if problem == "tracked" else set()),
    )
    monkeypatch.setattr(publication.wt, "output", Mock(return_value="tree"))
    original = path.read_bytes() if path.exists() else None
    if problem in {"changed", "source", "digest", "publication", "tree"}:
        with pytest.raises(ValueError):
            publication.wt.deploy_cleanup_task(tmp_path, state)
        assert path.read_bytes() == original
    elif problem == "tracked":
        assert publication.wt.deploy_cleanup_task(tmp_path, state) is None
        assert path.read_bytes() == original
    else:
        assert publication.wt.deploy_cleanup_task(tmp_path, state) == path
        assert path.read_text(encoding="utf-8") == after


if __name__ == "__main__":
    raise SystemExit(run(__file__))
