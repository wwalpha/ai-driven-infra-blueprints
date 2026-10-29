#!/usr/bin/env python3
"""Reset evidence crosses processes and Tasks; the real controller owns all AWS decisions."""

import json
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import operation_journal as J
from deploy import operation_reset as R
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    clients,
    seed,
)
from support.pytest_cli import run
from task_contract_core import start
from utils.aws.client import connection_context
from utils.aws.identity import execution_account
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.delenv("BLUEPRINT_TASK_FILE", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(tmp_path))


def child(root, report, aws, task="tasks/deploy.md"):
    helper = (
        Path(__file__).resolve().parents[1] / "support/deploy_controller_fixtures.py"
    )
    environment = child_environment() | {"BLUEPRINT_TASK_FILE": task}
    return subprocess.run(
        [sys.executable, "-B", str(helper), str(root), str(report), str(aws)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )


def reset(root, journal, mode):
    before = journal.read_bytes()
    with (
        patch.object(J, "location", return_value=journal),
        patch(
            "utils.aws.client.client", side_effect=AssertionError("Reset called AWS")
        ) as aws,
    ):
        selection = [fingerprint(J.read(journal)[0])] if mode == "record" else []
        document = R.plan(root, "dev", ACCOUNT, None, mode, selection)
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.object(sys.stdout, "isatty", return_value=True),
            patch("builtins.input", return_value=R.challenge(document)),
        ):
            result = R.apply(root, "dev", ACCOUNT, None, document["id"])
        aws.assert_not_called()
    assert result["result"] == "APPLIED"
    archive = Path(result["archive"])
    assert (archive / "original.bin").read_bytes() == before
    return document


def fresh_task(root):
    name = "tasks/fresh.md"
    text = (root / "tasks/deploy.md").read_text(encoding="utf-8")
    start(root, name, text.replace("tasks/deploy.md", name))
    return name


def interrupted(tmp_path):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report)
    aws_state(aws, crash_execute=True)
    result = child(root, report, aws)
    assert result.returncode == 73, result.stdout + result.stderr
    journal = report.with_suffix(".operations.json")
    records = J.read(journal)
    original = next(iter(records[0]["operations"].values()))
    provider = json.loads(aws.read_text(encoding="utf-8"))
    assert provider["stacks"][original["unit"]["name"]]["status"] == "CREATE_COMPLETE"
    assert not original["state"].get("observedSynced")
    return root, report, aws, journal, original


def check_record_reset_then_fresh_deploy_from_new_task(tmp_path):
    root, report, aws, journal, original = interrupted(tmp_path)
    reset(root, journal, "record")
    task = fresh_task(root)
    provider = json.loads(aws.read_text(encoding="utf-8"))
    provider["knobs"]["reset_updates"] = True
    aws.write_text(json.dumps(provider), encoding="utf-8")
    result = child(root, report, aws, task)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert (
        sum(
            op == "execute_change_set"
            and args["ChangeSetName"] == original["state"]["changeSetId"]
            for _, op, args in calls
        )
        == 1
    )
    assert any(
        op == "create_change_set"
        and args["StackName"] == original["unit"]["name"]
        and args["ChangeSetType"] == "UPDATE"
        for _, op, args in calls
    )
    assert json.loads(report.read_text(encoding="utf-8"))["taskFile"] == task
    assert (
        json.loads(aws.read_text(encoding="utf-8"))["stacks"][original["unit"]["name"]][
            "status"
        ]
        == "UPDATE_COMPLETE"
    )
    first_receipts = {
        path: path.read_bytes()
        for path in journal.parent.glob("resets/*/verified-*.json")
    }
    assert first_receipts
    again = child(root, report, aws, task)
    assert again.returncode == 0, again.stdout + again.stderr
    assert all(path.read_bytes() == raw for path, raw in first_receipts.items())
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert (
        sum(
            op == "execute_change_set"
            and args["ChangeSetName"] == original["state"]["changeSetId"]
            for _, op, args in calls
        )
        == 1
    )


def check_created_stack_before_observed_is_rechecked_after_all_reset(tmp_path):
    root, report, aws, journal, original = interrupted(tmp_path)
    document = reset(root, journal, "all")
    # A separate checkout has its own Model and Task, but shares the account's evidence.
    fresh = seed(tmp_path / "fresh-project", report)
    result = child(fresh, report, aws)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    old_execute = next(
        i for i, (_, op, _) in enumerate(calls) if op == "execute_change_set"
    )
    next_create = next(
        i
        for i, (_, op, _) in enumerate(calls[old_execute + 1 :], old_execute + 1)
        if op == "create_change_set"
    )
    checked = calls[old_execute + 1 : next_create]
    assert any(op == "describe_stack_events" for _, op, _ in checked)
    assert any(op == "describe_stacks" for _, op, _ in checked)
    assert calls[next_create][2]["ChangeSetType"] == "UPDATE"
    assert all(
        state["observedSynced"]
        for state in json.loads(report.read_text(encoding="utf-8"))["states"].values()
    )
    assert (journal.parent / "resets" / document["id"] / "intent.json").exists()
    assert original["state"]["executionEvidence"]


def check_corrupt_all_reset_preserves_evidence_and_new_task_stops_safely(tmp_path):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report)
    aws_state(aws)
    journal = report.with_suffix(".operations.json")
    journal.write_bytes(b'{"untrusted": broken')
    journal.chmod(0o600)
    document = reset(root, journal, "all")
    assert document["unknownScope"]
    task = fresh_task(root)
    result = child(root, report, aws, task)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "unknown AWS execution scope" in result.stdout + result.stderr
    assert not any(
        op in {"create_change_set", "execute_change_set", "delete_stack"}
        for _, op, _ in json.loads(aws.read_text(encoding="utf-8"))["calls"]
    )


def check_reset_with_unconfirmed_execute_stops_new_execution(tmp_path):
    root, report, aws, journal, original = interrupted(tmp_path)
    provider = json.loads(aws.read_text(encoding="utf-8"))
    provider["changes"][original["unit"]["name"]]["token"] = "different-token"
    aws.write_text(json.dumps(provider), encoding="utf-8")
    reset(root, journal, "all")
    task = fresh_task(root)
    result = child(root, report, aws, task)
    assert result.returncode == 2, result.stdout + result.stderr
    assert (
        "reset fence AWS execution is unfinished or unknown"
        in result.stdout + result.stderr
    )
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert sum(op == "execute_change_set" for _, op, _ in calls) == 1
    assert sum(op == "create_change_set" for _, op, _ in calls) == 1


def resolve_fence(root, report, aws_path, journal, reset, names):
    with (
        patch.object(J, "location", return_value=journal),
        patch("utils.aws.client.client", clients(root, report, aws_path)),
        patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
    ):
        target = reset["target"]
        aws = partial(
            R.read_fence_aws,
            connection_context(None, target["awsRegion"], execution_account(target)),
        )
        document = R.resolution_plan(
            root,
            "dev",
            ACCOUNT,
            None,
            reset["id"],
            names,
            "Human investigated the listed Stacks and accepts missing-token and duplicate-execution risk for this scope",
            aws,
        )
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch.object(sys.stdout, "isatty", return_value=True),
            patch("builtins.input", return_value=R.resolution_challenge(document)),
        ):
            R.resolution_apply(root, "dev", ACCOUNT, None, document["id"], aws)
    return document


def check_corrupt_reset_human_resolution_then_fresh_process_starts(tmp_path):
    report, aws = tmp_path / "run.json", tmp_path / "aws.json"
    root = seed(tmp_path / "project", report)
    aws_state(aws)
    journal = report.with_suffix(".operations.json")
    journal.write_bytes(b"lost original Execute scope")
    journal.chmod(0o600)
    document = reset(root, journal, "all")
    archive = journal.parent / "resets" / document["id"]
    original = R.fence_inventory(archive)
    names = ["cfn-stack-app-dev-first", "cfn-stack-app-dev-second"]
    resolve_fence(root, report, aws, journal, document, names)
    assert not any(
        operation == "execute_change_set"
        for _, operation, _ in json.loads(aws.read_text(encoding="utf-8"))["calls"]
    )
    task = fresh_task(root)
    result = child(root, report, aws, task)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert sum(operation == "execute_change_set" for _, operation, _ in calls) == 2
    assert all(
        R.digest(R.read_private(archive / path)) == digest
        for path, digest in original.items()
    )
    records = [
        R.signed_document(journal, path) for path in (archive / "resolutions").iterdir()
    ]
    assert records[0]["status"] == "HUMAN_RESOLVED"
    assert not list(archive.glob("verified-*.json"))


def pending_producer(tmp_path, dependent):
    root, report, aws, journal, original = interrupted(tmp_path)
    provider = json.loads(aws.read_text(encoding="utf-8"))
    producer, consumer = original["unit"]["name"], "cfn-stack-app-dev-second"
    provider["stacks"][producer]["status"] = "CREATE_IN_PROGRESS"
    provider["knobs"].update(
        fence_exports={
            producer: [
                {"OutputKey": "Id", "OutputValue": "id", "ExportName": "ProducerId"}
            ]
        },
        fence_imports={"ProducerId": [consumer] if dependent else []},
    )
    aws.write_text(json.dumps(provider), encoding="utf-8")
    document = reset(root, journal, "all")
    # An independent repository/Task shares the account journal but owns its current inputs.
    fresh = seed(tmp_path / "fresh-project", report, same_group=True)
    task = fresh_task(fresh)
    path = fresh / task
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "- Deployment scope: `cfn-stack-app-dev-first`, `cfn-stack-app-dev-second`",
        "- Deployment scope: `cfn-stack-app-dev-second`",
    )
    path.write_text(text, encoding="utf-8")
    # The fixture CLI obtains its invocation scope from this selected contract.
    (fresh / "tasks/deploy.md").write_text(text, encoding="utf-8")
    return fresh, report, aws, journal, task, document, producer


def check_reset_pending_producer_blocks_dependent_consumer(tmp_path):
    root, report, aws, journal, task, document, producer = pending_producer(
        tmp_path, True
    )
    result = child(root, report, aws, task)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "unfinished Stack dependency conflicts" in result.stdout + result.stderr
    calls = json.loads(aws.read_text(encoding="utf-8"))["calls"]
    assert sum(operation == "execute_change_set" for _, operation, _ in calls) == 1
    assert sum(operation == "create_change_set" for _, operation, _ in calls) == 1
    assert any(operation == "list_imports" for _, operation, _ in calls)
    assert (journal.parent / "resets" / document["id"] / "original.bin").exists()


def check_reset_pending_producer_allows_proven_independent_stack(tmp_path):
    root, report, aws, journal, task, document, producer = pending_producer(
        tmp_path, False
    )
    result = child(root, report, aws, task)
    assert result.returncode == 0, result.stdout + result.stderr
    provider = json.loads(aws.read_text(encoding="utf-8"))
    assert provider["stacks"][producer]["status"] == "CREATE_IN_PROGRESS"
    assert (
        sum(operation == "execute_change_set" for _, operation, _ in provider["calls"])
        == 2
    )
    assert any(operation == "list_imports" for _, operation, _ in provider["calls"])
    # It remains PENDING; an independent success cannot approve the old Execute.
    assert not list(
        (journal.parent / "resets" / document["id"]).glob("verified-*.json")
    )


if __name__ == "__main__":
    raise SystemExit(run(__file__))
