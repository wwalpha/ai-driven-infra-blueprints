"""Pinned AWS runtime recovery; never writes authoritative IaC."""

import copy
import time

import task_contract_core as _imports_task_contract
from utils.cloudformation.inputs import Blocked


def require_authorized(root):
    task_snapshot = _imports_task_contract.task_snapshot
    contract = task_snapshot(root).text
    if "- Runtime recovery: `allowed`" not in contract.splitlines():
        raise Blocked("runtime recovery not authorized in task contract")


def cleanup_unexecuted(aws, save, wait_cleanup, state):
    proof = state["preExecutionRecovery"]
    if (
        proof["operationType"] != "CREATE"
        or not proof["absentBeforeCreate"]
        or proof["stackId"] != state["stackId"]
    ):
        raise Blocked("unexecuted shell original ownership missing")
    try:
        stack = aws("describe_stacks", StackName=proof["stackId"])["Stacks"][0]
    except Blocked as error:
        if not getattr(error, "stack_absent", False):
            raise
        stack = None
    if stack is None:
        state.update(cleanupStatus="DELETE_COMPLETE", cleanupStackId=proof["stackId"])
        save()
        return
    if (
        stack["StackId"] != proof["stackId"]
        or stack.get("EnableTerminationProtection")
        or stack.get("ParentId")
        or stack.get("RootId")
    ):
        raise Blocked("unexecuted shell identity/protection changed")
    if state.get("cleanupStatus") == "DELETE_INTENT" and stack["StackStatus"] in {
        "DELETE_IN_PROGRESS",
        "DELETE_COMPLETE",
    }:
        wait_cleanup(state)
        return
    change = aws(
        "describe_change_set",
        StackName=proof["stackId"],
        ChangeSetName=proof["changeSetId"],
    )
    if (
        stack["StackStatus"] != "REVIEW_IN_PROGRESS"
        or change.get("StackId") != proof["stackId"]
        or change.get("ChangeSetId") != proof["changeSetId"]
        or change.get("Status") != "FAILED"
        or change.get("ExecutionStatus") != "UNAVAILABLE"
        or aws("list_stack_resources", StackName=proof["stackId"])[
            "StackResourceSummaries"
        ]
    ):
        raise Blocked("unexecuted shell is not proven failed, empty and unexecuted")
    state.update(cleanupStatus="DELETE_INTENT", cleanupStackId=proof["stackId"])
    save()
    aws("delete_stack", StackName=proof["stackId"])
    wait_cleanup(state)


def cleanup_failed_create(
    templates, aws, save, wait_cleanup, unit, state, *, empty_only=False
):
    if state.get("stackStatus") == "PRE_EXECUTION":
        return
    if state.get("stackStatus") != "ROLLBACK_COMPLETE":
        if state.get("stackStatus") != "UPDATE_ROLLBACK_COMPLETE":
            raise Blocked(
                "rollback recovery cannot be proven safe; no delete/ResourcesToSkip"
            )
        return
    if not state.get("stackId"):
        raise Blocked("failed CREATE StackId missing; never delete by name")
    if (
        state.get("cleanupStatus") == "DELETE_COMPLETE"
        and state.get("cleanupStackId") == state["stackId"]
    ):
        return True
    if state.get("cleanupStatus") == "DELETE_INTENT":
        try:
            current = aws("describe_stacks", StackName=state["stackId"])["Stacks"][0]
        except Blocked as error:
            if "does not exist" not in str(error):
                raise
            state["cleanupStatus"] = "DELETE_COMPLETE"
            save()
            return True
        if current["StackId"] != state["stackId"]:
            raise Blocked("interrupted cleanup stack identity changed")
        if current["StackStatus"] in {"DELETE_IN_PROGRESS", "DELETE_COMPLETE"}:
            wait_cleanup(state)
            return True
        if current["StackStatus"] != "ROLLBACK_COMPLETE":
            raise Blocked("interrupted cleanup state unsafe")
    document = state.get("failureTemplateSafety")
    if document is None:
        if state.get("externalRepair"):
            raise Blocked("original failed template safety evidence missing")
        document, _ = templates[unit["name"]]
    stack = aws("describe_stacks", StackName=state["stackId"])["Stacks"][0]
    if (
        stack["StackId"] != state["stackId"]
        or stack["StackStatus"] != "ROLLBACK_COMPLETE"
        or stack.get("EnableTerminationProtection")
        or stack.get("ParentId")
        or stack.get("RootId")
    ):
        raise Blocked("failed CREATE identity/state changed or protected")
    actuals = aws("list_stack_resources", StackName=state["stackId"])[
        "StackResourceSummaries"
    ]
    empty = all(item.get("ResourceStatus") == "DELETE_COMPLETE" for item in actuals)
    if empty_only and not empty:
        return False
    if not empty:
        if (
            state.get("operationType") != "CREATE"
            or not state.get("absentBeforeCreate")
            or state.get("operationStackId") != state["stackId"]
        ):
            raise Blocked(
                "failed CREATE session provenance missing; never delete by name"
            )
        if any(
            resource.get("DeletionPolicy", "Delete") != "Delete"
            or resource.get("UpdateReplacePolicy", "Delete") != "Delete"
            or resource["Type"].startswith(("Custom::", "AWS::CloudFormation::"))
            for resource in document.get("Resources", {}).values()
        ) or any(
            event["ResourceStatus"] == "DELETE_SKIPPED"
            for event in state.get("failureEvents", [])
        ):
            raise Blocked(
                "failed CREATE contains retained/custom resources; cleanup requires human"
            )
    if not empty and any(
        item["ResourceStatus"] not in {"DELETE_COMPLETE", "CREATE_FAILED"}
        or item["ResourceStatus"] == "CREATE_FAILED"
        and item.get("PhysicalResourceId")
        or item.get("LogicalResourceId") not in document.get("Resources", {})
        or item.get("ResourceType")
        != document["Resources"][item["LogicalResourceId"]]["Type"]
        for item in actuals
    ):
        raise Blocked("failed CREATE still owns resources; cleanup requires human")
    state.update(cleanupStatus="DELETE_INTENT", cleanupStackId=state["stackId"])
    save()
    aws("delete_stack", StackName=state["stackId"])
    wait_cleanup(state)
    return True


def wait_cleanup(aws, save, state):
    for _ in range(120):
        try:
            current = aws("describe_stacks", StackName=state["stackId"])["Stacks"][0][
                "StackStatus"
            ]
        except Blocked as error:
            if "does not exist" not in str(error):
                raise
            current = "DELETE_COMPLETE"
        if current == "DELETE_COMPLETE":
            state["cleanupStatus"] = "DELETE_COMPLETE"
            save()
            return
        if current != "DELETE_IN_PROGRESS":
            raise Blocked("failed CREATE cleanup stopped: " + current)
        time.sleep(5)
    raise Blocked("failed CREATE cleanup timeout; inspect same StackId before resuming")


def reset_after_cleanup(save, state, *, retain_delivery=False):
    archive_failure(state)
    retained = {
        key: state[key]
        for key in (
            "repairs",
            "cleanupStatus",
            "cleanupStackId",
            "emptyStackRecreated",
            "failureArchive",
            "externalRepair",
            "recoveryPending",
        )
        if key in state
    }
    if retain_delivery and "delivery" in state:
        retained["delivery"] = state["delivery"]
    state.clear()
    state.update(retained, status="NOT_STARTED")
    save()


def finish_repair(
    refresh_validation,
    save,
    cleanup_failed_create,
    reset_after_cleanup,
    unit,
    state,
    entry,
):
    if entry.get("classification") != "RUNTIME_BOOTSTRAP":
        raise Blocked("only runtime bootstrap can finish internal recovery")
    refresh_validation(unit)
    entry["stage"] = "BOOTSTRAP_CONFIRMED"
    save()
    cleanup_failed_create(unit, state)
    entry["stage"] = "RETRY_READY"
    reset_after_cleanup(state)
    save()


def archive_failure(state):
    keys = (
        "failureEvents",
        "failureTemplateSafety",
        "executionEvidence",
        "clientToken",
        "stackId",
        "operationStackId",
        "stackStatus",
        "operationType",
        "absentBeforeCreate",
        "changeSetId",
        "changeSetFailure",
        "preExecutionRecovery",
        "failure",
        "successEvents",
    )
    record = {key: copy.deepcopy(state[key]) for key in keys if key in state}
    if record and record not in state.setdefault("failureArchive", []):
        state["failureArchive"].append(record)
