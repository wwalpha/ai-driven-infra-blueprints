"""Transient semantic changes and reference contracts; no Model quality checks."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

import design.layout as layout
import import_guard
from utils.arn_components import ARN_COMPONENTS
from utils.input_cache import memo_table
from utils.reference_contracts import (
    ARN_SHAPES,
    RETURN_ATTRIBUTE_PROPERTIES,
    reference_attribute,
    requires_context,
    row_contexts,
)

import model.identity as model_identity
import model.impact_changes as impact_changes
import model.references as references
import model.validation as model_validation
from model import dependency_index, environment_values, reference_metadata, sources
from model.change_scope import change_reads
from model.core import resource_groups
from model.core import structural_entries as entries
from model.format import KEY, owner, parse
from model.reference_nodes import nodes


@dataclass
class ServiceChange:
    before: object
    after: object
    resources: set = field(default_factory=set)
    added: set = field(default_factory=set)
    deleted: set = field(default_factory=set)
    rows: set = field(default_factory=set)
    properties: set = field(default_factory=set)
    keys: set = field(default_factory=set)
    reference_keys: set = field(default_factory=set)
    identity_resources: set = field(default_factory=set)
    observed_rows: set = field(default_factory=set)


@dataclass
class ChangePlan:
    changes: dict = field(default_factory=dict)
    contracts: dict = field(default_factory=dict)
    views: set = field(default_factory=set)
    dependencies: set = field(default_factory=set)
    reads: object = None
    metadata: dict = field(default_factory=dict)

    @property
    def services(self):
        return frozenset(self.changes)


def resource_map(values):
    return {
        logical
        if logical and len(matches) == 1
        else "<unknown identity: " + number + ">": (number, resource)
        for logical, matches in resource_groups(values).items()
        for number, resource in matches
    }


def property_rows(values, number):
    """Formal Property and occurrence survive internal Row renumbering."""
    result, counts = {}, {}
    for rid, row in entries(values, "desired.row."):
        if rid.rpartition("-")[0] != number:
            continue
        prop = row.get("property")
        counts[prop] = counts.get(prop, 0) + 1
        result[prop, counts[prop]] = rid, row
    return result


def context_changes(old, new, old_number, number, kind, root):
    previous, current = property_rows(old, old_number), property_rows(new, number)
    mapping = environment_values.mapping_for(root, kind)
    old_context = {
        **row_contexts(
            kind,
            [
                (rid, row)
                for rid, row in previous.values()
                if {"property", "value"} <= row.keys()
            ],
        ),
        **environment_values.row_contexts(
            kind,
            [
                (rid, row)
                for rid, row in previous.values()
                if {"property", "value"} <= row.keys()
            ],
            mapping,
        ),
    }
    new_context = {
        **row_contexts(
            kind,
            [
                (rid, row)
                for rid, row in current.values()
                if {"property", "value"} <= row.keys()
            ],
        ),
        **environment_values.row_contexts(
            kind,
            [
                (rid, row)
                for rid, row in current.values()
                if {"property", "value"} <= row.keys()
            ],
            mapping,
        ),
    }
    for values, indexed, contexts in (
        (old, previous, old_context),
        (new, current, new_context),
    ):
        for rid, row in indexed.values():
            if "value" in row and requires_context(row["property"]):
                contexts[rid] = model_validation.reference_context_for(
                    values, rid, row, row["value"], "", root
                )
    return {
        rid
        for prop, (rid, row) in current.items()
        if (
            prop in previous
            and impact_changes.frozen(old_context.get(previous[prop][0]))
            != impact_changes.frozen(new_context.get(rid))
        )
    }


def compare(before, after):
    old = {} if before is None else before.authoritative
    new = {} if after is None else after.authoritative
    change = ServiceChange(before, after)
    previous, current = resource_map(old), resource_map(new)
    change.added = set(current) - set(previous)
    change.deleted = set(previous) - set(current)
    change.keys = {
        key for key in old.keys() | new.keys() if old.get(key) != new.get(key)
    }
    for logical in previous.keys() | current.keys():
        old_number, old_resource = previous.get(logical, (None, {}))
        number, resource = current.get(logical, (None, {}))
        old_rows, rows = property_rows(old, old_number), property_rows(new, number)
        for prop in old_rows.keys() | rows.keys():
            old_row = old_rows.get(prop, (None, {}))[1]
            rid, row = rows.get(prop, (None, {}))
            old_rid = old_rows.get(prop, (None, {}))[0]
            if old.get(f"observed.row.{old_rid}.value") != new.get(
                f"observed.row.{rid}.value"
            ):
                change.resources.add(logical)
                if rid is not None:
                    change.observed_rows.add(rid)
            if impact_changes.frozen(
                {key: value for key, value in old_row.items() if key != "comment"}
            ) != impact_changes.frozen(
                {key: value for key, value in row.items() if key != "comment"}
            ):
                change.resources.add(logical)
                change.properties.add((logical, prop[0]))
                if rid is not None:
                    change.rows.add(rid)
                    change.reference_keys.update(
                        f"desired.row.{rid}.{f}"
                        for f in ("value", "document")
                        if f in row
                    )
        if number is not None and before is not None and logical in change.resources:
            dependent = context_changes(
                old, new, old_number, number, resource["resourceType"], after.scope.root
            )
            change.rows.update(dependent)
            change.reference_keys.update(
                f"desired.row.{rid}.{field}"
                for rid in dependent
                for field in ("value", "document")
                if f"desired.row.{rid}.{field}" in new
            )
        if old_resource != resource:
            change.resources.add(logical)
            change.identity_resources.add(logical)
        if number is not None:
            for key in change.keys:
                if (
                    key in new
                    and owner(key, new) == ("resource", number)
                    and not key.startswith(("desired.row.", "observed.row."))
                ):
                    change.resources.add(logical)
                    if key.endswith(".parentReference"):
                        change.reference_keys.add(key)
    # Declaration edits validate their receiving field even when its literal is unchanged.
    for identity, spec in entries(new, "desired.reference."):
        if any(key.startswith(f"desired.reference.{identity}.") for key in change.keys):
            change.reference_keys.add(spec.get("consumerKey"))
    unknown = {
        logical
        for logical in change.resources
        if logical.startswith("<unknown identity:")
        and (
            logical in current
            or previous[logical][0] not in {number for number, _ in current.values()}
        )
    }
    if unknown:
        raise ValueError(
            "change comparison cannot identify changed Resource: "
            + ", ".join(sorted(unknown))
        )
    return change


def signature(values, logical, attribute=None):
    matches = resource_groups(values).get(logical, ())
    if len(matches) > 1:
        raise ValueError(
            "reference contract has ambiguous producer logicalId: " + logical
        )
    number, resource = matches[0] if matches else (None, {})
    if number is None:
        return None
    kind = resource["resourceType"]
    attribute = reference_attribute(kind, attribute) if attribute is not None else None
    fields = (
        {RETURN_ATTRIBUTE_PROPERTIES.get((kind, attribute), attribute)}
        if attribute
        else set()
    )
    if kind in ARN_SHAPES and attribute == reference_attribute(kind, "Arn"):
        identifiers = ARN_SHAPES[kind][0]
        fields.update(identifiers if isinstance(identifiers, dict) else [identifiers])
        fields.update(ARN_COMPONENTS.get(kind, (None, ()))[1])
    if attribute is None:
        fields.update(
            layout.configured_name_fields(Path(__file__).resolve().parents[3], kind)
        )
    rows = [
        (
            key,
            {field: value for field, value in row.items() if field != "comment"},
            values.get(f"observed.row.{rid}.value"),
        )
        for key, (rid, row) in property_rows(values, number).items()
        if any(
            key[0] == kind + "." + field or key[0].startswith(kind + "." + field + ".")
            for field in fields
            if field
        )
    ]
    identity = {key: resource.get(key) for key in ("resourceType", "logicalId")}
    if attribute is None:
        identity.update((key, resource.get(key)) for key in ("anchor", "resourceMode"))
    return impact_changes.frozen(
        [
            identity,
            rows,
            values.get(f"display.resource.{number}.label")
            if attribute is None
            else None,
        ]
    )


def incomplete_reference_affected(snapshot, error, changes):
    """Use partial target/attribute evidence; unknown relationships are not empty edges."""
    for identity, change in changes.items():
        if not reference_metadata.possible(
            error,
            snapshot.scope,
            {"/".join(identity)},
            {(*identity[:2], logical) for logical in change.resources | change.deleted},
        ):
            continue
        old = {} if change.before is None else change.before.authoritative
        new = {} if change.after is None else change.after.authoritative
        logical = error.get("targetLogicalId")
        attribute = error.get("attribute")
        for target in change.resources | change.deleted:
            if logical and logical != target:
                continue
            anchor = error.get("anchor")
            if anchor and not any(
                resource.get("anchor", name) == anchor
                for values in (old, new)
                for name, (_, resource) in resource_map(values).items()
                if name == target
            ):
                continue
            if (
                not attribute
                and error.get("kind") != "link"
                or signature(old, target, attribute)
                != signature(new, target, attribute)
            ):
                return True
    return False


def incoming_keys(snapshot, changes):
    """Select references whose actual producer inputs changed, before rule execution."""
    values, result = snapshot.authoritative, set()
    for _, spec in entries(values, "desired.reference."):
        scope = tuple(spec.get("producerScope", "").split("/"))
        if scope not in changes:
            continue
        change = changes[scope]
        logical = spec.get("producerLogicalId")
        attribute = (
            spec.get("property", "").split(".", 2)[-1] if spec.get("property") else None
        )
        old = {} if change.before is None else change.before.authoritative
        new = {} if change.after is None else change.after.authoritative
        if logical in change.resources and signature(
            old, logical, attribute
        ) != signature(new, logical, attribute):
            result.add(spec["consumerKey"])
        elif spec.get("producerKind") == "stack" and any(
            k.startswith(f"desired.stack.{spec.get('producerId')}.")
            for k in change.keys
        ):
            result.add(spec["consumerKey"])
    _, _, errors = dependency_index.reference_metadata(snapshot)
    for key, diagnostics in errors.items():
        for error in diagnostics:
            if incomplete_reference_affected(snapshot, error, changes):
                raise ValueError(
                    f"cannot determine affected reference metadata: {snapshot.scope.path}: {key}: {error['message']}"
                )
    for key, raw in values.items():
        if not (
            key.startswith("desired.row.")
            and key.endswith((".value", ".document"))
            or key.endswith(".parentReference")
        ):
            continue
        for node in nodes(raw.strip("`"), errors=[]):
            for identity, change in changes.items():
                if (
                    identity[:2] != (snapshot.scope.environment, snapshot.scope.target)
                    or node.logical_id not in change.resources
                ):
                    continue
                old = {} if change.before is None else change.before.authoritative
                new = {} if change.after is None else change.after.authoritative
                if signature(old, node.logical_id, node.attribute) != signature(
                    new, node.logical_id, node.attribute
                ):
                    result.add(key)
        for token in model_identity.reference_tokens(raw):
            try:
                address = model_identity.parse_reference(token[0], snapshot.scope)
            except ValueError:
                continue  # Incomplete link metadata was checked above.
            change = changes.get(address[:3])
            if change is None:
                continue
            old = {} if change.before is None else change.before.authoritative
            new = {} if change.after is None else change.after.authoritative
            logicals = {
                logical
                for source in (old, new)
                for logical, (_, resource) in resource_map(source).items()
                if logical in change.resources
                and resource.get("anchor", logical) == address[3]
            }
            if any(
                signature(old, logical) != signature(new, logical)
                for logical in logicals
            ):
                result.add(key)
    return result


def previous_snapshot(scope, reads):
    """Old bytes are comparison inputs, never a Model validity precondition."""
    base = sources.edit_base(scope.path, reads)
    return comparison_snapshot(base)


def comparison_snapshot(base):
    values, duplicates = {}, set()
    for text in base.files.values():
        try:
            records = parse(text).values
        except (ValueError, UnicodeError):
            records = {}
            for line in text.splitlines():
                key, separator, value = line.partition("=")
                if separator and KEY.fullmatch(key):
                    if key in records:
                        duplicates.add(key)
                    records[key] = value
        for key, value in records.items():
            if key in values:
                duplicates.add(key)
            values[key] = value
    for key in duplicates:
        values[key] = "<ambiguous before value: " + key + ">"
    return base._replace(authoritative=values, values=values)


def assemble(root, changed, before, reads, *, context=False):
    plan = ChangePlan(reads=reads)
    for identity in sorted(changed):
        scope = sources.Scope(root, *identity)
        old_scope = sources.Scope(before, *identity) if before is not None else scope
        old_reads = sources.FileReads() if before is not None else reads
        old = (
            previous_snapshot(old_scope, old_reads)
            if old_reads.kind(old_scope.path) != "missing"
            else None
        )
        after = (
            sources.raw_model(scope, reads)
            if reads.kind(scope.path) != "missing"
            else None
        )
        if before is None and old is not None:
            raise ValueError(
                "change comparison unavailable: an existing Model requires its before snapshot"
            )
        change = compare(old, after)
        plan.changes[identity] = change
        if change.keys:
            plan.views.add(identity)
    plan.metadata["snapshots"] = {
        change.after.scope.path: change.after
        for change in plan.changes.values()
        if change.after is not None
    }
    if context:
        with change_reads(root, reads, metadata=plan.metadata):
            context_contracts(root, before, reads, plan)
    collect_contracts(root, plan)
    return plan


def collect_contracts(root, plan):
    """Share affected incoming-reference selection between Task and prepared saves."""
    reads = plan.reads
    # No reference discovery for comment-only changes.
    semantic = {
        identity: change
        for identity, change in plan.changes.items()
        if change.resources or any(k.startswith("desired.stack.") for k in change.keys)
    }
    if not semantic:
        return
    scopes = {"/".join(identity) for identity in semantic}
    identifiers = {
        (*identity[:2], logical)
        for identity, change in semantic.items()
        for logical in change.resources | change.deleted
    }
    with change_reads(root, reads, metadata=plan.metadata):
        consumers = dependency_index.change_consumers(
            root, scopes, identifiers, set(plan.changes), reads=reads
        )
        for path in consumers:
            scope = sources.scope_for(path)
            snapshot = plan.changes.get(
                (scope.environment, scope.target, scope.service)
            )
            snapshot = (
                snapshot.after
                if snapshot is not None
                else dependency_index.change_snapshot(scope.path, reads, plan.metadata)
            )
            if snapshot is None:
                continue
            keys = incoming_keys(snapshot, semantic)
            if keys:
                identity = scope.environment, scope.target, scope.service
                plan.contracts[identity] = (
                    snapshot,
                    keys | plan.contracts.get(identity, (None, set()))[1],
                )
                plan.views.add(identity)
                plan.dependencies.add(path)


def task_plan(
    root, changed=None, *, output=None, base=None, contract_file=None, read_context=None
):
    root = Path(root).resolve()
    changed = import_guard.changed_sources(root, changed, contract_file=contract_file)
    output = output or {}
    changed |= import_guard.changed_sources(
        root, [p.relative_to(root).as_posix() for p in output]
    )
    identities = set()
    for path in changed:
        if path.startswith("model/"):
            scope = sources.source_scope(root, root / path)
            identities.add((scope.environment, scope.target, scope.service))
    reads = read_context or sources._invocation_reads(root)
    reads = sources.CandidateReads(reads, output) if output else reads
    if not identities and "project.json" not in changed:
        return ChangePlan(reads=reads)
    base = (
        base or import_guard.base_revision(root, contract_file=contract_file)
        if (root / ".git").exists()
        else base
    )
    paths = [
        "project.json",
        *[f"model/{e}/{t}/{s}.properties" for e, t, s in identities],
        *[f"model/{e}/{t}/{s}" for e, t, s in identities],
    ]
    memo = memo_table()
    key = (
        task_plan,
        root,
        base,
        frozenset(identities),
        tuple(sorted(output.items())),
        id(read_context),
    )
    if memo is not None and key in memo:
        return memo[key]
    with change_reads():
        if base is None and (root / ".git").exists():
            with TemporaryDirectory(prefix="blueprint-initial-model-") as directory:
                plan = assemble(
                    root,
                    identities,
                    Path(directory),
                    reads,
                    context="project.json" in changed,
                )
        elif base is None:
            plan = assemble(
                root,
                identities,
                root if output else None,
                reads,
                context="project.json" in changed,
            )
        else:
            with import_guard.snapshots(root, base, {}, source_paths=paths) as (
                before,
                _,
            ):
                plan = assemble(
                    root, identities, before, reads, context="project.json" in changed
                )
    if memo is not None:
        memo[key] = plan
    return plan


def target_contexts(raw):
    if raw is None:
        return {}
    topology = json.loads(raw)
    return {
        (target["environment"], target.get("alias", target.get("awsAccountId"))): tuple(
            target.get(field)
            for field in ("awsRegion", "awsAccountId", "awsExecutionAccountId")
        )
        for target in topology.get("targets", [])
    }


def context_contracts(root, before, reads, plan):
    old = (
        target_contexts(sources.FileReads().read(before / "project.json"))
        if before is not None
        else {}
    )
    new = target_contexts(reads.read(root / "project.json"))
    targets = {
        identity
        for identity in old.keys() | new.keys()
        if old.get(identity) != new.get(identity)
    }
    if not targets:
        return
    # Inventory membership is metadata; only actual context-reference inputs are parsed.
    index = dependency_index.check_change_inventory(
        root, set(plan.changes), reads=reads
    )
    for relative, entry in index["models"].items():
        if tuple(relative.split("/")[1:3]) not in targets or not (
            entry["typed"] or any(scope.count("/") == 1 for scope in entry["links"])
        ):
            continue
        snapshot = dependency_index.change_snapshot(
            root / relative, reads, plan.metadata
        )
        keys = {
            spec["consumerKey"]
            for _, spec in entries(snapshot.authoritative, "desired.reference.")
            if spec.get("producerKind") == "context"
        }
        for key, raw in snapshot.authoritative.items():
            if (
                not key.startswith("desired.row.")
                or not key.endswith((".value", ".document"))
                or "$modelRef" not in raw
            ):
                continue
            value, _ = references._json(key, raw)
            for node in nodes(value):
                if node.attribute.lower().endswith("arn") or node.attribute in {
                    "Id",
                    "Ref",
                }:
                    keys.add(key)
        if keys:
            identity = (
                snapshot.scope.environment,
                snapshot.scope.target,
                snapshot.scope.service,
            )
            plan.contracts[identity] = (
                snapshot,
                keys | plan.contracts.get(identity, (None, set()))[1],
            )
            plan.views.add(identity)
            plan.dependencies.add(snapshot.scope.path)
