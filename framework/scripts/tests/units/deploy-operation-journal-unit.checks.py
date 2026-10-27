"""Independent runs, minimal durable operations, exact current approval and AWS Output facts."""

import copy
import json
import subprocess
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import change_sets, handoff, run_context
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


@pytest.fixture(autouse=True)
def local_publication_boundary():
    # Plan authority and actual Model publication are exercised by observed-resume UTs.
    with patch.object(J.observed_resume, "reauthorize"):
        yield


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
    record = J.read(path)[0]
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
    assert J.read(path)[0]["operations"]["Kms"]["state"]["clientToken"] == "original"
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
    assert backend.poll.call_args.args[1]["clientToken"] == "original"
    backend.execute.assert_not_called()
    assert not path.exists()


def test_publication_recovery_failure_preserves_evidence(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"].update(status="SUCCESS", stackStatus="UPDATE_COMPLETE")
    backend.run_context["pendingObserved"] = {"stage": "PREPARED"}
    J.save(path, backend)
    before = path.read_bytes()
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
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
    J.adopt_prepared(backend, path, [CHANGE])
    assert backend.states["Kms"]["status"] == "BLOCKED"
    assert "approvedChangeDigest" not in backend.states["Kms"]
    J.recover(backend, path, task, ["Kms"])
    backend.input_digest.return_value = "latest"
    with pytest.raises(Blocked, match="inputs changed"):
        J.adopt_prepared(backend, path, [CHANGE])
    assert backend.claim_inputs.call_args.args[0] == unit


def test_new_task_is_not_owned_by_unexecuted_old_changeset(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"] = {
        "status": "BLOCKED",
        "changeSetId": CHANGE,
        "stackId": STACK,
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
            {"Stacks": [{"StackId": STACK, "StackStatus": "UPDATE_COMPLETE"}]},
            {},
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


def test_adoption_claim_failure_keeps_every_unprocessed_changeset(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    units = [unit, {**unit, "name": "Other"}]
    backend.units = units
    backend.states.clear()
    backend.states.update(
        {
            u["name"]: {
                "status": "BLOCKED",
                "stackId": STACK.replace("/Kms/", "/" + u["name"] + "/"),
                "changeSetId": "change-" + u["name"],
            }
            for u in units
        }
    )
    backend.run_context["inputDigests"] = {u["name"]: "input" for u in units}
    J.save(path, backend)
    backend.describe_change_set.side_effect = [
        {
            "StackId": STACK.replace("/Kms/", "/" + u["name"] + "/"),
            "ChangeSetId": "change-" + u["name"],
            "ExecutionStatus": "AVAILABLE",
        }
        for u in units
    ]
    J.recover(backend, path, task, [u["name"] for u in units])
    backend.states = {u["name"]: {"status": "NOT_STARTED"} for u in units}
    backend.run_context["states"] = backend.states
    backend.save = J.JournalSave(path, backend)
    backend.input_digest = Mock(return_value="input")
    backend.describe_change_set.side_effect = OSError("read interrupted")
    backend.claim_inputs = SaveThenFail(backend.save)
    with pytest.raises(OSError, match="read interrupted"):
        J.adopt_prepared(backend, path, [])
    assert set(J.read(path)[0]["operations"]) == {"Kms", "Other"}
    backend.execute.assert_not_called()


class SaveThenFail:
    def __init__(self, save):
        self.save = save

    def __call__(self, unit):
        self.save()
        raise OSError("read interrupted")


def test_terminal_output_failure_discards_execution_intent(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    J.save(path, backend)
    backend.poll.side_effect = TerminalOutputFailure()
    with pytest.raises(change_sets.OutputNotReflected, match="Export missing"):
        J.recover(backend, path, task, ["Kms"])
    assert not path.exists()
    backend.execute.assert_not_called()


class TerminalOutputFailure:
    def __call__(self, unit, state):
        state.update(status="FAILED", stackStatus="UPDATE_COMPLETE")
        raise change_sets.OutputNotReflected("Export missing")


def test_bootstrap_restart_restores_failure_and_only_current_owner(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    owner_unit = {**unit, "name": "Owner"}
    entry = {
        "clientRequestToken": "original-secret-token",
        "owner": {
            "stack": "Owner",
            "stackId": "owner-stack",
            "unit": owner_unit,
            "inputDigest": "owner-input",
        },
    }
    backend.states["Kms"].update(
        status="FAILED", stackStatus="UPDATE_ROLLBACK_COMPLETE", bootstrap=entry
    )
    backend.input_digest = Mock(side_effect=["input", "owner-input"])
    backend.poll.side_effect = ConfirmBootstrapFailure()
    backend.aws = Mock(
        return_value={
            "Stacks": [{"StackId": "owner-stack", "StackStatus": "CREATE_COMPLETE"}]
        }
    )
    backend.bootstrap = Mock(side_effect=FinishBootstrap())
    J.save(path, backend)
    with (
        patch.object(J, "require_authorized"),
        patch.object(J, "_recovery_guard"),
    ):
        J.recover(backend, path, task, ["Kms", "Owner"])
    assert (
        backend.bootstrap.call_args.args[2]["clientRequestToken"]
        == "original-secret-token"
    )
    assert backend.states["Owner"]["stackId"] == "owner-stack"
    assert not path.exists()
    backend.execute.assert_not_called()


class ConfirmBootstrapFailure:
    def __call__(self, unit, state):
        state["failureEvents"] = [
            {"ResourceStatusReason": "SECRET_CURRENT_VALUE_MISSING"}
        ]
        return "UPDATE_ROLLBACK_COMPLETE"


class FinishBootstrap:
    def __call__(self, unit, state, entry):
        assert (
            state["failureEvents"][0]["ResourceStatusReason"]
            == "SECRET_CURRENT_VALUE_MISSING"
        )
        state.pop("bootstrap")
        state["status"] = "NOT_STARTED"


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


@pytest.mark.parametrize("changed", ["none", "consumer", "owner"])
def test_recovery_mutation_guard_fixes_bootstrap_inputs(tmp_path, changed):
    backend, task, unit, _ = backend_for(tmp_path)
    owner_unit = {**unit, "name": "Owner"}
    backend.states["Kms"]["bootstrap"] = {
        "owner": {"unit": owner_unit, "inputDigest": "owner-input"}
    }
    backend.expected_digests = {"Kms": "input"}
    backend.input_digest = Mock(
        side_effect=[
            "changed" if changed == "consumer" else "input",
            "changed" if changed == "owner" else "owner-input",
        ]
    )
    with (
        patch.object(J.deploy_context, "load_target", return_value=TARGET),
        patch.object(J, "task_snapshot", return_value=task),
    ):
        if changed == "none":
            J._recovery_guard(backend, task)
        else:
            with pytest.raises(Blocked, match="inputs changed"):
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


def test_waiting_generation_recovers_scope_without_inheriting_completed_stacks(
    tmp_path,
):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"].update(status="SUCCESS", observedSynced=True)
    view = "docs/designs/dev/123456789012/kms.md"
    backend.run_context["pendingGeneration"] = {
        view: {
            "identity": {"inputDigest": "previous-run"},
            "generated": {"outputs": None},
            "producers": [{"stack": "Later"}],
        }
    }
    J.save(path, backend)
    with (
        patch.object(J, "_recovery_guard"),
        patch.object(J.generation_resume, "reconcile"),
        patch.object(
            J.generation_resume, "recover_publications"
        ) as settle_publications,
        patch.object(J.generation_resume, "run") as generate,
    ):
        J.recover(backend, path, task, ["Kms", "Later"])
    settle_publications.assert_called_once_with(backend)
    generate.assert_not_called()
    assert backend.states == {
        "Kms": {"status": "NOT_STARTED"},
        "Later": {"status": "NOT_STARTED"},
    }
    assert not J.read(path)[0]["operations"]
    fresh = run_context.new_context(
        backend.root, task, TARGET, "dev", "account", [], backend
    )
    assert (
        fresh["pendingGeneration"][view]["identity"]["inputDigest"]
        == fresh["inputDigest"]
    )
    assert (
        backend.pending_publication["pendingGeneration"][view]["identity"][
            "inputDigest"
        ]
        == "previous-run"
    )
    backend.pending_publication["pendingGeneration"][view]["generated"]["outputs"] = {
        view: "unfinished"
    }
    with pytest.raises(Blocked, match="settle unfinished generated candidates"):
        run_context.new_context(
            backend.root, task, TARGET, "dev", "account", [], backend
        )
    backend.execute.assert_not_called()


def test_new_task_recovers_original_execution_then_uses_latest_inputs(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    J.save(path, backend)
    task.name, task.task_digest = "tasks/new-deploy.md", "new-authority"
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
        patch.object(J, "from_run_sync", side_effect=finish_sync),
    ):
        J.recover(backend, path, task, ["Kms"])
    J.observed_resume.reauthorize.assert_called_once_with(backend, task)
    assert backend.poll.call_args.args[1]["clientToken"] == "original"
    backend.deployment_input_paths = Mock(return_value=[])
    backend.run_context = run_context.new_context(
        backend.root, task, TARGET, "dev", TARGET["awsAccountId"], [unit], backend
    )
    backend.states = backend.run_context["states"]
    backend.claim_inputs = Mock()
    J.adopt_recovered(backend)
    assert backend.states["Kms"] == {"status": "NOT_STARTED"}
    assert not backend.run_context["inputDigests"]
    backend.execute.assert_not_called()


def test_foreign_destination_settles_aws_before_refusing_local_publication(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.run_context["repository"] = str(tmp_path / "other-checkout")
    J.save(path, backend)
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
        pytest.raises(Blocked, match="destination differs"),
    ):
        J.recover(backend, path, task, ["Kms"])
    assert backend.poll.call_args.args[1]["clientToken"] == "original"
    saved = J.read(path)[0]["operations"]["Kms"]["state"]
    assert saved["status"] == "SUCCESS" and not saved.get("observedSynced")
    J.observed_resume.reauthorize.assert_not_called()
    backend.execute.assert_not_called()


@pytest.mark.parametrize("partial", [False, True])
def test_unrelated_stack_operations_survive_recovery_and_new_run_saves(
    tmp_path, partial
):
    backend, task, unit, path = backend_for(tmp_path)
    other = {**unit, "name": "Other"}
    if partial:
        backend.units.append(other)
        backend.states["Other"] = copy.deepcopy(backend.states["Kms"])
        backend.states["Other"]["stackId"] = STACK.replace("/Kms/", "/Other/")
        backend.states["Other"]["executionEvidence"]["StackId"] = backend.states[
            "Other"
        ]["stackId"]
        backend.run_context["inputDigests"]["Other"] = "input"
    J.save(path, backend)
    expected = copy.deepcopy(
        J.read(path)[0]["operations"]["Other" if partial else "Kms"]
    )
    scope = ["Kms"] if partial else ["Other"]
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
        patch.object(J, "from_run_sync", side_effect=finish_sync),
    ):
        J.recover(backend, path, task, scope)
    if not partial:
        backend.poll.assert_not_called()
    backend.units = [unit if partial else other]
    backend.deployment_input_paths = Mock(return_value=[])
    backend.run_context = run_context.new_context(
        backend.root,
        task,
        TARGET,
        "dev",
        TARGET["awsAccountId"],
        backend.units,
        backend,
    )
    backend.states = backend.run_context["states"]
    J.save(path, backend)
    remaining = J.read(path)[0]["operations"]
    assert remaining == {"Other" if partial else "Kms": expected}
    backend.execute.assert_not_called()


@pytest.mark.parametrize(
    "field", ["stackId", "changeSetId", "clientToken", "changeDigest", "inputDigest"]
)
def test_changed_original_operation_proof_blocks_before_aws(tmp_path, field):
    backend, task, _, path = backend_for(tmp_path)
    key = {"stackId": "StackId", "changeSetId": "ChangeSetId"}.get(field, field)
    backend.states["Kms"]["executionEvidence"][key] = "different"
    J.save(path, backend)
    with pytest.raises(Blocked, match="execution evidence changed"):
        J.recover(backend, path, task, ["Kms"])
    backend.poll.assert_not_called()
    backend.execute.assert_not_called()
    assert path.exists()


@pytest.mark.parametrize("change", ["region", "account", "stack"])
def test_signed_operation_must_match_execution_target(tmp_path, change):
    backend, task, _, path = backend_for(tmp_path)
    original = STACK
    changed = (
        original.replace("ap-northeast-1", "us-east-1")
        if change == "region"
        else original.replace("123456789012", "999999999999")
        if change == "account"
        else original.replace("/Kms/", "/Different/")
    )
    backend.states["Kms"]["stackId"] = changed
    backend.states["Kms"]["executionEvidence"]["StackId"] = changed
    J.save(path, backend)
    with pytest.raises(Blocked, match="Account/Region/Stack identity"):
        J.recover(backend, path, task, ["Kms"])
    backend.poll.assert_not_called()


@pytest.mark.parametrize(
    "dependency", ["none", "inbound", "outbound", "live-inbound", "new-iac", "unknown"]
)
def test_unrelated_stack_requires_proved_dependency_boundary(tmp_path, dependency):
    backend, _, unit, path = backend_for(tmp_path)
    backend.states["Kms"]["delivery"] = {"imports": {}}
    if dependency == "inbound":
        backend.states["Kms"]["delivery"]["imports"] = {
            "export": {"ExportingStackId": STACK.replace("/Kms/", "/Other/")}
        }
    if dependency == "unknown":
        backend.states["Kms"].pop("delivery")
    J.save(path, backend)
    backend.retained_records = J.read(path)
    other = {**unit, "name": "Other"}
    backend.states = {"Other": {"status": "NOT_STARTED"}}
    backend.templates = {"Other": ({"Resources": {}, "Outputs": {}}, {})}
    exports, edges = [], []
    if dependency == "live-inbound":
        exports = [
            {
                "Name": "Export",
                "Value": "value",
                "ExportingStackId": STACK.replace("/Kms/", "/Other/"),
            }
        ]
        edges = [("Kms", "Export")]
    if dependency == "inbound":
        backend.retained_records[0]["operations"]["Kms"]["state"]["delivery"][
            "imports"
        ] = {
            "Export": {
                "Value": "value",
                "ExportingStackId": STACK.replace("/Kms/", "/Other/"),
            }
        }
        exports = [
            {
                "Name": "Export",
                "Value": "value",
                "ExportingStackId": STACK.replace("/Kms/", "/Other/"),
            }
        ]
    if dependency == "new-iac":
        backend.templates["Other"][0]["Resources"] = {
            "X": {"Properties": {"Value": {"Fn::ImportValue": "KmsExport"}}}
        }
        exports = [{"Name": "KmsExport", "Value": "value", "ExportingStackId": STACK}]
    backend.aws = Mock(side_effect=partial(dependency_response, exports, edges, ""))
    boundary = {}
    current = backend.exports_for([other], boundary)
    dependency_states = partial(
        J.dependency_states,
        backend,
        other,
        imports=boundary["importNames"]["Other"],
        hints=current,
        boundary=boundary,
    )
    if dependency in {"inbound", "unknown", "live-inbound", "new-iac"}:
        with pytest.raises(Blocked):
            dependency_states()
    else:
        states = dependency_states()
        assert states["Kms"]["status"] == "RUNNING"
        if dependency == "outbound":
            backend.templates["Other"][0]["Resources"] = {
                "X": {"Properties": {"Value": {"Fn::ImportValue": "KmsExport"}}}
            }
            with pytest.raises(Blocked, match="producer Kms has not succeeded"):
                change_sets.check_imports(
                    TARGET,
                    backend.templates,
                    states,
                    backend.aws,
                    other,
                    {"KmsExport": {"ExportingStackId": STACK}},
                )


def test_process_kill_releases_lock_retains_original_journal_and_token(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    J.save(path, backend)
    script = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from deploy.operation_journal import locked
with locked(Path(sys.argv[2])):
    print('READY', flush=True)
    sys.stdin.read()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(Path(J.__file__).parent.parent), str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "READY"
        inode = path.with_suffix(".lock").stat().st_ino
        with pytest.raises(Blocked, match="lock busy"):
            with J.locked(path):
                raise AssertionError("second controller acquired the lock")
        process.kill()
        process.wait(timeout=5)
        with J.locked(path):
            assert path.with_suffix(".lock").stat().st_ino == inode
            with (
                patch.object(J, "_restore_template"),
                patch.object(J.change_sets, "verify_outputs"),
                patch.object(J, "from_run_sync", side_effect=finish_sync),
            ):
                J.recover(backend, path, task, ["Kms"])
        assert backend.poll.call_args.args[1]["clientToken"] == "original"
        assert not path.exists() and path.with_suffix(".lock").exists()
        backend.execute.assert_not_called()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


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


def test_partial_scope_keeps_atomic_plan_with_all_original_operation_proofs(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    other = {**unit, "name": "Other"}
    backend.units.append(other)
    backend.states["Other"] = copy.deepcopy(backend.states["Kms"])
    backend.states["Other"]["stackId"] = STACK.replace("/Kms/", "/Other/")
    backend.states["Other"]["executionEvidence"]["StackId"] = backend.states["Other"][
        "stackId"
    ]
    backend.run_context["inputDigests"]["Other"] = "input"
    backend.run_context["pendingObserved"] = {
        "beforeManifest": {"model/x.properties": "original"}
    }
    J.save(path, backend)
    with (
        patch.object(J, "_restore_template"),
        patch.object(J.change_sets, "verify_outputs"),
        pytest.raises(Blocked, match="shared publication"),
    ):
        J.recover(backend, path, task, ["Kms"])
    record = J.read(path)[0]
    assert set(record["operations"]) == {"Kms", "Other"}
    assert record["operations"]["Kms"]["state"]["status"] == "SUCCESS"
    assert record["operations"]["Other"]["state"]["status"] == "RUNNING"
    assert record["publication"]["pendingObserved"]["beforeManifest"] == {
        "model/x.properties": "original"
    }
    J.observed_resume.reauthorize.assert_not_called()
    backend.execute.assert_not_called()


def test_peer_owners_keep_every_entry_when_new_operation_is_saved(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    J.save(path, backend)
    original = J.read(path)[0]
    backend.retained_records = [original]
    other = {**unit, "name": "Other"}
    backend.units = [other]
    backend.states = {
        "Other": {
            "status": "BLOCKED",
            "stackId": STACK.replace("/Kms/", "/Other/"),
            "changeSetId": "prepared",
        }
    }
    backend.run_context = dict(
        backend.run_context,
        taskFile="tasks/other.md",
        taskDigest="other",
        states=backend.states,
        inputDigests={"Other": "latest"},
    )
    J.save(path, backend)
    records = J.read(path)
    assert len(records) == 2 and records[0] == original
    assert records[1]["publication"]["taskFile"] == "tasks/other.md"
    assert set(records[1]["operations"]) == {"Other"}


def test_unrelated_publication_blocks_only_shared_task_files(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.run_context["pendingGeneration"] = {
        "view": {
            "producers": [],
            "generated": {
                "originals": {"docs/designs/dev/account/kms.md": "before"},
                "outputs": None,
            },
        }
    }
    J.save(path, backend)
    backend.retained_records = J.read(path)
    task.text = "## Modified files\n- `docs/designs/dev/account/s3.md`\n"
    J.publication_conflicts(backend, task)
    task.text += "- `docs/designs/dev/account/kms.md`\n"
    with pytest.raises(Blocked, match="shares current Task files"):
        J.publication_conflicts(backend, task)


def test_existing_readable_lock_is_reused_without_unlink(tmp_path):
    path = tmp_path / "journal.json"
    lock = path.with_suffix(".lock")
    lock.write_text("")
    lock.chmod(0o644)
    inode = lock.stat().st_ino
    with J.locked(path):
        pass
    assert lock.stat().st_ino == inode


def dependency_response(exports, edges, defect, operation, **arguments):
    if operation == "describe_stacks":
        name = arguments["StackName"].split(":stack/")[-1].split("/")[0]
        identity = STACK.replace("/Kms/", "/" + name + "/")
        return {
            "Stacks": [
                {
                    "StackId": identity,
                    "StackStatus": "UPDATE_COMPLETE",
                    "Outputs": None
                    if defect == "invalid-exports"
                    else [
                        {
                            "OutputKey": entry["Name"],
                            "ExportName": entry["Name"],
                            "OutputValue": entry.get("Value", "value"),
                        }
                        for entry in exports
                        if entry["ExportingStackId"] == identity
                    ],
                }
            ]
        }
    if operation == "list_exports":
        return {
            "Exports": [
                dict(entry, Value=entry.get("Value", "value")) for entry in exports
            ]
        }
    assert operation == "list_imports"
    return {
        "Imports": {}
        if defect == "invalid-consumers"
        else [
            consumer
            for consumer, producer in edges
            if producer == arguments["ExportName"]
        ]
    }


@pytest.mark.parametrize(
    "source", ["delivery", "outputs", "pending", "both", "unknown"]
)
def test_controller_passes_current_import_proof_to_independence(tmp_path, source):
    backend = create_runtime(tmp_path, "dev", TARGET["awsAccountId"], TARGET)
    entry = {
        "Name": "Common",
        "Value": "value",
        "ExportingStackId": STACK.replace("/Kms/", "/Common/"),
    }
    backend.templates = {
        "S3": (
            {
                "Conditions": {"Disabled": {"Fn::Equals": ["yes", "no"]}},
                "Outputs": {
                    "Used": {"Value": {"Fn::ImportValue": "Common"}},
                    "Unused": {
                        "Condition": "Disabled",
                        "Value": {"Fn::ImportValue": "Missing"},
                    },
                },
            },
            {},
        )
    }
    backend.states = {"S3": {"status": "NOT_STARTED"}}
    saved = {key: entry[key] for key in ("Value", "ExportingStackId")}
    if source in {"delivery", "both"}:
        backend.states["S3"]["delivery"] = {"imports": {"Common": dict(saved)}}
    elif source == "outputs":
        backend.states["Common"] = {
            "status": "SUCCESS",
            "stackId": entry["ExportingStackId"],
            "expectedOutputs": {"Common": {"export": "Common"}},
        }
    backend.retained_records = [
        {"operations": {"Kms": {"state": {"delivery": {"imports": {}}}}}}
    ]
    if source in {"pending", "both"}:
        backend.retained_records[0]["operations"]["Kms"]["state"]["delivery"][
            "imports"
        ] = {"Common": dict(saved)}
    backend.aws = Mock(side_effect=partial(dependency_response, [entry], [], ""))
    backend.check_imports({"name": "S3"})
    operations = [c.args[0] for c in backend.aws.call_args_list]
    assert operations.count("list_exports") == (1 if source == "unknown" else 0), (
        operations
    )
    assert (
        sum(
            c.args[0] == "describe_stacks"
            and c.kwargs["StackName"] == entry["ExportingStackId"]
            for c in backend.aws.call_args_list
        )
        == 1
    )
    if source in {"delivery", "pending", "both"}:
        for field in ("Value", "ExportingStackId"):
            original = entry[field]
            entry[field] += "-changed"
            backend.aws.reset_mock()
            with pytest.raises(Blocked, match="Producer/value changed"):
                backend.check_imports({"name": "S3"})
            assert all(c.args[0] != "list_exports" for c in backend.aws.call_args_list)
            entry[field] = original


@pytest.mark.parametrize("defect", ["producer", "value"])
def test_planned_hints_cannot_override_unfinished_operation_evidence(defect):
    entry = {
        "Name": "Common",
        "Value": "value",
        "ExportingStackId": STACK.replace("/Kms/", "/Common/"),
    }
    saved = {key: entry[key] for key in ("Value", "ExportingStackId")}
    pending = {"Kms": {"delivery": {"imports": {"Common": saved}}}}
    changed = dict(entry)
    changed["ExportingStackId" if defect == "producer" else "Value"] += "-changed"
    aws = Mock(side_effect=AssertionError("conflicts must block before AWS"))
    with pytest.raises(Blocked, match="saved Export Producer/value is ambiguous"):
        J.require_independent(
            pending,
            {"S3"},
            aws,
            imports={"S3": {"Common"}},
            hints={"Common": changed},
        )
    aws.assert_not_called()


@pytest.mark.parametrize("defect", ["producer", "value"])
def test_controller_without_imports_ignores_unrelated_saved_hint_conflicts(
    tmp_path, defect
):
    backend = create_runtime(tmp_path, "dev", TARGET["awsAccountId"], TARGET)
    saved = {
        "Value": "value",
        "ExportingStackId": STACK.replace("/Kms/", "/Common/"),
    }
    changed = dict(saved)
    changed["ExportingStackId" if defect == "producer" else "Value"] += "-changed"
    backend.templates = {"S3": ({}, {})}
    backend.states = {
        "S3": {"status": "NOT_STARTED"},
        "One": {"delivery": {"imports": {"Common": saved}}},
        "Two": {"delivery": {"imports": {"Common": changed}}},
    }
    backend.retained_records = [
        {"operations": {"Kms": {"state": {"delivery": {"imports": {}}}}}}
    ]
    backend.aws = Mock(side_effect=partial(dependency_response, [], [], ""))
    backend.check_imports({"name": "S3"})
    assert all(c.args[0] != "list_exports" for c in backend.aws.call_args_list)


def test_no_planned_imports_keep_unfinished_operation_export_proof():
    entry = {
        "Name": "Common",
        "Value": "stale",
        "ExportingStackId": STACK.replace("/Kms/", "/Common/"),
    }
    saved = {key: entry[key] for key in ("Value", "ExportingStackId")}
    aws = Mock(
        side_effect=partial(dependency_response, [dict(entry, Value="current")], [], "")
    )
    with pytest.raises(Blocked, match="Producer/value changed"):
        J.require_independent(
            {"Kms": {"delivery": {"imports": {"Common": saved}}}},
            {"S3"},
            aws,
            imports={"S3": set()},
        )
    assert all(c.args[0] != "list_exports" for c in aws.call_args_list)


@pytest.mark.parametrize(
    "relation",
    [
        "forward",
        "reverse",
        "transitive-forward",
        "transitive-reverse",
        "shared-producer",
        "missing-imports",
        "invalid-exports",
        "invalid-consumers",
    ],
)
def test_deploy_and_handoff_dependency_graph(relation):
    pending = {"Kms": {"status": "RUNNING", "delivery": {"imports": {}}}}
    if relation == "missing-imports":
        pending["Kms"].pop("delivery")
    edges = {
        "forward": [("S3", "Kms")],
        "reverse": [("Kms", "S3")],
        "transitive-forward": [("S3", "Middle"), ("Middle", "Kms")],
        "transitive-reverse": [("Kms", "Middle"), ("Middle", "S3")],
        "shared-producer": [("Kms", "Common"), ("S3", "Common")],
    }.get(relation, [])
    owners = sorted({producer for _, producer in edges})
    exports = [
        {
            "Name": name,
            "Value": "value",
            "ExportingStackId": STACK.replace("/Kms/", "/" + name + "/"),
        }
        for name in owners
    ]
    if relation == "invalid-consumers":
        exports = [{"Name": "Kms", "ExportingStackId": STACK}]
    aws = Mock(side_effect=partial(dependency_response, exports, edges, relation))
    if relation == "shared-producer":
        pending["Kms"]["delivery"]["imports"] = {
            "Common": {key: exports[0][key] for key in ("Value", "ExportingStackId")}
        }
        J.require_independent(pending, {"S3"}, aws, imports={"S3": {"Common"}})
        assert all(
            call.args[0] not in {"list_exports", "list_imports"}
            for call in aws.call_args_list
        )
    else:
        with pytest.raises(Blocked):
            J.require_independent(pending, {"S3"}, aws)


@pytest.mark.parametrize("unrelated", [0, 199, 1000])
def test_dependency_api_calls_are_bounded_by_reachable_exports(unrelated):
    pending = {"Kms": {"status": "RUNNING", "delivery": {"imports": {}}}}
    exports = [
        {
            "Name": name,
            "Value": "value",
            "ExportingStackId": STACK.replace("/Kms/", "/" + name + "/"),
        }
        for name in ["Kms", *["Unrelated" + str(i) for i in range(unrelated)]]
    ]
    aws = Mock(side_effect=partial(dependency_response, exports, [], ""))
    J.require_independent(pending, {"S3"}, aws, imports={"S3": set()})
    assert [(c.args[0], c.kwargs) for c in aws.call_args_list] == [
        ("describe_stacks", {"StackName": "Kms"}),
        ("describe_stacks", {"StackName": "S3"}),
        ("list_imports", {"ExportName": "Kms"}),
    ]


def test_dependency_cache_is_per_proof_and_deduplicates_diamonds_and_cycles():
    pending = {"Kms": {"status": "RUNNING", "delivery": {"imports": {}}}}
    names = ["Kms", "S3", "Left", "Right", "Join"]
    exports = [
        {
            "Name": name,
            "Value": "value",
            "ExportingStackId": STACK.replace("/Kms/", "/" + name + "/"),
        }
        for name in names
    ]
    edges = [
        ("Left", "Kms"),
        ("Right", "Kms"),
        ("Join", "Left"),
        ("Join", "Right"),
        ("Left", "Join"),
        ("Join", "S3"),
    ]
    aws = Mock(side_effect=partial(dependency_response, exports, edges, ""))
    for _ in range(2):
        aws.reset_mock()
        J.require_independent(pending, {"S3"}, aws)
        called = [
            c.kwargs["ExportName"]
            for c in aws.call_args_list
            if c.args[0] == "list_imports"
        ]
        assert len(called) == len(set(called)) == len(names)


@pytest.mark.parametrize("reverse", [False, True])
def test_delivered_and_new_iac_imports_connect_transitive_paths(reverse):
    pending = {"Kms": {"status": "RUNNING", "delivery": {"imports": {}}}}
    exports = [
        {
            "Name": name,
            "Value": "value",
            "ExportingStackId": STACK.replace("/Kms/", "/" + name + "/"),
        }
        for name in ["Middle", "Kms", "S3"]
    ]
    imports = {"S3": {"Middle"}} if not reverse else {"S3": set()}
    if reverse:
        pending["Kms"]["delivery"]["imports"] = {
            "Middle": {key: exports[0][key] for key in ("Value", "ExportingStackId")}
        }
    edges = [("Middle", "S3" if reverse else "Kms")]
    aws = Mock(side_effect=partial(dependency_response, exports, edges, ""))
    with pytest.raises(Blocked, match="unfinished Stack dependency conflicts"):
        J.require_independent(pending, {"S3"}, aws, imports=imports)


@pytest.mark.parametrize(
    "response",
    [
        {},
        None,
        {"Exports": None},
        {"Exports": [], "NextToken": "unfinished"},
        {"Exports": [{"Name": "x"}]},
        {"Exports": [{"Name": "x", "ExportingStackId": STACK}] * 2},
    ],
)
def test_incomplete_dependency_inventory_blocks(response):
    with pytest.raises(Blocked):
        J.require_independent(
            {"Kms": {"delivery": {"imports": {}}}}, {"S3"}, Mock(return_value=response)
        )


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"Imports": [], "NextToken": "unfinished"},
        {"Imports": [None]},
        {"Imports": [""]},
    ],
)
def test_incomplete_or_failed_required_import_reads_block(response):
    exports = [{"Name": "Kms", "ExportingStackId": STACK}]
    for failure in [response, Blocked("read denied")]:
        aws = Mock(side_effect=[{"Exports": exports}, failure])
        with pytest.raises(Blocked):
            J.require_independent({"Kms": {"delivery": {"imports": {}}}}, {"S3"}, aws)


def test_missing_new_iac_export_blocks_without_assuming_independence():
    with pytest.raises(Blocked, match="missing Export"):
        J.require_independent(
            {"Kms": {"delivery": {"imports": {}}}},
            {"S3"},
            Mock(side_effect=partial(dependency_response, [], [], "")),
            imports={"S3": {"Missing"}},
        )


if __name__ == "__main__":
    raise SystemExit(run(__file__))


def test_out_of_scope_no_change_does_not_block_dependent_stack(tmp_path):
    backend, task, _, path = backend_for(tmp_path)
    backend.states["Kms"] = {
        "status": "BLOCKED",
        "stackId": STACK,
        "changeSetId": CHANGE,
        "operationType": "UPDATE",
        "absentBeforeCreate": False,
        "expectedOutputs": {},
        "delivery": {"imports": {}},
    }
    backend.describe_change_set.return_value = {
        "Status": "FAILED",
        "StatusReason": "The submitted information didn't contain changes",
        "ExecutionStatus": "UNAVAILABLE",
        "Changes": [],
        "StackName": "Kms",
        "StackId": STACK,
        "ChangeSetId": CHANGE,
    }
    J.save(path, backend)
    backend.aws = Mock(
        side_effect=lambda operation, **kwargs: backend.describe_change_set.return_value
        if operation == "describe_change_set"
        else {"Stacks": [{"StackId": STACK, "StackStatus": "CREATE_COMPLETE"}]}
    )
    J.recover(backend, path, task, ["Consumer"])
    backend.states = {"Consumer": {"status": "NOT_STARTED"}}
    with patch.object(J, "require_independent") as independent:
        states = J.dependency_states(
            backend, {"name": "Consumer"}, imports={"Export"}, hints={}, boundary={}
        )
    assert "Kms" not in independent.call_args.args[0]
    assert states.get("Kms", {}).get("status") != "RUNNING"
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "SUCCESS"
    backend.execute.assert_not_called()


def no_change_fixture(tmp_path):
    backend, task, unit, path = backend_for(tmp_path)
    backend.states["Kms"] = {
        "status": "BLOCKED",
        "stackId": STACK,
        "changeSetId": CHANGE,
        "operationType": "UPDATE",
        "absentBeforeCreate": False,
        "expectedOutputs": {},
        "delivery": {"imports": {}},
    }
    change = {
        "Status": "FAILED",
        "StatusReason": "No updates are to be performed",
        "ExecutionStatus": "UNAVAILABLE",
        "Changes": [],
        "StackName": "Kms",
        "StackId": STACK,
        "ChangeSetId": CHANGE,
    }
    stack = {"StackId": STACK, "StackStatus": "CREATE_COMPLETE"}
    backend.aws = Mock(side_effect=partial(no_change_response, change, stack))
    return backend, task, unit, path, change, stack


def no_change_response(change, stack, operation, **kwargs):
    if operation == "describe_change_set":
        return change
    if operation == "describe_stacks":
        return {"Stacks": [stack]}
    raise AssertionError(operation)


@pytest.mark.parametrize(
    "defect", ["in-progress", "stack-id", "changeset-id", "token", "outputs"]
)
def test_no_change_evidence_must_be_complete(tmp_path, defect):
    backend, task, _, path, change, stack = no_change_fixture(tmp_path)
    state = backend.states["Kms"]
    if defect == "in-progress":
        stack["StackStatus"] = "UPDATE_IN_PROGRESS"
    elif defect == "stack-id":
        stack["StackId"] += "-different"
    elif defect == "changeset-id":
        change["ChangeSetId"] += "-different"
    elif defect == "token":
        state["clientToken"] = "contradiction"
    else:
        state["expectedOutputs"] = {
            "missing": {"export": "X", "definitionDigest": "bad", "valueDigest": None}
        }
        backend.aws.side_effect = partial(no_change_output_response, change, stack)
    J.save(path, backend)
    before = path.read_bytes()
    with pytest.raises(Blocked):
        J.recover(backend, path, task, ["Consumer"])
    assert path.read_bytes() == before
    backend.execute.assert_not_called()


def no_change_output_response(change, stack, operation, **kwargs):
    if operation == "get_template":
        return {"TemplateBody": {"Outputs": {}}}
    return no_change_response(change, stack, operation, **kwargs)


def test_no_change_restart_and_owner_publication_recovery(tmp_path):
    backend, task, _, path, _, _ = no_change_fixture(tmp_path)
    J.save(path, backend)
    J.recover(backend, path, task, ["Consumer"])
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "SUCCESS"
    J.recover(backend, path, task, ["Consumer"])
    with (
        patch.object(J, "_restore_template"),
        patch.object(J, "from_run_sync", side_effect=finish_sync),
    ):
        J.recover(backend, path, task, ["Kms"])
    assert not path.exists()
    backend.execute.assert_not_called()


def test_no_change_other_repository_never_publishes(tmp_path):
    backend, task, _, path, _, _ = no_change_fixture(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    backend.run_context["repository"] = str(other)
    J.save(path, backend)
    with patch.object(J, "from_run_sync") as sync:
        J.recover(backend, path, task, ["Consumer"])
    sync.assert_not_called()
    assert J.read(path)[0]["publication"]["repository"] == str(other)
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "SUCCESS"


def no_change_dependency_response(change, exports, operation, **arguments):
    if operation == "describe_change_set":
        return change
    return dependency_response(exports, [], "", operation, **arguments)


def test_consumer_uses_current_export_after_no_change_recovery(tmp_path):
    backend, task, _, path, change, _ = no_change_fixture(tmp_path)
    backend.states["Kms"]["delivery"]["imports"] = {
        "KmsExport": {"Value": "old", "ExportingStackId": STACK}
    }
    export = {"Name": "KmsExport", "Value": "current", "ExportingStackId": STACK}
    backend.aws = Mock(
        side_effect=partial(no_change_dependency_response, change, [export])
    )
    J.save(path, backend)
    J.recover(backend, path, task, ["Consumer"])
    backend.states = {"Consumer": {"status": "NOT_STARTED"}}
    backend.templates = {
        "Consumer": (
            {
                "Resources": {
                    "R": {"Properties": {"V": {"Fn::ImportValue": "KmsExport"}}}
                }
            },
            {},
        )
    }
    backend.check_imports({"name": "Consumer"})
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "SUCCESS"
    backend.execute.assert_not_called()


def test_handoff_uses_same_no_change_classification(tmp_path):
    backend, _, _, path, _, _ = no_change_fixture(tmp_path)
    J.save(path, backend)
    request = {
        "target": TARGET,
        "diagnosis": {"Consumer": {"inputRefs": [], "modelRefs": []}},
        "allowedPaths": [],
    }
    with (
        patch.object(J, "location", return_value=path),
        patch.object(handoff, "dependency_reader", return_value=backend.aws),
        patch.object(handoff.inputs, "load_units") as load_units,
    ):
        handoff.require_settled(backend.root, request)
        load_units.assert_not_called()
    backend.execute.assert_not_called()


def unavailable_change_response(exports, edges, operation, **kwargs):
    if operation == "describe_change_set":
        raise AwsError("cloudformation", operation, "ChangeSetNotFound")
    return dependency_response(exports, edges, "", operation, **kwargs)


def test_verified_no_change_survives_missing_changeset(tmp_path):
    backend, task, _, path, _, _ = no_change_fixture(tmp_path)
    J.save(path, backend)
    J.recover(backend, path, task, ["Consumer"])
    backend.aws = Mock(side_effect=partial(unavailable_change_response, [], []))
    J.recover(backend, path, task, ["Consumer"])
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "SUCCESS"
    backend.execute.assert_not_called()


def test_unverified_missing_changeset_allows_independent_stack(tmp_path):
    backend, task, _, path, _, _ = no_change_fixture(tmp_path)
    J.save(path, backend)
    backend.aws = Mock(side_effect=partial(unavailable_change_response, [], []))
    J.recover(backend, path, task, ["S3"])
    backend.states = {"S3": {"status": "NOT_STARTED"}}
    J.dependency_states(backend, {"name": "S3"}, imports=set(), hints={}, boundary={})
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "BLOCKED"
    backend.execute.assert_not_called()


@pytest.mark.parametrize("defect", ["stack-id", "in-progress", "outputs", "evidence"])
def test_saved_no_change_requires_current_and_consistent_evidence(tmp_path, defect):
    backend, task, _, path, change, stack = no_change_fixture(tmp_path)
    J.save(path, backend)
    J.recover(backend, path, task, ["Consumer"])
    record = J.read(path)[0]
    state = record["operations"]["Kms"]["state"]
    if defect == "stack-id":
        stack["StackId"] += "-changed"
    elif defect == "in-progress":
        stack["StackStatus"] = "UPDATE_IN_PROGRESS"
    elif defect == "outputs":
        state["expectedOutputs"] = {
            "missing": {"export": "X", "definitionDigest": "bad", "valueDigest": None}
        }
        backend.aws.side_effect = partial(no_change_output_response, change, stack)
    else:
        state["noChangeEvidence"]["ChangeSetId"] += "-changed"
    J.write_records(path, [record])
    with pytest.raises(Blocked):
        J.recover(backend, path, task, ["Consumer"])
    assert path.exists()
    backend.execute.assert_not_called()


def test_unverified_missing_changeset_blocks_s3_export_consumer(tmp_path):
    backend, task, _, path, _, _ = no_change_fixture(tmp_path)
    J.save(path, backend)
    export = {"Name": "BucketExport", "Value": "bucket", "ExportingStackId": STACK}
    backend.aws = Mock(side_effect=partial(unavailable_change_response, [export], []))
    J.recover(backend, path, task, ["S3"])
    backend.states = {"S3": {"status": "NOT_STARTED"}}
    with pytest.raises(Blocked, match="dependency conflicts"):
        J.dependency_states(
            backend, {"name": "S3"}, imports={"BucketExport"}, hints={}, boundary={}
        )
    assert J.read(path)[0]["operations"]["Kms"]["state"]["status"] == "BLOCKED"
    backend.execute.assert_not_called()


def test_unverified_old_success_cannot_publish_when_changeset_missing(tmp_path):
    backend, task, _, path, _, _ = no_change_fixture(tmp_path)
    backend.states["Kms"]["status"] = "SUCCESS"
    J.save(path, backend)
    backend.aws = Mock(side_effect=partial(unavailable_change_response, [], []))
    with pytest.raises(Blocked, match="unverified no-change"):
        J.recover(backend, path, task, ["Kms"])
    assert path.exists()
    backend.execute.assert_not_called()


def test_unverified_s3_export_blocks_consumer(tmp_path):
    backend, task, unit, path, _, _ = no_change_fixture(tmp_path)
    unit["name"] = "S3"
    state = backend.states.pop("Kms")
    state["stackId"] = STACK.replace("/Kms/", "/S3/")
    backend.states["S3"] = state
    backend.run_context["inputDigests"]["S3"] = "input"
    J.save(path, backend)
    export = {
        "Name": "BucketExport",
        "Value": "bucket",
        "ExportingStackId": state["stackId"],
    }
    backend.aws = Mock(side_effect=partial(unavailable_change_response, [export], []))
    J.recover(backend, path, task, ["Consumer"])
    backend.states = {"Consumer": {"status": "NOT_STARTED"}}
    with pytest.raises(Blocked, match="dependency conflicts"):
        J.dependency_states(
            backend,
            {"name": "Consumer"},
            imports={"BucketExport"},
            hints={},
            boundary={},
        )
    backend.execute.assert_not_called()


def verified_output_response(change, document, operation, **kwargs):
    if operation == "describe_change_set":
        return change
    if operation == "describe_stacks":
        return {
            "Stacks": [
                {
                    "StackId": STACK,
                    "StackStatus": "UPDATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": "Bucket",
                            "OutputValue": "bucket",
                            "ExportName": "BucketExport",
                        }
                    ],
                }
            ]
        }
    if operation == "get_template":
        return {"TemplateBody": document}
    if operation == "list_exports":
        return {
            "Exports": [
                {"Name": "BucketExport", "Value": "bucket", "ExportingStackId": STACK}
            ]
        }
    raise AssertionError(operation)


def test_normal_review_persists_verified_output_evidence_for_restart(tmp_path):
    backend, task, unit, path, change, _ = no_change_fixture(tmp_path)
    document = {
        "Outputs": {"Bucket": {"Value": "bucket", "Export": {"Name": "BucketExport"}}}
    }
    state = backend.states["Kms"]
    state["expectedOutputs"] = change_sets.required_outputs(document, {}, TARGET, "Kms")
    backend.aws = Mock(side_effect=partial(verified_output_response, change, document))
    state["status"] = backend.review_prepared(unit, state, change)
    J.save(path, backend)
    backend.aws.reset_mock()
    J.recover(backend, path, task, ["Consumer"])
    assert J.read(path)[0]["operations"]["Kms"]["state"]["noChangeEvidence"]
    assert all(
        call.args[0] != "describe_change_set" for call in backend.aws.call_args_list
    )
    assert any(call.args[0] == "get_template" for call in backend.aws.call_args_list)
    backend.execute.assert_not_called()
