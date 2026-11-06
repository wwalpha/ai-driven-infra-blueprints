"""Deploy-only snapshot, ownership, progress and Git failure boundaries without Git fixtures."""

import json
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
import worktree_state as ws
from deploy import (
    controller,
    guards,
    operation_journal,
    run_context,
    worktree,
)
from deploy import progress as deploy_progress
from support.pytest_cli import run
from task_contract_core import task_digest
from utils.cloudformation.inputs import Blocked as DeployBlocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")










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
    meta.write_text(json.dumps(state), encoding="utf-8")
    git = Mock(side_effect=partial(_callback_snapshot_git, replies))
    monkeypatch.setattr(ws, "git", git)
    if problem not in {None, "repository-lines"}:
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
        progress_task_file=identity["taskFile"],
        progress_root=root.resolve(),
        progress_directory=context.get("directory"),
        progress_destination=deploy_progress.progress_path(root, identity["taskFile"], create=True),
    )


def check_progress_uses_fixed_identity_without_git(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    first = deploy_progress.progress_path(isolated, "tasks/first.md", create=True)
    second = deploy_progress.progress_path(isolated, "tasks/second.md", create=True)
    assert first != second
    assert first.parent == operation_journal.location(isolated, "tasks/first.md").parent
    identity = {"taskFile": "tasks/first.md", "taskDigest": "digest", "target": {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}, "environment": "dev", "stacks": ["A"]}
    backend = progress_backend(isolated, {"states": {"A": {"status": "RUNNING", "clientToken": "token"}}, "inputDigests": {}})
    backend.progress_identity = identity
    backend.run_context.update(identity)
    backend.progress_task_file = identity["taskFile"]
    backend.progress_destination = first
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    with operation_journal.locked(first), operation_journal.locked(second):
        with pytest.raises(DeployBlocked, match="lock busy"):
            with operation_journal.locked(first):
                pass
    assert deploy_progress.read_progress(isolated, {"deployIdentity": identity}, identity["taskFile"])["runContext"]["states"]["A"]["clientToken"] == "token"
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
        "syncPending": {"stacks": ["A"], "final": True},
        "generationError": "failed generation",
        "snapshotValidation": "FAIL",
        "deployResult": "FAIL",
    }
    backend = progress_backend(tmp_path, context)
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    saved = deploy_progress.read_progress(
        tmp_path, {"deployIdentity": backend.progress_identity}
    )
    assert set(saved) == {"identity", "runContext"}
    for key in (
        "states",
        "inputDigests",
        "pendingObserved",
        "pendingGeneration",
        "syncPending",
        "generationError",
        "snapshotValidation",
        "deployResult",
    ):
        assert saved["runContext"][key] == context[key]
    for key in ("pendingObserved", "pendingGeneration", "syncPending"):
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








































if __name__ == "__main__":
    raise SystemExit(run(__file__))
