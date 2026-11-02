"""Offline validation of the Task's fixed Stack and Resource execution boundary."""

import json
import re
from functools import partial

import model.adapters.observed as observed_adapter
from model.change_plan import ServiceChange
from model.core import structural_entries
from model.format import owner
from model.sources import FileReads, load_model, stack_snapshot
from model.validations.change_inputs import check_change_inputs
from task_contract_core import section, task_snapshot
from utils.cloudformation.inputs import load_template_inputs
from utils.iac_values import cfn_resource_identity
from utils.project_targets import load_target_directory
from validation.change import check_references

from deploy import inputs


def check_fixed_resources(root, mapped, *, task=None, keys=None):
    task = task or task_snapshot(root, required=False, executable=False)
    if task is None:
        return
    actual = {
        (name, logical, path.stem, resource["logicalId"])
        for name, resources in mapped.items()
        for logical, (path, _, resource, _, _) in resources.items()
    }
    records = section(task.text, "## Execution scope")
    if records:
        fixed = []
        for line in records:
            if not line.startswith("- `") or not line.endswith("`"):
                raise ValueError("invalid fixed Execution scope entry")
            record = json.loads(line[3:-1])
            if set(record) != {"stack", "logicalId", "service", "resource"}:
                raise ValueError("invalid fixed Execution scope fields")
            fixed.append(
                tuple(
                    record[key] for key in ("stack", "logicalId", "service", "resource")
                )
            )
        if keys is not None:
            actual = {entry for entry in actual if entry[:2] in keys}
            fixed = [entry for entry in fixed if entry[:2] in keys]
        if len(set(fixed)) != len(fixed) or set(fixed) != actual:
            raise ValueError(
                "Resource ownership differs from the Task's fixed Execution scope"
            )


def validate_selected(root, task, findings, definitions_root=None, plan=None):
    lines = section(task.text, "## Task contract")
    value = partial(inputs._callback_task_deployment_input_paths_value, lines)
    environment = value("Target environment")
    directory = value("Target alias", optional=True) or value("Target AWS account")
    target = load_target_directory(root, environment, directory)
    if target["iacEngine"] != "cloudformation":
        return []
    scope_lines = [line for line in lines if line.startswith("- Deployment scope:")]
    if len(scope_lines) != 1:
        raise ValueError("Deploy requires one fixed Deployment scope")
    names = re.findall(r"`([^`]+)`", scope_lines[0])
    _, units = inputs.load_units(root, environment, directory, names)
    source = (
        root / "model" / environment / directory / "cloudformation-stacks.properties"
    )
    inputs.check_stack_markdown(root, stack_snapshot(source))
    templates = {
        unit["name"]: load_template_inputs(
            *inputs.paths(root, environment, directory, target, unit)
        )
        for unit in units
    }
    selected = {
        name: set(document.get("Resources", {}))
        for name, (document, _) in templates.items()
    }
    _, mapped = observed_adapter.resolve_resources(
        root, environment, directory, templates, units, selected, target=target
    )
    check_fixed_resources(
        root,
        mapped,
        task=task,
        keys={
            (name, logical)
            for name, (document, _) in templates.items()
            for logical in document.get("Resources", {})
        },
    )
    by_path = {}
    for resources in mapped.values():
        for path, _, resource, _, _ in resources.values():
            by_path.setdefault(path, set()).add(resource["logicalId"])
    if plan is not None:
        for change in plan.changes.values():
            if change.after is None:
                continue
            authority = change.after.authoritative
            permitted = by_path.get(change.after.scope.path, set())
            for row in change.observed_rows:
                logical = authority.get(
                    f"desired.resource.{row.rpartition('-')[0]}.logicalId"
                )
                cfn = authority.get(
                    f"desired.resource.{row.rpartition('-')[0]}.cfn-logicalId"
                )
                removed_owner = cfn_resource_identity(cfn) if cfn else (None, None)
                removal = removed_owner[0] in templates and removed_owner[
                    1
                ] not in templates[removed_owner[0]][0].get("Resources", {})
                if logical not in permitted and not removal:
                    raise ValueError(
                        f"observed write outside fixed selected Resources: {change.after.scope.path}: {logical}/{row}"
                    )
    for path, logicals in by_path.items():
        snapshot = load_model(path)
        values = snapshot.authoritative
        numbers = {
            number
            for number, resource in structural_entries(values, "desired.resource.")
            if resource.get("logicalId") in logicals
        }
        keys = {
            key
            for key in values
            if key.startswith(
                (
                    "desired.resource.",
                    "desired.row.",
                    "observed.row.",
                    "display.resource.",
                    "desired.reference.",
                )
            )
            and owner(key, values) in {("resource", number) for number in numbers}
        }
        rows = {
            rid
            for rid, _ in structural_entries(values, "desired.row.")
            if rid.rpartition("-")[0] in numbers
        }
        change = ServiceChange(
            snapshot,
            snapshot,
            resources=logicals,
            added=logicals,
            rows=rows,
            keys=keys,
            identity_resources=logicals,
            observed_rows=rows,
            properties={
                (
                    values[f"desired.resource.{rid.rpartition('-')[0]}.logicalId"],
                    row["property"],
                )
                for rid, row in structural_entries(values, "desired.row.")
                if rid in rows
            },
        )
        result = check_change_inputs(
            path, values, root, change, definitions_root=definitions_root
        )
        findings.include_diagnostics(result)
        findings.checks += result.checks
        check_references(snapshot, keys, FileReads(), findings)
    return units
