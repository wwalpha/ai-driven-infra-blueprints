"""Independent runs, minimal durable operations, exact current approval and AWS Output facts."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import change_sets, run_context
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


def backend_for(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    unit = {
        "name": "Kms",
        "template": "kms.yaml",
        "parameters": "kms.json",
        "deployOrder": 10,
    }
    task = SimpleNamespace(name="tasks/deploy.md", task_digest="task")
    backend = create_runtime(root, "dev", TARGET["awsAccountId"], TARGET)
    context = run_context.new_context(
        root, task, TARGET, "dev", TARGET["awsAccountId"], [], backend
    )
    context["states"] = {
        "Kms": {
            "status": "RUNNING",
            "stackId": "stack",
            "clientToken": "original",
            "changeSetId": "change",
            "executionEvidence": {"clientToken": "original"},
        }
    }
    context["inputDigests"] = {"Kms": "input"}
    context["modelInputs"] = {}
    backend.run_context, backend.states, backend.units = (
        context,
        context["states"],
        [unit],
    )
    backend.load_inputs = Mock()
    backend.poll = Mock(return_value="UPDATE_COMPLETE")
    backend.execute = Mock(side_effect=AssertionError("recovery must never Execute"))
    backend.guard = Mock()
    backend.describe_change_set = Mock(
        return_value={
            "StackId": "stack",
            "ChangeSetId": "change",
            "ExecutionStatus": "AVAILABLE",
        }
    )
    return backend, task, unit, tmp_path / "journal.json"


def finish_sync(backend):
    for state in backend.states.values():
        if state["status"] == "SUCCESS":
            state["observedSynced"] = True


def test_journal_excludes_history_and_approval_and_discards_success(tmp_path):
    backend, _, _, path = backend_for(tmp_path)
    backend.run_context.update(
        workflow={"attempts": ["past"]},
        failureArchive=["past"],
        approvedChangeDigest="past",
    )
    backend.states["Kms"].update(
        approvedChangeDigest="current", repairs=["past"], failureArchive=["past"]
    )
    J.save(path, backend)
    record = J.read(path)
    assert "original" == record["operations"]["Kms"]["state"]["clientToken"]
    text = path.read_text()
    assert not any(
        key in text
        for key in (
            "workflow",
            "attempts",
            "approvedChangeDigest",
            "repairs",
            "failureArchive",
        )
    )
    backend.states["Kms"].update(status="SUCCESS", observedSynced=True)
    J.save(path, backend)
    assert not path.exists()


def test_running_restart_observes_original_token_without_execute(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    J.save(path, backend)
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
        patch.object(J, "from_run_sync", side_effect=finish_sync),
    ):
        J.recover(backend, path, task, ["Kms"])
    assert backend.poll.call_args.args[1]["clientToken"] == "original"
    backend.execute.assert_not_called()
    assert not path.exists()


def test_uncertain_operation_is_retained_without_new_token(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    J.save(path, backend)
    backend.poll.side_effect = Blocked("AWS read unavailable")
    with pytest.raises(Blocked, match="unavailable"):
        J.recover(backend, path, task, ["Kms"])
    assert J.read(path)["operations"]["Kms"]["state"]["clientToken"] == "original"
    backend.execute.assert_not_called()


def test_aws_success_before_observed_recovers_without_execute(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"].update(status="SUCCESS", stackStatus="UPDATE_COMPLETE")
    J.save(path, backend)
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
        patch.object(J, "from_run_sync", side_effect=finish_sync) as sync,
    ):
        J.recover(backend, path, task, ["Kms"])
    sync.assert_called_once()
    backend.poll.assert_not_called()
    backend.execute.assert_not_called()
    assert not path.exists()


def test_publication_recovery_failure_preserves_evidence(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"].update(status="SUCCESS", stackStatus="UPDATE_COMPLETE")
    backend.run_context["pendingObserved"] = {"stage": "PREPARED"}
    J.save(path, backend)
    before = path.read_bytes()
    with (
        patch.object(
            J.observed_resume,
            "reconcile",
            side_effect=Blocked("third-party Model bytes"),
        ),
        pytest.raises(Blocked, match="third-party"),
    ):
        J.recover(backend, path, task, ["Kms"])
    assert path.read_bytes() == before
    backend.execute.assert_not_called()


def test_journal_tampering_and_redirects_are_rejected(tmp_path):
    backend, _, _, path = backend_for(tmp_path)
    J.save(path, backend)
    raw = json.loads(path.read_text())
    raw["payload"]["operations"]["Kms"]["state"]["clientToken"] = "new-token"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="modified"):
        J.read(path)
    link = tmp_path / "redirect.json"
    link.symlink_to(path)
    with pytest.raises(Blocked, match="redirected"):
        J.read(link)


def test_current_changeset_approval_is_not_restored(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    state = backend.states["Kms"]
    state.pop("executionEvidence")
    state.pop("clientToken")
    state.update(status="BLOCKED", approvedChangeDigest="old", changeDigest="same")
    J.save(path, backend)
    J.recover(backend, path, task, ["Kms"])
    assert "approvedChangeDigest" not in backend.prepared_operations["Kms"]["state"]
    backend.claim_inputs = Mock()
    backend.input_digest = Mock(return_value="input")
    J.adopt_prepared(backend, path, ["change"])
    assert backend.states["Kms"]["status"] == "BLOCKED"
    assert "approvedChangeDigest" not in backend.states["Kms"]
    backend.input_digest.return_value = "latest"
    with pytest.raises(Blocked, match="inputs changed"):
        J.adopt_prepared(backend, path, ["change"])
    assert backend.claim_inputs.call_args.args[0] == unit


def test_new_task_is_not_owned_by_unexecuted_old_changeset(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"] = {
        "status": "BLOCKED",
        "changeSetId": "change",
        "stackId": "stack",
    }
    J.save(path, backend)
    task.task_digest, task.name = "new-task", "tasks/new-deploy.md"
    J.recover(backend, path, task, ["Kms"])
    backend.states = {"Kms": {"status": "NOT_STARTED"}}
    backend.run_context["states"] = backend.states
    backend.save = J.JournalSave(path, backend)
    backend.claim_inputs = Mock()
    backend.input_digest = Mock(return_value="changed-latest-input")
    J.adopt_prepared(backend, path, [])
    assert not path.exists()
    assert backend.states == {"Kms": {"status": "NOT_STARTED"}}


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
    original["states"] = {"Kms": {"status": "SUCCESS"}}
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
            {"Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]},
            {},
            {"Id": "new-change", "StackId": "stack"},
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
        "stackId": "stack",
        "changeSetId": "change",
        "expectedOutputs": expected,
    }
    change = {
        "Status": "FAILED",
        "ExecutionStatus": "UNAVAILABLE",
        "StatusReason": "No updates are to be performed",
        "StackName": "Kms",
        "StackId": "stack",
        "ChangeSetId": "change",
        "Changes": [],
    }
    backend.aws = Mock(
        return_value={
            "Stacks": [{"StackId": "stack", "StackStatus": "UPDATE_COMPLETE"}]
        }
    )
    assert (
        change_sets.review_prepared(unit, state, set(), backend.aws, Mock(), change)
        == "SUCCESS"
    )
    backend.aws.side_effect = [
        {
            "Stacks": [
                {"StackId": "stack", "StackStatus": "UPDATE_COMPLETE", "Outputs": []}
            ]
        },
        {"TemplateBody": {"Outputs": {}}},
        {"Exports": []},
    ]
    with pytest.raises(Blocked, match="not reflected"):
        change_sets.verify_outputs(backend.aws, unit, state, expected)
    backend.execute.assert_not_called()


@pytest.mark.parametrize("changed", ["none", "target", "task", "model"])
def test_recovery_guard_preserves_current_task_target_and_model(tmp_path, changed):
    backend, task, _, _ = backend_for(tmp_path)
    source = backend.root / "model.properties"
    source.write_text("original")
    backend.run_context["modelInputs"] = {
        "model.properties": backend.file_digest(source)
    }
    target = dict(TARGET)
    current = SimpleNamespace(task_digest=task.task_digest)
    if changed == "target":
        target["awsRegion"] = "different"
    elif changed == "task":
        current.task_digest = "different"
    elif changed == "model":
        source.write_text("changed")
    with (
        patch.object(J.deploy_context, "load_target", return_value=target),
        patch.object(J, "task_snapshot", return_value=current),
    ):
        if changed == "none":
            J._recovery_guard(backend, task)
        else:
            with pytest.raises(Blocked, match="changed"):
                J._recovery_guard(backend, task)


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
        "StackId": "stack",
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
            "ExportingStackId": "stack",
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
    change_sets.verify_outputs(aws, unit, {"stackId": "stack"}, expected)
    assert len(expected) == 4 and aws.call_args_list[-1].args[0] == "list_exports"
    for missing in ("output", "export", "owner", "value", "definition"):
        deployed = copy.deepcopy(document)
        actual, values = copy.deepcopy(stack), copy.deepcopy(exports)
        if missing == "output":
            actual["Outputs"].pop()
        elif missing == "export":
            values.pop()
        elif missing == "owner":
            values[-1]["ExportingStackId"] = "other"
        elif missing == "definition":
            deployed["Outputs"]["KeyId3"]["Value"] = "old-key"
        else:
            values[-1]["Value"] = "other"
        aws.side_effect = [
            {"Stacks": [actual]},
            {"TemplateBody": deployed},
            {"Exports": values},
        ]
        with pytest.raises(Blocked, match="not reflected"):
            change_sets.verify_outputs(aws, unit, {"stackId": "stack"}, expected)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
