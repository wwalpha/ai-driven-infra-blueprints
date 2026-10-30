#!/usr/bin/env python3
"""Six real controller flows; condition matrices live in direct unit checks."""

import hashlib
import json
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import sync_runtime
from deploy import (
    contracts,
    controller,
    current_request,
    generation_resume,
    operation_journal,
    steps,
    worktree,
)
from model.core import properties
from model.files import read_model
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    ordinary_base,
    recover_owned_lock,
    seed,
    unresolved_requests,
)
from support.deploy_controller_fixtures import (
    drive as invoke,
)
from support.pytest_cli import run
from task_contract import complete
from task_contract_core import selected_task, status
from validation.findings import Findings
from validation.task import TaskValidation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

FIRST = "cfn-stack-app-dev-first"
SECOND = "cfn-stack-app-dev-second"
THIRD = "cfn-stack-app-dev-third"


@pytest.fixture(autouse=True)
def offline_workflow(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    monkeypatch.setattr(contracts, "task_start_commit", ordinary_base)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(tmp_path))
    for name, value in child_environment().items():
        if name.startswith("AWS_"):
            monkeypatch.setenv(name, value)


def child_run(root, session, aws, options=(), fault=None):
    helper = (
        Path(__file__).resolve().parents[1] / "support/deploy_controller_fixtures.py"
    )
    environment = child_environment()
    if fault:
        environment["BLUEPRINT_OBSERVED_FAULT"] = fault
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(helper),
            str(root),
            str(session),
            str(aws),
            *options,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )


def assert_single_execution(aws, states):
    calls = json.loads(aws.read_text())["calls"]
    for name, state in states.items():
        assert (
            sum(
                op == "create_change_set" and args["StackName"] == name
                for _, op, args in calls
            )
            == 1
        )
        assert (
            sum(
                op == "execute_change_set"
                and args["StackName"] == state["executionEvidence"]["StackId"]
                for _, op, args in calls
            )
            == 1
        )


def assert_published(root, session, evidence):
    saved = json.loads(session.read_text())
    assert generation_resume.complete(saved)
    TestCase().assertFalse(unresolved_requests(session, saved["states"]))
    assert saved["repository"] == str(root) and saved["taskFile"] == "tasks/deploy.md"
    assert all(
        state["status"] == "SUCCESS" and state["observedSynced"]
        for state in saved["states"].values()
    )
    assert {
        name: saved["states"][name]["executionEvidence"] for name in evidence
    } == evidence
    ec2 = properties(read_model(root / f"model/dev/{ACCOUNT}/ec2.properties"))
    assert ec2["observed.row.001-001.value"].strip("`") == "vpc-fixture"
    removed = any(item["Action"] == "Remove" for item in evidence[FIRST]["resources"])
    subnet = "PENDING_DEPLOY" if removed else "subnet-fixture"
    assert ec2["observed.row.002-001.value"].strip("`") == subnet
    if "desired.resource.003.cfn-logicalId" in ec2:
        assert ec2["observed.row.003-001.value"].strip("`") == "vpc-first-fixture"
    design = root / f"docs/designs/dev/{ACCOUNT}"
    assert (
        subnet in (design / "ec2.md").read_text()
        and "vpc-fixture" in (design / "ec2.md").read_text()
    )
    policy = json.loads((design / "s3/s3-bucket-001-bucket-policy.json").read_text())
    s3 = properties(read_model(root / f"model/dev/{ACCOUNT}/s3.properties"))
    assert policy == json.loads(s3["desired.row.001-003.document"])
    if THIRD in saved["states"]:
        assert "app-dev-third" in (design / "s3.md").read_text()
        assert s3["desired.row.003-001.value"].strip("`") == "app-dev-third"
    with selected_task(root, "tasks/deploy.md"):
        assert all(
            (
                hashlib.sha256((root / path).read_bytes()).hexdigest()
                if (root / path).is_file()
                else None
            )
            == digest
            for path, digest in saved["modelInputs"].items()
        )
        # Verify every final generated byte against the final combined Model, not an older peer plan.
        assert (
            sync_runtime.sync(
                root,
                False,
                "dev",
                ACCOUNT,
                services=["s3", "ec2", "cloudformation-stacks"],
            )
            == 0
        )


def check_ordered_delivery_and_observed(tmp_path, monkeypatch):
    session, aws = tmp_path / "session.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", session, "ordered-delivery")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    inventory = root / f"issues/dev/{ACCOUNT}/issues.md"
    inventory.parent.mkdir(parents=True)
    original = "### ec2\n1. ERROR: Framework diagnostic\n### Unknown owner\n2. CRITICAL: unresolved\n"
    inventory.write_text(original, encoding="utf-8")
    subprocess.run(["git", "add", str(inventory)], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "Existing issue report"], cwd=root, check=True
    )
    aws_state(aws, delivery=True)
    assert invoke(root, session, aws) == 0
    assert inventory.read_text(encoding="utf-8") == original
    saved, provider = json.loads(session.read_text()), json.loads(aws.read_text())
    calls = provider["calls"]
    first_create = next(
        i for i, (_, op, _) in enumerate(calls) if op == "create_change_set"
    )
    expected = {
        (obj["bucket"], obj["key"])
        for name in (FIRST,)
        for obj in saved["states"][name]["delivery"]["objects"]
    }
    puts = [
        (args["Bucket"], args["Key"])
        for _, op, args in calls[:first_create]
        if op == "put_object"
    ]
    assert set(puts) == expected and len(puts) == len(expected)
    barrier = provider["barriers"][THIRD]
    assert set(barrier["earlier"]) == {FIRST, SECOND}
    TestCase().assertTrue(
        all(s["status"] == "SUCCESS" for s in barrier["states"].values())
    )
    assert_single_execution(aws, saved["states"])
    assert_published(
        root,
        session,
        {name: s["executionEvidence"] for name, s in saved["states"].items()},
    )

    findings = Findings(root)
    task = TaskValidation(root, findings)
    task.task_type = "infrastructure"
    assert not findings.errors and not findings.warnings
    with patch.object(worktree, "require", return_value={}):
        complete(root, "tasks/deploy.md")
    assert status((root / "tasks/deploy.md").read_text()) == "completed"
    assert inventory.read_text(encoding="utf-8") == original


def check_delivery_failure_stops_execution(tmp_path, monkeypatch):
    session, aws = tmp_path / "session.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", session, "delivery")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    aws_state(aws, delivery=True, delivery_fail=True)
    assert invoke(root, session, aws) == 2
    calls = json.loads(aws.read_text())["calls"]
    assert any(op == "put_object" for _, op, _ in calls)
    assert not any(
        op in {"create_change_set", "execute_change_set"} for _, op, _ in calls
    )
    saved = json.loads(session.read_text())
    assert any(
        s.get("failure", {}).get("code") == "AccessDenied"
        for s in saved["states"].values()
    )


def fake_aws(operation, **kwargs):
    if operation == "describe_stacks":
        return {
            "Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_ROLLBACK_COMPLETE"}]
        }
    if operation == "describe_change_set":
        return {
            "StackId": "stack",
            "ChangeSetId": "change",
            "ExecutionStatus": "EXECUTE_FAILED",
        }
    if operation == "describe_stack_events":
        return {"StackEvents": []}
    raise AssertionError(operation)


def check_approved_remove_recovers_without_duplicate_execute(tmp_path, monkeypatch):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "remove")
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", "tasks/deploy.md")
    aws_state(aws, remove=True, crash_execute=True)
    assert invoke(root, report, aws) == 2
    blocked = json.loads(report.read_text())["states"][FIRST]
    assert blocked["status"] == "BLOCKED" and "executionEvidence" not in blocked
    change_id = blocked["changeSetId"]
    child = child_run(root, report, aws, ["--approve-change-set", change_id])
    assert child.returncode == 73, child.stdout + child.stderr
    interrupted = json.loads(report.read_text())
    evidence = interrupted["states"][FIRST]["executionEvidence"]
    recover_owned_lock(root, child)
    recovered = child_run(root, report, aws, ["--recover-operations"])
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    saved = json.loads(report.read_text())
    assert saved["states"][FIRST]["observedSynced"]
    assert saved["states"][FIRST]["executionEvidence"] == evidence
    assert "approvedChangeDigest" not in saved["states"][FIRST]
    TestCase().assertFalse(unresolved_requests(report, saved["states"]))
    calls = json.loads(aws.read_text())["calls"]
    assert (
        sum(
            op == "execute_change_set"
            and args["StackName"]
            == saved["states"][FIRST]["executionEvidence"]["StackId"]
            for _, op, args in calls
        )
        == 1
    )
    values = properties(read_model(root / f"model/dev/{ACCOUNT}/ec2.properties"))
    assert values["observed.row.002-001.value"] == "`PENDING_DEPLOY`"

    # Save real Task progress before release, then resume after an interrupted release.
    local = tmp_path / "settlement"
    local.mkdir(mode=0o700)
    request = local / "request.json"
    record = {
        "operation": "execute_change_set",
        "name": "A",
        "stackId": "stack",
        "changeSetId": "change",
        "token": "original",
        "submission": "SENDING",
    }
    request.write_text(json.dumps(record), encoding="utf-8")
    request.chmod(0o600)
    state = {
        "status": "RUNNING",
        "clientToken": "original",
        "changeSetId": "change",
        "executionEvidence": {
            "StackId": "stack",
            "ChangeSetId": "change",
            "clientToken": "original",
        },
    }
    identity = {
        "taskFile": "tasks/deploy.md",
        "taskDigest": "digest",
        "target": {},
        "environment": "dev",
        "stacks": ["A"],
    }
    context = {
        **identity,
        "repository": str(local),
        "directory": "team",
        "states": {"A": state},
        "inputDigests": {},
        "stepUnits": [{"name": "A"}],
    }

    backend = SimpleNamespace(
        root=local,
        phase="deploy",
        target={},
        environment="dev",
        templates={},
        states=context["states"],
        units=context["stepUnits"],
        run_context=context,
        progress_identity=identity,
        progress_root=local.resolve(),
        progress_directory="team",
        progress_destination=worktree.progress_path(local, create=True),
        aws=fake_aws,
    )
    backend.save = partial(
        worktree.save_progress, backend, operation_journal.OPERATION_FIELDS
    )
    backend.poll = partial(controller.poll, backend)
    with patch.object(current_request, "location", return_value=request):
        with patch.object(
            current_request, "release", side_effect=RuntimeError("interrupted")
        ):
            with pytest.raises(RuntimeError, match="interrupted"):
                steps.refresh_requests(backend)
        saved = worktree.read_progress(local, {"deployIdentity": identity})
        assert saved["states"]["A"]["status"] == "SETTLED" and request.exists()
        assert saved["states"]["A"]["attemptResult"] == "UNKNOWN"
        backend.states = saved["states"]
        backend.run_context["states"] = backend.states
        steps.refresh_requests(backend)
        assert not request.exists()
        assert (
            worktree.read_progress(local, {"deployIdentity": identity})["states"]["A"][
                "status"
            ]
            == "SETTLED"
        )


def check_pending_observed_recovers_before_model_load(tmp_path):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "multi-observed")
    aws_state(aws)
    child = child_run(root, report, aws, fault="model-partial")
    assert child.returncode == 76, child.stdout + child.stderr
    interrupted = json.loads(report.read_text())
    plan = interrupted["pendingObserved"]
    assert plan["stage"] == "PREPARED" and len(plan["outputs"]) >= 2
    evidence = interrupted["states"][FIRST]["executionEvidence"]
    recover_owned_lock(root, child)
    recovered = child_run(root, report, aws, ["--recover-operations"])
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    saved = json.loads(report.read_text())
    assert saved["states"][FIRST]["observedSynced"]
    assert saved["states"][FIRST]["executionEvidence"] == evidence
    assert not saved.get("pendingObserved") and not saved.get("pendingGeneration")
    TestCase().assertFalse(unresolved_requests(report, saved["states"]))
    assert (
        sum(
            op == "execute_change_set" and args["StackName"] == evidence["StackId"]
            for _, op, args in json.loads(aws.read_text())["calls"]
        )
        == 1
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
