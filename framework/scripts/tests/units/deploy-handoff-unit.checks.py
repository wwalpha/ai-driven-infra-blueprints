"""Current failure/Task authority and one-shot Implement evidence checks."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from types import SimpleNamespace

import pytest
from deploy import contracts, failures, handoff
from deploy.recovery import cleanup_unexecuted
from support.pytest_cli import run
from task_contract_core import set_status, task_digest
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked
from utils.file_operations import sha
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from utils.sealed_evidence import evidence_store, write_sealed

if not __debug__:
    raise SystemExit("checks require assertions")


@pytest.mark.parametrize(
    "stage,code,service,operation,expected",
    [
        (
            "PREPARATION",
            "ValidationError",
            "cloudformation",
            "validate_template",
            "IAC_CANDIDATE",
        ),
        (
            "PREPARATION",
            "ValidationException",
            "cloudformation",
            "create_change_set",
            "IAC_CANDIDATE",
        ),
        (
            "PREPARATION",
            "AccessDenied",
            "cloudformation",
            "create_change_set",
            "AUTHORIZATION",
        ),
        (
            "PREPARATION",
            "ReadTimeoutError",
            "cloudformation",
            "create_change_set",
            "NEEDS_HUMAN",
        ),
        ("POLL", "ValidationError", "cloudformation", "describe_stacks", "NEEDS_HUMAN"),
        (
            "EXECUTE",
            "ReadTimeoutError",
            "cloudformation",
            "execute_change_set",
            "SUBMISSION_UNKNOWN",
        ),
    ],
)
def check_failure_classes(stage, code, service, operation, expected):
    error = ValueError("must not be persisted as diagnosis")
    error.code, error.deploy_service, error.deploy_operation = code, service, operation
    state = {"status": "RUNNING" if stage == "EXECUTE" else "BLOCKED"}
    failures.exception(state, error, stage)
    assert state["failure"]["classification"] == expected
    assert "must not be persisted" not in json.dumps(state)


def check_status_helpers_preserve_task_identity():
    text = "## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Authorized delete/replacement: `none`\n"
    suspended = (
        set_status(text, "suspend") + "\n## Suspension reason\n\n    awaiting child\n"
    )
    assert (
        task_digest(text)
        == task_digest(suspended)
        == task_digest(set_status(suspended, "running"))
    )
    assert task_digest(text) == task_digest(text.replace("`none`", "`change-set`"))
    assert task_digest(text) != task_digest(text + "\n## Other\nchanged\n")


def _callback_check_unexecuted_shell_recovery_aws(
    calls, change, defect, stack, /, operation, **arguments
):
    calls.append((operation, arguments))
    assert arguments["StackName"] == "original"
    if operation == "describe_stacks":
        if defect == "interrupted":
            raise AwsError(
                "cloudformation", operation, "ValidationError", stack_absent=True
            )
        return {"Stacks": [stack]}
    if operation == "describe_change_set":
        return change
    if operation == "list_stack_resources":
        if defect == "read":
            raise AwsError("cloudformation", operation, "AccessDenied")
        return {"StackResourceSummaries": [{}] if defect == "resources" else []}
    assert operation == "delete_stack"


@pytest.mark.parametrize(
    "defect",
    [
        "none",
        "origin",
        "identity",
        "protected",
        "parent",
        "status",
        "change-stack",
        "executed",
        "change-status",
        "resources",
        "read",
        "interrupted",
    ],
)
def check_unexecuted_shell_recovery(defect):
    proof = {
        "stackId": "original",
        "changeSetId": "change",
        "operationType": "CREATE",
        "absentBeforeCreate": True,
    }
    state = {
        "status": "NOT_STARTED",
        "stackId": "original",
        "preExecutionRecovery": proof,
    }
    stack = {"StackId": "original", "StackStatus": "REVIEW_IN_PROGRESS"}
    change = {
        "StackId": "original",
        "ChangeSetId": "change",
        "Status": "FAILED",
        "ExecutionStatus": "UNAVAILABLE",
    }
    if defect == "origin":
        proof["absentBeforeCreate"] = False
    if defect == "identity":
        stack["StackId"] = "reused"
    if defect == "protected":
        stack["EnableTerminationProtection"] = True
    if defect == "parent":
        stack["ParentId"] = "parent"
    if defect == "status":
        stack["StackStatus"] = "CREATE_COMPLETE"
    if defect == "change-stack":
        change["StackId"] = "other"
    if defect == "executed":
        change["ExecutionStatus"] = "EXECUTE_COMPLETE"
    if defect == "change-status":
        change["Status"] = "CREATE_COMPLETE"
    if defect == "interrupted":
        state.update(cleanupStatus="DELETE_INTENT", cleanupStackId="original")
    calls, saves, waits = [], [], []
    aws = _bind_framework_callback(
        _callback_check_unexecuted_shell_recovery_aws, calls, change, defect, stack
    )
    if defect in {"none", "interrupted"}:
        cleanup_unexecuted(
            aws,
            lambda: saves.append(copy.deepcopy(state)),
            lambda s: waits.append(s["stackId"]),
            state,
        )
        assert state["status"] == "NOT_STARTED" and "stackStatus" not in state
        assert (waits == ["original"]) == (defect == "none")
    else:
        with pytest.raises(Blocked):
            cleanup_unexecuted(
                aws,
                lambda: saves.append(copy.deepcopy(state)),
                lambda s: waits.append(s["stackId"]),
                state,
            )
        assert not any(op == "delete_stack" for op, _ in calls)
        assert not waits
    assert saves or defect not in {"none", "interrupted"}


def check_validation_snapshot_project_paths(tmp_path):
    paths = {"README.md", "infra/new.json", "missing.md"}
    for relative in paths - {"missing.md"}:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(relative)
    with (
        patch.object(contracts, "paths", return_value=paths) as listing,
        patch.object(contracts, "sha", wraps=sha) as hashes,
    ):
        snapshot = contracts.validation_snapshot(tmp_path)
    listing.assert_called_once_with(
        tmp_path,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        ":(top,exclude)framework",
    )
    assert set(snapshot) == paths and snapshot["missing.md"] is None
    assert {call.args[0] for call in hashes.call_args_list} == {
        tmp_path / p for p in paths - {"missing.md"}
    }


@pytest.mark.parametrize("defect", ["none", "model", "path", "failure"])
def check_one_shot_request_requires_current_authority(tmp_path, defect):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "infra/cloudformation/templates/kms.yaml"
    model = root / "model/dev/team/kms.properties"
    for path, text in (
        (source, "Resources: {}"),
        (model, "desired.row.001-001.value=`approved`\n"),
    ):
        path.parent.mkdir(parents=True)
        path.write_text(text)
    relative, model_relative = (
        source.relative_to(root).as_posix(),
        model.relative_to(root).as_posix(),
    )
    task = SimpleNamespace(
        name="tasks/deploy.md",
        task_digest="task",
        text="- External IaC repair: `allowed`\n## Validation scope\n- `dev/team/kms`\n",
    )
    target = {"awsAccountId": "123456789012", "awsRegion": "region"}
    failure = {
        "repository": str(root),
        "taskFile": task.name,
        "taskDigest": task.task_digest,
        "target": target,
        "environment": "dev",
        "directory": "team",
        "inputs": {relative: sha(source), model_relative: sha(model)},
        "states": {
            "Kms": {
                "status": "BLOCKED",
                "failure": {
                    "classification": "IAC_CANDIDATE",
                    "executionState": "NOT_EXECUTED",
                },
            }
        },
    }
    if defect == "failure":
        failure["states"]["Kms"]["failure"]["classification"] = "SUBMISSION_UNKNOWN"
    path = tmp_path / "failure.json"
    write_sealed(root, path, failure)
    diagnosis = {
        "Kms": {
            "reason": "The current template differs from the explicitly approved desired Model entry.",
            "inputRefs": [{"path": relative, "sha256": sha(source)}],
            "modelRefs": [
                {
                    "path": model_relative,
                    "sha256": sha(model),
                    "key": "desired.row.001-001.value",
                }
            ],
        }
    }
    if defect == "model":
        model.write_text("desired.row.001-001.value=`changed`\n")
    allowed = ["infra/unrelated.yaml"] if defect == "path" else [relative]
    with (
        patch.object(handoff, "task_snapshot", return_value=task),
        patch.object(handoff.operation_journal, "read", return_value=None),
    ):
        if defect == "none":
            request = handoff.issue_request(root, path, diagnosis, allowed)
            assert request["allowedPaths"] == [relative]
            assert (
                not {"workflow", "attempts", "session", "approvedChangeDigest"}
                & request.keys()
            )
            handoff.verify_inputs(root, request)
            model.write_text("desired.row.001-001.value=`changed`\n")
            with pytest.raises(Blocked, match="dependency changed"):
                handoff.verify_inputs(root, request)
        else:
            with pytest.raises(Blocked):
                handoff.issue_request(root, path, diagnosis, allowed)


@pytest.mark.parametrize("unknown", [False, True])
def check_delivered_request_evidence_is_discarded(tmp_path, unknown):
    root = tmp_path / "project"
    root.mkdir()
    directory = evidence_store(root) / "deploy-repair-current"
    directory.mkdir()
    path = directory / "request.json"
    failure = evidence_store(root) / "deploy-failure-current.json"
    identity = {"taskFile": "tasks/deploy.md", "taskDigest": "task"}
    write_sealed(root, failure, identity)
    write_sealed(
        root,
        path,
        {
            **identity,
            "repository": str(root),
            "requestId": "current",
            "failureEvidence": str(failure),
        },
    )
    write_sealed(
        root, directory / "result.json", {"requestId": "current", "commit": "commit"}
    )
    write_sealed(root, directory / "validation.json", {"requestId": "current"})
    state = {
        "deployRepair": str(path),
        "verified": True,
        "merged": "commit",
        "commit": "commit",
    }
    if unknown:
        extra = directory / "user-note.txt"
        extra.write_text("preserve user evidence")
        with pytest.raises(Blocked, match="unknown files"):
            handoff.discard_request(state)
        assert (
            extra.read_text() == "preserve user evidence"
            and path.exists()
            and failure.exists()
        )
    else:
        handoff.discard_request(state)
        assert not directory.exists() and not failure.exists()


if __name__ == "__main__":
    raise SystemExit(run(__file__))
