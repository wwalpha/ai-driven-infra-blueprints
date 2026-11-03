"""Safe structured failure evidence; cause diagnosis belongs to the supervising LLM."""

from __future__ import annotations

import copy
import re

from contracts.deploy import DEPLOY_RUNNING
from contracts.model import REFERENCE_PENDING_DEPLOY
from model.core import ReferenceDiagnosticError
from utils.cloudformation.environment import EnvironmentValuePending
from utils.json_format import fingerprint
from utils.type_contracts import JsonObject
from utils.type_contracts import JsonValue as JsonValue

from deploy.guards import secret_value_missing
from deploy.typing import AwsResponse, StackState
from deploy.typing import AwsValue as AwsValue

# A transport failure, approval wait or guard failure never becomes an IaC failure.
AUTH_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
}

HANDLER_CODES = AUTH_CODES | {
    "AlreadyExists",
    "NotFound",
    "InvalidRequest",
    "InvalidParameter",
    "ValidationError",
    "AccessDenied",
    "GeneralServiceException",
    "ServiceInternalError",
    "ServiceLimitExceeded",
    "Throttling",
    "NotUpdatable",
    "ResourceConflict",
    "NetworkFailure",
    "NotStabilized",
    "InternalFailure",
    "ReadTimeoutError",
    "EndpointConnectionError",
    "ConnectionClosedError",
}


def safe_reason(reason):
    """Return only recognized evidence, never AWS prose or untrusted error values."""
    reason = reason if isinstance(reason, str) else ""
    match = re.search(r"HandlerErrorCode:\s*([A-Za-z][A-Za-z0-9]+)", reason)
    code = match.group(1) if match and match.group(1) in HANDLER_CODES else None
    if not code and re.search(
        r"\b(access denied|not authorized|accessdenied)\b", reason, re.IGNORECASE
    ):
        code = "AccessDenied"
    if secret_value_missing(reason):
        message = "A required current secret value is missing."
    elif code:
        message = f"CloudFormation reported error {code}."
    else:
        message = (
            "The specific AWS reason is unavailable or cannot be safely displayed."
        )
    return {"code": code, "message": message, "reasonRedacted": bool(reason)}


def exception_message(error):
    code = getattr(error, "code", None)
    if code in AUTH_CODES:
        return f"AWS access was denied or credentials were rejected ({code})."
    if code in {"ReadTimeoutError", "EndpointConnectionError", "ConnectionClosedError"}:
        return f"AWS request transport failed ({code}); its outcome may be unconfirmed."
    if str(error) == "busy":
        return "busy"
    if str(error) == "unsafe rollback state; no automatic delete or ResourcesToSkip":
        return str(error)
    if "missing Export" in str(error):
        return "A required CloudFormation import has a missing Export; review the producer."
    if "inputs changed" in str(error):
        return "Deployment inputs changed; review the fixed inputs."
    return "The operation could not be confirmed; inspect the structured diagnostic."


def dependency_wait(error: Exception) -> bool:
    return isinstance(error, EnvironmentValuePending) or (
        isinstance(error, ReferenceDiagnosticError)
        and bool(error.diagnostics)
        and all(
            d.get("category") == REFERENCE_PENDING_DEPLOY for d in error.diagnostics
        )
    )


def exception(state: StackState, error: Exception, stage: str) -> None:
    if hasattr(error, "deploy_failure"):
        state["failure"] = copy.deepcopy(error.deploy_failure)
        return
    code = getattr(error, "code", None)
    service = getattr(error, "deploy_service", None)
    operation = getattr(error, "deploy_operation", None)
    classification = (
        "AUTHORIZATION"
        if code in AUTH_CODES
        else "IAC_CANDIDATE"
        if service == "cloudformation"
        and operation in {"validate_template", "create_change_set"}
        and code in {"ValidationError", "ValidationException"}
        else "INPUT_CANDIDATE"
        if stage == "INPUT_DECODE"
        else "SUBMISSION_UNKNOWN"
        if state.get("status") == DEPLOY_RUNNING
        else "NEEDS_HUMAN"
    )
    state["failure"] = {
        "stage": stage,
        "service": service,
        "operation": operation,
        "code": code if code in HANDLER_CODES | {"InputDecodeError"} else None,
        "classification": classification,
        "executionState": "UNKNOWN"
        if state.get("status") == DEPLOY_RUNNING
        else "NOT_EXECUTED",
        "message": exception_message(error),
        "requiredAction": "Review the operation and its available evidence before deciding how to continue.",
        "retryable": False,
    }

    if dependency_wait(error):
        state["failure"]["dependencyWait"] = True


def event(event: AwsResponse, document: AwsResponse) -> JsonObject:
    logical = event.get("LogicalResourceId")
    reason = event.get("ResourceStatusReason") or ""
    # Keep names only when confirmed by the authored template. Never persist raw AWS prose.
    properties = document.get("Resources", {}).get(logical, {}).get("Properties", {})
    mentioned = [
        key
        for key in properties
        if re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])", reason
        )
    ]
    diagnostic = safe_reason(reason)
    result = {
        key: event.get(key)
        for key in ("LogicalResourceId", "ResourceType", "ResourceStatus", "EventId")
    }
    result.update(
        resourcePath=event.get("ResourcePath", logical),
        properties=sorted(mentioned),
        code=diagnostic["code"],
        message=diagnostic["message"],
        reasonRedacted=diagnostic["reasonRedacted"],
        timestamp=str(event["Timestamp"]) if event.get("Timestamp") else None,
        stackEvent=bool(
            event.get("StackId")
            and event.get("PhysicalResourceId") == event.get("StackId")
        ),
        reasonDigest=fingerprint(reason),
    )
    if secret_value_missing(reason):
        result["ResourceStatusReason"] = "SECRET_CURRENT_VALUE_MISSING"
    else:
        result["ResourceStatusReason"] = "STRUCTURED_RESOURCE_FAILURE"
    return result


def diagnostic(state):
    """Describe saved evidence without changing the attempt or requesting AWS."""
    failure = state.get("failure") or {}
    events = state.get("failureEvents") or []
    current = state.get("currentStack") or {}
    event_read_failed = state.get("eventReadStatus") == "EVENT_READ_FAILED"
    candidates = [
        item
        for item in events
        if item.get("ResourceStatus") in {"CREATE_FAILED", "UPDATE_FAILED"}
        and item.get("timestamp")
        and not item.get("stackEvent")
    ]
    root = min(candidates, key=lambda item: item["timestamp"]) if candidates else None
    if root and sum(item["timestamp"] == root["timestamp"] for item in candidates) > 1:
        root = None
    pending = (
        state.get("requestPending")
        or state.get("attemptResult") == "UNKNOWN"
        or failure.get("classification") == "SUBMISSION_UNKNOWN"
    )
    operation = None
    if not (
        failure
        or events
        or pending
        or event_read_failed
        or state.get("failureClassification")
        or state.get("status") in {"FAILED", "BLOCKED"}
    ):
        return None
    if failure.get("classification") == "APPROVAL":
        message = failure.get("message") or "The ChangeSet requires Human approval."
        action = (
            failure.get("requiredAction")
            or "Review the listed changes and approve or reject the ChangeSet."
        )
        code, stage, source = "APPROVAL_REQUIRED", "CHANGESET_REVIEW", "CHANGE_SET"
    elif root:
        message = (
            root.get("message")
            or "CloudFormation reported a Resource failure; the reason is unavailable."
        )
        action = "Review the failure evidence and request a correction if needed."
        code, stage, source = (
            root.get("code") or "UNKNOWN_REASON",
            "STACK_EXECUTION",
            "STACK_EVENT",
        )
    elif pending:
        operation = failure.get("operation") or state.get("endedRequest", {}).get(
            "request", {}
        ).get("operation")
        if operation not in {
            "create_change_set",
            "execute_change_set",
            "delete_stack",
            "continue_update_rollback",
            "put_secret_value",
            "update_secret_version_stage",
        }:
            operation = None
        message = f"The AWS {operation or 'request'} outcome is not yet confirmed."
        action = "Review the current request and AWS observation before deciding how to continue."
        code, stage, source = (
            failure.get("code")
            if failure.get("code") in HANDLER_CODES
            else "REQUEST_UNCONFIRMED",
            failure.get("stage") or "STACK_EXECUTION",
            "REQUEST",
        )
    elif event_read_failed:
        message = "Stack events could not be read; the failure cause is unconfirmed."
        action = "Review event read access and inspect the current AWS operation."
        code, stage, source = "EVENT_READ_FAILED", "STACK_EXECUTION", "STACK_EVENT"
    elif events and not failure and not state.get("changeSetFailure"):
        message = "The observed events do not establish the initial Resource failure."
        action = "Review the available Stack events before deciding how to continue."
        code, stage, source = "UNKNOWN_REASON", "STACK_EXECUTION", "STACK_EVENT"
    else:
        detail = state.get("changeSetFailure") or current.get("statusReason") or failure
        message = (
            detail.get("message")
            or "The operation stopped; a specific safe cause is not available."
        )
        action = (
            failure.get("requiredAction")
            or "Review the operation and available evidence before deciding how to continue."
        )
        code = detail.get("code") or failure.get("code") or "UNKNOWN_REASON"
        if code not in HANDLER_CODES | {"InputDecodeError", "UNKNOWN_REASON"}:
            code = "UNKNOWN_REASON"
        stage = failure.get("stage") or "STACK_EXECUTION"
        source = (
            "CHANGE_SET"
            if state.get("changeSetFailure")
            else "STACK_STATUS"
            if current.get("statusReason")
            else "CONTROLLER"
        )
    result = {
        "classification": state.get("failureClassification")
        or failure.get("classification")
        or ("REQUEST_UNCONFIRMED" if pending else "NEEDS_DIAGNOSIS"),
        "stage": stage,
        "code": code,
        "message": message,
        "requiredAction": action,
        "retryable": False,
        "source": source,
        "reasonRedacted": bool(
            (
                root
                or state.get("changeSetFailure")
                or current.get("statusReason")
                or failure
            ).get("reasonRedacted")
        ),
        "resource": {"StackId": state.get("stackId")},
        "eventReadStatus": state.get("eventReadStatus", "NOT_OBSERVED"),
    }
    if root:
        result["resource"].update(
            {
                key: root.get(key)
                for key in ("LogicalResourceId", "ResourceType", "ResourceStatus")
            }
        )
        result.update(eventId=root.get("EventId"), timestamp=root.get("timestamp"))
    if pending and not root and operation:
        result["operation"] = operation
    return result


def template_safety(document: AwsResponse) -> JsonObject:
    return {
        "Resources": {
            key: {
                field: value
                for field, value in resource.items()
                if field in {"Type", "DeletionPolicy", "UpdateReplacePolicy"}
            }
            for key, resource in document.get("Resources", {}).items()
        }
    }
