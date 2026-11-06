"""Real scoped publication and normal Worktree checkpoint while a peer is running."""

import json
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import worktree_task as wt
from deploy import progress as deploy_progress
from deploy import steps
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
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


def step(target, report, aws, action, names=(), final=False):
    with selected_task(target, f"tasks/{target.name}.md"):
        return invoke(
            target,
            report,
            aws,
            [
                "--action",
                action,
                *[arg for n in names for arg in ("--sync-stack", n)],
                *(["--final"] if final else []),
            ],
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


def check_parallel_checkpoint_and_restart(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    primary = Path(wt.load(target, target.name)[3]["primary"])
    base = git(primary, "rev-parse", "HEAD").strip()
    task_head = git(target, "rev-parse", "HEAD").strip()
    models_before = {
        p: p.read_bytes() for p in (target / "model").rglob("*.properties")
    }
    first_success(target, report, aws)
    assert all(p.read_bytes() == raw for p, raw in models_before.items())
    before_status = deploy_progress.progress_path(target, f"tasks/{target.name}.md").read_bytes()
    assert step(target, report, aws, "status") == 0
    assert deploy_progress.progress_path(target, f"tasks/{target.name}.md").read_bytes() == before_status
    with patch.object(steps.completion, "validate_local", side_effect=ValueError("interrupted validation")):
        assert step(target, report, aws, "sync", [FIRST]) != 0
    calls_before = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert step(target, report, aws, "checkpoint") == 0
    resumed_calls = json.loads(aws.read_text(encoding="utf-8"))["calls"][len(calls_before):]
    assert not any(op in {"create_change_set", "execute_change_set"} for _, op, _ in resumed_calls)
    assert not json.loads(report.read_text(encoding="utf-8")).get("syncPending")
    after_sync = {p: p.read_bytes() for p in models_before}
    TestCase().assertEqual(step(target, report, aws, "sync", [FIRST]), 0)
    TestCase().assertTrue(all(p.read_bytes() == raw for p, raw in after_sync.items()))
    sha = git(primary, "rev-parse", "HEAD").strip()
    assert sha == base
    assert git(primary, "rev-list", "--count", base + "..HEAD").strip() == "0"
    assert status((target / f"tasks/{target.name}.md").read_text(encoding="utf-8")) == "running"
    assert git(primary, "rev-parse", "HEAD").strip() == sha
    assert (
        json.loads(aws.read_text(encoding="utf-8"))["stacks"][SECOND]["status"]
        == "CREATE_IN_PROGRESS"
    )
    finish_peer(aws)
    assert step(target, report, aws, "advance") == 0
    assert step(target, report, aws, "sync", [SECOND]) == 0
    assert step(target, report, aws, "status") == 0
    assert not report.with_suffix(".operations.json").exists()
    provider = json.loads(aws.read_text(encoding="utf-8"))
    executions = [
        args["StackName"]
        for _, op, args in provider["calls"]
        if op == "execute_change_set"
    ]
    assert sorted(executions) == sorted(
        provider["stacks"][name]["id"] for name in (FIRST, SECOND)
    )
    assert git(primary, "rev-list", "--count", base + "..HEAD").strip() == "0"
    assert git(target, "rev-parse", "HEAD").strip() == task_head
    assert step(target, report, aws, "sync", final=True) == 0
    assert git(target, "rev-parse", "HEAD").strip() == task_head
    assert (
        status((target / f"tasks/{target.name}.md").read_text(encoding="utf-8")) == "completed"
    )
    assert "`subnet-fixture`" in (
        target / f"model/dev/{ACCOUNT}/ec2.properties"
    ).read_text(encoding="utf-8")
    task_id = target.name
    assert task_id.startswith("deploy-") and len(task_id.rsplit("-", 1)[1]) == 6
    monkeypatch.chdir(primary)
    result = wt.finalize(primary, task_id)
    assert result["merged"] and result["cleaned"]
    assert not target.exists()
    assert git(primary, "rev-parse", "HEAD").strip() != base
    assert "`subnet-fixture`" in (primary / f"model/dev/{ACCOUNT}/ec2.properties").read_text(encoding="utf-8")


def check_combined_checkpoint_after_peer_completion(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    target = seed(tmp_path / "project", report, same_group=True)
    monkeypatch.chdir(target)
    aws_state(aws)
    first_success(target, report, aws)
    finish_peer(aws)
    TestCase().assertEqual(step(target, report, aws, "advance"), 0)
    TestCase().assertEqual(step(target, report, aws, "sync", [FIRST, SECOND]), 0)
    saved = json.loads(report.read_text(encoding="utf-8"))
    TestCase().assertTrue(
        all(saved["states"][name]["status"] == "SUCCESS" for name in (FIRST, SECOND))
    )
    assert not report.with_suffix(".operations.json").exists()




if __name__ == "__main__":
    raise SystemExit(run(__file__))
