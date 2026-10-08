"""Stack ownership, Change Set preparation, exact content approval and execution checks."""
import time
import uuid
from pathlib import Path

from cloudformation_inputs import Blocked, resolve_value
from iac_values import fingerprint
from deployment.scheduler import SUCCESS


def import_names(template, parameters, pseudo):
    """Resolve only stack-independent intrinsic expressions; unknown expressions block."""
    names = set()
    conditions = template.get("Conditions", {})
    def condition(name):
        return resolve_value({"Condition": name}, parameters, pseudo, conditions=conditions)

    def visit(value):
        if isinstance(value, dict):
            if "Fn::If" in value:
                argument = value["Fn::If"]
                if len(value) != 1 or not isinstance(argument, list) or len(argument) != 3:
                    raise Blocked("invalid Fn::If expression")
                visit(argument[1 if condition(argument[0]) else 2])
                return
            for key, child in value.items():
                if key == "Fn::ImportValue":
                    name = resolve_value(child, parameters, pseudo, conditions=conditions)
                    if not isinstance(name, str) or not name:
                        raise Blocked("ImportValue name must be nonempty")
                    names.add(name)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
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
        if resource.get("Action") == "Modify" and resource.get("Replacement") not in {"True", "False", "Conditional"}:
            raise Blocked("unknown change set replacement")
        result.append({key: resource.get(key) for key in
                       ("LogicalResourceId", "PhysicalResourceId", "ResourceType", "Action", "Replacement", "PolicyAction")})
    return sorted(result, key=lambda item: item["LogicalResourceId"] or "")


def check_imports(target, templates, states, aws, unit):
    document, parameters = templates[unit["name"]]
    names = import_names(document, parameters, {"AWS::AccountId": target.get("awsExecutionAccountId", target["awsAccountId"]),
        "AWS::Region": target["awsRegion"], "AWS::StackName": unit["name"]})
    if names:
        exports = {entry["Name"]: entry for entry in aws("list-exports").get("Exports", [])}
        missing = names - exports.keys()
        if missing:
            raise Blocked("designed DeployOrder conflicts with Import/Export: missing export / producer deploy required: "
                          + ", ".join(sorted(missing)) + "; scope/order unchanged")
        for name in names:
            owner = exports[name].get("ExportingStackId", "").split(":stack/")[-1].split("/")[0]
            if owner in states and states[owner]["status"] != "SUCCESS":
                raise Blocked(f"designed DeployOrder conflicts with Import/Export: producer {owner} has not succeeded")


def describe_change_set(aws, unit, state):
    return aws("describe-change-set", "--stack-name", unit["name"], "--change-set-name", state["changeSetId"])


def verify_stack_ownership(aws, templates, unit):
    """Inspect the exact designed stack, never enumerate unrelated stacks."""
    actuals = aws("list-stack-resources", "--stack-name", unit["name"]).get("StackResourceSummaries", [])
    actual_by_id = {item["LogicalResourceId"]: item for item in actuals}
    if len(actual_by_id) != len(actuals):
        raise Blocked("existing stack has ambiguous resource ownership")
    document, _ = templates[unit["name"]]
    for logical, definition in document.get("Resources", {}).items():
        if logical in actual_by_id and actual_by_id[logical]["ResourceType"] != definition["Type"]:
            raise Blocked(f"existing stack resource type differs from designed ownership: {unit['name']}/{logical}")


def begin_prepare(unit, state, aws, save, check_imports, template_arguments, cleanup_failed_create,
        reset_after_cleanup, verify_stack_ownership, paths):
    check_imports(unit)  # Also recheck when resuming an approved change set.
    if state.get('cleanupStatus') == 'DELETE_INTENT':
        if not cleanup_failed_create(unit, state, empty_only=True):
            raise Blocked('failed CREATE resources are not all deleted; cleanup requires human')
        state['emptyStackRecreated'] = True
        reset_after_cleanup(state)
    arguments = template_arguments(unit, state)
    if not state.get("changeSetId"):
        try:
            stack = aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]
        except Blocked as error:
            if "does not exist" not in str(error):
                raise
            stack = None
        if stack and state.get('cleanupStatus') == 'DELETE_COMPLETE':
            raise Blocked('failed CREATE name was reused after cleanup; never adopt another stack')
        if stack and stack['StackStatus'] == 'ROLLBACK_COMPLETE':
            if state.get('stackId') and state['stackId'] != stack['StackId']:
                raise Blocked('failed CREATE stack identity changed')
            state.update(stackStatus='ROLLBACK_COMPLETE', stackId=stack['StackId'])
            save()
            if not cleanup_failed_create(unit, state, empty_only=True):
                raise Blocked('failed CREATE resources are not all deleted; cleanup requires human')
            state['emptyStackRecreated'] = True
            reset_after_cleanup(state)
            arguments = template_arguments(unit, state)
            stack = None
        if stack and stack["StackStatus"] not in SUCCESS | {"UPDATE_ROLLBACK_COMPLETE"}:
            raise Blocked(f"stack not updateable: {stack['StackStatus']}")
        if stack:
            verify_stack_ownership(unit)
        _, parameters = paths(unit)
        aws("validate-template", *arguments)
        state["operationType"] = "UPDATE" if stack else "CREATE"
        state["absentBeforeCreate"] = stack is None
        state["changeSetId"] = "blueprint-" + uuid.uuid4().hex
        state["changeSetStarted"] = time.time()
        save()
        started = time.perf_counter()
        response = aws("create-change-set", "--stack-name", unit["name"],
            "--change-set-name", state["changeSetId"],
            "--change-set-type", "UPDATE" if stack else "CREATE",
            *arguments, "--parameters", "file://" + str(parameters),
            "--capabilities", "CAPABILITY_NAMED_IAM")
        state["changeSetId"] = response["Id"]
        state["stackId"] = response.get("StackId")
        state["changeSetCreateSeconds"] = time.perf_counter() - started
        save()
    return "CHANGESET_CREATING"


def review_prepared(unit, state, approvals, aws, describe_change_set, change_set=None):
    change_set = describe_change_set(unit, state) if change_set is None else change_set
    if change_set["Status"] in {"CREATE_PENDING", "CREATE_IN_PROGRESS"}:
        return "CHANGESET_CREATING"
    state["changeSetWaitSeconds"] = max(0, time.time() - state.get("changeSetStarted", time.time())
                                         - state.get("changeSetCreateSeconds", 0))
    if change_set["Status"] == "FAILED" and any(text in change_set.get("StatusReason", "") for text in
            ("didn't contain changes", "No updates are to be performed")):
        if aws("describe-stacks", "--stack-name", unit["name"])["Stacks"][0]["StackStatus"] in SUCCESS:
            state["reason"] = "no changes; existing stack terminal success"
            return "SUCCESS"
    if change_set["Status"] != "CREATE_COMPLETE" or change_set["ExecutionStatus"] != "AVAILABLE":
        raise Blocked("change set is not CREATE_COMPLETE/AVAILABLE: " + change_set.get("StatusReason", change_set["Status"]))
    summary = change_summary(change_set)
    digest = fingerprint(change_set.get("Changes", []))
    if state.get("changeDigest") and digest != state["changeDigest"]:
        raise Blocked("same change set contents changed; previous approval invalid")
    state["changeDigest"], state["changes"] = digest, summary
    destructive = any(item["Action"] == "Remove" or item["Replacement"] in {"True", "Conditional"} for item in summary)
    if destructive and state["changeSetId"] not in approvals:
        state["failureClassification"] = "HUMAN_REQUIRED"
        state["reason"] = "unapproved delete/replacement; change set unexecuted; human confirmation required"
        return "BLOCKED"
    state.pop("reason", None)
    return "READY"


def verify_execution(unit, state, expected, input_digest, file_digest, template_arguments, check_imports,
        describe_change_set):
    if expected is not None and input_digest(unit, fresh=True) != expected:
        state["status"] = "BLOCKED"
        raise Blocked("deployment inputs changed before execution")
    if state.get("delivery") and file_digest(Path(state["delivery"]["path"]), fresh=True) != state["delivery"]["templateSha256"]:
        state["status"] = "BLOCKED"
        raise Blocked("prepared deployment template changed")
    try:
        template_arguments(unit, state)
    except Blocked:
        state['status'] = 'BLOCKED'  # No stack execution was sent; drain only already-running peers.
        raise
    check_imports(unit)
    current = describe_change_set(unit, state)
    if current["Status"] != "CREATE_COMPLETE" or current["ExecutionStatus"] != "AVAILABLE" or \
            fingerprint(current.get("Changes", [])) != state["changeDigest"]:
        state["status"] = "BLOCKED"
        raise Blocked("change set expired or changed before execution; approval invalid")

