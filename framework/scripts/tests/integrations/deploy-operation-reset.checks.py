#!/usr/bin/env python3
"""Reset evidence crosses processes and Tasks; the real controller owns all AWS decisions."""

import json
import subprocess
import sys
import tempfile
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
    seed,
)
from support.pytest_cli import run
from task_contract_core import start
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


if __name__ == "__main__":
    raise SystemExit(run(__file__))
