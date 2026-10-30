"""Real scoped publication and normal Worktree checkpoint while a peer is running."""

import json
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import worktree_task as wt
from deploy import generation_resume, worktree
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    git,
    invoke,
)
from support.pytest_cli import run
from support.worktree_deploy_fixtures import seed
from task_contract_core import selected_task, status

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

FIRST = "cfn-stack-app-dev-first"
SECOND = "cfn-stack-app-dev-second"


@pytest.fixture(autouse=True)
def private_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(tmp_path))


def step(target, report, aws, action, names=()):
    with selected_task(target, "tasks/deploy.md"):
        return invoke(
            target,
            report,
            aws,
            ["--action", action, *[arg for n in names for arg in ("--sync-stack", n)]],
        )


def first_success(target, report, aws):
    for _ in range(5):
        provider = json.loads(aws.read_text(encoding="utf-8"))
        provider["knobs"]["defer_peer"] = True
        if SECOND in provider["stacks"]:
            provider["stacks"][SECOND]["status"] = "CREATE_IN_PROGRESS"
        aws.write_text(json.dumps(provider), encoding="utf-8")
        assert step(target, report, aws, "advance") == 0
        saved = json.loads(report.read_text(encoding="utf-8"))
        if saved["states"][FIRST]["status"] == "SUCCESS":
            assert saved["states"][SECOND]["status"] == "RUNNING"
            return
    raise AssertionError("first Stack never completed")


def finish_peer(aws):
    provider = json.loads(aws.read_text(encoding="utf-8"))
    provider["stacks"][SECOND]["status"] = "CREATE_COMPLETE"
    aws.write_text(json.dumps(provider), encoding="utf-8")


def interrupted_git(real, boundary, witnessed, target, *args, **kwargs):
    if boundary == "before-commit" and args[:1] == ("commit",) and not witnessed:
        witnessed.append(True)
        raise InterruptedError("injected before commit")
    result = real(target, *args, **kwargs)
    event = (boundary == "commit" and args[:1] == ("commit",)) or (
        boundary == "merge" and args[:2] == ("merge", "--ff-only")
    )
    if event and not witnessed:
        witnessed.append(True)
        raise InterruptedError("injected after " + boundary)
    return result


@pytest.mark.parametrize(
    "boundary", ["normal", "before-commit", "commit", "merge", "receipt", "delivery"]
)
def check_parallel_checkpoint_and_restart(tmp_path, monkeypatch, boundary):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(
        tmp_path / "project",
        report,
        "delivery" if boundary == "delivery" else "orders",
        same_group=True,
    )
    monkeypatch.chdir(target)
    aws_state(aws)
    primary = Path(wt.load(target, "deploy")[3]["primary"])
    base = git(primary, "rev-parse", "HEAD").strip()
    models_before = {
        p: p.read_bytes() for p in (target / "model").rglob("*.properties")
    }
    first_success(target, report, aws)
    assert all(p.read_bytes() == raw for p, raw in models_before.items())
    before_status = worktree.progress_path(target).read_bytes()
    assert step(target, report, aws, "status") == 0
    assert worktree.progress_path(target).read_bytes() == before_status
    witnessed = []
    if boundary not in {"normal", "delivery"}:
        with (
            patch.object(wt, "save", partial(interrupted_receipt, wt.save, witnessed))
            if boundary == "receipt"
            else patch.object(
                wt, "git", partial(interrupted_git, wt.git, boundary, witnessed)
            )
        ):
            assert step(target, report, aws, "sync", [FIRST]) == (
                0 if boundary == "merge" else 2
            )
        assert witnessed
    else:
        TestCase().assertEqual(step(target, report, aws, "sync", [FIRST]), 0)
    after_sync = {p: p.read_bytes() for p in models_before}
    TestCase().assertEqual(step(target, report, aws, "sync", [FIRST]), 0)
    TestCase().assertTrue(all(p.read_bytes() == raw for p, raw in after_sync.items()))
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    sha = git(primary, "rev-parse", "HEAD").strip()
    assert sha != base
    assert git(primary, "rev-list", "--count", base + "..HEAD").strip() == "2"
    assert status((target / "tasks/deploy.md").read_text(encoding="utf-8")) == "running"
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    assert git(primary, "rev-parse", "HEAD").strip() == sha
    assert (
        json.loads(aws.read_text(encoding="utf-8"))["stacks"][SECOND]["status"]
        == "CREATE_IN_PROGRESS"
    )
    finish_peer(aws)
    assert step(target, report, aws, "advance") == 0
    assert step(target, report, aws, "sync", [SECOND]) == 0
    assert step(target, report, aws, "checkpoint", [SECOND]) == 0
    assert step(target, report, aws, "status") == 0
    assert not report.with_suffix(".operations.json").exists()
    provider = json.loads(aws.read_text(encoding="utf-8"))
    assert (
        len([op for _, op, _ in provider["calls"] if op == "execute_change_set"]) == 2
    )
    assert git(primary, "rev-list", "--count", base + "..HEAD").strip() == "4"
    assert "`subnet-fixture`" in (
        primary / f"model/dev/{ACCOUNT}/ec2.properties"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["outside", "base", "failure"])
def check_checkpoint_rejects_foreign_changes_and_preserves_success(
    tmp_path, monkeypatch, bad
):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    if bad == "failure":
        contract = target / "tasks/deploy.md"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace(
                "- Runtime recovery: `allowed`", "- Runtime recovery: `forbidden`"
            ),
            encoding="utf-8",
        )
    monkeypatch.chdir(target)
    aws_state(aws)
    primary = Path(wt.load(target, "deploy")[3]["primary"])
    first_success(target, report, aws)
    assert step(target, report, aws, "sync", [FIRST]) == 0
    if bad == "outside":
        (target / "README.md").write_text("foreign change\n", encoding="utf-8")
    elif bad == "base":
        (primary / "README.md").write_text("base advance\n", encoding="utf-8")
        git(primary, "add", "README.md")
        git(primary, "commit", "-qm", "other Task")
    base = git(primary, "rev-parse", "HEAD")
    if bad == "outside":
        TestCase().assertEqual(step(target, report, aws, "checkpoint", [FIRST]), 0)
        TestCase().assertEqual(git(primary, "rev-parse", "HEAD"), base)
        TestCase().assertEqual((target / "README.md").read_text(), "foreign change\n")
        return
    if bad == "base":
        assert step(target, report, aws, "checkpoint", [FIRST]) == 0
        assert (primary / "README.md").read_text() == "base advance\n"
        finish_peer(aws)
        assert step(target, report, aws, "advance") == 0
        assert step(target, report, aws, "sync", [SECOND]) == 0
        assert step(target, report, aws, "checkpoint", [SECOND]) == 0
        return
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    sha = git(primary, "rev-parse", "HEAD")
    provider = json.loads(aws.read_text(encoding="utf-8"))
    provider["stacks"][SECOND]["status"] = "ROLLBACK_COMPLETE"
    provider["changes"][SECOND]["failed"] = True
    aws.write_text(json.dumps(provider), encoding="utf-8")
    assert step(target, report, aws, "advance") == 2
    assert git(primary, "rev-parse", "HEAD") == sha
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["states"][SECOND]["status"] == "FAILED"
    assert saved["states"][FIRST].get("checkpointed")
    TestCase().assertEqual(step(target, report, aws, "sync", [SECOND]), 0)
    saved = json.loads(report.read_text(encoding="utf-8"))
    TestCase().assertEqual(saved["deployResult"], "FAIL")
    TestCase().assertEqual(saved["states"][SECOND]["status"], "FAILED")
    TestCase().assertEqual(saved["snapshotValidation"], "PASS")
    TestCase().assertEqual(
        status((target / "tasks/deploy.md").read_text(encoding="utf-8")), "completed"
    )
    TestCase().assertIn(
        "ROLLBACK_COMPLETE",
        (primary / f"model/dev/{ACCOUNT}/cloudformation-stacks.properties").read_text(),
    )
    count = len(
        [
            entry
            for entry in json.loads(aws.read_text())["calls"]
            if entry[1] == "execute_change_set"
        ]
    )
    TestCase().assertEqual(step(target, report, aws, "checkpoint", [SECOND]), 0)
    TestCase().assertEqual(
        len(
            [
                entry
                for entry in json.loads(aws.read_text())["calls"]
                if entry[1] == "execute_change_set"
            ]
        ),
        count,
    )


def interrupted_receipt(real, witnessed, path, state):
    real(path, state)
    if (
        state.get("deployCheckpoints")
        and not state.get("stackCheckpointIntent")
        and not witnessed
    ):
        witnessed.append(True)
        raise InterruptedError("after durable receipt, before Journal acknowledgement")


def check_model_publication_interruption(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    first_success(target, report, aws)
    helper = Path(__file__).resolve().parents[1] / "support/worktree_deploy_fixtures.py"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(helper),
            str(target),
            str(report),
            str(aws),
            "--action",
            "sync",
            "--sync-stack",
            FIRST,
        ],
        cwd=target,
        env=child_environment() | {"BLUEPRINT_OBSERVED_FAULT": "model-partial"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 76, result.stdout + result.stderr
    assert json.loads(report.read_text(encoding="utf-8"))["pendingObserved"]
    assert step(target, report, aws, "sync", [FIRST]) == 0
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert len([op for _, op, _ in calls if op == "execute_change_set"]) == 2


def wait_for_peer(real, backend):
    for view, record in backend.run_context.get("pendingGeneration", {}).items():
        if view.endswith("/ec2.md"):
            record["reason"] = "REFERENCE_PENDING_DEPLOY"
            record["producers"] = [
                {
                    "stack": SECOND,
                    "producerModel": str(
                        backend.root / f"model/dev/{ACCOUNT}/ec2.properties"
                    ),
                    "logicalId": "EC2_VPC_001",
                    "templateLogicalId": "Vpc",
                    "observedSynced": False,
                }
            ]
    real(backend)


def check_generation_wait_and_resume(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    first_success(target, report, aws)
    with patch.object(
        generation_resume, "run", partial(wait_for_peer, generation_resume.run)
    ):
        TestCase().assertEqual(step(target, report, aws, "sync", [FIRST]), 2)
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["pendingGeneration"]
    assert step(target, report, aws, "checkpoint", [FIRST]) == 2
    finish_peer(aws)
    assert step(target, report, aws, "advance") == 0
    assert step(target, report, aws, "sync", [SECOND]) == 0
    assert step(target, report, aws, "checkpoint", [FIRST, SECOND]) == 0
    assert not report.with_suffix(".operations.json").exists()


def check_zero_difference_checkpoint(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, "matched", same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    primary = Path(wt.load(target, "deploy")[3]["primary"])
    base = git(primary, "rev-parse", "HEAD")
    first_success(target, report, aws)
    assert step(target, report, aws, "sync", [FIRST]) == 0
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["states"][FIRST]["observedCoverage"]["Subnet"]["status"] == "MATCHED"
    assert step(target, report, aws, "checkpoint", [FIRST]) == 0
    TestCase().assertNotEqual(git(primary, "rev-parse", "HEAD"), base)
    unchanged = git(primary, "rev-parse", "HEAD")
    TestCase().assertEqual(step(target, report, aws, "sync", [FIRST]), 0)
    TestCase().assertEqual(git(primary, "rev-parse", "HEAD"), unchanged)
    finish_peer(aws)
    assert step(target, report, aws, "advance") == 0
    assert step(target, report, aws, "sync", [SECOND]) == 0
    assert step(target, report, aws, "checkpoint", [SECOND]) == 0
    TestCase().assertNotEqual(git(primary, "rev-parse", "HEAD"), base)
    assert not report.with_suffix(".operations.json").exists()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
