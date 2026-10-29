"""Deploy-only snapshot, ownership, progress and Git failure boundaries without Git fixtures."""

import copy
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import worktree_state as ws
from deploy import git_publication as publication
from deploy import guards, operation_journal, run_context, worktree
from support.pytest_cli import run
from task_contract_core import task_digest


def task(root):
    text = "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Infrastructure phase: `deploy`\n"
    return SimpleNamespace(
        name="tasks/deploy.md", text=text, task_digest=task_digest(text)
    )


@pytest.mark.parametrize("problem", [None, "head", "ancestry", "owner", "merged"])
def check_snapshot_ignores_base_history(tmp_path, monkeypatch, problem):
    primary = tmp_path / "primary"
    root = primary / ".worktrees/deploy"
    meta = primary / "state.json"
    meta.parent.mkdir()
    meta.touch()
    state = dict(
        task_id="deploy",
        task_file="tasks/deploy.md",
        worktree=str(root),
        start="snapshot",
        tip="tip",
        merged=None,
    )
    if problem == "owner":
        state["worktree"] += "-other"
    if problem == "merged":
        state["merged"] = "published"
    monkeypatch.setattr(
        ws, "repository", Mock(return_value=(root, primary / ".git", primary))
    )
    monkeypatch.setattr(ws, "state_path", Mock(return_value=meta))
    monkeypatch.setattr(ws, "load", Mock(return_value=(primary, None, meta, state)))
    monkeypatch.setattr(ws, "task_worktree", Mock(return_value=root))
    values = iter(["snapshot", "bad" if problem == "head" else "tip"])
    monkeypatch.setattr(ws, "output", Mock(side_effect=values))
    git = Mock(return_value=SimpleNamespace(returncode=int(problem == "ancestry")))
    monkeypatch.setattr(ws, "git", git)
    if problem:
        with pytest.raises(ValueError):
            ws.deploy_start_commit(root, "tasks/deploy.md", required=True)
    else:
        assert (
            ws.deploy_start_commit(root, "tasks/deploy.md", required=True) == "snapshot"
        )
        assert git.call_args.args[1:4] == ("merge-base", "--is-ancestor", "snapshot")
        assert git.call_args.args[4] == "tip"
    assert all("refs/heads/main" not in str(call) for call in git.call_args_list)


@pytest.mark.parametrize("operation", sorted(guards.MUTATIONS))
def check_unmanaged_mutation_is_rejected(tmp_path, monkeypatch, operation):
    snapshot = task(tmp_path)
    monkeypatch.setattr(worktree.tasks, "task_snapshot", Mock(return_value=snapshot))
    monkeypatch.setattr(
        ws,
        "deploy_start_commit",
        Mock(side_effect=ws.Blocked("registered managed worktree required")),
    )
    monkeypatch.setattr(guards, "task_reads", Mock(return_value=nullcontext()))
    runtime = SimpleNamespace(
        root=tmp_path, guard=Mock(), timing=Mock(), connection=None
    )
    with pytest.raises(ValueError, match="managed worktree"):
        guards.call(runtime, "cloudformation", operation, {})
    runtime.guard.assert_not_called()
    runtime.timing.phase.assert_not_called()


@pytest.mark.parametrize("problem", [None, "setup", "contract"])
def check_managed_task_authority(tmp_path, monkeypatch, problem):
    snapshot = task(tmp_path)
    state = {
        "python_setup": {"status": "failed" if problem == "setup" else "ready"},
        "deployIdentity": {
            "taskDigest": "changed" if problem == "contract" else snapshot.task_digest
        },
    }
    monkeypatch.setattr(ws, "deploy_start_commit", Mock(return_value="snapshot"))
    monkeypatch.setattr(ws, "managed_task_state", Mock(return_value=state))
    if problem:
        with pytest.raises(ValueError):
            worktree.require(tmp_path, snapshot)
    else:
        assert worktree.require(tmp_path, snapshot) is state


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
    assert backend.run_context["gitPublication"]["status"] == "PENDING"
    assert states == original
    assert not getattr(backend, "sync_failed", False)
    backend.save.assert_called_once()


@pytest.mark.parametrize(
    "digest,repair", [("hash", False), ("changed", False), ("changed", True)]
)
def check_resume_adopts_only_unchanged_successes(tmp_path, monkeypatch, digest, repair):
    saved = {
        "status": "SUCCESS",
        "observedSynced": True,
        "executionEvidence": {"clientToken": "original"},
    }
    progress = {"states": {"A": saved}, "inputDigests": {"A": "hash"}}
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
    "pending", [None, "observed", "generation", "aws", "git", "tip", "dirty", "intent"]
)
def check_completion_keeps_states_separate(tmp_path, monkeypatch, pending):
    state = {
        "tip": "tip",
        "deployIdentity": {"stacks": ["A"]},
        "deployPublication": {"status": "SUCCESS", "publishedSource": "tip"},
    }
    progress = {
        "states": {"A": {"status": "SUCCESS", "observedSynced": True}},
        "pendingObserved": pending == "observed",
        "pendingGeneration": pending == "generation",
    }
    if pending == "aws":
        progress["states"]["A"]["status"] = "RUNNING"
    if pending == "git":
        state["deployPublication"]["status"] = "CONFLICT"
    if pending == "tip":
        state["deployPublication"]["publishedSource"] = "old"
    if pending == "intent":
        state["deployCheckpointIntent"] = {"head": "previous"}
    monkeypatch.setattr(
        ws,
        "changed_paths",
        Mock(return_value={"output"} if pending == "dirty" else set()),
    )
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    if pending:
        with pytest.raises(ValueError):
            worktree.require_complete(tmp_path, task(tmp_path))
    else:
        worktree.require_complete(tmp_path, task(tmp_path))


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


def check_progress_preserves_success_and_omits_unowned_fields(tmp_path, monkeypatch):
    state = {"deployIdentity": {"taskFile": "tasks/deploy.md", "snapshot": "fixed"}}
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
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
    backend = SimpleNamespace(root=tmp_path, phase="deploy", run_context=context)
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    context["states"]["A"] = {"status": "NOT_STARTED"}
    context["inputDigests"] = {}
    worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
    progress = worktree.read_progress(tmp_path, state)
    assert progress["states"]["A"] == {
        "status": "SUCCESS",
        "observedSynced": True,
        "clientToken": "original",
    }
    assert progress["inputDigests"]["A"] == "hash"


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
        with pytest.raises(ValueError, match="unfinished"):
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
        "states": {"A": saved},
        "pendingObserved": kind == "observed",
        "pendingGeneration": kind == "generation",
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


if __name__ == "__main__":
    raise SystemExit(run(__file__))
