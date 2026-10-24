"""Pure Stack inputs and immutable file fingerprints; no AWS clients."""

import hashlib
import re
from functools import partial as _bind_framework_callback

import cloudformation_inputs as _imports_cloudformation_inputs
from cloudformation_inputs import Blocked
from model.core import deployment_settings, properties, stack_model
from model.files import read_model
from model.projection import deployment_bucket
from model.render import markdown_for
from task_contract_core import (
    section,
    task_snapshot,
)
from utils.json_format import fingerprint as fingerprint

import deploy.delivery as _imports_deploy_delivery


def load_units(root, environment, directory, scope):
    source = root / "model" / environment / directory / "cloudformation-stacks.properties"
    values = properties(read_model(source))
    limit, stacks = stack_model(values)
    design = root / "docs/designs" / environment / directory / "cloudformation-stacks.md"
    if design.read_text(encoding="utf-8") != markdown_for(design, values, root):
        raise Blocked("stack model/generated design mismatch; run sync-model before deploy")
    by_name = {stack["name"]: stack for _, stack in stacks}
    if not scope or len(set(scope)) != len(scope) or set(scope) - by_name.keys():
        raise Blocked("Deployment scope must contain unique designed StackName values")
    settings, artifacts = deployment_settings(values)
    selected = [dict(stack) for _, stack in stacks if stack["name"] in scope]
    for unit in selected:
        if settings:
            unit.update(settings)
            unit["templateBucket"] = deployment_bucket(settings["templateBucket"], design, root)
        assigned = [dict(artifact) for _, artifact in artifacts if artifact["stack"] == unit["name"]]
        for artifact in assigned:
            artifact["bucket"] = deployment_bucket(artifact["bucket"], design, root)
        if assigned:
            unit["artifacts"] = assigned
    return limit, selected


def paths(root, environment, directory, target, unit):
    return (root / "infra/cloudformation/templates" / target.get("alias", "") / unit["template"],
            root / "infra/cloudformation/parameters" / environment / directory / unit["parameters"])

def deployment_input_paths(root, environment, directory, target, units):
    source_path = _imports_deploy_delivery.source_path
    return [path for unit in units for path in [*paths(root, environment, directory, target, unit),
        *[source_path(root, a) for a in unit.get("artifacts", [])]]]

def file_digest(hashes, path, fresh=False):
    stat = path.stat()
    identity = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    previous = hashes.get(path)
    if fresh or previous is None or previous[:4] != identity:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino) != identity:
            raise Blocked("deployment input changed while hashing")
        hashes[path] = (*identity, digest)
    return hashes[path][4]

def _callback_task_deployment_input_paths_value(lines, /, name, optional=False):
    entries = [line for line in lines if line.startswith(f"- {name}:")]
    if optional and not entries:
        return None
    if len(entries) != 1 or not (match := re.fullmatch(rf"- {re.escape(name)}: `([^`]+)`", entries[0])):
        raise ValueError(f"task must specify exactly one {name}")
    return match.group(1)


def task_deployment_input_paths(root):
    """Resolve deploy/update IaC offline through the controller's authoritative readers."""
    Blocked = _imports_cloudformation_inputs.Blocked
    load_target = _imports_cloudformation_inputs.load_target
    snapshot = task_snapshot(root, required=False)
    path = snapshot.path if snapshot is not None else None
    if path is None:
        return None
    text = snapshot.text
    lines = section(text, "## Task contract")
    if "- Task type: `infrastructure`" not in lines or not any(
            f"- Infrastructure phase: `{phase}`" in lines for phase in ("deploy", "update")):
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
        return set(deployment_input_paths(root, environment, alias or account, target, units))
    except Blocked as error:
        raise ValueError(str(error)) from error
