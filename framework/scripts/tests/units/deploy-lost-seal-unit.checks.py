"""Lost-key exceptions preserve original archives and release only reviewed future scope."""

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from deploy import lost_seal as L
from deploy import operation_journal as J
from deploy import operation_reset as R
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TARGET = dict(
    awsAccountId="123456789012",
    awsRegion="ap-northeast-1",
    iacEngine="cloudformation",
    alias="app",
)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir(mode=0o700)
    (root / "project.json").write_text(
        json.dumps(dict(projectName="demo", targets=[dict(TARGET, environment="dev")]))
    )
    journal = tmp_path / "operations" / "journal.json"
    archive = journal.parent / "resets" / ("a" * 64)
    archive.mkdir(parents=True, mode=0o700)
    (archive.parent).chmod(0o700)
    journal.parent.chmod(0o700)
    evidence = archive / "intent.json"
    evidence.write_text('{"unverified":"preserve bytes"}')
    evidence.chmod(0o600)
    monkeypatch.setattr(J, "location", lambda target: journal)

    def aws(operation, **kwargs):
        assert operation == "describe_stacks"
        name = kwargs["StackName"]
        return dict(
            Stacks=[
                dict(
                    StackName=name,
                    StackId=f"arn:aws:cloudformation:ap-northeast-1:123456789012:stack/{name}/id",
                    StackStatus="UPDATE_COMPLETE",
                )
            ]
        )

    args = SimpleNamespace(
        action="lost-key-plan",
        environment="dev",
        aws_account_id=None,
        alias="app",
        stack=["IAM", "Network"],
        risk="Human accepts unverifiable prior scope and dependency/duplicate-execution risk",
        plan=None,
    )
    backend = SimpleNamespace(
        root=root, environment="dev", target=TARGET, reset_pending=["old"]
    )
    return root, journal, evidence, aws, args, backend


def approve(case):
    root, journal, evidence, aws, args, backend = case
    value = L.run(args, root, aws)
    apply = copy.copy(args)
    apply.action, apply.stack, apply.risk, apply.plan = (
        "lost-key-apply",
        [],
        None,
        value["id"],
    )
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch("builtins.input", return_value=L.challenge(value)),
    ):
        result = L.run(apply, root, aws)
    return value, result


def test_apply_preserves_bytes_and_scopes_real_fence_check(case):
    root, journal, evidence, aws, args, backend = case
    original = evidence.read_bytes()
    with pytest.raises(ValueError):
        R.check_fences(journal, TARGET, ["IAM"], backend)
    value, result = approve(case)
    assert result["status"] == "HUMAN_ACCEPTED_LOST_KEY"
    assert evidence.read_bytes() == original and not journal.exists()
    R.check_fences(journal, TARGET, ["IAM", "Network"], backend)
    assert backend.reset_pending == []
    for scope in (["Other"], ["IAM", "Other"]):
        with pytest.raises(ValueError):
            R.check_fences(journal, TARGET, scope, backend)
    assert "VERIFIED_COMPLETE" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    ["archives", "configuration", "repository", "environment", "target", "receipt"],
)
def test_changed_or_foreign_evidence_never_releases(case, change):
    root, journal, evidence, aws, args, backend = case
    value, _ = approve(case)
    if change == "archives":
        evidence.write_text("changed")
    elif change == "configuration":
        (root / "project.json").write_text("changed")
    elif change == "repository":
        backend.root = root.parent
    elif change == "environment":
        backend.environment = "stg"
    elif change == "target":
        backend.target = dict(TARGET, alias="other")
    else:
        path = journal.parent / "lost-key-approvals" / (value["id"] + ".json")
        item = json.loads(path.read_text())
        item["payload"]["plan"]["stacks"].append("Other")
        path.write_text(json.dumps(item))
    try:
        allowed = L.approved(journal, backend, ["IAM"])
    except (ValueError, OSError, Blocked):
        allowed = False
    assert not allowed


@pytest.mark.parametrize(
    "status", ["UPDATE_IN_PROGRESS", "UNKNOWN", "ROLLBACK_COMPLETE"]
)
def test_unknown_running_failed_aws_blocks_plan(case, status):
    root, _, _, aws, args, _ = case

    def changed(operation, **kwargs):
        response = aws(operation, **kwargs)
        response["Stacks"][0]["StackStatus"] = status
        return response

    with pytest.raises(Blocked, match="absent or successful"):
        L.run(args, root, changed)


def test_active_journal_blocks_and_confirmation_cannot_be_automated(case):
    root, journal, _, aws, args, _ = case
    journal.write_text("pending")
    journal.chmod(0o600)
    with pytest.raises(Blocked, match="active operation journal"):
        L.run(args, root, aws)
    journal.unlink()
    value = L.run(args, root, aws)
    with (
        patch.object(sys.stdin, "isatty", return_value=False),
        pytest.raises(Blocked, match="human-operated"),
    ):
        L.confirm(value)
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch("builtins.input", return_value="yes"),
        pytest.raises(Blocked, match="does not match"),
    ):
        L.confirm(value)


def test_archive_change_during_consent_stops_apply(case):
    root, journal, evidence, aws, args, _ = case
    value = L.run(args, root, aws)
    args.action, args.plan, args.stack, args.risk = (
        "lost-key-apply",
        value["id"],
        [],
        None,
    )

    def consent(value):
        evidence.write_text("changed during consent")
        return dict(method="interactive-console", challenge=L.challenge(value))

    with (
        patch.object(L, "confirm", side_effect=consent),
        pytest.raises(Blocked, match="changed during"),
    ):
        L.run(args, root, aws)
    assert not (journal.parent / "lost-key-approvals").exists()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
