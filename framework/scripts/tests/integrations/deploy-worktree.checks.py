"""Real managed Git lifecycle, plus synthetic AWS controller/Model publication integration."""

import json
import os
import sys
import tempfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import worktree_state as ws
import worktree_task as wt
from deploy import git_publication as publication
from deploy import guards, operation_journal, worktree
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


if __name__ == "__main__":
    raise SystemExit(run(__file__))
