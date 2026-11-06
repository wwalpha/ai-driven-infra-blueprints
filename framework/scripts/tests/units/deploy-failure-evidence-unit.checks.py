"""Deploy failure classification, recovery and validation snapshot checks."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))



import pytest
from deploy import contracts, failures
from deploy import operation_journal as J
from deploy.recovery import cleanup_unexecuted
from support.pytest_cli import run
from task_contract_core import relative_path, safe_path, set_status, task_digest
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked
from utils.file_operations import sha
from utils.function_wrapper import BoundCallback as _bind_framework_callback

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


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


@pytest.mark.parametrize("lock_path", [".lock", ".lock/registration"])
def check_validation_snapshot_project_paths(tmp_path, lock_path):
    paths = {"README.md", "infra/new.json", "missing.md", "model/.lock", ".lockfile"}
    contracts.output(tmp_path, "init", "-q")
    for relative in paths - {"missing.md"}:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(relative)
    for relative in (lock_path, "framework/ignored.py", "missing.md"):
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic")
    contracts.output(tmp_path, "add", "README.md", "missing.md", lock_path, "framework")
    (tmp_path / "missing.md").unlink()
    with (
        patch.object(contracts, "paths", wraps=contracts.paths) as listing,
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
        ":(top,exclude).lock",
    )
    assert set(snapshot) == paths and snapshot["missing.md"] is None
    assert {call.args[0] for call in hashes.call_args_list} == {
        tmp_path / p for p in paths - {"missing.md"}
    }
    assert snapshot["README.md"] == sha(tmp_path / "README.md")
    (tmp_path / "README.md").write_text("changed")
    changed = contracts.validation_snapshot(tmp_path)
    assert changed != snapshot
    assert changed | {"README.md": snapshot["README.md"]} == snapshot
    for forbidden in (".lock", ".lock/registration", ".git/config", "../outside"):
        with pytest.raises(ValueError, match="exact repository-relative path"):
            relative_path(forbidden)
        with pytest.raises(ValueError, match="exact repository-relative path"):
            safe_path(tmp_path, forbidden)


@pytest.mark.parametrize("lock", ["journal", "failure"])
def check_failure_lock_order_fails_without_waiting_or_releasing_owner(tmp_path, lock):
    root = tmp_path / "repo"
    root.mkdir()
    journal = tmp_path / "journal/journal.json"
    with J.locked(journal) if lock == "journal" else failures.failure_lock(root):
        with pytest.raises(Blocked, match="lock busy"):
            with J.locked(journal), failures.failure_lock(root):
                raise AssertionError("concurrent operation acquired controller locks")
    with J.locked(journal), failures.failure_lock(root):
        pass


if __name__ == "__main__":
    raise SystemExit(run(__file__))
