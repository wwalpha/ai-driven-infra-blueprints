"""Post-success synchronization and execution-bound deletion evidence."""

import re

import design.layout as _imports_design_layout
import utils.cloudformation.inputs as _imports_cfn_inputs
from design.catalog import DesignSchemaCatalog
from model.adapters.observed import (
    active_outputs,
    ambiguous,
    identifier_source,
    observed_destinations,
    own_key,
    propagate_references,
    resolve_resources,
    static_export_handle,
)
from model.core import entries, properties
from model.files import read_model
from utils.aws.client import AwsError
from utils.cloudformation.inputs import Blocked as Blocked
from utils.json_format import fingerprint

import deploy.observed_resume as _dependency_deploy_observed_resume
from deploy import current_state
from model import dependency_index


def removed_resources(units, states):
    result = {}
    for unit in units:
        state = states[unit["name"]]
        evidence = state.get("executionEvidence")
        changes = (
            evidence.get("resources", []) if evidence else state.get("changes", [])
        )
        removed = {}
        for change in changes:
            if change["Action"] != "Remove":
                continue
            definition = {
                "Type": change["ResourceType"],
                "PolicyAction": change.get("PolicyAction"),
                "PhysicalResourceId": change.get("PhysicalResourceId"),
            }
            if change.get("parentLogicalId"):
                definition["Properties"] = {
                    change["parentProperty"]: {"Ref": change["parentLogicalId"]}
                }
            removed[change["LogicalResourceId"]] = definition
        result[unit["name"]] = removed
    return result


def removal_candidate(name, logical, removal):
    """Deletion intent can require synchronization, but never proves destruction."""
    policy = removal.get("PolicyAction")
    if policy in {"Retain", "RetainExceptOnCreate"}:
        return False
    if policy not in {"Delete", "Snapshot"}:
        ambiguous(f"{name}/{logical}: removal policy is unknown")
    return True


def selected_resources(document, parameters, pseudo, removed, grouped):
    """Select the same possible identifier updates before and after execution."""
    selected = {
        logical
        for logical, definition in document.get("Resources", {}).items()
        if logical not in removed
        and _imports_cfn_inputs.condition_active(
            document, parameters, pseudo, definition
        )
    }
    for logical, definition in removed.items():
        if definition["Type"] not in grouped:
            selected.add(logical)
    return selected


def readiness(backend, unit, state=None):
    """Check only this Stack's known synchronization inputs; never publish placeholders."""
    name = unit["name"]
    try:
        dependency_index.load(backend.root)
        document, parameters = backend.templates[name]
        removed = removed_resources([unit], {name: state or {}})
        key = (name, fingerprint([document, parameters, removed, state is not None]))
        checked = getattr(backend, "observed_checks", set())
        if key in checked:
            return
        pseudo = {
            "AWS::StackName": name,
            "AWS::Region": backend.target["awsRegion"],
            "AWS::AccountId": backend.target.get(
                "awsExecutionAccountId", backend.target["awsAccountId"]
            ),
        }
        grouped = {
            DesignSchemaCatalog(backend.root).cloudformation_type(kind)
            for kind, rule in _imports_design_layout.GROUPED.items()
            if rule["identityProperty"] is None
        }
        selected = selected_resources(
            document, parameters, pseudo, removed[name], grouped
        )
        loaded, mapped = resolve_resources(
            backend.root,
            backend.environment,
            backend.directory,
            backend.templates,
            [unit],
            {name: selected},
            removed,
            target=backend.target,
        )
        changes, identifiers = {}, {}
        for path, _identity, resource, rows, outputs in (
            mapped[name].values() if state is not None else ()
        ):
            for rid, row in rows:
                if row["property"] in outputs:
                    changes.setdefault(path, {})[f"observed.row.{rid}.value"] = (
                        "`PENDING_DEPLOY`"
                    )
                    identifiers[own_key(path, resource)] = "PENDING_DEPLOY"
        if changes:
            propagate_references(backend.root, loaded, changes, identifiers)
            observed_destinations(
                backend.root, backend.environment, backend.directory, loaded, changes
            )
        checked.add(key)
        backend.observed_checks = checked
    except (OSError, ValueError, Blocked) as error:
        raise Blocked(f"{name}: Observed readiness: {error}") from error


def collect_successful(backend, units, states, *, generated_views=None):
    """Resolve exact candidates from fresh successful Stack reads without writing."""
    GROUPED = _imports_design_layout.GROUPED
    root, environment, directory = backend.root, backend.environment, backend.directory
    removed = removed_resources(units, states)
    selected = {}
    grouped = {
        DesignSchemaCatalog(root).cloudformation_type(kind)
        for kind, rule in GROUPED.items()
        if rule["identityProperty"] is None
    }
    for unit in units:
        name = unit["name"]
        if name not in backend.templates:
            backend.load_inputs(unit)
        document, parameters = backend.templates[name]
        pseudo = {
            "AWS::StackName": name,
            "AWS::Region": backend.target["awsRegion"],
            "AWS::AccountId": backend.target.get(
                "awsExecutionAccountId", backend.target["awsAccountId"]
            ),
        }
        selected[name] = selected_resources(
            document, parameters, pseudo, removed[name], grouped
        )
    loaded, mapped = resolve_resources(
        root,
        environment,
        directory,
        backend.templates,
        units,
        selected,
        removed,
        target=backend.target,
    )
    catalog = DesignSchemaCatalog(root) if loaded else None
    for unit in units:
        states[unit["name"]]["observedServices"] = sorted(
            {entry[0].stem for entry in mapped[unit["name"]].values()}
        )
    changes, identifiers = {}, {}
    stack_path = (
        root / "model" / environment / directory / "cloudformation-stacks.properties"
    )
    stack_values = properties(read_model(stack_path))
    loaded[stack_path] = stack_values
    stack_ids = {
        item["name"]: identity
        for identity, item in entries(stack_values, "desired.stack.")
    }
    for unit in units:
        name = unit["name"]
        state = states[name]
        stack = current_state.read(backend.aws, name)
        actuals, complete = [], False
        if current_state.category(stack) not in {"ABSENT", "UNKNOWN"}:
            try:
                actuals = current_state.pages(
                    backend.aws,
                    "list_stack_resources",
                    "StackResourceSummaries",
                    StackName=stack["StackId"],
                )
                after = current_state.read(backend.aws, name)
                complete = current_state.identity(stack) == current_state.identity(
                    after
                )
                if not complete:
                    stack = after
                    actuals = []
            except (AwsError, OSError, Blocked):
                stack = {**stack, "reason": "RESOURCE_READ_FAILED"}
        state["currentStack"] = current_state.observation(stack)
        state["stackId"], state["stackStatus"] = (
            stack.get("StackId"),
            stack["StackStatus"],
        )
        outputs = (
            {
                item["OutputKey"]: item["OutputValue"]
                for item in stack.get("Outputs", [])
            }
            if complete
            else {}
        )
        by_logical = {}
        for actual in actuals:
            logical = actual["LogicalResourceId"]
            if logical in by_logical:
                ambiguous(f"{name}/{logical}: duplicate actual resource")
            by_logical[logical] = actual
        document, parameters = backend.templates[name]
        pseudo = {
            "AWS::StackName": name,
            "AWS::AccountId": backend.target.get(
                "awsExecutionAccountId", backend.target["awsAccountId"]
            ),
            "AWS::Region": backend.target["awsRegion"],
        }
        coverage = {}
        state["observedCoverage"] = coverage
        unit_changed = False
        for logical, (path, _identity, resource, rows, selected_outputs) in mapped[
            name
        ].items():
            actual = by_logical.get(logical)
            if actual and actual.get("ResourceType") != document.get(
                "Resources", {}
            ).get(logical, removed.get(name, {}).get(logical, {})).get("Type"):
                actual = None
                stack["reason"] = "RESOURCE_TYPE_UNCONFIRMED"
            if not selected_outputs:
                coverage[logical] = {"status": "NO_IDENTIFIER"}
                continue
            unknown, updated, absent = False, False, False
            if logical in removed.get(name, {}) and complete:
                try:
                    absent = deleted_resource(
                        backend,
                        name,
                        logical,
                        removed[name][logical],
                        state,
                        by_logical,
                    )
                except Blocked:
                    absent = False
            for rid, row in rows:
                prop = row["property"]
                if prop not in selected_outputs:
                    continue
                value = None
                if absent:
                    value = "PENDING_DEPLOY"
                elif (
                    actual
                    and isinstance(actual.get("ResourceStatus"), str)
                    and actual["ResourceStatus"]
                    and actual["ResourceStatus"]
                    not in {
                        "DELETE_COMPLETE",
                        "DELETE_SKIPPED",
                    }
                ):
                    primary, keys = identifier_source(
                        catalog,
                        resource,
                        selected_outputs,
                        logical,
                        prop,
                        active_outputs(document, parameters, pseudo),
                    )
                    values = [outputs[key] for key in keys if key in outputs]
                    physical = actual.get("PhysicalResourceId") if primary else None
                    if values and (
                        len(set(values)) != 1
                        or physical is not None
                        and physical != values[0]
                    ):
                        # A moving/partial Stack cannot confirm mutually inconsistent reads.
                        value = None
                    elif values and len(values) == len(keys):
                        value = values[0]
                    else:
                        value = physical
                    if (
                        not isinstance(value, str)
                        or not value
                        or value in {"PENDING_DEPLOY", "UNKNOWN"}
                        or re.search(r"\barn:aws[a-z-]*:", value, re.I)
                        or any(c in value for c in "\r\n`")
                    ):
                        value = None
                key = f"observed.row.{rid}.value"
                raw = f"`{value}`" if value is not None else None
                changed = loaded[path].get(key) != raw or (key in loaded[path]) != (
                    raw is not None
                )
                updated |= changed
                unit_changed |= changed
                unknown |= value is None
                changes.setdefault(path, {})[key] = raw
                identifiers[own_key(path, resource)] = value
            coverage[logical] = {
                "status": "UNCONFIRMED"
                if unknown
                else "UPDATED"
                if updated
                else "MATCHED"
            }
        for logical in document.get("Resources", {}) | removed.get(name, {}):
            if logical not in coverage:
                if logical in selected[name] and not static_export_handle(
                    document, logical, parameters, pseudo
                ):
                    ambiguous(f"{name}/{logical}: selected resource was not mapped")
                coverage[logical] = {
                    "status": "EXCLUDED",
                    "reason": "Condition inactive or static/retained scaffold",
                }
        identity = stack_ids[name]
        prefix = f"observed.stack.{identity}."
        patch = {
            prefix + "status": stack["StackStatus"],
            prefix + "reason": stack.get("reason"),
        }
        if (
            unit_changed
            or any(stack_values.get(key) != value for key, value in patch.items())
            or prefix + "observedAt" not in stack_values
        ):
            patch[prefix + "observedAt"] = stack["observedAt"]
        changes.setdefault(stack_path, {}).update(patch)
        state["observedServices"] = sorted(
            {
                "cloudformation-stacks",
                *[entry[0].stem for entry in mapped[name].values()],
            }
        )
    if not changes:
        if not getattr(backend, "run_context", {}).get("stepwise"):
            return {}, [], None
        changes = {
            entry[0]: {} for mapping in mapped.values() for entry in mapping.values()
        }
        if not changes:
            return {}, [], None
    propagate_references(root, loaded, changes, identifiers)
    destinations, views, sync = observed_destinations(
        root, environment, directory, loaded, changes
    )
    if generated_views is not None:
        generated_views.update(views)
    return destinations, sorted({path.stem for path in changes}), sync


def sync_successful(backend, units, states):
    """Confirm the Model barrier; generated views have their own durable queue."""
    if backend.run_context.get("pendingObserved"):
        names = list(backend.run_context["pendingObserved"]["evidence"])
        destinations = _dependency_deploy_observed_resume.finish(backend, units)
    else:
        views = set()
        destinations, services, _ = collect_successful(
            backend, units, states, generated_views=views
        )
        names = [unit["name"] for unit in units]
        if destinations:
            _dependency_deploy_observed_resume.prepare(
                backend, units, destinations, services, views
            )
            destinations = _dependency_deploy_observed_resume.finish(backend, units)
    for name in names:
        states[name]["observedSynced"] = True
    return destinations or None


def deleted_resource(runtime, name, logical, removal, state, actuals):
    """A Remove is intent. Only execution-bound physical destruction resets an identifier."""
    if not removal_candidate(name, logical, removal):
        return False
    evidence = state.get("executionEvidence", {})
    if any(
        evidence.get(key) != state.get(field)
        for key, field in (
            ("StackId", "stackId"),
            ("ChangeSetId", "changeSetId"),
            ("changeDigest", "changeDigest"),
            ("clientToken", "clientToken"),
        )
    ):
        ambiguous(f"{name}/{logical}: original execution evidence missing or changed")
    if not evidence or not removal.get("PhysicalResourceId"):
        ambiguous(f"{name}/{logical}: physical deletion identity unknown")
    actual = actuals.get(logical)
    if actual and actual.get("ResourceStatus") == "DELETE_SKIPPED":
        return False
    if (
        actual
        and actual.get("ResourceStatus") == "DELETE_COMPLETE"
        and all(
            actual.get(key) == removal.get(key if key != "ResourceType" else "Type")
            for key in ("PhysicalResourceId", "ResourceType")
        )
    ):
        return True
    events = runtime.aws("describe_stack_events", StackName=evidence["StackId"])[
        "StackEvents"
    ]
    matched = [
        event
        for event in events
        if event.get("LogicalResourceId") == logical
        and event.get("ResourceType") == removal["Type"]
        and event.get("PhysicalResourceId") == removal["PhysicalResourceId"]
        and event.get("ClientRequestToken") == evidence["clientToken"]
        and event.get("StackId") == evidence["StackId"]
    ]
    if any(event.get("ResourceStatus") == "DELETE_SKIPPED" for event in matched):
        return False
    if not any(event.get("ResourceStatus") == "DELETE_COMPLETE" for event in matched):
        ambiguous(f"{name}/{logical}: physical destruction is unconfirmed")
    return True
