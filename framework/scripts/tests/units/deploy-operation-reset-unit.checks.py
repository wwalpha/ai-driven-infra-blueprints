"""Human console consent, exact snapshots, preserved peers and reset evidence."""

import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import operation_journal as J
from deploy import operation_reset as R
from deploy import temporary
from deploy.controller import create_runtime
from support.pytest_cli import run
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TARGET = {
    "awsAccountId": "123456789012",
    "awsRegion": "ap-northeast-1",
    "iacEngine": "cloudformation",
}


def record(root, name="One", task="tasks/old.md"):
    return {
        "target": dict(TARGET),
        "operations": {
            name: {
                "unit": {"name": name},
                "inputDigest": "inputs",
                "state": {"status": "BLOCKED", "changeSetId": "prepared-" + name},
            }
        },
        "publication": {
            "target": dict(TARGET),
            "repository": str(root),
            "taskFile": task,
            "taskDigest": "task",
        },
    }


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps({"targets": [{"environment": "dev", **TARGET}]}),
        encoding="utf-8",
    )
    directory = tmp_path / "journal"
    directory.mkdir(mode=0o700)
    journal = directory / "journal.json"
    J.write_records(journal, [record(root)])
    with patch.object(J, "location", return_value=journal):
        yield root, journal


def plan(root, mode="all", records=()):
    return R.plan(root, "dev", TARGET["awsAccountId"], None, mode, records)


def human_apply(root, document):
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch("builtins.input", return_value=R.challenge(document)),
    ):
        return R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])


def test_apply_requires_human_console(workspace):
    root, journal = workspace
    document = plan(root)
    before = journal.read_bytes()
    with (
        patch.object(sys.stdin, "isatty", return_value=False),
        pytest.raises(Blocked, match="human-operated"),
    ):
        R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])
    assert journal.read_bytes() == before


def test_plan_is_read_only_and_changed_snapshot_rejects_apply(workspace):
    root, journal = workspace
    before = journal.read_bytes()
    document = plan(root)
    assert journal.read_bytes() == before
    J.write_records(journal, [record(root, "Changed")])
    changed = journal.read_bytes()
    with pytest.raises(Blocked, match="snapshot changed"):
        human_apply(root, document)
    assert journal.read_bytes() == changed


def test_record_reset_preserves_other_task_and_shared_publication(workspace):
    root, journal = workspace
    first = record(root)
    first["operations"].update(record(root, "Shared")["operations"])
    first["publication"]["pendingObserved"] = {"stage": "PREPARED"}
    other = record(root, "Other", "tasks/other.md")
    J.write_records(journal, [copy.deepcopy(first), copy.deepcopy(other)])
    document = plan(root, "record", [fingerprint(first)])
    assert set(document["records"][0]["stacks"]) == {"One", "Shared"}
    human_apply(root, document)
    assert J.read(journal) == [other]
    archive = journal.parent / "resets" / document["id"]
    assert (archive / "original.bin").read_bytes()
    assert (archive / "intent.json").is_file()


@pytest.mark.parametrize("corruption", ["json", "signature"])
def test_corrupt_journal_all_only_preserves_complete_original(workspace, corruption):
    root, journal = workspace
    if corruption == "json":
        journal.write_bytes(b"{broken-json\xff")
    else:
        text = json.loads(journal.read_text(encoding="utf-8"))
        text["signature"] = "0" * 64
        journal.write_text(json.dumps(text), encoding="utf-8")
    before = journal.read_bytes()
    with pytest.raises(Blocked, match="RECORD"):
        plan(root, "record", ["0" * 64])
    document = plan(root)
    assert document["unknownScope"]
    human_apply(root, document)
    assert not journal.exists()
    archive = journal.parent / "resets" / document["id"]
    assert (archive / "original.bin").read_bytes() == before
    with pytest.raises(Blocked, match="unknown.*Human"):
        R.check_fences(journal, TARGET, ["One"], Mock())


def test_wrong_confirmation_and_cli_bypass_options_are_rejected(workspace):
    root, journal = workspace
    document = plan(root)
    before = journal.read_bytes()
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch("builtins.input", return_value="yes"),
        pytest.raises(Blocked, match="approval does not match"),
    ):
        R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])
    for option in ("--yes", "--force", "--human-approved"):
        with pytest.raises(SystemExit) as failure:
            R.main(
                [
                    "apply",
                    "--environment",
                    "dev",
                    "--aws-account-id",
                    TARGET["awsAccountId"],
                    "--plan",
                    document["id"],
                    option,
                ]
            )
        assert failure.value.code == 2
    assert journal.read_bytes() == before


def test_record_cannot_select_only_one_stack_in_a_shared_record(workspace):
    root, journal = workspace
    first = record(root)
    first["operations"].update(record(root, "Shared")["operations"])
    first["publication"]["pendingGeneration"] = {"service": {"producers": []}}
    J.write_records(journal, [first])
    before = journal.read_bytes()
    with pytest.raises(Blocked, match="not in this journal"):
        plan(root, "record", [fingerprint(record(root))])
    assert journal.read_bytes() == before


def test_peer_from_another_repository_is_preserved(workspace, tmp_path):
    root, journal = workspace
    other_root = tmp_path / "other-repository"
    other_root.mkdir()
    first, other = record(root), record(other_root, "Other", "tasks/other.md")
    J.write_records(journal, [copy.deepcopy(first), copy.deepcopy(other)])
    human_apply(root, plan(root, "record", [fingerprint(first)]))
    assert J.read(journal) == [other]


def test_lock_contention_keeps_original(workspace):
    root, journal = workspace
    document = plan(root)
    before = journal.read_bytes()
    with J.locked(journal), pytest.raises(Blocked, match="lock busy"):
        human_apply(root, document)
    assert journal.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "owner", "relative-path"])
def test_unsafe_identity_and_paths_are_rejected(workspace, tmp_path, kind):
    root, journal = workspace
    before = journal.read_bytes()
    if kind in {"symlink", "hardlink"}:
        original = journal.with_name("source.json")
        journal.rename(original)
        if kind == "symlink":
            journal.symlink_to(original)
        else:
            os.link(original, journal)
        with pytest.raises(Blocked, match="redirected|private and owned"):
            plan(root)
        assert original.read_bytes() == before
    elif kind == "owner":
        with (
            patch.object(os, "getuid", return_value=os.getuid() + 1),
            pytest.raises(Blocked, match="owned"),
        ):
            plan(root)
        assert journal.read_bytes() == before
    else:
        with (
            patch.object(J, "location", return_value=Path("relative/journal.json")),
            pytest.raises(Blocked, match="absolute"),
        ):
            plan(root)
        assert journal.read_bytes() == before


def test_changed_target_and_tampered_plan_cannot_apply(workspace):
    root, journal = workspace
    document = plan(root)
    project = root / "project.json"
    before = project.read_bytes()
    project.write_bytes(before + b"\n")
    with pytest.raises(Blocked, match="configuration changed"):
        human_apply(root, document)
    project.write_bytes(before)
    path = journal.parent / "reset-plans" / (document["id"] + ".json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"]["unknownScope"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="modified"):
        human_apply(root, document)
    assert journal.exists()


class FailSave:
    def __init__(self, original, filename):
        self.original, self.filename = original, filename

    def __call__(self, path, content):
        if path.name == self.filename:
            raise OSError("simulated persistence failure")
        return self.original(path, content)


@pytest.mark.parametrize("filename", ["original.bin", "intent.json"])
def test_backup_or_audit_failure_never_changes_journal(workspace, filename):
    root, journal = workspace
    document = plan(root)
    before = journal.read_bytes()
    with (
        patch.object(R, "save_once", side_effect=FailSave(R.save_once, filename)),
        pytest.raises(OSError, match="persistence"),
    ):
        human_apply(root, document)
    assert journal.read_bytes() == before
    R.check_fences(journal, TARGET, ["One"], Mock())
    human_apply(root, document)
    assert not journal.exists()
    assert (
        journal.parent / "resets" / document["id"] / "original.bin"
    ).read_bytes() == before


def test_crash_after_reset_is_idempotently_reconciled_without_losing_evidence(
    workspace,
):
    root, journal = workspace
    document = plan(root)
    before = journal.read_bytes()
    with (
        patch.object(R, "save_once", side_effect=FailSave(R.save_once, "result.json")),
        pytest.raises(OSError, match="persistence"),
    ):
        human_apply(root, document)
    assert not journal.exists()
    archive = journal.parent / "resets" / document["id"]
    original = (archive / "original.bin").read_bytes()
    intent = (archive / "intent.json").read_bytes()
    assert original == before
    assert human_apply(root, document)["result"] == "ALREADY_APPLIED"
    assert (archive / "original.bin").read_bytes() == original
    assert (archive / "intent.json").read_bytes() == intent
    assert (archive / "result.json").is_file()
    J.write_records(journal, [record(root, "NewTask", "tasks/new.md")])
    new = journal.read_bytes()
    with pytest.raises(Blocked, match="snapshot changed"):
        human_apply(root, document)
    assert journal.read_bytes() == new


def test_templates_are_archived_and_survive_normal_reclamation(workspace):
    root, journal = workspace
    task = SimpleNamespace(name="tasks/old.md", task_digest="task")
    folder = temporary.create(journal, root, task, TARGET, ["One"])
    template = folder / "One.json"
    template.write_text('{"Resources":{}}', encoding="utf-8")
    template.chmod(0o600)
    document = plan(root)
    human_apply(root, document)
    temporary.reclaim(journal, root, TARGET)
    assert template.exists()
    archived = (
        journal.parent
        / "resets"
        / document["id"]
        / "templates"
        / folder.name
        / template.name
    )
    assert archived.read_bytes() == template.read_bytes()


def test_template_changes_after_plan_stop_apply(workspace):
    root, journal = workspace
    folder = journal.parent / "inputs-one"
    folder.mkdir(mode=0o700)
    template = folder / "One.json"
    template.write_bytes(b"original")
    template.chmod(0o600)
    document = plan(root)
    template.write_bytes(b"changed")
    before = journal.read_bytes()
    with pytest.raises(Blocked, match="template snapshot changed"):
        human_apply(root, document)
    assert journal.read_bytes() == before


class ChangeDuringApproval:
    def __init__(self, root, journal, document):
        self.root, self.journal, self.document = root, journal, document

    def __call__(self, prompt):
        J.write_records(self.journal, [record(self.root, "Concurrent")])
        return R.challenge(self.document)


def test_approval_does_not_hide_concurrent_changes(workspace):
    root, journal = workspace
    document = plan(root)
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch(
            "builtins.input", side_effect=ChangeDuringApproval(root, journal, document)
        ),
        pytest.raises(Blocked, match="during Human approval"),
    ):
        R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])
    assert set(J.read(journal)[0]["operations"]) == {"Concurrent"}


def test_reset_never_calls_aws(workspace):
    root, _ = workspace
    with patch(
        "utils.aws.client.client",
        side_effect=AssertionError("Reset must not call AWS"),
    ) as aws:
        human_apply(root, plan(root))
    aws.assert_not_called()


def executed_record(root):
    value = record(root)
    state = value["operations"]["One"]["state"]
    state.update(
        status="RUNNING",
        stackId="arn:aws:cloudformation:ap-northeast-1:123456789012:stack/One/id",
        changeSetId="arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/old/id",
        clientToken="original-token",
        changeDigest="changes",
    )
    state["executionEvidence"] = {
        "StackId": state["stackId"],
        "ChangeSetId": state["changeSetId"],
        "clientToken": state["clientToken"],
        "changeDigest": state["changeDigest"],
        "inputDigest": "inputs",
    }
    return value


class FenceAws:
    def __init__(self, state, condition):
        self.state, self.condition, self.calls = state, condition, []

    def __call__(self, operation, **arguments):
        self.calls.append(operation)
        if self.condition == "unreadable":
            raise AwsError("cloudformation", operation, "AccessDenied")
        status = (
            "CREATE_IN_PROGRESS" if self.condition == "running" else "CREATE_COMPLETE"
        )
        if operation == "describe_stack_events":
            return {
                "StackEvents": []
                if self.condition == "unknown"
                else [
                    {
                        "StackId": self.state["stackId"],
                        "ResourceType": "AWS::CloudFormation::Stack",
                        "ClientRequestToken": self.state["clientToken"],
                        "ResourceStatus": status,
                    }
                ]
            }
        if operation == "describe_change_set":
            return {
                "StackId": self.state["stackId"],
                "ChangeSetId": self.state["changeSetId"],
            }
        if operation == "describe_stacks":
            return {
                "Stacks": [{"StackId": self.state["stackId"], "StackStatus": status}]
            }
        raise AssertionError("Fence must never write AWS: " + operation)


@pytest.mark.parametrize("condition", ["success", "running", "unknown", "unreadable"])
def test_fence_uses_actual_original_token_polling(workspace, condition):
    root, journal = workspace
    original = executed_record(root)
    J.write_records(journal, [original])
    document = plan(root)
    human_apply(root, document)
    backend = create_runtime(root, "dev", TARGET["awsAccountId"], TARGET)
    backend.aws = FenceAws(original["operations"]["One"]["state"], condition)
    if condition == "success":
        R.check_fences(journal, TARGET, ["One"], backend)
    else:
        with pytest.raises(Blocked):
            R.check_fences(journal, TARGET, ["One"], backend)
    assert backend.aws.calls
    assert (journal.parent / "resets" / document["id"]).exists()


@pytest.mark.parametrize(
    "malformation", ["target", "publication", "operation", "shared"]
)
def test_signed_structural_damage_still_all_resets(workspace, malformation):
    root, journal = workspace
    value = record(root)
    if malformation == "target":
        value["target"]["awsRegion"] = "another-region"
    elif malformation == "publication":
        value["publication"].pop("taskFile")
    elif malformation == "operation":
        value["operations"]["One"]["unit"]["name"] = "Wrong"
    else:
        value["publication"]["pendingGeneration"] = {"broken": {"generated": 1}}
    J.write_records(journal, [value])
    before = journal.read_bytes()
    document = plan(root)
    assert document["unknownScope"] and not document["removedRecords"]
    human_apply(root, document)
    assert (
        journal.parent / "resets" / document["id"] / "original.bin"
    ).read_bytes() == before


class FailJournalReplace:
    def __init__(self, original, journal):
        self.original, self.journal = original, journal

    def __call__(self, path, content, **options):
        if path == self.journal:
            raise OSError("simulated journal replacement failure")
        return self.original(path, content, **options)


def test_atomic_replacement_failure_retains_original_and_retry_evidence(workspace):
    root, journal = workspace
    first, other = record(root), record(root, "Other", "tasks/other.md")
    J.write_records(journal, [copy.deepcopy(first), copy.deepcopy(other)])
    before = journal.read_bytes()
    document = plan(root, "record", [fingerprint(first)])
    with (
        patch.object(
            R,
            "atomic_replace_file",
            side_effect=FailJournalReplace(R.atomic_replace_file, journal),
        ),
        pytest.raises(OSError, match="replacement failure"),
    ):
        human_apply(root, document)
    assert journal.read_bytes() == before
    archive = journal.parent / "resets" / document["id"]
    assert (archive / "original.bin").read_bytes() == before
    assert human_apply(root, document)["result"] == "APPLIED"
    assert J.read(journal) == [other]


def test_unsafe_archive_and_record_ids_cannot_redirect_apply(workspace):
    root, journal = workspace
    document = plan(root)
    before = journal.read_bytes()
    with pytest.raises(Blocked, match="fingerprint"):
        R.apply(root, "dev", TARGET["awsAccountId"], None, "../journal")
    destination = journal.parent / "resets"
    destination.symlink_to(root, target_is_directory=True)
    with pytest.raises(Blocked, match="redirected"):
        human_apply(root, document)
    assert journal.read_bytes() == before


class FailActivation:
    def __init__(self, original, destination):
        self.original, self.destination = original, destination

    def __call__(self, source, destination):
        if destination == self.destination:
            raise OSError("simulated activation failure")
        return self.original(source, destination)


def test_staged_backup_without_activation_does_not_install_a_fence(workspace):
    root, journal = workspace
    document = plan(root)
    original = R.os.replace
    before = journal.read_bytes()
    with (
        patch.object(
            R.os,
            "replace",
            side_effect=FailActivation(
                original, journal.parent / "resets" / document["id"]
            ),
        ),
        pytest.raises(OSError, match="activation failure"),
    ):
        human_apply(root, document)
    assert journal.read_bytes() == before
    staging = journal.parent / "reset-staging" / document["id"]
    assert (staging / "original.bin").read_bytes() == before
    R.check_fences(journal, TARGET, ["One"], Mock())
    human_apply(root, document)
    assert not staging.exists()
    assert (
        journal.parent / "resets" / document["id"] / "original.bin"
    ).read_bytes() == before


if __name__ == "__main__":
    raise SystemExit(run(__file__))
