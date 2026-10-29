"""Real managed Git lifecycle, plus synthetic AWS controller/Model publication integration."""

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import task_contract as tasks
import task_contract_runtime as transitions
import worktree_checkpoint as checkpoints
import worktree_state as ws
import worktree_task as wt
from deploy import contracts, guards, inputs, operation_journal, worktree
from deploy import git_publication as publication
from model.format import parse
from model.format import patch as patch_properties
from support.deploy_controller_fixtures import ACCOUNT, aws_state, invoke
from support.pytest_cli import run
from support.worktree_deploy_fixtures import seed
from support.worktree_task_fixtures import fixture, git
from task_contract_core import read_task_snapshot, selected_task, set_status, start


@pytest.fixture(autouse=True)
def private_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)


def deploy_contract(name, files):
    listed = "\n".join(f"- `{p}`" for p in [name, *files])
    return f"""## Task contract
- Task type: `infrastructure`
- Task status: `running`
- Infrastructure phase: `deploy`
## Required changes
- [R1] Publish observations
## Acceptance checks
- [R1] `exists:{files[0]}`
## Validation scope
- `dev/123456789012/ec2`
## Modified files
{listed}
## Allowed paths
{listed}
"""


def rewrite_base(root):
    old = git(root, "rev-parse", "HEAD")
    replacement = git(
        root, "commit-tree", "HEAD^{tree}", "-m", "Unrelated replacement history"
    )
    git(root, "update-ref", "refs/heads/main", replacement, old)
    assert (
        not ws.git(
            root, "merge-base", "--is-ancestor", old, "main", check=False
        ).returncode
        == 0
    )


def check_start_creates_and_reuses_official_worktree(monkeypatch):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
    ):
        state = worktree.start(primary, "deploy")
        root = Path(state["worktree"])
        start(
            root, state["task_file"], deploy_contract(state["task_file"], ["file.txt"])
        )
        assert worktree.start(primary, "deploy")["start"] == state["start"]
        assert len(ws.worktrees(primary)) == 2
        (primary / "file.txt").write_text("main advanced\n")
        git(primary, "add", "file.txt")
        git(primary, "commit", "-qm", "Advance")
        assert (
            ws.deploy_start_commit(root, state["task_file"], required=True)
            == state["start"]
        )
        rewrite_base(primary)
        assert (
            ws.deploy_start_commit(root, state["task_file"], required=True)
            == state["start"]
        )
        with pytest.raises(ValueError, match="rewritten"):
            ws.task_start_commit(root, state["task_file"])
        # A same-named Task in the primary checkout cannot execute this Deploy.
        with selected_task(root, state["task_file"]):
            assert worktree.require(root)["task_id"] == "deploy"
        with pytest.raises(ValueError, match="another managed worktree"):
            ws.deploy_start_commit(primary, state["task_file"], required=True)
        start(
            primary,
            state["task_file"],
            deploy_contract(state["task_file"], ["file.txt"]),
        )
        runtime = SimpleNamespace(root=primary, guard=Mock())
        with (
            selected_task(primary, state["task_file"]),
            pytest.raises(ValueError, match="another managed worktree"),
        ):
            guards.call(runtime, "cloudformation", "execute_change_set", {})
        runtime.guard.assert_not_called()


def check_git_conflict_checkpoints_peers_and_recovers(monkeypatch, tmp_path):
    # This case isolates real Git retention; the controller case below runs real Model guards.
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
    ):
        relative = "model/dev/a/ec2.properties"
        source = primary / relative
        source.parent.mkdir(parents=True)
        source.write_text("# model-format: 2\nobserved.row.001-001.value=`before`\n")
        git(primary, "add", relative)
        git(primary, "commit", "-qm", "Model fixture")
        state = worktree.start(primary, "deploy")
        root = Path(state["worktree"])
        name = state["task_file"]
        start(root, name, deploy_contract(name, [relative, "file.txt"]))
        with selected_task(root, name):
            worktree.bind(root, read_task_snapshot(root, name), {}, "dev", ["A", "B"])
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context={
                    "taskFile": name,
                    "states": {
                        "A": {"status": "SUCCESS", "observedSynced": True},
                        "B": {"status": "NOT_STARTED"},
                    },
                    "inputDigests": {"A": "digest"},
                },
                save=Mock(),
            )
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            (root / relative).write_text(
                "# model-format: 2\nobserved.row.001-001.value=`aws`\n"
            )
            source.write_text("# model-format: 2\nobserved.row.001-001.value=`main`\n")
            git(primary, "add", relative)
            git(primary, "commit", "-qm", "Conflicting main observation")
            result = publication.publish(root, "deploy")
            assert (
                result["status"] == "CONFLICT"
                and result["conflicts"][0]["items"][0]["deployed"] == "`aws`"
            )
            first = git(root, "rev-parse", "HEAD")
            (root / "file.txt").write_text("Independent Stack B\n")
            backend.run_context["states"]["B"] = {
                "status": "SUCCESS",
                "observedSynced": True,
            }
            backend.run_context["inputDigests"]["B"] = "b-digest"
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            publication.sync(backend)
            assert backend.run_context["gitPublication"]["status"] == "CONFLICT"
            assert git(root, "rev-parse", "HEAD") != first
            assert (primary / "file.txt").read_text() == "original\n"
            result = publication.publish(root, "deploy")
            resolution = tmp_path / "resolution.json"
            resolution.write_text(
                json.dumps(
                    {
                        "approval": "Fixture Human chooses the AWS observation",
                        "base": result["base"],
                        "source": result["source"],
                        "files": {relative: (root / relative).read_text()},
                    }
                )
            )
            assert (
                publication.publish(root, "deploy", resolution)["status"] == "SUCCESS"
            )
            assert (
                source.read_text()
                == "# model-format: 2\nobserved.row.001-001.value=`aws`\n"
            )
            assert (primary / "file.txt").read_text() == "Independent Stack B\n"
            assert all(
                s["status"] == "SUCCESS" for s in backend.run_context["states"].values()
            )
            assert not wt.changed_paths(root) and not wt.changed_paths(primary)


def run_controller(root, report, aws, driver):
    if driver == "batch":
        return invoke(root, report, aws)
    for _ in range(12):
        assert invoke(root, report, aws, ["--action", "advance"]) == 0
        context = json.loads(report.read_text())
        names = [
            name
            for name, saved in context["states"].items()
            if saved["status"] == "SUCCESS" and not saved.get("observedSynced")
        ]
        if names:
            assert (
                invoke(
                    root,
                    report,
                    aws,
                    [
                        "--action",
                        "sync",
                        *[arg for name in names for arg in ("--sync-stack", name)],
                    ],
                )
                == 0
            )
        context = json.loads(report.read_text())
        pending = context.get("checkpointPending")
        if (
            pending
            and pending.get("after") is not None
            and not context.get("pendingGeneration")
        ):
            assert (
                invoke(
                    root,
                    report,
                    aws,
                    [
                        "--action",
                        "checkpoint",
                        *[
                            arg
                            for name in pending["stacks"]
                            for arg in ("--sync-stack", name)
                        ],
                    ],
                )
                == 0
            )
        context = json.loads(report.read_text())
        if all(
            saved["status"] == "SUCCESS" and saved.get("checkpointed")
            for saved in context["states"].values()
        ):
            return 0
    raise AssertionError("short operations did not complete local checkpoints")


@pytest.mark.parametrize("driver", ["batch", "steps"])
def check_controller_keeps_aws_success_after_rewrite_and_conflict(
    tmp_path, monkeypatch, driver
):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders")
    primary = Path(ws.load(root, "deploy")[0])
    rewrite_base(primary)
    source = primary / f"model/dev/{ACCOUNT}/ec2/001.properties"
    if not source.is_file():
        source = primary / f"model/dev/{ACCOUNT}/ec2.properties"
    source.write_text(
        patch_properties(
            parse(source.read_text()), {"observed.row.001-001.value": "`vpc-main`"}
        )
    )
    git(primary, "add", source.relative_to(primary).as_posix())
    git(primary, "commit", "-qm", "Main conflicting observation")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    aws_state(aws)
    assert run_controller(root, report, aws, driver) == 0
    context = json.loads(report.read_text())
    assert all(
        s["status"] == "SUCCESS" and s.get("observedSynced")
        for s in context["states"].values()
    )
    assert context["gitPublication"]["status"] == "CONFLICT", context.get(
        "gitPublication"
    )
    before = json.loads(aws.read_text())["calls"]
    assert run_controller(root, report, aws, driver) == 0
    resumed = json.loads(report.read_text())
    assert resumed["gitPublication"]["status"] == "CONFLICT"
    assert all(s["status"] == "SUCCESS" for s in resumed["states"].values())
    assert not any(
        op in {"create_change_set", "execute_change_set"}
        for _, op, _ in json.loads(aws.read_text())["calls"][len(before) :]
    )
    before = json.loads(aws.read_text())["calls"]
    with selected_task(root, "tasks/deploy.md"):
        result = publication.publish(root, "deploy")
        assert result["status"] == "CONFLICT"
        resolution = tmp_path / "human-resolution.json"
        resolution.write_text(
            json.dumps(
                {
                    "approval": "Fixture Human accepts AWS values and generated views",
                    "base": result["base"],
                    "source": result["source"],
                    "files": {
                        r["path"]: (root / r["path"]).read_text()
                        for r in result["conflicts"]
                    },
                }
            )
        )
        assert publication.publish(root, "deploy", resolution)["status"] == "SUCCESS"
        worktree.require_complete(root, read_task_snapshot(root, "tasks/deploy.md"))
    assert json.loads(aws.read_text())["calls"] == before
    assert (
        invoke(
            root,
            report,
            aws,
            ["--recover-operations"] if driver == "batch" else ["--action", "status"],
        )
        == 0
    )
    assert not any(
        op == "execute_change_set"
        for _, op, _ in json.loads(aws.read_text())["calls"][len(before) :]
    )


def interrupt_git(actual, owner, boundary, root, *args, **kwargs):
    result = actual(root, *args, **kwargs)
    if root == owner and (
        boundary == "commit"
        and args[0] == "commit"
        or boundary == "merge"
        and args[:2] == ("merge", "--ff-only")
    ):
        raise OSError("interrupted after Git " + boundary)
    return result


def check_managed_journal_recovery_never_reexecutes_success(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    aws_state(aws)
    assert invoke(root, report, aws, fault="design-io") == 2
    first = json.loads(report.read_text())
    assert first["pendingGeneration"]
    journal = report.with_suffix(".operations.json")
    retained = report.with_suffix(".retained.json")
    journal.rename(
        retained
    )  # Synthetic loss; keep the exact sealed bytes for restoration.
    before = json.loads(aws.read_text())["calls"]
    assert invoke(root, report, aws, ["--recover-operations"]) == 2
    assert not any(
        op in {"create_change_set", "execute_change_set"}
        for _, op, _ in json.loads(aws.read_text())["calls"][len(before) :]
    )
    retained.rename(journal)
    assert invoke(root, report, aws, ["--recover-operations"]) == 0
    recovered = json.loads(report.read_text())
    assert not recovered.get("pendingGeneration")
    assert invoke(root, report, aws) == 0
    states = json.loads(report.read_text())["states"]
    calls = json.loads(aws.read_text())["calls"]
    for name, saved in states.items():
        assert saved["status"] == "SUCCESS"
        assert (
            sum(
                op == "execute_change_set" and args["StackName"] == saved["stackId"]
                for _, op, args in calls
            )
            == 1
        ), name


@pytest.mark.parametrize("boundary", ["commit", "merge"])
def check_interrupted_publication_retries_and_cleans(monkeypatch, boundary):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
    ):
        state = worktree.start(primary, "deploy")
        root = Path(state["worktree"])
        name = state["task_file"]
        start(root, name, deploy_contract(name, ["file.txt"]))
        with selected_task(root, name):
            worktree.bind(root, read_task_snapshot(root, name), {}, "dev", ["A"])
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context={
                    "states": {"A": {"status": "SUCCESS", "observedSynced": True}},
                    "inputDigests": {"A": "hash"},
                },
            )
            worktree.save_progress(backend, operation_journal.OPERATION_FIELDS)
            (root / "file.txt").write_text("Task output\n")
            owner = root if boundary == "commit" else primary
            with patch.object(
                wt, "git", partial(interrupt_git, wt.git, owner, boundary)
            ):
                with pytest.raises(OSError, match="interrupted"):
                    publication.publish(root, "deploy")
            assert publication.publish(root, "deploy")["status"] == "SUCCESS"
            assert (primary / "file.txt").read_text() == "Task output\n"
            snapshot = read_task_snapshot(root, name, live=True)
            snapshot.path.write_text(set_status(snapshot.text, "completed"))
            publication.finalize(root, "deploy")
            assert wt.cleanup(primary, "deploy")["cleaned"]
            assert not root.exists() and not wt.branch_exists(primary, state["branch"])


@contextmanager
def stepwise_repository(tracked_contract=False):
    with (
        fixture() as primary,
        patch.object(wt.python_env, "setup", return_value={"status": "ready"}),
        patch.object(
            wt.python_env, "runtime", return_value=(sys.executable, dict(os.environ))
        ),
        patch.object(publication, "check_scope"),
        patch.object(wt, "_run_model_guard"),
        patch.object(publication, "validate_candidate"),
        patch.object(checkpoints, "validate"),
    ):
        relative = "model/dev/app/ec2.properties"
        text = (
            "# model-format: 2\nobserved.a.value=`before`\nobserved.b.value=`before`\n"
        )
        source = primary / relative
        source.parent.mkdir(parents=True)
        source.write_text(text, encoding="utf-8")
        units = [
            {"name": name, "template": name + ".yaml", "parameters": name + ".json"}
            for name in ["A", "B"]
        ]
        for path in inputs.deployment_input_paths(primary, "dev", "app", {}, units):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("immutable input", encoding="utf-8")
        name = "tasks/deploy.md"
        contract = deploy_contract(name, [relative])
        if tracked_contract:
            (primary / name).parent.mkdir()
            (primary / name).write_text(contract, encoding="utf-8")
            git(primary, "add", "-f", name)
        git(primary, "add", "model", "infra")
        git(primary, "commit", "-qm", "Stepwise synthetic inputs")
        state = wt.create(primary, "deploy")
        root = Path(state["worktree"])
        if not tracked_contract:
            start(root, name, contract)
        with selected_task(root, name):
            task = read_task_snapshot(root, name, live=True)
            worktree.bind(root, task, {}, "dev", ["A", "B"])
            context = {
                "taskFile": name,
                "taskDigest": task.task_digest,
                "directory": "app",
                "stepwise": True,
                "stepUnits": units,
                "inputDigests": {},
                "consumedInputs": {},
                "states": {
                    n: {
                        "status": "RUNNING",
                        "stackId": "stack-" + n,
                        "stackStatus": "CREATE_COMPLETE",
                    }
                    for n in ["A", "B"]
                },
            }
            for unit in units:
                paths = inputs.deployment_input_paths(root, "dev", "app", {}, [unit])
                digests = [inputs.file_digest({}, p, fresh=True) for p in paths]
                context["inputDigests"][unit["name"]] = inputs.fingerprint(digests)
                context["consumedInputs"].update(
                    {
                        p.relative_to(root).as_posix(): digest
                        for p, digest in zip(paths, digests, strict=True)
                    }
                )
            backend = SimpleNamespace(
                root=root,
                phase="deploy",
                run_context=context,
                states=context["states"],
                guard=Mock(),
                deployment_input_paths=partial(
                    inputs.deployment_input_paths, root, "dev", "app", {}
                ),
            )
            backend.save = partial(
                worktree.save_progress, backend, operation_journal.OPERATION_FIELDS
            )
            backend.save()
            yield primary, backend, relative


def synchronized_candidate(backend, relative, name):
    root, context = backend.root, backend.run_context
    before = contracts.validation_snapshot(root)
    source = root / relative
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "observed." + name.lower() + ".value=`before`",
            "observed." + name.lower() + ".value=`aws`",
        ),
        encoding="utf-8",
    )
    backend.states[name].update(status="SUCCESS", observedSynced=True)
    context["checkpointPending"] = {
        "stacks": [name],
        "before": before,
        "after": contracts.validation_snapshot(root),
    }
    backend.save()


def interrupt_saved_state(actual, boundary, path, state):
    actual(path, state)
    if (
        boundary == "receipt"
        and state.get("deployCheckpoints")
        or boundary == "intent"
        and state.get("deployPublication", {}).get("intent")
    ):
        raise OSError("interrupted after saved " + boundary)


def change_publication_candidate(root, tree, base, task):
    source = root / "model/dev/app/ec2.properties"
    source.write_text(
        source.read_text(encoding="utf-8") + "# concurrent candidate\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "boundary",
    [
        None,
        "commit",
        "receipt",
        "intent",
        "merge",
        "pendingObserved",
        "pendingGeneration",
        "candidate-change",
    ],
)
def check_stepwise_checkpoint_publication_isolation(boundary):
    with stepwise_repository() as (primary, backend, relative):
        root = backend.root
        synchronized_candidate(backend, relative, "A")
        base = git(primary, "rev-parse", "HEAD")
        with pytest.raises(ValueError, match="checkpoint evidence"):
            publication.publish(root, "deploy")
        assert git(primary, "rev-parse", "HEAD") == base
        if boundary in {"commit", "receipt"}:
            guard = (
                patch.object(wt, "git", partial(interrupt_git, wt.git, root, "commit"))
                if boundary == "commit"
                else patch.object(
                    wt, "save", partial(interrupt_saved_state, wt.save, "receipt")
                )
            )
            with guard, pytest.raises(OSError, match="interrupted"):
                checkpoints.snapshot_checkpoint(backend, ["A"])
            committed = git(root, "rev-parse", "HEAD")
            if boundary == "commit":
                with pytest.raises(ValueError, match="checkpoint operation"):
                    publication.publish(root, "deploy")
            else:
                assert publication.publish(root, "deploy")["status"] == "SUCCESS"
            checkpoints.snapshot_checkpoint(backend, ["A"])
            assert git(root, "rev-parse", "HEAD") == committed
        else:
            checkpoints.snapshot_checkpoint(backend, ["A"])
        saved = git(root, "rev-parse", "HEAD")
        if boundary == "candidate-change":
            with (
                patch.object(
                    publication, "validate_candidate", change_publication_candidate
                ),
                pytest.raises(ValueError, match="inputs changed"),
            ):
                publication.publish(root, "deploy")
            assert git(primary, "rev-parse", "HEAD") == base
            assert git(root, "rev-parse", "HEAD") == saved
            return
        publication.sync(backend)
        assert backend.run_context["gitPublication"]["status"] == "SUCCESS"
        # B edits the same Model file; A's Git retry must preserve B's staged candidate.
        synchronized_candidate(backend, relative, "B")
        if boundary in {"pendingObserved", "pendingGeneration"}:
            backend.run_context[boundary] = {"B": "retained candidate"}
            backend.save()
        git(root, "add", relative)
        candidate = (root / relative).read_bytes()
        index = git(root, "write-tree")
        first_main = git(primary, "rev-parse", "HEAD")
        result = publication.publish(root, "deploy")
        assert result["status"] == "SUCCESS"
        assert git(primary, "rev-parse", "HEAD") == first_main
        assert git(root, "rev-parse", "HEAD") == saved
        assert (
            git(root, "write-tree") == index
            and (root / relative).read_bytes() == candidate
        )
        assert "observed.b.value=`before`" in (primary / relative).read_text()
        backend.run_context.pop("pendingObserved", None)
        backend.run_context.pop("pendingGeneration", None)
        checkpoints.snapshot_checkpoint(backend, ["B"])
        if boundary in {"intent", "merge"}:
            guard = (
                patch.object(
                    wt, "save", partial(interrupt_saved_state, wt.save, "intent")
                )
                if boundary == "intent"
                else patch.object(
                    wt, "git", partial(interrupt_git, wt.git, primary, "merge")
                )
            )
            with guard, pytest.raises(OSError, match="interrupted"):
                publication.publish(root, "deploy")
        result = publication.publish(root, "deploy")
        merged = git(primary, "rev-parse", "HEAD")
        assert result["status"] == "SUCCESS" and result["commit"] == merged
        assert not result["nextActions"]
        assert publication.publish(root, "deploy")["commit"] == merged
        assert git(primary, "rev-parse", "HEAD") == merged
        assert (primary / relative).read_bytes() == candidate


@pytest.mark.parametrize("boundary", [None, "commit"])
def check_stepwise_final_contract_checkpoint(boundary):
    with stepwise_repository(tracked_contract=True) as (primary, backend, relative):
        root = backend.root
        for name in ["A", "B"]:
            synchronized_candidate(backend, relative, name)
            checkpoints.snapshot_checkpoint(backend, [name])
            publication.publish(root, "deploy")
        snapshot = read_task_snapshot(root, "tasks/deploy.md", live=True)
        snapshot.path.write_text(
            set_status(snapshot.text, "completed"), encoding="utf-8"
        )
        if boundary:
            with (
                patch.object(wt, "git", partial(interrupt_git, wt.git, root, boundary)),
                pytest.raises(OSError, match="interrupted"),
            ):
                publication.finalize(root, "deploy")
        result = publication.finalize(root, "deploy")
        assert result["verified"]
        assert "- Task status: `completed`" in (primary / snapshot.name).read_text()
        assert wt.cleanup(primary, "deploy")["cleaned"]


@pytest.mark.parametrize("problem", ["target", "commit", "zero"])
def check_task_completion_rechecks_checkpoint_receipts(problem):
    with stepwise_repository() as (primary, backend, relative):
        root = backend.root
        for name in ["A", "B"]:
            if name == "B" and problem == "zero":
                snapshot = contracts.validation_snapshot(root)
                backend.states[name].update(status="SUCCESS", observedSynced=True)
                backend.run_context["checkpointPending"] = {
                    "stacks": [name],
                    "before": snapshot,
                    "after": snapshot,
                }
                backend.save()
            else:
                synchronized_candidate(backend, relative, name)
            checkpoints.snapshot_checkpoint(backend, [name])
            publication.publish(root, "deploy")
        _, _, path, state = wt.load(root, "deploy")
        if problem == "target":
            state["deployCheckpoints"]["A"]["identity"] = {
                **state["deployIdentity"],
                "target": {"awsAccountId": "other"},
            }
        elif problem == "commit":
            state["deployCheckpoints"]["A"]["commit"] = "unrecorded-commit"
        else:
            assert (
                state["deployCheckpoints"]["A"]["commit"]
                == state["deployCheckpoints"]["B"]["commit"]
            )
        wt.save(path, state)
        progress = worktree.read_progress(root, state)
        before = json.loads(json.dumps(progress["states"]))
        with (
            patch.object(transitions, "Validator") as validator,
            patch.object(transitions._imports_import_guard, "require_import_changes"),
        ):
            validator.return_value.report.return_value = 0
            if problem == "zero":
                tasks.complete(root, "tasks/deploy.md")
            else:
                with pytest.raises(ValueError, match="checkpoint"):
                    tasks.complete(root, "tasks/deploy.md")
        task = read_task_snapshot(root, "tasks/deploy.md", live=True)
        assert task.status == ("completed" if problem == "zero" else "running")
        assert worktree.read_progress(root, state)["states"] == before
        assert all(
            s["status"] == "SUCCESS" and s["observedSynced"] for s in before.values()
        )


def check_stepwise_success_while_peer_running(tmp_path, monkeypatch):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "orders", same_group=True)
    primary = Path(ws.load(root, "deploy")[0])
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    monkeypatch.setenv("TMPDIR", tempfile.gettempdir())
    aws_state(aws)
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    provider = json.loads(aws.read_text())
    second = "cfn-stack-app-dev-second"
    first = "cfn-stack-app-dev-first"
    provider["stacks"][second]["status"] = "CREATE_IN_PROGRESS"
    aws.write_text(json.dumps(provider))
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    context = json.loads(report.read_text())
    assert context["states"][first]["status"] == "SUCCESS"
    assert context["states"][second]["status"] == "RUNNING"
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", first]) == 0
    before = git(primary, "rev-parse", "HEAD")
    with (
        selected_task(root, "tasks/deploy.md"),
        pytest.raises(ValueError, match="checkpoint evidence"),
    ):
        publication.publish(root, "deploy")
    assert git(primary, "rev-parse", "HEAD") == before
    with patch.object(
        publication, "publish", side_effect=ws.Blocked("temporary Git interruption")
    ):
        assert (
            invoke(root, report, aws, ["--action", "checkpoint", "--sync-stack", first])
            == 0
        )
    context = json.loads(report.read_text())
    assert context["gitPublication"]["status"] == "PENDING"
    assert context["gitPublication"]["retryable"]
    provider = json.loads(aws.read_text())
    provider["stacks"][second]["status"] = "CREATE_COMPLETE"
    aws.write_text(json.dumps(provider))
    assert invoke(root, report, aws, ["--action", "advance"]) == 0
    assert invoke(root, report, aws, ["--action", "sync", "--sync-stack", second]) == 0
    candidates = {p: (root / p).read_bytes() for p in wt.changed_paths(root)}
    assert candidates
    calls = json.loads(aws.read_text())["calls"]
    result = wt.run_deploy_publication(root, "deploy")
    assert result["status"] == "SUCCESS"
    assert wt.changed_paths(root) == set(candidates)
    assert all((root / p).read_bytes() == content for p, content in candidates.items())
    assert json.loads(aws.read_text())["calls"] == calls
    assert git(primary, "rev-parse", "HEAD") != before
    assert result["checkpointRequired"] == [second]
    assert (
        invoke(root, report, aws, ["--action", "checkpoint", "--sync-stack", second])
        == 0
    )
    with selected_task(root, "tasks/deploy.md"):
        worktree.require_complete(
            root, read_task_snapshot(root, "tasks/deploy.md", live=True)
        )
        tasks.complete(root, "tasks/deploy.md")
    assert wt.finalize(root, "deploy")["cleaned"]
    assert not root.exists()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
