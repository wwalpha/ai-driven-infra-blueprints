"""Current input contexts and private request lock safety, without Journal replay."""

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import change_sets, controller, run_context
from deploy import operation_journal as J
from deploy.controller import create_runtime
from support.pytest_cli import run
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TARGET = {
    "awsAccountId": "123456789012",
    "awsRegion": "ap-northeast-1",
    "iacEngine": "cloudformation",
}

STACK = "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/Kms/original"
CHANGE = "arn:aws:cloudformation:ap-northeast-1:123456789012:changeSet/original/id"


def backend_for(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    unit = {
        "name": "Kms",
        "template": "kms.yaml",
        "parameters": "kms.json",
        "deployOrder": 10,
    }
    task = SimpleNamespace(
        name="tasks/deploy.md",
        task_digest="task",
        text="## Modified files\n- `tasks/deploy.md`\n",
    )
    backend = create_runtime(root, "dev", TARGET["awsAccountId"], TARGET)
    context = run_context.new_context(
        root, task, TARGET, "dev", TARGET["awsAccountId"], [], backend
    )
    context["states"] = {
        "Kms": {
            "status": "RUNNING",
            "stackId": STACK,
            "clientToken": "original",
            "changeSetId": CHANGE,
            "changeDigest": "changes",
            "executionEvidence": {
                "clientToken": "original",
                "StackId": STACK,
                "ChangeSetId": CHANGE,
                "changeDigest": "changes",
                "inputDigest": "input",
            },
        }
    }
    context["inputDigests"] = {"Kms": "input"}
    context["modelInputs"] = {}
    backend.run_context, backend.states, backend.units = (
        context,
        context["states"],
        [unit],
    )
    backend.aws = Mock(side_effect=AssertionError("unexpected AWS read"))
    backend.load_inputs = Mock()
    backend.poll = Mock(return_value="UPDATE_COMPLETE")
    backend.execute = Mock(side_effect=AssertionError("recovery must never Execute"))
    backend.guard = Mock()
    backend.describe_change_set = Mock(
        return_value={
            "StackId": STACK,
            "ChangeSetId": CHANGE,
            "ExecutionStatus": "AVAILABLE",
        }
    )
    return backend, task, unit, tmp_path / "journal.json"


def test_new_context_accepts_latest_iac_and_ignores_old_files(tmp_path):
    backend, task, unit, _ = backend_for(tmp_path)
    old = backend.root / "old-session.json"
    old.write_text(
        json.dumps(
            {
                "version": 5,
                "workflow": {"reserved": 20},
                "consumedInputs": {"kms.yaml": "old"},
            }
        )
    )
    registry = backend.root / "deploy-workflows"
    registry.mkdir()
    (registry / "old.json").write_text("unfinished old workflow")
    original = run_context.new_context(
        backend.root, task, TARGET, "dev", "account", [], backend
    )
    original["states"] = {"Kms": {"status": "FAILED", "reason": "old uncertain request"}}
    current = run_context.new_context(
        backend.root, task, TARGET, "dev", "account", [], backend
    )
    assert not current["states"] and not current["inputDigests"]
    assert "workflow" not in current and old.exists()


def test_successful_stack_latest_iac_is_claimed_for_new_update(tmp_path):
    backend, task, unit, _ = backend_for(tmp_path)
    backend.phase = "update"
    template, parameters = backend.paths(unit)
    template.parent.mkdir(parents=True)
    parameters.parent.mkdir(parents=True)
    template.write_text("Resources: {}")
    parameters.write_text("[]")
    previous = run_context.new_context(
        backend.root, task, TARGET, "dev", "account", [unit], backend
    )
    run_context._callback_claim_inputs(
        backend.root, previous, backend, lambda: None, unit
    )
    previous["states"]["Kms"]["status"] = "SUCCESS"
    template.write_text("Resources: {}\nOutputs: {KeyId: {Value: latest}}")
    current = run_context.new_context(
        backend.root, task, TARGET, "dev", "account", [unit], backend
    )
    run_context._callback_claim_inputs(
        backend.root, current, backend, lambda: None, unit
    )
    assert current["inputDigests"]["Kms"] != previous["inputDigests"]["Kms"]
    assert current["states"]["Kms"]["status"] == "NOT_STARTED"
    aws = Mock(
        side_effect=[
            {"Stacks": [{"StackId": STACK, "StackStatus": "UPDATE_COMPLETE"}]},
            {},
            {"Stacks": [{"StackId": STACK, "StackStatus": "UPDATE_COMPLETE"}]},
            {"Id": "new-change", "StackId": STACK},
        ]
    )
    current_state = current["states"]["Kms"]
    change_sets.begin_prepare(
        unit,
        current_state,
        aws,
        Mock(),
        Mock(),
        Mock(return_value={"TemplateBody": template.read_text()}),
        Mock(),
        Mock(),
        Mock(),
        backend.paths,
    )
    assert aws.call_args.kwargs["ChangeSetType"] == "UPDATE"
    assert current_state["changeSetId"] == "new-change"


@pytest.mark.parametrize("unsafe", ["symlink", "permissions", "hardlink"])
def test_lock_rejects_unsafe_files_without_unlinking(tmp_path, unsafe):
    path = tmp_path / "journal.json"
    lock = path.with_suffix(".lock")
    target = tmp_path / "original"
    target.write_text("keep")
    target.chmod(0o600)
    if unsafe == "symlink":
        lock.symlink_to(target)
    elif unsafe == "hardlink":
        lock.hardlink_to(target)
    else:
        lock.write_text("existing")
        lock.chmod(0o666)
    with pytest.raises(Blocked):
        with J.locked(path):
            raise AssertionError("unsafe lock acquired")
    assert target.read_text() == "keep" and lock.exists()


def test_existing_readable_lock_is_reused_without_unlink(tmp_path):
    path = tmp_path / "journal.json"
    lock = path.with_suffix(".lock")
    lock.write_text("")
    lock.chmod(0o644)
    inode = lock.stat().st_ino
    with J.locked(path):
        pass
    assert lock.stat().st_ino == inode


def test_approval_diagnostics_clear_after_same_changeset_is_approved():
    state = {"status": "CHANGESET_CREATING", "changeSetId": CHANGE, "stackId": STACK}
    change = {
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "ChangeSetId": CHANGE,
        "StackId": STACK,
        "Changes": [
            {
                "ResourceChange": {
                    "LogicalResourceId": "Key",
                    "ResourceType": "AWS::KMS::Key",
                    "Action": "Remove",
                }
            }
        ],
    }
    unit = {"name": "Kms"}
    assert (
        change_sets.review_prepared(unit, state, set(), Mock(), Mock(), change)
        == "BLOCKED"
    )
    assert (
        state["failure"]["requiredAction"]
        and state["changes"][0]["LogicalResourceId"] == "Key"
    )
    assert (
        change_sets.review_prepared(unit, state, {CHANGE}, Mock(), Mock(), change)
        == "READY"
    )
    assert "failure" not in state and "failureClassification" not in state


def test_no_change_still_checks_all_four_kms_exports(tmp_path):
    backend, _, unit, _ = backend_for(tmp_path)
    document = {
        "Outputs": {
            f"KeyId{i}": {"Value": f"key-{i}", "Export": {"Name": f"KeyId{i}"}}
            for i in range(4)
        }
    }
    expected = change_sets.required_outputs(document, {}, TARGET, "Kms")
    state = {
        "status": "CHANGESET_CREATING",
        "operationType": "UPDATE",
        "absentBeforeCreate": False,
        "stackId": STACK,
        "changeSetId": CHANGE,
        "expectedOutputs": expected,
    }
    change = {
        "Status": "FAILED",
        "ExecutionStatus": "UNAVAILABLE",
        "StatusReason": "No updates are to be performed",
        "StackName": "Kms",
        "StackId": STACK,
        "ChangeSetId": CHANGE,
        "Changes": [],
    }
    backend.aws = Mock(
        return_value={"Stacks": [{"StackId": STACK, "StackStatus": "UPDATE_COMPLETE"}]}
    )
    assert (
        change_sets.review_prepared(unit, state, set(), backend.aws, Mock(), change)
        == "SUCCESS"
    )
    backend.aws.side_effect = [
        {
            "Stacks": [
                {"StackId": STACK, "StackStatus": "UPDATE_COMPLETE", "Outputs": []}
            ]
        },
        {"TemplateBody": {"Outputs": {}}},
        {"Exports": []},
    ]
    with pytest.raises(Blocked):
        change_sets.verify_outputs(backend.aws, unit, state, expected)
    backend.execute.assert_not_called()


def test_kms_four_exports_update_and_no_change_require_aws_facts(tmp_path):
    backend, _, unit, _ = backend_for(tmp_path)
    document = {
        "Outputs": {
            f"KeyId{i}": {"Value": f"key-{i}", "Export": {"Name": f"KeyId{i}"}}
            for i in range(4)
        }
    }
    expected = change_sets.required_outputs(document, {}, TARGET, unit["name"])
    stack = {
        "StackId": STACK,
        "StackStatus": "UPDATE_COMPLETE",
        "Outputs": [
            {"OutputKey": k, "ExportName": k, "OutputValue": f"key-{i}"}
            for i, k in enumerate(expected)
        ],
    }
    exports = [
        {
            "Name": o["ExportName"],
            "Value": o["OutputValue"],
            "ExportingStackId": STACK,
        }
        for o in stack["Outputs"]
    ]
    aws = Mock(
        side_effect=[
            {"Stacks": [stack]},
            {"TemplateBody": document},
            {"Exports": exports},
        ]
    )
    change_sets.verify_outputs(aws, unit, {"stackId": STACK}, expected)
    assert len(expected) == 4 and [call.args[0] for call in aws.call_args_list] == [
        "describe_stacks",
        "get_template",
    ]
    for missing in ("output", "export", "owner", "value", "definition"):
        deployed = copy.deepcopy(document)
        actual, values = copy.deepcopy(stack), copy.deepcopy(exports)
        if missing == "output":
            actual["Outputs"].pop()
        elif missing == "export":
            actual["Outputs"][-1].pop("ExportName")
        elif missing == "owner":
            actual["StackId"] = STACK + "-replacement"
        elif missing == "definition":
            deployed["Outputs"]["KeyId3"]["Value"] = "old-key"
        else:
            actual["Outputs"][-1]["OutputValue"] = "other"
        aws.side_effect = [
            {"Stacks": [actual]},
            {"TemplateBody": deployed},
            {"Exports": values},
        ]
        with pytest.raises(Blocked):
            change_sets.verify_outputs(aws, unit, {"stackId": STACK}, expected)


if __name__ == "__main__":
    raise SystemExit(run(__file__))

@pytest.mark.parametrize(
    ("status", "expected"),
    [("ABSENT", "CREATE"), ("UPDATE_COMPLETE", "UPDATE"), ("UPDATE_ROLLBACK_COMPLETE", "UPDATE")],
)
def test_new_changeset_uses_current_stack_state(tmp_path, monkeypatch, status, expected):
    parameters = tmp_path / "parameters.json"
    parameters.write_text("[]", encoding="utf-8")
    stack = {"StackStatus": status, **({"StackId": STACK} if status != "ABSENT" else {})}
    monkeypatch.setattr(change_sets, "read", Mock(return_value=stack))
    aws = Mock(side_effect=[{}, {"Id": "fresh", "StackId": STACK}])
    state = {}
    result = change_sets.begin_prepare(
        {"name": "Kms"}, state, aws, Mock(), Mock(),
        Mock(return_value={"TemplateBody": "Resources: {}"}), Mock(), Mock(), Mock(),
        Mock(return_value=(tmp_path / "template.yaml", parameters)),
    )
    assert result == "CHANGESET_CREATING"
    assert aws.call_args.kwargs["ChangeSetType"] == expected


@pytest.mark.parametrize("status", ["CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UNKNOWN"])
def test_new_changeset_never_starts_on_active_or_unknown_stack(tmp_path, monkeypatch, status):
    stack = {"StackStatus": status, "StackId": STACK}
    monkeypatch.setattr(change_sets, "read", Mock(return_value=stack))
    aws = Mock()
    with pytest.raises(Blocked):
        change_sets.begin_prepare(
            {"name": "Kms"}, {}, aws, Mock(), Mock(), Mock(return_value={}),
            Mock(), Mock(), Mock(), Mock(),
        )
    aws.assert_not_called()

@pytest.mark.parametrize("status", ["CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS", "UNKNOWN"])
def test_execution_rechecks_stack_and_rejects_active_or_unknown(monkeypatch, status):
    state = {"operationType": "UPDATE", "stackId": STACK, "status": "RUNNING"}
    backend = SimpleNamespace(
        expected_digests={}, load_inputs=Mock(), observed_readiness=Mock(),
        input_digest=Mock(return_value="digest"), file_digest=Mock(),
        template_arguments=Mock(), check_imports=Mock(), describe_change_set=Mock(),
        templates={"Kms": ({}, {})}, aws=Mock(), save=Mock(),
    )
    monkeypatch.setattr(controller.change_sets, "verify_execution", Mock(return_value={}))
    monkeypatch.setattr(controller.change_sets, "change_summary", Mock(return_value=[]))
    monkeypatch.setattr(controller.change_sets, "record_execution", Mock(return_value={}))
    monkeypatch.setattr(controller.current_state, "read", Mock(return_value={"StackStatus": status, "StackId": STACK}))
    with pytest.raises(Blocked):
        controller.execute(backend, {"name": "Kms"}, state)
    backend.aws.assert_not_called()
    assert state["status"] == "BLOCKED"

@pytest.mark.parametrize("previous", ['{"status":"REQUEST_UNCONFIRMED"}', "{broken"])
def test_old_request_does_not_affect_new_task(tmp_path, monkeypatch, previous):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    backend, task, unit, _ = backend_for(tmp_path)
    old_dir = tmp_path / ("blueprint-cfn-current-v3-" + J.fingerprint([TARGET["awsAccountId"], TARGET["awsRegion"]]))
    old_dir.mkdir()
    old = old_dir / ("request-" + J.fingerprint(unit["name"]) + ".json")
    old.write_text(previous, encoding="utf-8")
    for path in backend.paths(unit):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    context = run_context.new_context(backend.root, task, TARGET, "dev", "account", [unit], backend)
    assert context["states"][unit["name"]]["status"] == "NOT_STARTED"
    assert J.location(backend.root, task.name).parent != old_dir
    assert old.read_text(encoding="utf-8") == previous


def test_stack_read_error_reports_aws_code(tmp_path, monkeypatch):
    monkeypatch.setattr(change_sets, "read", Mock(return_value={"StackStatus": "UNKNOWN", "errorCode": "AccessDenied"}))
    with pytest.raises(Blocked, match="AccessDenied"):
        change_sets.begin_prepare(
            {"name": "Kms"}, {}, Mock(), Mock(), Mock(), Mock(return_value={}),
            Mock(), Mock(), Mock(), Mock(),
        )
