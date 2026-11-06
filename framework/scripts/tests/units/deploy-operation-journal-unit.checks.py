"""Current input contexts and private request lock safety, without Journal replay."""

import copy
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import change_sets, controller, run_context, scheduler
from deploy import operation_journal as J
from deploy.controller import create_runtime
from support.pytest_cli import run
from utils.aws.client import AwsError
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
    recorded = Mock(return_value={})
    monkeypatch.setattr(controller.change_sets, "record_execution", recorded)
    monkeypatch.setattr(controller.current_state, "read", Mock(return_value={"StackStatus": status, "StackId": STACK}))
    with pytest.raises(Blocked):
        controller.execute(backend, {"name": "Kms"}, state)
    backend.aws.assert_not_called()
    assert state["status"] == "BLOCKED"
    assert "executionEvidence" not in state
    recorded.assert_not_called()
    backend.save.assert_not_called()

def test_stack_read_error_reports_aws_code(tmp_path, monkeypatch):
    monkeypatch.setattr(change_sets, "read", Mock(return_value={"StackStatus": "UNKNOWN", "errorCode": "AccessDenied"}))
    with pytest.raises(Blocked, match="AccessDenied"):
        change_sets.begin_prepare(
            {"name": "Kms"}, {}, Mock(), Mock(), Mock(), Mock(return_value={}),
            Mock(), Mock(), Mock(), Mock(),
        )


def test_stack_change_before_create_allows_next_advance(tmp_path, monkeypatch):
    parameters = tmp_path / "parameters.json"
    parameters.write_text("[]", encoding="utf-8")
    stable = {"StackStatus": "UPDATE_COMPLETE", "StackId": STACK}
    busy = {"StackStatus": "UPDATE_IN_PROGRESS", "StackId": STACK}
    monkeypatch.setattr(change_sets, "read", Mock(side_effect=[stable, busy, stable, stable]))
    aws = Mock(side_effect=[{}, {}, {"Id": "new-change", "StackId": STACK}])
    state = {"status": "NOT_STARTED"}
    saved = []
    save = Mock(side_effect=lambda: saved.append(copy.deepcopy(state)))
    begin = partial(
        change_sets.begin_prepare, aws=aws, save=save, check_imports=Mock(),
        template_arguments=Mock(return_value={"TemplateBody": "Resources: {}"}),
        cleanup_failed_create=Mock(), reset_after_cleanup=Mock(),
        verify_stack_ownership=Mock(),
        paths=Mock(return_value=(tmp_path / "template.yaml", parameters)),
    )
    backend = SimpleNamespace(
        prepare=Mock(), begin_prepare=begin, poll=Mock(), describe_change_set=Mock(return_value={}),
        review_prepared=Mock(return_value="CHANGESET_CREATING"),
    )
    unit = {"name": "Kms", "deployOrder": 1}
    assert scheduler.run_group([unit], 1, {"Kms": state}, backend, save) == "STOPPED"
    assert state["status"] == "BLOCKED"
    assert "changeSetId" not in state
    assert all("changeSetId" not in snapshot for snapshot in saved)
    assert [call.args[0] for call in aws.call_args_list] == ["validate_template"]
    assert scheduler.run_group([unit], 1, {"Kms": state}, backend, save) == "ACTIVE"
    assert state["changeSetId"] == "new-change"
    assert sum(call.args[0] == "create_change_set" for call in aws.call_args_list) == 1
    assert any(snapshot.get("changeSetId", "").startswith("blueprint-") for snapshot in saved)


def test_stack_read_failure_before_create_retains_no_intent(tmp_path, monkeypatch):
    parameters = tmp_path / "parameters.json"
    parameters.write_text("[]", encoding="utf-8")
    stable = {"StackStatus": "UPDATE_COMPLETE", "StackId": STACK}
    unknown = {"StackStatus": "UNKNOWN", "errorCode": "AccessDenied"}
    monkeypatch.setattr(change_sets, "read", Mock(side_effect=[stable, unknown]))
    aws = Mock(return_value={})
    state, saved = {}, []
    save = Mock(side_effect=lambda: saved.append(copy.deepcopy(state)))
    with pytest.raises(Blocked, match="AccessDenied"):
        change_sets.begin_prepare(
            {"name": "Kms"}, state, aws, save, Mock(), Mock(return_value={}),
            Mock(), Mock(), Mock(), Mock(return_value=(tmp_path / "template.yaml", parameters)),
        )
    assert "changeSetId" not in state
    assert all("changeSetId" not in snapshot for snapshot in saved)
    assert [call.args[0] for call in aws.call_args_list] == ["validate_template"]


def test_create_timeout_keeps_submission_intent_without_resending(tmp_path, monkeypatch):
    parameters = tmp_path / "parameters.json"
    parameters.write_text("[]", encoding="utf-8")
    stable = {"StackStatus": "UPDATE_COMPLETE", "StackId": STACK}
    monkeypatch.setattr(change_sets, "read", Mock(return_value=stable))
    aws = Mock(side_effect=[{}, AwsError("cloudformation", "create_change_set", "ReadTimeoutError")])
    state, saved = {}, []
    save = Mock(side_effect=lambda: saved.append(copy.deepcopy(state)))
    args = (
        {"name": "Kms"}, state, aws, save, Mock(), Mock(return_value={}),
        Mock(), Mock(), Mock(), Mock(return_value=(tmp_path / "template.yaml", parameters)),
    )
    with pytest.raises(AwsError, match="ReadTimeoutError"):
        change_sets.begin_prepare(*args)
    assert state["changeSetId"].startswith("blueprint-")
    assert saved[-1]["changeSetId"] == state["changeSetId"]
    assert saved[-1]["preparationId"] == state["preparationId"]
    assert change_sets.begin_prepare(*args) == "CHANGESET_CREATING"
    assert sum(call.args[0] == "create_change_set" for call in aws.call_args_list) == 1


def test_execution_rejects_changed_stack_identity_without_evidence(monkeypatch):
    state = {"operationType": "UPDATE", "stackId": STACK, "status": "RUNNING"}
    backend = SimpleNamespace(
        expected_digests={}, load_inputs=Mock(), observed_readiness=Mock(),
        input_digest=Mock(return_value="digest"), file_digest=Mock(),
        template_arguments=Mock(), check_imports=Mock(), describe_change_set=Mock(),
        templates={"Kms": ({}, {})}, aws=Mock(), save=Mock(),
    )
    monkeypatch.setattr(controller.change_sets, "verify_execution", Mock(return_value={}))
    monkeypatch.setattr(controller.change_sets, "change_summary", Mock(return_value=[]))
    recorded = Mock(return_value={})
    monkeypatch.setattr(controller.change_sets, "record_execution", recorded)
    monkeypatch.setattr(controller.current_state, "read", Mock(return_value={"StackStatus": "UPDATE_COMPLETE", "StackId": STACK + "-other"}))
    with pytest.raises(Blocked, match="identity changed"):
        controller.execute(backend, {"name": "Kms"}, state)
    backend.aws.assert_not_called()
    backend.save.assert_not_called()
    recorded.assert_not_called()
    assert "executionEvidence" not in state


def test_execute_saves_evidence_before_aws_submission(monkeypatch):
    state = {
        "operationType": "UPDATE", "stackId": STACK, "status": "RUNNING",
        "changeSetId": CHANGE, "clientToken": "current-token",
    }
    saved, sent = [], []
    backend = SimpleNamespace(
        expected_digests={}, load_inputs=Mock(), observed_readiness=Mock(),
        input_digest=Mock(return_value="digest"), file_digest=Mock(),
        template_arguments=Mock(), check_imports=Mock(), describe_change_set=Mock(),
        templates={"Kms": ({}, {})},
        save=Mock(side_effect=lambda: saved.append(copy.deepcopy(state))),
        aws=Mock(side_effect=lambda *args, **kwargs: sent.append(copy.deepcopy(state)) or {}),
    )
    evidence = {"StackId": STACK, "ChangeSetId": CHANGE, "clientToken": "current-token"}
    monkeypatch.setattr(controller.change_sets, "verify_execution", Mock(return_value={}))
    monkeypatch.setattr(controller.change_sets, "change_summary", Mock(return_value=[]))
    monkeypatch.setattr(controller.change_sets, "record_execution", Mock(return_value=evidence))
    monkeypatch.setattr(controller.current_state, "read", Mock(return_value={"StackStatus": "UPDATE_COMPLETE", "StackId": STACK}))
    controller.execute(backend, {"name": "Kms"}, state)
    assert saved[0]["executionEvidence"] == evidence
    assert sent[0]["executionEvidence"] == evidence
    assert saved[0]["clientToken"] == sent[0]["clientToken"] == "current-token"
    backend.aws.assert_called_once_with(
        "execute_change_set", StackName=STACK, ChangeSetName=CHANGE,
        ClientRequestToken="current-token",
    )
