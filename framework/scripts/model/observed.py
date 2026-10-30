"""Observation-only proposals preserve every non-observed byte and field."""

import re

import model.adapters.task as _imports_model_adapters_task
import model.configuration as _configuration
import model.core as _imports_model_core
import model.format as _imports_model_format
import model.operations as _dependency_model_operations
import model.operations as _imports_model_operations
import model.projection as _imports_model_projection
import model.sources as _imports_model_sources
from model.format import patch


def verify_observed_outputs(previous, outputs):
    """Prove the writer's outputs contain only explicit observation patches, byte for byte."""
    parse = _imports_model_format.parse
    for file, text in outputs.items():
        if file not in previous or previous[file] is None or not isinstance(text, str):
            raise ValueError(
                "observed publication cannot add an authority file: " + str(file)
            )
        before, after = parse(previous[file].decode("utf-8")), parse(text)
        changes = {
            key: after.values.get(key)
            for key in dict.fromkeys([*after.values, *before.values])
            if before.values.get(key) != after.values.get(key)
            or (key in before.values) != (key in after.values)
        }
        if any(
            re.fullmatch(
                r"observed\.(?:row\.[A-Za-z0-9_-]+\.value|stack\.[A-Za-z0-9_-]+\.(?:status|observedAt|reason))",
                key,
            )
            is None
            for key in changes
        ):
            raise ValueError(
                "observed publication changed non-observed authority: " + str(file)
            )
        if patch(before, changes) != text:
            raise ValueError(
                "observed publication changed unrelated original bytes: " + str(file)
            )


def foreign_observation(snapshot, row):
    return _configuration.foreign_observation(
        snapshot, row, outputs=_imports_model_projection.catalog_outputs
    )


def require_observable_row(snapshot, row):
    resource_id = row.rpartition("-")[0]
    if snapshot.authoritative.get(
        f"desired.resource.{resource_id}.resourceMode"
    ) == "IMPORT" and not foreign_observation(snapshot, row):
        raise ValueError(
            "general observation updates cannot change an IMPORT physical identity: "
            + row
        )


def prepare_observed(snapshot, changes, policy):
    _dependency_model_operations._context(snapshot, policy)
    by_file = {}
    for key, value in changes.items():
        match = re.fullmatch(r"observed\.row\.([A-Za-z0-9_-]+)\.value", key)
        stack = re.fullmatch(
            r"observed\.stack\.([A-Za-z0-9_-]+)\.(status|observedAt|reason)", key
        )
        if stack:
            desired = f"desired.stack.{stack[1]}.name"
            if (
                snapshot.scope.service != "cloudformation-stacks"
                or desired not in snapshot.authoritative
            ):
                raise ValueError("Stack observation has no desired Stack: " + key)
            if value is not None and not isinstance(value, str):
                raise ValueError("Stack observation must be a string")
            by_file.setdefault(snapshot.locations[desired][0], {})[key] = value
            continue
        if not match or value is not None and not isinstance(value, str):
            raise ValueError(
                "observation changes require observed.row.<id>.value string fields only"
            )
        row = match[1]
        desired = "desired.row." + row + ".value"
        if desired not in snapshot.authoritative:
            raise ValueError("observation has no desired Row: " + key)
        if snapshot.authoritative.get(key) != value or (
            key in snapshot.authoritative
        ) != (value is not None):
            require_observable_row(snapshot, row)
        if value is not None:
            entries = _imports_model_core.entries
            observed_value = _imports_model_projection.observed_value
            observed_value(
                row,
                dict(entries(snapshot.authoritative, "desired.row."))[row],
                value,
                (),
            )
        file = snapshot.locations[desired][0]
        by_file.setdefault(file, {})[key] = value
    output = {
        file: patch(snapshot.documents[file], changes)
        for file, changes in by_file.items()
    }
    plan = _dependency_model_operations.prepare_edit(snapshot, output, policy)
    previous = {
        key: value
        for key, value in snapshot.authoritative.items()
        if not key.startswith("observed.")
    }
    current = {
        key: value
        for key, value in plan.candidate.authoritative.items()
        if not key.startswith("observed.")
    }
    if previous != current:
        raise ValueError("observation proposal changed non-observed authority")
    return plan


def observed_outputs(path, values):
    """Produce only byte-preserving observation patches; no derived metadata is serialized."""
    entries = _imports_model_core.entries
    observed_value = _imports_model_projection.observed_value
    load_model = _imports_model_sources.load_model
    snapshot = load_model(path)
    if {
        key: value
        for key, value in snapshot.values.items()
        if not key.startswith("observed.")
    } != {
        key: value for key, value in values.items() if not key.startswith("observed.")
    }:
        raise ValueError(
            "observed writer cannot change desired, display or derived design values"
        )
    changes = {
        key: values.get(key)
        for key in snapshot.values.keys() | values.keys()
        if key.startswith("observed.")
        and (
            snapshot.values.get(key) != values.get(key)
            or (key in snapshot.values) != (key in values)
        )
    }
    by_file = {}
    rows = dict(entries(snapshot.authoritative, "desired.row."))
    for key, value in changes.items():
        match = re.fullmatch(r"observed\.row\.([A-Za-z0-9_-]+)\.value", key)
        stack = re.fullmatch(
            r"observed\.stack\.([A-Za-z0-9_-]+)\.(status|observedAt|reason)", key
        )
        if stack:
            desired = f"desired.stack.{stack[1]}.name"
            if (
                snapshot.scope.service != "cloudformation-stacks"
                or desired not in snapshot.authoritative
            ):
                raise ValueError("Stack observation has no desired Stack: " + key)
            by_file.setdefault(snapshot.locations[desired][0], {})[key] = value
            continue
        if not match or match[1] not in rows:
            raise ValueError("observed writer requires an existing desired Row")
        row = match[1]
        require_observable_row(snapshot, row)
        if value is not None:
            observed_value(row, rows[row], value, ())
        file = snapshot.locations[f"desired.row.{row}.value"][0]
        by_file.setdefault(file, {})[key] = value
    return {
        file: patch(snapshot.documents[file], updates)
        for file, updates in by_file.items()
    }


def publish_observed_candidates(root, outputs, inputs=None):
    """Recheck selected Rows under the real Task context and publish one atomic Model batch."""
    observed_write_context = _imports_model_adapters_task.observed_write_context
    parse = _imports_model_format.parse
    _publish_plans = _imports_model_operations._publish_plans
    load_model = _imports_model_sources.load_model
    source_scope = _imports_model_sources.source_scope
    changes, candidates = {}, {}
    for file, text in outputs.items():
        scope = source_scope(root, file)
        snapshot = load_model(scope)
        verify_observed_outputs(
            {path: value.encode("utf-8") for path, value in snapshot.files.items()},
            {file: text},
        )
        old, new = snapshot.documents[file].values, parse(text).values
        updates = {
            key: new.get(key)
            for key in dict.fromkeys([*new, *old])
            if old.get(key) != new.get(key) or (key in old) != (key in new)
        }
        changes.setdefault(scope.path, {}).update(updates)
        candidates.setdefault(scope.path, {})[file] = text
    if not any(changes.values()):
        return ()
    with observed_write_context(root, changes) as context:
        if inputs is not None and any(
            context.snapshot.read(path) != raw for path, raw in inputs.items()
        ):
            raise ValueError("observed input snapshot changed before publication")
        plans = []
        for path, updates in changes.items():
            if not updates:
                continue
            snapshot = load_model(path, context.snapshot)
            plan = prepare_observed(snapshot, updates, context)
            if dict(plan.changes) != candidates[path]:
                raise ValueError(
                    "observed candidate differs from the authorized exact patch"
                )
            plans.append(plan)
        return _publish_plans(tuple(plans), context)
