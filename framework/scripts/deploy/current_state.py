"""Bounded current AWS reads; no history, publication or scheduling decisions."""

from datetime import datetime, timezone

from contracts.deploy import DEPLOY_RUNNING, DEPLOY_SUCCESS
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked

from deploy.failures import safe_reason

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


def _event_page(aws, operation, **arguments):
    response = aws(operation, **arguments)
    if not isinstance(response, dict) or "StackEvents" not in response:
        raise Blocked("incomplete Stack event page")
    return response


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
    result = {
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
    if stack.get("StackStatusReason"):
        result["statusReason"] = safe_reason(stack["StackStatusReason"])
    elif stack.get("statusReason"):
        result["statusReason"] = stack["statusReason"]
    return result


def progress_phase(status, attempt, stage=None):
    if "ROLLBACK" in (status or ""):
        return "ROLLBACK"
    if attempt in {"CHANGESET_CREATING", "READY"} or stage == "CHANGESET_REVIEW":
        return "CHANGESET"
    if attempt == "NOT_STARTED":
        return "NOT_STARTED"
    if status and status != "UNKNOWN":
        return "EXECUTION"
    return "UNKNOWN"


def event_time(value):
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).isoformat()
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def event_progress(stack, events, token, stack_id, stack_name):
    """Count only the latest attributable Resource events, never an inferred total."""
    result = {"available": False, "partial": True, "eventAsOf": stack.get("observedAt")}
    if not token or not stack_id or stack.get("StackId") != stack_id:
        return result
    stack_status = stack.get("StackStatus") or ""
    marker = (
        "UPDATE_ROLLBACK_IN_PROGRESS"
        if stack_status.startswith("UPDATE_ROLLBACK")
        else "ROLLBACK_IN_PROGRESS"
        if "ROLLBACK" in stack_status
        else "UPDATE_IN_PROGRESS"
        if stack_status.startswith("UPDATE")
        else "DELETE_IN_PROGRESS"
        if stack_status.startswith("DELETE")
        else "CREATE_IN_PROGRESS"
        if stack_status.startswith("CREATE")
        else None
    )
    starts = [
        event_time(item.get("Timestamp"))
        for item in events
        if marker
        and item.get("StackId") == stack_id
        and item.get("ClientRequestToken") == token
        and item.get("ResourceStatus") == marker
        and (
            item.get("PhysicalResourceId") == stack_id
            or item.get("ResourceType") == "AWS::CloudFormation::Stack"
            and item.get("LogicalResourceId") == stack_name
        )
    ]
    boundary = max((value for value in starts if value), default=None)
    counts_available = bool(boundary)
    latest, seen, history, partial = {}, {}, [], False
    for item in events:
        if item.get("ClientRequestToken") != token:
            if item.get("StackId") == stack_id and not item.get("ClientRequestToken"):
                partial = True
            continue
        if item.get("StackId") != stack_id:
            partial = True
            continue
        logical, kind, status, event_id = (
            item.get(key)
            for key in (
                "LogicalResourceId",
                "ResourceType",
                "ResourceStatus",
                "EventId",
            )
        )
        if item.get("PhysicalResourceId") == stack_id or (
            kind == "AWS::CloudFormation::Stack" and logical == stack_name
        ):
            continue
        if not all(
            isinstance(value, str) and value
            for value in (logical, kind, status, event_id)
        ):
            partial = True
            continue
        when = event_time(item.get("Timestamp"))
        if not when:
            partial = True
            continue
        identity = (logical, kind, status, when)
        if event_id in seen:
            partial |= seen[event_id] != identity
            continue
        seen[event_id] = identity
        if status.endswith("_FAILED"):
            history.append(
                {
                    "logicalId": logical,
                    "resourceType": kind,
                    "resourceStatus": status,
                    "timestamp": when,
                    "eventId": event_id,
                    **safe_reason(item.get("ResourceStatusReason")),
                }
            )
        if not boundary or when < boundary:
            continue
        previous = latest.get(logical)
        if (
            previous
            and previous["timestamp"] == when
            and previous["eventId"] != event_id
        ):
            partial = True
        if not previous or (when, event_id) > (
            previous["timestamp"],
            previous["eventId"],
        ):
            latest[logical] = {
                "logicalId": logical,
                "resourceType": kind,
                "resourceStatus": status,
                "timestamp": when,
                "eventId": event_id,
            }
    records = list(latest.values())
    active = sorted(
        (item for item in records if item["resourceStatus"].endswith("_IN_PROGRESS")),
        key=lambda item: (item["timestamp"], item["eventId"]),
        reverse=True,
    )
    failed = sorted(
        (item for item in records if item["resourceStatus"].endswith("_FAILED")),
        key=lambda item: (item["timestamp"], item["eventId"]),
        reverse=True,
    )
    history.sort(key=lambda item: (item["timestamp"], item["eventId"]), reverse=True)
    result.update(
        available=True,
        partial=partial or not counts_available,
        stale=False,
        stackId=stack_id,
        observedResources=len(records) if counts_available else None,
        countsAvailable=counts_available,
        completed=sum(item["resourceStatus"].endswith("_COMPLETE") for item in records)
        if counts_available
        else None,
        inProgress=len(active) if counts_available else None,
        failed=len(failed) if counts_available else None,
        resources=sorted(records, key=lambda item: item["logicalId"]),
        activeResources=active[:30],
        activeResourcesTruncated=len(active) > 30,
        recentFailures=history[:10],
        recentFailuresTruncated=len(history) > 10,
    )
    return result


def category(stack):
    return stack.get("classification", classify(stack.get("StackStatus", "UNKNOWN")))


def refresh(backend, units):
    for unit in units:
        state = backend.states[unit["name"]]
        current = read(backend.aws, unit["name"])
        if state.get("progress"):
            if state["progress"].get("stackId") != current.get("StackId"):
                state["progress"] = {"available": False, "partial": True, "stale": True}
            else:
                state["progress"].update(stale=True, partial=True)
        if state.get("currentStack") and identity(state["currentStack"]) != identity(
            current
        ):
            state.pop("observedSynced", None)
            state.pop("checkpointed", None)
            if state["status"] == DEPLOY_SUCCESS:
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
    if status in {"ATTEMPT_SUCCESS", "ATTEMPT_FAIL"}:
        state["status"] = DEPLOY_SUCCESS if status == "ATTEMPT_SUCCESS" else "FAILED"
        if status == "ATTEMPT_SUCCESS":
            for key in (
                "failure",
                "failureClassification",
                "failureEvents",
                "changeSetFailure",
                "eventReadStatus",
                "reason",
            ):
                state.pop(key, None)
        state.pop("failureDetected", None)
        state.pop("unexecutedReason", None)
        state.pop("attemptResult", None)
        return
    if status == "ATTEMPT_SETTLED":
        state.update(status="SETTLED", attemptResult="UNKNOWN")
        state.pop("failureDetected", None)
        state.pop("unexecutedReason", None)
        state.pop("reason", None)
        return
    if status == "UNCONFIRMED":
        state.update(
            status="BLOCKED",
            attemptResult="UNKNOWN",
            reason="settled request outcome is unconfirmed; current observation is independent",
        )
        return
    if status in FAILED or "ROLLBACK" in status:
        state["failureDetected"] = True
    if status in SUCCESS:
        state["status"] = "FAILED" if state.get("failureDetected") else DEPLOY_SUCCESS
    elif status in FAILED:
        state["status"] = "FAILED"
    elif status.endswith("_IN_PROGRESS"):
        state["status"] = DEPLOY_RUNNING
    else:
        raise Blocked("unrecognized stack status: " + status)
    if state["status"] in {DEPLOY_SUCCESS, "FAILED"}:
        state.pop("unexecutedReason", None)
        state.pop("attemptResult", None)
