"""Current, scoped Export proof; callers own the lifetime of each read boundary."""

import re

from utils.cloudformation.inputs import Blocked

SUCCESS = {
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "IMPORT_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE",
}

STACK_STATUSES = SUCCESS | {
    "CREATE_IN_PROGRESS",
    "CREATE_FAILED",
    "ROLLBACK_IN_PROGRESS",
    "ROLLBACK_FAILED",
    "ROLLBACK_COMPLETE",
    "DELETE_IN_PROGRESS",
    "DELETE_FAILED",
    "DELETE_COMPLETE",
    "UPDATE_IN_PROGRESS",
    "UPDATE_FAILED",
    "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
    "UPDATE_ROLLBACK_IN_PROGRESS",
    "UPDATE_ROLLBACK_FAILED",
    "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
    "REVIEW_IN_PROGRESS",
    "IMPORT_IN_PROGRESS",
    "IMPORT_ROLLBACK_IN_PROGRESS",
    "IMPORT_ROLLBACK_FAILED",
    "IMPORT_ROLLBACK_COMPLETE",
}


def stack_name(identity):
    match = re.fullmatch(
        r"arn:[^:]+:cloudformation:[^:]+:[0-9]{12}:stack/([^/]+)/[^/]+",
        identity if isinstance(identity, str) else "",
    )
    if not match:
        raise Blocked("Export Producer StackId is invalid")
    return match[1]


def stack_exports(stack, identity, *, successful=True):
    """Validate DescribeStacks evidence without depending on a Deploy runtime."""
    if not isinstance(stack, dict):
        raise Blocked("Export Producer Stack evidence unavailable")
    actual = stack.get("StackId")
    name = stack_name(actual)
    status = stack.get("StackStatus")
    if (
        (actual != identity if ":stack/" in identity else name != identity)
        or not isinstance(status, str)
        or status not in STACK_STATUSES
        or status == "DELETE_COMPLETE"
        or (successful and status not in SUCCESS)
    ):
        raise Blocked("Export Producer Stack identity/status changed")
    outputs = stack.get("Outputs", [])
    if not isinstance(outputs, list):
        raise Blocked("Export Producer Outputs unavailable")
    result, keys = {}, set()
    for output in outputs:
        if not isinstance(output, dict):
            raise Blocked("Export Producer Output is invalid")
        key, value = output.get("OutputKey"), output.get("OutputValue")
        if (
            not isinstance(key, str)
            or not key
            or key in keys
            or not isinstance(value, str)
        ):
            raise Blocked("Export Producer Outputs are incomplete or ambiguous")
        keys.add(key)
        if "ExportName" in output:
            export = output["ExportName"]
            if not isinstance(export, str) or not export or export in result:
                raise Blocked("Export Producer Export identity is ambiguous")
            result[export] = {
                "Name": export,
                "Value": value,
                "ExportingStackId": actual,
            }
    return result


def describe_exports(aws, identity, boundary, *, successful=True):
    stacks = boundary.setdefault("exportStacks", {})
    if identity not in stacks:
        response = aws("describe_stacks", StackName=identity)
        values = response.get("Stacks") if isinstance(response, dict) else None
        if (
            not isinstance(values, list)
            or len(values) != 1
            or response.get("NextToken") is not None
        ):
            raise Blocked("Export Producer Stack inventory is incomplete")
        stack_exports(values[0], identity, successful=successful)
        stacks[identity] = stacks[values[0]["StackId"]] = values[0]
        stacks[stack_name(values[0]["StackId"])] = values[0]
    return stack_exports(stacks[identity], identity, successful=successful)


def merge_hints(records):
    hints = {}
    for record in records:
        if not isinstance(record, dict):
            raise Blocked("saved Export evidence is incomplete")
        for name, entry in record.items():
            if name in hints and hints[name] != entry:
                raise Blocked("saved Export Producer/value is ambiguous: " + name)
            hints[name] = entry
    return hints


def resolve_exports(aws, names, *, hints=None, boundary=None):
    boundary = {} if boundary is None else boundary
    hints = {} if hints is None else hints
    names = set(names)
    if any(not isinstance(name, str) or not name for name in names):
        raise Blocked("required Export name is invalid")
    known = {name: hints[name] for name in names & hints.keys()}
    # Already acquired Stack evidence may identify an otherwise unknown Producer.
    acquired = {
        stack["StackId"]: stack for stack in boundary.get("exportStacks", {}).values()
    }
    discovered = {}
    for stack in acquired.values():
        for name, entry in stack_exports(
            stack, stack["StackId"], successful=False
        ).items():
            if name in names:
                if name in discovered and discovered[name] != entry:
                    raise Blocked("required Export Producer is ambiguous: " + name)
                discovered[name] = entry
                if name not in known:
                    known[name] = entry
    unknown = names - known.keys()
    if unknown:
        if "exportInventory" not in boundary:
            response = aws("list_exports")
            inventory = response.get("Exports") if isinstance(response, dict) else None
            if not isinstance(inventory, list) or response.get("NextToken") is not None:
                raise Blocked("required Export inventory is incomplete")
            boundary["exportInventory"] = inventory
        for entry in boundary["exportInventory"]:
            if isinstance(entry, dict) and entry.get("Name") in unknown:
                name = entry["Name"]
                if name in known:
                    raise Blocked("required Export identity is ambiguous: " + name)
                known[name] = entry
    if names - known.keys():
        raise Blocked("missing Export: " + ", ".join(sorted(names - known.keys())))
    result = {}
    for name, saved in known.items():
        if (
            not isinstance(saved, dict)
            or not isinstance(saved.get("Value"), str)
            or saved.get("Name", name) != name
        ):
            raise Blocked("required Export identity/value is incomplete")
        identity = saved.get("ExportingStackId")
        stack_name(identity)
        actual = describe_exports(aws, identity, boundary).get(name)
        if actual is None or any(
            actual[key] != saved.get(key) for key in ("Value", "ExportingStackId")
        ):
            raise Blocked("required Export Producer/value changed: " + name)
        result[name] = actual
    return result
