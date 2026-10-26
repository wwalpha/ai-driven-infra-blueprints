"""Safe structured failure evidence; cause diagnosis belongs to the supervising LLM."""

from __future__ import annotations

import copy
import re

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


def dependency_wait(error: Exception) -> bool:
    return isinstance(error, EnvironmentValuePending) or (
        isinstance(error, ReferenceDiagnosticError)
        and bool(error.diagnostics)
        and all(
            d.get("category") == "REFERENCE_PENDING_DEPLOY" for d in error.diagnostics
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
        if state.get("status") == "RUNNING"
        else "NEEDS_HUMAN"
    )
    state["failure"] = {
        "stage": stage,
        "service": service,
        "operation": operation,
        "code": code,
        "classification": classification,
        "executionState": "UNKNOWN"
        if state.get("status") == "RUNNING"
        else "NOT_EXECUTED",
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
    handler = re.search(r"HandlerErrorCode:\s*([A-Za-z][A-Za-z0-9]+)", reason)
    result = {
        key: event.get(key)
        for key in ("LogicalResourceId", "ResourceType", "ResourceStatus", "EventId")
    }
    result.update(
        resourcePath=event.get("ResourcePath", logical),
        properties=sorted(mentioned),
        code=handler.group(1) if handler else None,
        reasonDigest=fingerprint(reason),
    )
    if secret_value_missing(reason):
        result["ResourceStatusReason"] = "SECRET_CURRENT_VALUE_MISSING"
    else:
        result["ResourceStatusReason"] = "STRUCTURED_RESOURCE_FAILURE"
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
