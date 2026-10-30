"""Stack ownership, Change Set preparation, exact content approval and execution checks."""

import json
import time
import uuid
from functools import partial as _bind_framework_callback
from pathlib import Path

from utils.cloudformation.export_resolution import resolve_exports, stack_exports
from utils.cloudformation.format import decode
from utils.cloudformation.inputs import Blocked, condition_active, resolve_value
from utils.json_format import fingerprint

import deploy.failures as _imports_deploy_failures
from deploy.current_state import (
    SUCCESS,
    UPDATEABLE,
    category,
    pages,
    read,
    same_change_set,
)


def _callback_import_names_condition(conditions, parameters, pseudo, /, name):
    return resolve_value({"Condition": name}, parameters, pseudo, conditions=conditions)


def _recursive_import_names_visit(
    condition, conditions, names, parameters, pseudo, /, value
):
    if isinstance(value, dict):
        if "Fn::If" in value:
            argument = value["Fn::If"]
            if len(value) != 1 or not isinstance(argument, list) or len(argument) != 3:
                raise Blocked("invalid Fn::If expression")
            _recursive_import_names_visit(
                condition,
                conditions,
                names,
                parameters,
                pseudo,
                argument[1 if condition(argument[0]) else 2],
            )
            return
        for key, child in value.items():
            if key == "Fn::ImportValue":
                name = resolve_value(child, parameters, pseudo, conditions=conditions)
                if not isinstance(name, str) or not name:
                    raise Blocked("ImportValue name must be nonempty")
                names.add(name)
            else:
                _recursive_import_names_visit(
                    condition, conditions, names, parameters, pseudo, child
                )
    elif isinstance(value, list):
        for child in value:
            _recursive_import_names_visit(
                condition, conditions, names, parameters, pseudo, child
            )


def import_names(template, parameters, pseudo):
    """Resolve only stack-independent intrinsic expressions; unknown expressions block."""
    names = set()
    conditions = template.get("Conditions", {})
    condition = _bind_framework_callback(
        _callback_import_names_condition, conditions, parameters, pseudo
    )

    visit = _bind_framework_callback(
        _recursive_import_names_visit, condition, conditions, names, parameters, pseudo
    )
    for section, contents in template.items():
        if section in {"Resources", "Outputs"}:
            for definition in contents.values():
                if "Condition" not in definition or condition(definition["Condition"]):
                    visit(definition)
        elif section not in {"Conditions", "Mappings", "Parameters"}:
            visit({section: contents})
    return names


def change_summary(change_set):
    result = []
    for change in change_set.get("Changes", []):
        resource = change.get("ResourceChange", {})
        if resource.get("Action") not in {"Add", "Modify", "Remove"}:
            raise Blocked("unknown change set action")
        if resource.get("Action") == "Modify" and resource.get("Replacement") not in {
            "True",
            "False",
            "Conditional",
        }:
            raise Blocked("unknown change set replacement")
        result.append(
            {
                key: resource.get(key)
                for key in (
                    "LogicalResourceId",
                    "PhysicalResourceId",
                    "ResourceType",
                    "Action",
                    "Replacement",
                    "PolicyAction",
                )
            }
        )
    return sorted(result, key=lambda item: item["LogicalResourceId"] or "")


def check_imports(target, templates, states, aws, unit, exports=None):
    document, parameters = templates[unit["name"]]
    names = import_names(
        document,
        parameters,
        {
            "AWS::AccountId": target.get(
                "awsExecutionAccountId", target["awsAccountId"]
            ),
            "AWS::Region": target["awsRegion"],
            "AWS::StackName": unit["name"],
        },
    )
    if names:
        exports = (
            resolve_exports(
                aws,
                names,
                hints=states.get(unit["name"], {})
                .get("delivery", {})
                .get("imports", {}),
            )
            if exports is None
            else exports
        )
        missing = names - exports.keys()
        if missing:
            raise Blocked(
                "designed DeployOrder conflicts with Import/Export: missing export / producer deploy required: "
                + ", ".join(sorted(missing))
                + "; scope/order unchanged"
            )
        for name in names:
            owner = (
                exports[name]
                .get("ExportingStackId", "")
                .split(":stack/")[-1]
                .split("/")[0]
            )
            if owner in states and states[owner]["status"] != "SUCCESS":
                raise Blocked(
                    f"designed DeployOrder conflicts with Import/Export: producer {owner} has not succeeded"
                )


def describe_change_set(aws, unit, state):
    return aws(
        "describe_change_set",
        StackName=unit["name"],
        ChangeSetName=state["changeSetId"],
    )


def verify_stack_ownership(aws, templates, unit):
    """Inspect the exact designed stack, never enumerate unrelated stacks."""
    actuals = [
        item
        for item in pages(
            aws,
            "list_stack_resources",
            "StackResourceSummaries",
            StackName=unit["name"],
        )
        if item.get("ResourceStatus") != "DELETE_COMPLETE"
    ]
    actual_by_id = {item["LogicalResourceId"]: item for item in actuals}
    if len(actual_by_id) != len(actuals):
        raise Blocked("existing stack has ambiguous resource ownership")
    document, _ = templates[unit["name"]]
    for logical, definition in document.get("Resources", {}).items():
        if (
            logical in actual_by_id
            and actual_by_id[logical]["ResourceType"] != definition["Type"]
        ):
            raise Blocked(
                f"existing stack resource type differs from designed ownership: {unit['name']}/{logical}"
            )


def begin_prepare(
    unit,
    state,
    aws,
    save,
    check_imports,
    template_arguments,
    cleanup_failed_create,
    reset_after_cleanup,
    verify_stack_ownership,
    paths,
):
    state.setdefault("preparationId", uuid.uuid4().hex)
    boundary = {}
    check_imports(
        unit, boundary=boundary
    )  # Fresh Create boundary, never shared across approval waits.
    if state.get("cleanupStatus") == "DELETE_INTENT":
        if not cleanup_failed_create(unit, state, empty_only=True):
            raise Blocked(
                "failed CREATE resources are not all deleted; cleanup requires human"
            )
        state["emptyStackRecreated"] = True
        reset_after_cleanup(state, retain_delivery=True)
        state.setdefault("preparationId", uuid.uuid4().hex)
        boundary = {}
        check_imports(unit, boundary=boundary)
    arguments = template_arguments(unit, state, boundary=boundary)
    resubmit = state.pop("createUnconfirmed", False)
    if not state.get("changeSetId") or resubmit:
        current = read(aws, unit["name"])
        if current["StackStatus"] == "UNKNOWN":
            raise Blocked("current Stack state is unavailable")
        stack = None if category(current) == "ABSENT" else current
        if stack and stack["StackStatus"] == "ROLLBACK_COMPLETE":
            if state.get("stackId") and state["stackId"] != stack["StackId"]:
                raise Blocked("failed CREATE stack identity changed")
            state.update(stackStatus="ROLLBACK_COMPLETE", stackId=stack["StackId"])
            save()
            if not cleanup_failed_create(unit, state, empty_only=True):
                raise Blocked(
                    "failed CREATE resources are not all deleted; cleanup requires human"
                )
            state["emptyStackRecreated"] = True
            reset_after_cleanup(state, retain_delivery=True)
            state.setdefault("preparationId", uuid.uuid4().hex)
            boundary = {}
            check_imports(unit, boundary=boundary)
            arguments = template_arguments(unit, state, boundary=boundary)
            stack = None
        if stack and category(stack) == "RUNNING":
            state.update(stackId=stack["StackId"], externalOperation=True)
            return "RUNNING"  # Observe an already-running AWS operation before preparing new inputs.
        if stack and stack["StackStatus"] not in UPDATEABLE | {"REVIEW_IN_PROGRESS"}:
            raise Blocked(f"stack not updateable: {stack['StackStatus']}")
        if stack:
            verify_stack_ownership(unit)
        _, parameters = paths(unit)
        aws("validate_template", **arguments)
        state.setdefault("successfulPreparationOperations", {})["validate_template"] = (
            state["preparationId"]
        )
        if not resubmit:
            state["operationType"] = (
                "UPDATE"
                if stack and stack["StackStatus"] != "REVIEW_IN_PROGRESS"
                else "CREATE"
            )
            state["absentBeforeCreate"] = stack is None
            state["changeSetId"] = "blueprint-" + uuid.uuid4().hex
            state["changeSetStarted"] = time.time()
        save()
        started = time.perf_counter()
        response = aws(
            "create_change_set",
            StackName=unit["name"],
            ChangeSetName=state["changeSetId"],
            ChangeSetType=state["operationType"],
            ClientToken=state["preparationId"],
            **arguments,
            Parameters=json.loads(parameters.read_text(encoding="utf-8")),
            Capabilities=["CAPABILITY_NAMED_IAM"],
        )
        state["changeSetId"] = response["Id"]
        state["stackId"] = response.get("StackId")
        state["changeSetCreateSeconds"] = time.perf_counter() - started
        save()
    return "CHANGESET_CREATING"


def no_changes(change_set):
    return change_set.get("Status") == "FAILED" and any(
        text in change_set.get("StatusReason", "")
        for text in ("didn't contain changes", "No updates are to be performed")
    )


def verify_no_change_state(name, state):
    """A no-change UPDATE cannot have any saved execution or approval contract."""
    if (
        state.get("operationType") != "UPDATE"
        or state.get("absentBeforeCreate") is not False
        or any(
            not isinstance(state.get(key), str) or not state[key].strip()
            for key in ("stackId", "changeSetId")
        )
        or any(
            state.get(key) is not None
            for key in (
                "executionEvidence",
                "executionStarted",
                "clientToken",
                "changeDigest",
                "approvedChangeDigest",
            )
        )
    ):
        raise Blocked("not a saved unexecuted no-change UPDATE: " + name)


def verify_no_change(name, state, change_set):
    """Require complete identity and non-execution evidence for an existing UPDATE."""
    verify_no_change_state(name, state)
    if (
        not no_changes(change_set)
        or change_set.get("ExecutionStatus") != "UNAVAILABLE"
        or change_set.get("Changes") != []
        or change_set.get("NextToken") is not None
        or change_set.get("ChangeSetId") != state["changeSetId"]
        or change_set.get("StackId") != state["stackId"]
        or change_set.get("StackName") != name
    ):
        raise Blocked("cannot prove the saved unexecuted no-change UPDATE: " + name)


def verify_no_change_completion(aws, unit, state, change_set):
    verify_no_change(unit["name"], state, change_set)
    response = aws("describe_stacks", StackName=unit["name"])
    stacks = response.get("Stacks", [])
    if (
        response.get("NextToken") is not None
        or len(stacks) != 1
        or stacks[0].get("StackStatus") not in UPDATEABLE
    ):
        raise Blocked("no-change stack has no terminal success evidence")
    stack = stacks[0]
    if stack.get("StackId") != state["stackId"]:
        raise Blocked("no-change Stack ID differs from saved ChangeSet target")
    return stack["StackStatus"]


def review_prepared(unit, state, approvals, aws, describe_change_set, change_set=None):
    change_set = describe_change_set(unit, state) if change_set is None else change_set
    if change_set.get("ChangeSetId") and not same_change_set(
        state.get("changeSetId"), change_set["ChangeSetId"]
    ):
        raise Blocked("current ChangeSet identity differs from submitted request")
    if (
        state.get("stackId")
        and change_set.get("StackId")
        and state["stackId"] != change_set["StackId"]
    ):
        raise Blocked("current Stack identity differs from submitted request")
    if change_set.get("ChangeSetId"):
        state["changeSetId"] = change_set["ChangeSetId"]
    if change_set["Status"] in {"CREATE_PENDING", "CREATE_IN_PROGRESS"}:
        return "CHANGESET_CREATING"
    state["changeSetWaitSeconds"] = max(
        0,
        time.time()
        - state.get("changeSetStarted", time.time())
        - state.get("changeSetCreateSeconds", 0),
    )
    if no_changes(change_set):
        state["stackStatus"] = verify_no_change_completion(aws, unit, state, change_set)
        state["noChangeCandidate"] = change_set
        state["reason"] = "no changes; existing stack terminal success"
        return "SUCCESS"
    if (
        change_set["Status"] != "CREATE_COMPLETE"
        or change_set["ExecutionStatus"] != "AVAILABLE"
    ):
        failures = _imports_deploy_failures
        diagnostic = failures.event(
            {"ResourceStatusReason": change_set.get("StatusReason", "")}, {}
        )
        state["changeSetFailure"] = {
            "status": change_set["Status"],
            "executionStatus": change_set.get("ExecutionStatus"),
            "code": diagnostic["code"],
            "reasonDigest": diagnostic["reasonDigest"],
        }
        code = diagnostic["code"]
        classification = (
            "AUTHORIZATION"
            if code in failures.AUTH_CODES
            else "IAC_CANDIDATE"
            if change_set["Status"] == "FAILED"
            and code in {"InvalidRequest", "InvalidParameter", "ValidationError"}
            else "NEEDS_HUMAN"
        )
        error = Blocked(
            "change set is not CREATE_COMPLETE/AVAILABLE; inspect safe structured changeSetFailure"
        )
        error.deploy_failure = {
            "stage": "CHANGESET_REVIEW",
            "service": "cloudformation",
            "operation": "create_change_set",
            "code": code,
            "classification": classification,
            "executionState": "NOT_EXECUTED",
        }
        raise error
    if state.get("preparationId"):
        state.setdefault("successfulPreparationOperations", {})["create_change_set"] = (
            state["preparationId"]
        )
    summary = change_summary(change_set)
    digest = fingerprint(change_set.get("Changes", []))
    if state.get("changeDigest") and digest != state["changeDigest"]:
        raise Blocked("same change set contents changed; previous approval invalid")
    state["changeDigest"], state["changes"] = digest, summary
    destructive = any(
        item["Action"] == "Remove" or item["Replacement"] in {"True", "Conditional"}
        for item in summary
    )
    if destructive and state["changeSetId"] not in approvals:
        state["failureClassification"] = "HUMAN_REQUIRED"
        state["failure"] = {
            "classification": "APPROVAL",
            "stage": "CHANGESET_REVIEW",
            "executionState": "NOT_EXECUTED",
        }
        state["reason"] = (
            "unapproved delete/replacement; change set unexecuted; human confirmation required"
        )
        return "BLOCKED"
    state["approvedChangeDigest"] = digest
    state.pop("reason", None)
    state.pop("failure", None)
    return "READY"


def verify_execution(
    unit,
    state,
    expected,
    input_digest,
    file_digest,
    template_arguments,
    check_imports,
    describe_change_set,
    boundary=None,
):
    boundary = {} if boundary is None else boundary
    if expected is not None and input_digest(unit, fresh=True) != expected:
        state["status"] = "BLOCKED"
        raise Blocked("deployment inputs changed before execution")
    if (
        state.get("delivery")
        and file_digest(Path(state["delivery"]["path"]), fresh=True)
        != state["delivery"]["templateSha256"]
    ):
        state["status"] = "BLOCKED"
        raise Blocked("prepared deployment template changed")
    try:
        template_arguments(unit, state, boundary=boundary)
    except Blocked:
        state["status"] = (
            "BLOCKED"  # No stack execution was sent; drain only already-running peers.
        )
        raise
    check_imports(unit, boundary=boundary)
    current = describe_change_set(unit, state)
    if (
        current["Status"] != "CREATE_COMPLETE"
        or current["ExecutionStatus"] != "AVAILABLE"
        or fingerprint(current.get("Changes", [])) != state["changeDigest"]
    ):
        state["status"] = "BLOCKED"
        raise Blocked(
            "change set expired or changed before execution; approval invalid"
        )

    if (
        current.get("ChangeSetId") != state["changeSetId"]
        or current.get("StackId") != state["stackId"]
    ):
        state["status"] = "BLOCKED"
        raise Blocked("latest ChangeSet/Stack identity differs from saved execution")
    if state.get("approvedChangeDigest") != state["changeDigest"]:
        state["status"] = "BLOCKED"
        raise Blocked("same ChangeSet content has not been approved")
    return current


def record_execution(aws, unit, state, current, input_digest):
    resources = change_summary(current)
    missing = [
        item
        for item in resources
        if item["Action"] == "Remove" and not item.get("PhysicalResourceId")
    ]
    if missing:
        actuals = aws("list_stack_resources", StackName=current["StackId"])[
            "StackResourceSummaries"
        ]
        for item in missing:
            candidates = [
                actual
                for actual in actuals
                if actual.get("LogicalResourceId") == item["LogicalResourceId"]
                and actual.get("ResourceType") == item["ResourceType"]
                and actual.get("PhysicalResourceId")
            ]
            if len(candidates) == 1:
                item["PhysicalResourceId"] = candidates[0]["PhysicalResourceId"]
    return {
        "StackId": current["StackId"],
        "ChangeSetId": current["ChangeSetId"],
        "changeDigest": state["changeDigest"],
        "clientToken": state["clientToken"],
        "inputDigest": input_digest,
        "resources": resources,
    }


class OutputNotReflected(Blocked):
    """AWS completed the operation but did not expose the intended Output contract."""


def required_outputs(document, parameters, target, name):
    pseudo = {
        "AWS::StackName": name,
        "AWS::Region": target["awsRegion"],
        "AWS::AccountId": target.get("awsExecutionAccountId", target["awsAccountId"]),
    }
    result = {}
    for key, definition in document.get("Outputs", {}).items():
        if not condition_active(document, parameters, pseudo, definition):
            continue
        export = (
            resolve_value(
                definition["Export"]["Name"],
                parameters,
                pseudo,
                conditions=document.get("Conditions", {}),
            )
            if "Export" in definition
            else None
        )
        try:
            value = resolve_value(
                definition["Value"],
                parameters,
                pseudo,
                conditions=document.get("Conditions", {}),
            )
            value_digest = fingerprint(str(value))
        except Blocked:
            # Resource identifiers are verified through the deployed template and AWS Outputs.
            value_digest = None
        result[key] = {
            "export": export,
            "definitionDigest": fingerprint(definition),
            "valueDigest": value_digest,
        }
    return result


def verify_outputs(aws, unit, state, expected):
    """Outputs-only changes are successful only when AWS exposes every required Output/Export."""
    if not expected:
        return
    response = aws("describe_stacks", StackName=state["stackId"])
    stacks = response.get("Stacks") if isinstance(response, dict) else None
    if (
        not isinstance(stacks, list)
        or len(stacks) != 1
        or response.get("NextToken") is not None
    ):
        raise Blocked("Output verification Stack evidence is incomplete")
    stack = stacks[0]
    if (
        stack.get("StackId") != state["stackId"]
        or stack.get("StackStatus") not in SUCCESS
    ):
        raise Blocked("Output verification Stack identity/state changed")
    try:
        exports = stack_exports(stack, state["stackId"])
    except Blocked as error:
        raise OutputNotReflected(
            "AWS Output/Export not reflected: " + str(error)
        ) from None
    outputs = {item["OutputKey"]: item for item in stack.get("Outputs", [])}
    deployed = aws("get_template", StackName=state["stackId"])["TemplateBody"]
    if isinstance(deployed, str):
        deployed, errors = decode(deployed)
        if errors:
            raise Blocked("AWS deployed Output definitions cannot be verified")
    if not isinstance(deployed, dict):
        raise Blocked("AWS deployed Output definitions unavailable")
    for key, record in expected.items():
        export = record["export"]
        if (
            fingerprint(deployed.get("Outputs", {}).get(key))
            != record["definitionDigest"]
        ):
            raise OutputNotReflected(
                "AWS Output definition not reflected: " + unit["name"] + "/" + key
            )
        actual = outputs.get(key)
        if not actual or not isinstance(actual.get("OutputValue"), str):
            raise OutputNotReflected(
                "AWS output not reflected: " + unit["name"] + "/" + key
            )
        if (
            record["valueDigest"] is not None
            and fingerprint(actual["OutputValue"]) != record["valueDigest"]
        ):
            raise OutputNotReflected(
                "AWS output value not reflected: " + unit["name"] + "/" + key
            )
        if export is not None:
            entry = exports.get(export)
            if (
                not isinstance(export, str)
                or not export
                or actual.get("ExportName") != export
                or not entry
                or entry.get("ExportingStackId") != state["stackId"]
                or entry.get("Value") != actual["OutputValue"]
            ):
                raise OutputNotReflected("AWS Export not reflected: " + str(export))
