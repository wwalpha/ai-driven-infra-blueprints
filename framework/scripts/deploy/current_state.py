"""Bounded current AWS reads; no history, publication or scheduling decisions."""

from datetime import datetime, timezone

from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked

SUCCESS = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "IMPORT_COMPLETE"}
UPDATEABLE = SUCCESS | {"UPDATE_ROLLBACK_COMPLETE", "IMPORT_ROLLBACK_COMPLETE"}
FAILED = {
    "CREATE_FAILED",
    "ROLLBACK_COMPLETE",
    "ROLLBACK_FAILED",
    "DELETE_COMPLETE",
    "DELETE_FAILED",
    "UPDATE_FAILED",
    "UPDATE_ROLLBACK_COMPLETE",
    "UPDATE_ROLLBACK_FAILED",
    "IMPORT_ROLLBACK_COMPLETE",
    "IMPORT_ROLLBACK_FAILED",
}


def classify(status, change_sets=()):
    if not isinstance(status, str) or status == "UNKNOWN":
        return "UNKNOWN"
    if status in {"ABSENT", "DELETE_COMPLETE"}:
        return "ABSENT"
    if status == "REVIEW_IN_PROGRESS":
        return (
            "RUNNING"
            if any(
                item.get("ExecutionStatus") == "EXECUTE_IN_PROGRESS"
                for item in change_sets
            )
            else "REVIEW"
        )
    if status.endswith("_IN_PROGRESS"):
        return "RUNNING"
    if status in SUCCESS:
        return "SUCCESS"
    if status in UPDATEABLE:
        return "ROLLED_BACK"
    return "FAILED"


def pages(aws, operation, field, **arguments):
    result, token, seen = [], None, set()
    while True:
        response = aws(
            operation, **arguments, **({"NextToken": token} if token else {})
        )
        if (
            not isinstance(response, dict)
            or not isinstance(response.get(field, []), list)
            or any(not isinstance(item, dict) for item in response.get(field, []))
        ):
            raise Blocked("incomplete AWS page: " + operation)
        result.extend(response.get(field, []))
        token = response.get("NextToken")
        if not token:
            return result
        if not isinstance(token, str):
            raise Blocked("invalid AWS page token: " + operation)
        if token in seen:
            raise Blocked("AWS pagination repeated a token: " + operation)
        seen.add(token)


def unavailable(code, operation, **arguments):
    raise AwsError("cloudformation", operation, code)


def read(aws, name):
    now = datetime.now(timezone.utc).isoformat()
    try:
        response = aws("describe_stacks", StackName=name)
        stacks = response.get("Stacks") if isinstance(response, dict) else None
        if (
            not isinstance(stacks, list)
            or len(stacks) != 1
            or not isinstance(stacks[0], dict)
            or response.get("NextToken") is not None
            or not isinstance(stacks[0].get("StackStatus"), str)
            or not stacks[0]["StackStatus"]
            or not isinstance(stacks[0].get("StackId"), str)
            or not stacks[0]["StackId"]
        ):
            return {
                "StackStatus": "UNKNOWN",
                "reason": "INVALID_RESPONSE",
                "observedAt": now,
            }
        stack = dict(stacks[0])
        for key in ("CreationTime", "LastUpdatedTime", "DeletionTime"):
            if key in stack:
                stack[key] = str(stack[key])
        stack["observedAt"] = now
        if stack.get("StackStatus") == "REVIEW_IN_PROGRESS":
            sets = pages(
                aws, "list_change_sets", "Summaries", StackName=stack["StackId"]
            )
            stack["classification"] = classify(stack["StackStatus"], sets)
        else:
            stack["classification"] = classify(stack["StackStatus"])
        if stack["classification"] in {"FAILED", "ROLLED_BACK"}:
            stack["reason"] = "CURRENT_" + stack["StackStatus"]
        return stack
    except AwsError as error:
        return {
            "StackStatus": "ABSENT" if error.stack_absent else "UNKNOWN",
            "reason": "STACK_ABSENT" if error.stack_absent else "READ_FAILED",
            "observedAt": now,
        }
    except (OSError, Blocked):
        return {"StackStatus": "UNKNOWN", "reason": "READ_FAILED", "observedAt": now}


def identity(stack):
    return {
        key: str(stack.get(key, ""))
        for key in (
            "StackId",
            "StackStatus",
            "CreationTime",
            "LastUpdatedTime",
            "DeletionTime",
        )
    }


def observation(stack):
    return {
        key: value
        for key, value in stack.items()
        if key
        in {
            "StackId",
            "StackStatus",
            "CreationTime",
            "LastUpdatedTime",
            "DeletionTime",
            "observedAt",
            "reason",
            "classification",
        }
    }


def category(stack):
    return stack.get("classification", classify(stack.get("StackStatus", "UNKNOWN")))


def refresh(backend, units):
    for unit in units:
        state = backend.states[unit["name"]]
        current = read(backend.aws, unit["name"])
        if state.get("currentStack") and identity(state["currentStack"]) != identity(
            current
        ):
            state.pop("observedSynced", None)
            state.pop("checkpointed", None)
            if state["status"] == "SUCCESS":
                state["needsCurrentReview"] = True
        state["currentStack"] = observation(current)
        state["stackStatus"] = current["StackStatus"]
        state["stackId"] = current.get("StackId")


def same_change_set(expected, actual):
    return bool(
        expected
        and actual
        and (
            expected == actual
            or ":changeSet/" not in expected
            and actual.split(":changeSet/")[-1].split("/")[0] == expected
        )
    )


def record_attempt(state, status):
    """Attempt outcome and current Stack observation have different sources."""
    state["stackStatus"] = state.get("currentStack", {}).get("StackStatus", status)
    if status == "UNCONFIRMED":
        if state.get("failureDetected"):
            state["status"] = "FAILED"
            return
        state.update(
            status="BLOCKED",
            attemptResult="UNKNOWN",
            reason="settled request outcome is unconfirmed; current observation is independent",
        )
        return
    if status in FAILED or "ROLLBACK" in status:
        state["failureDetected"] = True
    if status in SUCCESS:
        state["status"] = "FAILED" if state.get("failureDetected") else "SUCCESS"
    elif status in FAILED:
        state["status"] = "FAILED"
    elif status.endswith("_IN_PROGRESS"):
        state["status"] = "RUNNING"
    else:
        raise Blocked("unrecognized stack status: " + status)
