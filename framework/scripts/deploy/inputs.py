"""Pure Stack inputs and immutable file fingerprints; no AWS clients."""

import hashlib
import re
from functools import partial as _bind_framework_callback

import utils.cloudformation.inputs as _imports_cfn_inputs
import utils.project_targets as _imports_project_targets
from model.core import (
    deployment_settings,
    entries,
    positive_integer,
    stack_context,
    stack_model,
    validate_stack_field,
)
from model.render import stack_markdown
from model.sources import stack_snapshot
from task_contract_core import (
    section,
    task_snapshot,
)
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint as fingerprint

from deploy.cli_guidance import DeployStepBlocked


def check_stack_markdown(root, snapshot):
    """Check the saved Stack design and identify the first mismatched Stack field."""
    design = (
        root
        / "docs/designs"
        / snapshot.scope.environment
        / snapshot.scope.target
        / "cloudformation-stacks.md"
    )
    expected = stack_markdown(
        design, snapshot.values, root, validate_delivery=False
    ).encode("utf-8")
    actual = design.read_bytes() if design.is_file() else b""
    if hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest():
        return
    detail = "deployment settings/header/format or artifact rows differ"
    actual_lines = actual.decode("utf-8").splitlines()
    expected_lines = expected.decode("utf-8").splitlines()
    for identity, stack in entries(snapshot.values, "desired.stack."):
        marker = "| " + stack["name"] + " |"
        wanted = [line for line in expected_lines if marker in line]
        saved = [line for line in actual_lines if marker in line]
        if wanted != saved:
            detail = f"{stack_context(identity, stack)}: generated Stack row missing/duplicate or differs"
            if len(wanted) == len(saved) == 1:
                fields = (
                    "No",
                    "deployOrder",
                    "name",
                    "template",
                    "parameters",
                    "comment",
                )
                before = [cell.strip() for cell in saved[0].strip("|").split("|")]
                after = [cell.strip() for cell in wanted[0].strip("|").split("|")]
                if len(before) == len(after) == len(fields):
                    detail += "; " + ", ".join(
                        f"{field}: saved={old!r}, Model={new!r}"
                        for field, old, new in zip(fields, before, after, strict=True)
                        if old != new
                    )
            break
    raise DeployStepBlocked(
        f"{design.relative_to(root)}: stack model/generated design missing or mismatch; {detail}; run sync-model before deploy"
    )


def select_stacks(values, scope=None, *, order_from=None, order_to=None):
    """Resolve selection using only globally necessary Stack metadata."""
    if scope and (order_from is not None or order_to is not None):
        raise Blocked("--stack cannot be combined with an Order range")
    if any(value is not None and value < 1 for value in (order_from, order_to)):
        raise Blocked("Order bounds must be positive integers")
    if order_from is not None and order_to is not None and order_from > order_to:
        raise Blocked("Order range is reversed")
    stacks = entries(values, "desired.stack.")
    names = {}
    for identity, stack in stacks:
        if not {"name", "deployOrder"} <= stack.keys():
            raise Blocked(
                f"{stack_context(identity, stack)}: missing selection fields: {sorted({'name', 'deployOrder'} - stack.keys())}"
            )
        try:
            validate_stack_field("name", stack["name"])
            positive_integer(stack["deployOrder"], "DeployOrder")
        except ValueError as error:
            raise Blocked(f"{stack_context(identity, stack)}: {error}") from error
        if stack["name"] in names:
            raise Blocked(
                f"{stack_context(identity, stack)}: duplicate stack name: {stack['name']}; also desired.stack.{names[stack['name']]}"
            )
        names[stack["name"]] = identity
    if scope and (len(set(scope)) != len(scope) or set(scope) - names.keys()):
        raise Blocked("Deployment scope must contain unique designed StackName values")
    selected = [
        (identity, stack)
        for identity, stack in stacks
        if (not scope or stack["name"] in scope)
        and (order_from is None or int(stack["deployOrder"]) >= order_from)
        and (order_to is None or int(stack["deployOrder"]) <= order_to)
    ]
    if not selected:
        raise Blocked("Deployment scope selects no Stacks")
    return selected


def load_units(root, environment, directory, scope, *, snapshot=None):
    source = (
        root / "model" / environment / directory / "cloudformation-stacks.properties"
    )
    values = (snapshot or stack_snapshot(source)).values
    select_stacks(values, scope)
    if not scope:
        raise Blocked("Deployment scope must contain unique designed StackName values")
    try:
        limit, stacks = stack_model(values)
    except ValueError as error:
        raise Blocked(f"{source.relative_to(root)}: {error}") from error
    stacks = [(identity, stack) for identity, stack in stacks if stack["name"] in scope]
    settings, artifacts = deployment_settings(values)
    result = [dict(stack) for _, stack in stacks]
    for unit in result:
        if settings:
            unit.update(settings)
        assigned = [
            dict(artifact)
            for _, artifact in artifacts
            if artifact["stack"] == unit["name"]
        ]
        if assigned:
            unit["artifacts"] = assigned
    return limit, result


def paths(root, environment, directory, target, unit):
    return (
        root
        / "infra/cloudformation/templates"
        / target.get("alias", "")
        / unit["template"],
        root
        / "infra/cloudformation/parameters"
        / environment
        / directory
        / unit["parameters"],
    )


def deployment_input_paths(root, environment, directory, target, units):
    return [
        path
        for unit in units
        for path in [
            *paths(root, environment, directory, target, unit),
            *[(root / a["source"]).resolve() for a in unit.get("artifacts", [])],
        ]
    ]


def file_digest(hashes, path, fresh=False):
    stat = path.stat()
    identity = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    previous = hashes.get(path)
    if fresh or previous is None or previous[:4] != identity:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
        if (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_ino,
        ) != identity:
            raise Blocked("deployment input changed while hashing")
        hashes[path] = (*identity, digest)
    return hashes[path][4]


def _callback_task_deployment_input_paths_value(lines, /, name, optional=False):
    entries = [line for line in lines if line.startswith(f"- {name}:")]
    if optional and not entries:
        return None
    if len(entries) != 1 or not (
        match := re.fullmatch(rf"- {re.escape(name)}: `([^`]+)`", entries[0])
    ):
        raise ValueError(f"task must specify exactly one {name}")
    return match.group(1)


def task_deployment_input_paths(root):
    """Resolve deploy/update IaC offline through the controller's authoritative readers."""
    Blocked = _imports_cfn_inputs.Blocked
    load_target = _imports_project_targets.load_target_directory
    snapshot = task_snapshot(root, required=False)
    path = snapshot.path if snapshot is not None else None
    if path is None:
        return None
    text = snapshot.text
    lines = section(text, "## Task contract")
    if "- Task type: `infrastructure`" not in lines or not any(
        f"- Infrastructure phase: `{phase}`" in lines for phase in ("deploy", "update")
    ):
        return None

    value = _bind_framework_callback(_callback_task_deployment_input_paths_value, lines)

    environment = value("Target environment")
    account, alias = value("Target AWS account"), value("Target alias", optional=True)
    try:
        target = load_target(root, environment, alias or account)
        if target["awsAccountId"] != account:
            raise ValueError("task AWS account does not match project target")
        if target["iacEngine"] != "cloudformation":
            return None
        scopes = [line for line in lines if line.startswith("- Deployment scope:")]
        if len(scopes) != 1:
            raise ValueError("task must specify an exact Deployment scope")
        stacks = re.findall(r"`([^`]+)`", scopes[0])
        _, units = load_units(root, environment, alias or account, stacks)
        return set(
            deployment_input_paths(root, environment, alias or account, target, units)
        )
    except Blocked as error:
        raise ValueError(str(error)) from error
