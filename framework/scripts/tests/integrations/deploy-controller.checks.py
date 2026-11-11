#!/usr/bin/env python3
"""Six real controller flows; condition matrices live in direct unit checks."""

import hashlib
import json
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import sync_runtime
from deploy import (
    controller,
    current_state,
    failures,
    generation_resume,
    operation_journal,
    steps,
)
from deploy import progress as deploy_progress
from model.core import properties
from model.files import read_model
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    git,
    seed,
)
from support.deploy_controller_fixtures import (
    drive as invoke,
)
from support.deploy_controller_fixtures import invoke as invoke_step
from support.model_design_fixtures import collapsed_json
from support.pytest_cli import run
from support.worktree_deploy_fixtures import seed as managed_seed
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
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(tmp_path))
    for name, value in child_environment().items():
        if name.startswith("AWS_"):
            monkeypatch.setenv(name, value)


def child_run(root, session, aws, options=()):
    helper = (
        Path(__file__).resolve().parents[1] / "support/deploy_controller_fixtures.py"
    )
    environment = child_environment()
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
                and args["StackName"]
                == state.get(
                    "executionEvidence",
                    state.get("executionEvidence"),
                )["StackId"]
                for _, op, args in calls
            )
            == 1
        )


def assert_published(root, session, evidence):
    design = root / f"docs/designs/dev/{ACCOUNT}"
    saved = json.loads(session.read_text())
    assert generation_resume.complete(saved)
    assert saved["repository"] == str(root) and saved["taskFile"] == "tasks/deploy.md"
    assert all(
        state["status"] == "SUCCESS" and state["observedSynced"]
        for state in saved["states"].values()
    )
    assert {
        name: saved["states"][name].get(
            "executionEvidence",
            saved["states"][name].get("executionEvidence"),
        )
        for name in evidence
    } == evidence
    ec2 = properties(read_model(root / f"model/dev/{ACCOUNT}/ec2.properties"))
    assert ec2["observed.row.001-001.value"].strip("`") == "vpc-fixture"
    removed = any(item["Action"] == "Remove" for item in evidence[FIRST]["resources"])
    subnet = "PENDING_DEPLOY" if removed else "subnet-fixture"
    assert ec2["observed.row.002-001.value"].strip("`") == subnet
    if "desired.resource.003.cfn-logicalId" in ec2:
        assert ec2["observed.row.003-001.value"].strip("`") == "vpc-first-fixture"
    assert (
        subnet in (design / "ec2.md").read_text()
        and "vpc-fixture" in (design / "ec2.md").read_text()
    )
    assert not (design / "s3/s3-bucket-001-bucket-policy.json").exists()
    policy = collapsed_json((design / "s3.md").read_text(encoding="utf-8"))
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
    git(root, "branch", "-m", "feature/local-deploy")
    head = git(root, "rev-parse", "HEAD")
    checkouts = git(root, "worktree", "list", "--porcelain")
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
        {
            name: s.get(
                "executionEvidence", s.get("executionEvidence")
            )
            for name, s in saved["states"].items()
        },
    )

    findings = Findings(root)
    task = TaskValidation(root, findings)
    task.task_type = "infrastructure"
    assert not findings.errors and not findings.warnings
    assert invoke_step(root, session, aws, ["--action", "sync", "--final"]) == 0
    assert git(root, "rev-parse", "HEAD") == head
    assert git(root, "worktree", "list", "--porcelain") == checkouts
    assert status((root / "tasks/deploy.md").read_text()) == "completed"
    assert inventory.read_text(encoding="utf-8") == original


def check_model_publication_across_process(tmp_path):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report, "multi-observed")
    aws_state(aws)
    child = child_run(root, report, aws)
    TestCase().assertEqual(child.returncode, 0, child.stdout + child.stderr)
    saved = json.loads(report.read_text())
    assert saved["states"][FIRST]["observedSynced"]
    assert not saved.get("pendingObserved") and not saved.get("pendingGeneration")
    TestCase().assertEqual(
        sum(
            (
                op == "execute_change_set"
                and args["StackName"]
                == saved["states"][FIRST]["executionEvidence"][
                    "StackId"
                ]
                for _, op, args in json.loads(aws.read_text())["calls"]
            )
        ),
        1,
    )


def check_failure_evidence_survives_progress_reload_and_status(tmp_path):
    root = tmp_path / "project"
    stack = "stack-a"
    secret = "private-parameter-value"
    events = [
        {
            "StackId": stack,
            "ClientRequestToken": "own",
            "LogicalResourceId": "Bucket",
            "ResourceType": "AWS::S3::Bucket",
            "ResourceStatus": "CREATE_FAILED",
            "EventId": "first",
            "Timestamp": "2026-01-01T00:00:01Z",
            "ResourceStatusReason": f"{secret} (HandlerErrorCode: InvalidRequest)",
        },
        {
            "StackId": stack,
            "ClientRequestToken": "other",
            "LogicalResourceId": "Other",
            "ResourceStatus": "CREATE_FAILED",
            "EventId": "foreign",
            "Timestamp": "2026-01-01T00:00:00Z",
        },
        {
            "StackId": stack,
            "ClientRequestToken": "own",
            "LogicalResourceId": "Bucket",
            "ResourceStatus": "DELETE_FAILED",
            "EventId": "rollback",
            "Timestamp": "2026-01-01T00:00:02Z",
        },
    ]
    state = {"status": "RUNNING", "clientToken": "own"}
    runtime = SimpleNamespace(
        aws=Mock(
            side_effect=[
                {
                    "Stacks": [
                        {
                            "StackId": stack,
                            "StackStatus": "UPDATE_ROLLBACK_IN_PROGRESS",
                            "StackStatusReason": secret,
                        }
                    ]
                },
                {"StackEvents": events},
            ]
        ),
        templates={"A": ({"Resources": {"Bucket": {"Properties": {}}}}, {})},
    )
    with nullcontext():
        assert (
            controller.poll(runtime, {"name": "A"}, state)
            == "UPDATE_ROLLBACK_IN_PROGRESS"
        )
    state["changeSetFailure"] = {"code": "InvalidRequest", "message": "safe"}
    state["failureClassification"] = "HUMAN_REQUIRED"
    identity = {
        "taskFile": "tasks/deploy.md",
        "taskDigest": "digest",
        "target": {},
        "environment": "dev",
        "stacks": ["A"],
        "snapshot": "fixed",
    }
    context = {
        **{
            key: identity[key]
            for key in ("taskFile", "taskDigest", "target", "environment")
        },
        "repository": str(root),
        "states": {"A": state},
        "consumedInputs": {},
        "inputDigests": {},
        "stepUnits": [{"name": "A"}],
    }
    backend = SimpleNamespace(
        root=root,
        phase="deploy",
        run_context=context,
        progress_identity=identity,
        progress_task_file=identity["taskFile"],
        progress_root=root.resolve(),
        progress_directory=None,
        progress_destination=deploy_progress.progress_path(root, identity["taskFile"], create=True),
    )
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    loaded = deploy_progress.read_progress(root, {"deployIdentity": identity})["runContext"]
    saved = loaded["states"]["A"]
    report = steps.describe(
        SimpleNamespace(states=loaded["states"], run_context=loaded)
    )
    diagnostic = report["states"]["A"]["diagnostic"]
    assert diagnostic["eventId"] == "first" and diagnostic["code"] == "InvalidRequest"
    assert report["deployResult"] != "FAIL"
    assert saved["changeSetFailure"]["code"] == "InvalidRequest"
    assert saved["currentStack"]["statusReason"]["reasonRedacted"]
    assert report["states"]["A"]["progress"]["available"]
    assert report["states"]["A"]["progress"]["phase"] == "ROLLBACK"
    assert secret not in json.dumps(loaded) + json.dumps(report)
    assert "foreign" not in json.dumps(saved["failureEvents"])
    runtime = SimpleNamespace(root=root, guard=lambda: None, save=lambda: None)
    with patch.object(controller.repair_ops, "require_authorized"):
        assert not controller.repair(runtime, {"name": "A"}, saved)
    backend.run_context = loaded
    deploy_progress.save_progress(backend, operation_journal.OPERATION_FIELDS)
    restored = deploy_progress.read_progress(root, {"deployIdentity": identity})["runContext"]
    diagnostic = steps.describe(
        SimpleNamespace(states=restored["states"], run_context=restored)
    )["states"]["A"]["diagnostic"]
    assert diagnostic["classification"] == "HUMAN_REQUIRED"
    assert diagnostic["code"] == "InvalidRequest"
    assert diagnostic["primaryFailure"]["eventId"] == "first"
    assert diagnostic["primaryFailure"]["resource"]["LogicalResourceId"] == "Bucket"
    assert diagnostic["recoveryFailure"]["code"] == "RECOVERY_BLOCKED"
    assert "unsafe rollback state" in diagnostic["recoveryFailure"]["message"]
    assert "eventId" not in diagnostic["recoveryFailure"]
    assert diagnostic["eventId"] == "first"
    assert diagnostic["requiredAction"]
    assert secret not in json.dumps(diagnostic)
    current_state.record_attempt(saved, "ATTEMPT_SUCCESS")
    assert failures.diagnostic(saved) is None


def check_event_read_failure_keeps_running_operation_unconfirmed():
    state = {"status": "RUNNING", "clientToken": "own"}
    runtime = SimpleNamespace(
        aws=Mock(
            side_effect=[
                {"Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_IN_PROGRESS"}]},
                OSError("private-secret"),
            ]
        ),
        templates={},
    )
    with nullcontext():
        assert controller.poll(runtime, {"name": "A"}, state) == "UPDATE_IN_PROGRESS"
    report = steps.describe(
        SimpleNamespace(states={"A": state}, run_context={"states": {"A": state}})
    )
    assert report["states"]["A"]["diagnostic"]["code"] == "EVENT_READ_FAILED"
    assert not report["states"]["A"]["progress"]["available"]
    assert report["deployResult"] == "PENDING"
    assert "private-secret" not in json.dumps(report) + json.dumps(state)




def check_advance_and_status_expose_observed_progress(tmp_path, monkeypatch, capsys):
    report, aws = tmp_path / "report.json", tmp_path / "aws.json"
    root = managed_seed(tmp_path / "project", report, "orders", same_group=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", f"tasks/{root.name}.md")
    aws_state(aws)
    capsys.readouterr()
    assert invoke_step(root, report, aws, ["--action", "advance"]) == 0
    capsys.readouterr()
    provider = json.loads(aws.read_text())
    provider["stacks"][FIRST]["status"] = "CREATE_IN_PROGRESS"
    provider["knobs"]["resource_events"] = {
        FIRST: [
            {
                "LogicalResourceId": FIRST,
                "ResourceType": "AWS::CloudFormation::Stack",
                "ResourceStatus": "CREATE_IN_PROGRESS",
                "EventId": "root-start",
                "Timestamp": "2026-01-01T00:00:00Z",
            },
            {
                "LogicalResourceId": "ObservedResource",
                "ResourceType": "AWS::S3::Bucket",
                "ResourceStatus": "CREATE_IN_PROGRESS",
                "EventId": "event-1",
                "Timestamp": "2026-01-01T00:00:01Z",
            },
        ]
    }
    aws.write_text(json.dumps(provider))
    assert invoke_step(root, report, aws, ["--action", "advance"]) == 0
    advanced = json.loads(capsys.readouterr().out)
    assert advanced["result"] == "PENDING"
    progress = advanced["states"][FIRST]["progress"]
    assert progress["available"] and progress["observedResources"] == 1
    assert progress["activeResources"][0]["logicalId"] == "ObservedResource"
    provider = json.loads(aws.read_text())
    provider["knobs"]["resource_events"][FIRST].append(
        {
            "LogicalResourceId": "ObservedResource",
            "ResourceType": "AWS::S3::Bucket",
            "ResourceStatus": "CREATE_COMPLETE",
            "EventId": "event-2",
            "Timestamp": "2026-01-01T00:00:02Z",
        }
    )
    provider["knobs"]["resource_events"][FIRST].append(
        {
            "LogicalResourceId": "ForeignResource",
            "ResourceType": "AWS::S3::Bucket",
            "ResourceStatus": "CREATE_IN_PROGRESS",
            "ClientRequestToken": "different-attempt",
            "EventId": "foreign-event",
            "Timestamp": "2026-01-01T00:00:03Z",
        }
    )
    before_calls = len(provider["calls"])
    aws.write_text(json.dumps(provider))
    assert invoke_step(root, report, aws, ["--action", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    progress = status["states"][FIRST]["progress"]
    assert progress["observedResources"] == 1 and progress["completed"] == 1
    assert progress["resources"][0]["resourceStatus"] == "CREATE_COMPLETE"
    assert not progress["stale"]
    calls = json.loads(aws.read_text())["calls"][before_calls:]
    assert (
        sum(
            op == "describe_stack_events" and args.get("StackName", "").endswith(FIRST)
            for _, op, args in calls
        )
        <= 1
    )
    assert all(op.startswith(("describe_", "list_", "get_")) for _, op, _ in calls)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
