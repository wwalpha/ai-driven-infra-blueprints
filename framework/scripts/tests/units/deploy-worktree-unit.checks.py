"""Deploy-only snapshot, ownership, progress and Git failure boundaries without Git fixtures."""

import copy
import hashlib
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
from deploy import guards, inputs, operation_journal, run_context, worktree
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
    "pending",
    [
        None,
        "observed",
        "generation",
        "aws",
        "git",
        "tip",
        "dirty",
        "intent",
        "main",
        "checkpoint",
        "checkpointPending",
        "mode",
    ],
)
def check_completion_keeps_states_separate(tmp_path, monkeypatch, pending):
    state = {
        "tip": "tip",
        "base": "main",
        "deployIdentity": {"stacks": ["A"]},
        "deployPublication": {
            "status": "SUCCESS",
            "publishedSource": "tip",
            "commit": "published",
        },
    }
    progress = {
        "stepwise": False,
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
    if pending in {"checkpoint", "checkpointPending"}:
        progress["stepwise"] = True
    if pending == "checkpointPending":
        progress["checkpointPending"] = {"stacks": ["A"]}
    if pending == "mode":
        progress.pop("stepwise")
    monkeypatch.setattr(
        ws,
        "changed_paths",
        Mock(return_value={"output"} if pending == "dirty" else set()),
    )
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    monkeypatch.setattr(
        worktree.wt,
        "git",
        Mock(return_value=SimpleNamespace(returncode=int(pending == "main"))),
    )
    if pending:
        with pytest.raises(ValueError):
            worktree.require_complete(tmp_path, task(tmp_path))
    else:
        worktree.require_complete(tmp_path, task(tmp_path))


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
        progress["states"]["A"]["status"] = "RUNNING"
    if problem:
        with pytest.raises(ValueError):
            publication.checkpoint_source(tmp_path, state, progress)
    else:
        assert publication.checkpoint_source(tmp_path, state, progress) == "checkpoint"


@pytest.mark.parametrize(
    "problem",
    [
        "normal",
        "zero",
        "receipt",
        "noReceipts",
        "digest",
        "target",
        "unit",
        "commit",
        "tree",
        "stackId",
        "stackStatus",
        "coverage",
        "services",
        "task",
        "checkpointIntent",
        "checkpointPending",
        "gitPending",
        "gitConflict",
        "batch",
    ],
)
def check_final_completion_rechecks_saved_checkpoint_evidence(
    tmp_path, monkeypatch, checkpoint_evidence, problem
):
    state, progress = checkpoint_evidence
    snapshot = task(tmp_path)
    snapshot.task_digest = "task"
    unit = {**progress["stepUnits"][0], "name": "B"}
    state["deployIdentity"]["stacks"] = ["A", "B"]
    state["deployCheckpoints"]["B"] = {
        **copy.deepcopy(state["deployCheckpoints"]["A"]),
        "unit": unit,
        "stackId": "stack-b",
    }
    state["deployCheckpoints"]["A"]["commit"] = "checkpoint-a"
    progress["stepUnits"].append(unit)
    progress["states"]["B"] = {**progress["states"]["A"], "stackId": "stack-b"}
    progress["inputDigests"]["B"] = progress["inputDigests"]["A"]
    progress.update(pendingObserved=False, pendingGeneration=False)
    state["deployPublication"] = {
        "status": "SUCCESS",
        "publishedSource": "checkpoint",
        "commit": "published",
    }
    entry = state["deployCheckpoints"]["A"]
    if problem == "receipt":
        state["deployCheckpoints"].pop("A")
    elif problem == "noReceipts":
        state["deployCheckpoints"] = {}
    elif problem == "digest":
        entry["inputDigest"] = "other"
    elif problem == "target":
        entry["identity"] = {**entry["identity"], "target": {"awsAccountId": "other"}}
    elif problem == "unit":
        entry["unit"] = {**entry["unit"], "name": "other"}
    elif problem == "commit":
        entry["commit"] = "unrecorded"
        monkeypatch.setattr(publication.wt, "ancestor", Mock(return_value=False))
    elif problem == "tree":
        entry["tree"] = "other"
    elif problem == "stackId":
        entry["stackId"] = "other"
    elif problem == "stackStatus":
        entry["stackStatus"] = "UPDATE_COMPLETE"
    elif problem == "coverage":
        entry["coverage"] = {"ec2": {"missing": True}}
    elif problem == "services":
        entry["services"] = ["other"]
    elif problem == "task":
        entry["taskDigest"] = "other"
    elif problem == "checkpointIntent":
        state["deployCheckpointIntent"] = {"head": "checkpoint"}
    elif problem == "checkpointPending":
        progress["checkpointPending"] = {"stacks": ["A"]}
    elif problem == "zero":
        entry["commit"] = state["tip"]
    elif problem in {"gitPending", "gitConflict"}:
        state["deployPublication"]["status"] = (
            "PENDING" if problem == "gitPending" else "CONFLICT"
        )
    elif problem == "batch":
        progress["stepwise"] = False
        state["deployCheckpoints"] = {}
    before = copy.deepcopy(progress["states"])
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
    monkeypatch.setattr(worktree, "read_progress", Mock(return_value=progress))
    monkeypatch.setattr(ws, "changed_paths", Mock(return_value=set()))
    monkeypatch.setattr(
        worktree.wt, "git", Mock(return_value=SimpleNamespace(returncode=0))
    )
    runtime = Mock(
        return_value=SimpleNamespace(checkpoint_source=publication.checkpoint_source)
    )
    monkeypatch.setattr(worktree.wt, "_worktree_runtime", runtime)
    if problem in {"normal", "zero", "batch"}:
        worktree.require_complete(tmp_path, snapshot)
    else:
        with pytest.raises(ValueError):
            worktree.require_complete(tmp_path, snapshot)
    if problem == "batch":
        runtime.assert_not_called()
    assert progress["states"] == before


@pytest.mark.parametrize("mode", [True, None])
def check_stepwise_without_receipt_never_creates_checkpoint(
    tmp_path, monkeypatch, checkpoint_evidence, mode
):
    state, progress = checkpoint_evidence
    state["worktree"] = str(tmp_path)
    state["deployCheckpoints"] = {}
    if mode is None:
        progress.pop("stepwise")
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
    "status", ["PENDING", "CONFLICT", "SUCCESS", "UNKNOWN", "INTENT"]
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
    progress["checkpointPending"] = {"stacks": ["B"]}
    if status == "UNKNOWN":
        progress.pop("stepwise")
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
        assert result["checkpointRequired"] == ["B"]
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
            "PENDING" if status in {"UNKNOWN", "INTENT"} else "SUCCESS"
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


@pytest.mark.parametrize("stepwise", [False, True])
def check_progress_preserves_success_and_omits_unowned_fields(
    tmp_path, monkeypatch, stepwise
):
    state = {"deployIdentity": {"taskFile": "tasks/deploy.md", "snapshot": "fixed"}}
    monkeypatch.setattr(worktree, "require", Mock(return_value=state))
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
    context["stepwise"] = not stepwise
    with pytest.raises(ValueError, match="execution mode changed"):
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
