"""Reference metadata describes saved text; reads never regenerate consumer values."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback
from pathlib import PurePosixPath

from utils.json_format import strict_json
from utils.model_addresses import resource_address as resource_address
from utils.reference_contracts import reference_error, row_contexts
from validation.diagnostics import Diagnostic, service_scope

import model.change_scope as change_plan
import model.core as _imports_model_core
import model.dependency_index as dependency_index
import model.environment_values as environment_values
import model.format as _imports_model_projection
import model.identity as _imports_model_identity
import model.importing.scope as _imports_model_importing_scope
import model.sources as source_models
from model.core import ReferenceDiagnosticError, entries, literal
from model.format import json_field, owner
from model.reference_nodes import (
    context_at,
    is_reference,
    nodes,
    parse,
    receiving_property,
    reference_document,
    resolve,
)
from model.reference_values import reference_value

FIELDS = {
    "consumerKey",
    "pointer",
    "text",
    "occurrence",
    "producerKind",
    "producerScope",
    "producerId",
    "producerLogicalId",
    "resourceType",
    "format",
    "property",
    "labelPolicy",
    "contextProperty",
}
BASE = {
    "consumerKey",
    "text",
    "occurrence",
    "producerKind",
    "producerScope",
    "format",
    "labelPolicy",
}


def pointer_value(value, pointer):
    if (
        not isinstance(pointer, str)
        or (pointer and not pointer.startswith("/"))
        or re.search(r"~(?![01])", pointer)
    ):
        raise ValueError("reference requires an RFC 6901 pointer")
    for token in pointer.split("/")[1:] if pointer else ():
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif (
            isinstance(value, list)
            and re.fullmatch(r"0|[1-9][0-9]*", token)
            and int(token) < len(value)
        ):
            value = value[int(token)]
        else:
            raise ValueError("reference pointer must select an existing string leaf")
    return value


def pointer_leaf(value, pointer):
    value = pointer_value(value, pointer)
    if not isinstance(value, str):
        raise ValueError("reference pointer must select an existing string leaf")
    return value


def _json(key, raw):
    if (
        key.endswith(".parentReference")
        or key == "desired.deployment.templateBucket"
        or key.startswith("desired.artifact.")
        and key.endswith(".bucket")
    ):
        return reference_document(parse(raw)), True
    body, ticked = json_field(key, raw)
    if body is None:
        return raw, False
    if ticked:
        if not body.endswith("`"):
            raise ValueError("missing closing JSON backtick: " + key)
        body = body[:-1]
    return strict_json(body), True


def string_leaves(value, pointer=""):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from string_leaves(
                child, pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from string_leaves(child, pointer + "/" + str(index))


def occurrence_positions(text, fragment):
    if not fragment:
        raise ValueError("reference text must be nonempty")
    positions, start = [], -1
    while (start := text.find(fragment, start + 1)) >= 0:
        positions.append(start)
    return positions


def declarations(values):
    result = dict(entries(values, "desired.reference."))
    for identity, spec in result.items():
        if not BASE <= spec.keys() or spec.keys() - FIELDS:
            raise ValueError("invalid reference fields: " + identity)
        key = spec["consumerKey"]
        if key not in values or key.startswith(("observed.", "desired.reference.")):
            raise ValueError(
                "reference consumerKey does not identify an authoritative consumer: "
                + identity
            )
        kind, block = owner(key, values)
        if (
            kind == "resource"
            and f"desired.resource.{block}.resourceType" not in values
            or kind == "stack"
            and f"desired.stack.{block}.name" not in values
        ):
            raise ValueError("reference consumer owner is absent: " + identity)
        if not spec["text"] or re.fullmatch(r"[1-9][0-9]*", spec["occurrence"]) is None:
            raise ValueError("reference text/occurrence is invalid: " + identity)
        scope = PurePosixPath(spec["producerScope"])
        if (
            scope.is_absolute()
            or ".." in scope.parts
            or "\\" in spec["producerScope"]
            or str(scope) != spec["producerScope"]
        ):
            raise ValueError("unsafe reference producerScope: " + identity)
        kind, mode = spec["producerKind"], spec["format"]
        required, forbidden = set(), set()
        if kind == "resource":
            required = {"producerLogicalId", "resourceType"}
            forbidden = {"contextProperty", "producerId"}
            if mode not in {"name", "identifier"} or len(scope.parts) != 3:
                raise ValueError("invalid resource reference format/scope: " + identity)
            required.add("property")
        elif kind == "stack":
            required = {"producerId", "property"}
            forbidden = {"resourceType", "contextProperty", "producerLogicalId"}
            if (
                mode != "name"
                or spec.get("property") != "name"
                or len(scope.parts) != 3
            ):
                raise ValueError("invalid stack reference: " + identity)
        elif kind == "context":
            required = {"contextProperty"}
            forbidden = {"producerId", "producerLogicalId", "resourceType", "property"}
            if (
                mode != "literal"
                or len(scope.parts) != 2
                or spec.get("contextProperty") != "executionAccountId"
            ):
                raise ValueError(
                    "invalid context reference (contextProperty must be executionAccountId): "
                    + identity
                )
        else:
            raise ValueError("unknown reference producerKind: " + identity)
        if (
            not required <= spec.keys()
            or forbidden & spec.keys()
            or any(not spec[field] for field in required)
        ):
            raise ValueError("missing or forbidden reference fields: " + identity)
        if spec["labelPolicy"] != "none":
            raise ValueError("reference requires labelPolicy none: " + identity)
        value, structured = _json(key, values[key])
        if structured != ("pointer" in spec):
            raise ValueError(
                "JSON references require a pointer; scalar references forbid one: "
                + identity
            )
        leaf = pointer_leaf(value, spec["pointer"]) if structured else value
        if len(occurrence_positions(leaf, spec["text"])) < int(spec["occurrence"]):
            raise ValueError(
                "reference occurrence does not identify saved text: " + identity
            )
    return result


@dataclass(frozen=True)
class Usage:
    consumer_key: str
    pointer: str | None
    start: int
    end: int
    text: str
    producer_scope: str | None
    producer_kind: str
    producer_id: str | None
    metadata_id: str | None = None
    logical_id: str | None = None
    attribute: str | None = None


def _producer(snapshot, address, reads, cache):
    env, target, service = address.split("/")
    scope = source_models.Scope(snapshot.scope.root, env, target, service)
    if scope.path not in cache:
        source_models.target_for(scope, reads)
        reference_reader = _imports_model_importing_scope.reference_reader
        with reference_reader(scope.path):
            cache[scope.path] = (
                None
                if reads.kind(scope.path) == "missing"
                else dependency_index.change_snapshot(scope.path, reads)
                if change_plan.active()
                else source_models._source_snapshot(scope, reads)
            )
    return cache[scope.path]


def _callback_usages_producer_for(cache, producers, reads, snapshot, /, scope):
    if scope not in producers:
        producers[scope] = _producer(snapshot, scope, reads, cache)
    return producers[scope]


def _callback_usages_fixed(indexes, producer_for, resource_index, /, scope, logical):
    if scope not in indexes:
        producer = producer_for(scope)
        if producer is None:
            return None
        indexes[scope] = (
            _imports_model_core.resource_groups(producer.authoritative)
            if change_plan.active()
            else {
                logical: [match]
                for logical, match in resource_index(producer.authoritative).items()
            }
        )
    matches = indexes[scope].get(logical, ())
    if len(matches) > 1:
        raise _imports_model_core.ModelNeedsFixError(
            "producer logicalId is ambiguous: " + logical,
            code="MODEL_REF_TARGET_AMBIGUOUS",
        )
    return matches[0][0] if matches else None


def usages(
    snapshot,
    read_context=None,
    *,
    _cache=None,
    _producer_scope=None,
    _typed=True,
    _diagnostics=None,
):
    """Extract typed Resource references and declared literal dependencies."""
    resource_index = _imports_model_identity.resource_index
    values, result = snapshot.authoritative, []
    reads = read_context or source_models._invocation_reads(snapshot.scope.root)
    cache = {snapshot.scope.path: snapshot} if _cache is None else _cache
    indexes, producers = {}, {}

    producer_for = _bind_framework_callback(
        _callback_usages_producer_for, cache, producers, reads, snapshot
    )

    fixed = _bind_framework_callback(
        _callback_usages_fixed, indexes, producer_for, resource_index
    )

    resolver = _imports_model_identity.Resolver(snapshot.scope.root, reads)
    cache.update(resolver.overrides)
    resolver.models = cache
    specs = declarations(values)
    for identity, spec in specs.items():
        scope = spec["producerScope"]
        if _producer_scope is not None and scope != _producer_scope:
            continue
        value, structured = _json(spec["consumerKey"], values[spec["consumerKey"]])
        leaf = pointer_leaf(value, spec["pointer"]) if structured else value
        offset = occurrence_positions(leaf, spec["text"])[int(spec["occurrence"]) - 1]
        producer_id = (
            fixed(scope, spec["producerLogicalId"])
            if spec["producerKind"] == "resource"
            else spec.get("producerId")
        )
        result.append(
            Usage(
                spec["consumerKey"],
                spec.get("pointer"),
                offset,
                offset + len(spec["text"]),
                spec["text"],
                scope,
                spec["producerKind"],
                producer_id,
                identity,
                spec.get("producerLogicalId"),
            )
        )
    for key, raw in values.items():
        if not (
            key.startswith("desired.row.")
            and key.endswith((".value", ".document"))
            or key.startswith("desired.resource.")
            and key.endswith(".parentReference")
            or key == "desired.deployment.templateBucket"
            or key.startswith("desired.artifact.")
            and key.endswith(".bucket")
        ):
            continue
        value, structured = _json(key, raw)
        diagnostics = []
        for node in nodes(value, errors=diagnostics) if _typed else ():
            try:
                producer, rid, resource, attribute = resolve(
                    node, snapshot.scope, resolver
                )
            except ReferenceDiagnosticError as error:
                if _diagnostics is None:
                    raise
                diagnostics.extend(
                    dict(
                        d,
                        pointer=node.pointer,
                        targetLogicalId=node.logical_id,
                        attribute=node.attribute,
                    )
                    for d in error.diagnostics
                )
                continue
            scope = "/".join(
                (
                    producer.scope.environment,
                    producer.scope.target,
                    producer.scope.service,
                )
            )
            if _producer_scope is None or scope == _producer_scope:
                text = {
                    "$modelRef": {"logicalId": node.logical_id, "attribute": attribute}
                }
                result.append(
                    Usage(
                        key,
                        node.pointer,
                        0,
                        0,
                        str(text),
                        scope,
                        "resource",
                        rid,
                        logical_id=node.logical_id,
                        attribute=attribute,
                    )
                )
        for diagnostic in diagnostics:
            diagnostic.update(model=str(snapshot.scope.path), modelKey=key)
            if key.startswith("desired.row."):
                number = key.split(".")[2].rpartition("-")[0]
                diagnostic["property"] = values.get(key.rsplit(".", 1)[0] + ".property")
                diagnostic["resourceLogicalId"] = values.get(
                    f"desired.resource.{number}.logicalId"
                )
            if _diagnostics is None:
                _imports_model_core.require_reference_diagnostics([diagnostic])
            _diagnostics.append(diagnostic)
    return tuple(result)


def _callback_diagnose_producer_entries(parsed, /, producer, prefix):
    key = (id(producer), prefix)
    if key not in parsed:
        result = (
            _imports_model_core.structural_entries if change_plan.active() else entries
        )(producer.authoritative, prefix)
        parsed[key] = dict(result) if prefix == "desired.resource." else result
    return parsed[key]


def _callback_diagnose_warn(usage, warnings, /, message):
    warnings.append(
        {
            "code": "reference.mismatch",
            "message": message,
            "consumerKey": usage.consumer_key,
            "pointer": usage.pointer,
            "reference": usage.metadata_id,
            "text": usage.text,
        }
    )


def kms_observation(values, row_id, node, scope, resolver):
    """Compare only a scalar KMS-normalized consumer against a proven Key identity."""
    if node.pointer or node.attribute not in {"Arn", "KeyId"}:
        return None
    prop = values.get(f"desired.row.{row_id}.property", "")
    kind = ".".join(prop.split(".")[:2])
    mapping = environment_values.mapping_for(scope.root, kind).get(prop)
    if mapping is None or mapping.field.norm != "kms":
        return None
    target, number, resource, _ = resolve(node, scope, resolver, field=prop)
    if resource["resourceType"] not in {"KMS.Key", "KMS.Alias"}:
        return None
    if target.scope == scope and number == row_id.rpartition("-")[0]:
        return None
    observed = values.get(f"observed.row.{row_id}.value")
    if observed is None:
        return "unobserved", None
    observed = literal(observed)
    if observed == "PENDING_DEPLOY":
        return "pending", observed
    if (
        re.fullmatch(
            r"(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})",
            observed,
        )
        is None
    ):
        return "unproven", observed
    try:
        if resource["resourceType"] == "KMS.Alias":
            if resource.get(
                "parentProperty"
            ) != "KMS.Alias.TargetKeyId" or not resource.get("parentReference"):
                return "unproven", observed
            parent = parse(resource["parentReference"])
            alias_scope = target.scope
            target, number, resource, _ = resolve(
                parent, alias_scope, resolver, field="KMS.Alias.TargetKeyId"
            )
            if target.scope != alias_scope or resource["resourceType"] != "KMS.Key":
                return "unproven", observed
        rows = [
            (rid, row)
            for rid, row in entries(target.authoritative, "desired.row.")
            if rid.rpartition("-")[0] == number
            and row.get("property") == "KMS.Key.KeyId"
        ]
        if (
            len(rows) != 1
            or f"observed.row.{rows[0][0]}.value" not in target.authoritative
        ):
            return "unproven", observed
        key_node = parse(
            {"$modelRef": {"logicalId": resource["logicalId"], "attribute": "KeyId"}}
        )
        key = reference_value(resolver, target.scope, key_node)
        if key.status != "resolved":
            return "unproven", observed
        return ("match" if key.value == observed else "mismatch"), observed
    except ReferenceDiagnosticError:
        return "unproven", observed


def diagnose(
    snapshot, read_context=None, *, _producer_scope=None, errors=None, details=None
):
    """Retain producer warnings; validation may collect proven receiving-type errors."""
    reads = read_context or source_models.FileReads()
    warnings, dependencies, cache = (
        [],
        dict(snapshot.dependencies),
        {snapshot.scope.path: snapshot},
    )
    # The producer cache retains snapshots, so their IDs stay unique for this diagnosis.
    parsed = {}

    producer_entries = _bind_framework_callback(
        _callback_diagnose_producer_entries, parsed
    )

    specs = declarations(snapshot.authoritative)
    try:
        extracted = usages(
            snapshot,
            reads,
            _cache=cache,
            _producer_scope=_producer_scope,
            _diagnostics=warnings,
        )
    except _imports_model_core.ReferenceResolutionError as error:
        warnings.append(error.diagnostic)
        for producer in cache.values():
            if producer is not None:
                dependencies.update(producer.dependencies)
        return tuple(warnings), dependencies
    if details is not None:
        details.update(usages=extracted, models=cache)
    for usage in extracted:
        spec = specs.get(usage.metadata_id, {})
        if usage.producer_kind == "context":
            env, target = usage.producer_scope.split("/")
            selected = source_models.Scope(
                snapshot.scope.root, env, target, snapshot.scope.service
            )
            context, project = source_models.target_for(selected, reads)
            expected = context.get("awsExecutionAccountId", context["awsAccountId"])
            if usage.text != expected:
                _callback_diagnose_warn(
                    usage, warnings, "context value differs from saved text"
                )
            continue
        producer = _producer(snapshot, usage.producer_scope, reads, cache)
        if producer is None:
            _callback_diagnose_warn(usage, warnings, "producer Model is absent")
            continue
        dependencies.update(producer.dependencies)
        values = producer.authoritative
        if usage.producer_kind == "stack":
            expected = values.get(f"desired.stack.{usage.producer_id}.name")
            if expected is None:
                _callback_diagnose_warn(usage, warnings, "producer Stack is absent")
            elif literal(usage.text) != literal(expected):
                _callback_diagnose_warn(
                    usage, warnings, "Stack name differs from saved text"
                )
            continue
        resources = producer_entries(producer, "desired.resource.")
        matches = [usage.producer_id] if usage.producer_id in resources else []
        if len(matches) != 1:
            _callback_diagnose_warn(
                usage, warnings, "producer Resource is absent or ambiguous"
            )
            continue
        identity = matches[0]
        resource = resources[identity]
        if usage.attribute is not None:
            if (
                resource["resourceType"] in {"KMS.Key", "KMS.Alias"}
                and usage.attribute in {"Arn", "KeyId"}
                and usage.consumer_key.startswith("desired.row.")
                and usage.consumer_key.endswith(".value")
                and usage.pointer == ""
            ):
                rid = usage.consumer_key.split(".")[2]
                raw, structured = _json(
                    usage.consumer_key, snapshot.authoritative[usage.consumer_key]
                )
                if structured and is_reference(raw):
                    resolver = _imports_model_identity.Resolver(
                        snapshot.scope.root, reads
                    )
                    resolver.models = cache
                    try:
                        state = kms_observation(
                            snapshot.authoritative,
                            rid,
                            parse(raw),
                            snapshot.scope,
                            resolver,
                        )
                    except ReferenceDiagnosticError:
                        state = None
                    if state and state[0] in {"mismatch", "unproven"}:
                        _callback_diagnose_warn(
                            usage,
                            warnings,
                            "observed KMS KeyId differs from the referenced Key"
                            if state[0] == "mismatch"
                            else "observed KMS KeyId relationship is unproven",
                        )
                        if state[0] == "unproven":
                            warnings[-1]["code"] = "reference.unresolved"
            continue
        if spec and resource["resourceType"] != spec["resourceType"]:
            _callback_diagnose_warn(usage, warnings, "producer Resource Type differs")
        if spec.get("format") in {"name", "identifier"}:
            REFERENCE_NAME_SUFFIXES = _imports_model_projection.REFERENCE_NAME_SUFFIXES
            prop = spec["property"]
            if prop.rsplit(".", 1)[0] != spec["resourceType"]:
                _callback_diagnose_warn(
                    usage,
                    warnings,
                    "producer Property does not belong to the expected Resource Type",
                )
                continue
            if spec["format"] == "name" and not prop.endswith(REFERENCE_NAME_SUFFIXES):
                _callback_diagnose_warn(
                    usage, warnings, "producer Property is not a raw name Property"
                )
                continue
            rows = [
                (rid, row)
                for rid, row in producer_entries(producer, "desired.row.")
                if rid.rpartition("-")[0] == identity
                and row.get("property") == spec["property"]
            ]
            if len(rows) != 1:
                _callback_diagnose_warn(
                    usage, warnings, "producer Property is absent or ambiguous"
                )
                continue
            rid, row = rows[0]
            expected = (
                row.get("value")
                if spec["format"] == "name"
                else values.get(f"observed.row.{rid}.value")
            )
            if expected is None or literal(expected) == "PENDING_DEPLOY":
                _callback_diagnose_warn(
                    usage, warnings, "producer Property is unobserved or pending"
                )
            elif spec["format"] == "identifier" and (
                not literal(expected) or literal(expected).startswith("arn:")
            ):
                _callback_diagnose_warn(
                    usage,
                    warnings,
                    "producer identifier is not a nonempty non-ARN string",
                )
            elif literal(usage.text) != literal(expected):
                _callback_diagnose_warn(
                    usage, warnings, "producer name/identifier differs from saved text"
                )
    for path, producer in cache.items():
        if producer is None:
            dependencies[path] = None
        else:
            dependencies.update(producer.dependencies)
    return tuple(warnings), dependencies


def incoming(snapshot, producer_id, read_context=None, *, warnings=None):
    """Read-only discovery has no dependency on a mutation/CREATE save guard."""
    result = []
    address = "/".join(
        (snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service)
    )
    read_consumers = _imports_model_importing_scope.read_consumers
    reads = read_context or source_models._invocation_reads(snapshot.scope.root)
    logical = snapshot.authoritative.get(
        f"desired.resource.{producer_id}.logicalId", producer_id
    )
    with change_plan.change_reads(
        snapshot.scope.root, reads, {snapshot.scope.path: snapshot}
    ):
        scopes = [
            source_models.scope_for(path)
            for path in dependency_index.change_consumers(
                snapshot.scope.root,
                {address},
                {(snapshot.scope.environment, snapshot.scope.target, logical)},
                set(),
                reads=reads,
            )
        ]
        with read_consumers(
            {(scope.environment, scope.target, scope.service) for scope in scopes}
        ):
            for scope in scopes:
                consumer = dependency_index.change_snapshot(scope.path, reads)
                relevant_warnings, _ = diagnose(
                    consumer, reads, _producer_scope=address
                )
                if warnings is not None:
                    warnings.extend(
                        {
                            "scope": "/".join(
                                (scope.environment, scope.target, scope.service)
                            ),
                            **warning,
                        }
                        for warning in relevant_warnings
                    )
                for usage in usages(consumer, reads, _producer_scope=address):
                    if usage.producer_scope == address and (
                        usage.producer_id == producer_id
                        or usage.logical_id == producer_id
                    ):
                        result.append((scope, usage))
        return tuple(result)


@dataclass(frozen=True)
class Reference:
    """Comparison identity for an existing saved fragment, never a value generator."""

    producer: str | None
    kind: str
    resource_type: str | None = None
    format: str | None = None
    property_name: str | None = None
    label: str | None = None
    label_policy: str | None = None
    selector: str | None = None
    value_selector: str | None = None


def _recursive_symbolic_tree(leaf, /, key, value, pointer=""):
    if is_reference(value):
        return leaf(key, pointer, value)
    if isinstance(value, str):
        return leaf(key, pointer, value)
    if isinstance(value, dict):
        return {
            name: _recursive_symbolic_tree(
                leaf,
                key,
                child,
                pointer + "/" + name.replace("~", "~0").replace("/", "~1"),
            )
            for name, child in value.items()
        }
    if isinstance(value, list):
        return [
            _recursive_symbolic_tree(leaf, key, child, pointer + "/" + str(index))
            for index, child in enumerate(value)
        ]
    return value


def _callback_symbolic_leaf(grouped, /, key, pointer, value):
    spans = sorted(grouped.get((key, pointer), []), key=lambda item: (item[0], item[1]))
    if not spans:
        return value
    if is_reference(value):
        parse(value, pointer)
        return spans[0][2] if len(spans) == 1 else Reference(None, "ambiguous")
    merged = []
    for start, end, record in spans:
        if merged and start < merged[-1][1]:
            previous = merged[-1]
            merged[-1] = previous[0], max(previous[1], end), (*previous[2], record)
        else:
            merged.append((start, end, (record,)))
    result, cursor = [], 0
    for start, end, records in merged:
        result.append(value[cursor:start])
        result.append(
            records[0]
            if len(records) == 1
            else Reference(None, "ambiguous", selector=repr(records))
        )
        cursor = end
    result.append(value[cursor:])
    return tuple(result)


def symbolic(snapshot, read_context=None):
    """Retain JSON/native structure and every literal affix around saved references."""
    values = snapshot.authoritative
    specs = declarations(values)
    grouped = {}
    reads = read_context or source_models._invocation_reads(snapshot.scope.root)
    cache = {snapshot.scope.path: snapshot}
    for usage in usages(snapshot, reads, _cache=cache):
        spec = specs.get(usage.metadata_id, {})
        producer_id = usage.producer_id
        address = usage.producer_scope
        if usage.producer_kind != "context":
            address = (
                None
                if producer_id is None
                else "/".join(
                    (
                        address,
                        *(["stack"] if usage.producer_kind == "stack" else []),
                        producer_id,
                    )
                )
            )
        record = Reference(
            address,
            usage.producer_kind,
            spec.get("resourceType"),
            "model" if usage.attribute else spec.get("format"),
            usage.attribute or spec.get("property"),
            None,
            spec.get("labelPolicy"),
            spec.get("contextProperty")
            if usage.producer_kind == "context"
            else usage.logical_id
            if producer_id is None
            else None,
        )
        grouped.setdefault((usage.consumer_key, usage.pointer), []).append(
            (usage.start, usage.end, record)
        )

    leaf = _bind_framework_callback(_callback_symbolic_leaf, grouped)

    tree = _bind_framework_callback(_recursive_symbolic_tree, leaf)

    result = {}
    for key, raw in values.items():
        if key.startswith("desired.reference."):
            continue
        value, structured = _json(key, raw)
        result[key] = tree(key, value) if structured else leaf(key, None, value)
    return result


def walk_references(value):
    if isinstance(value, Reference):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk_references(child)


def reference_positions(value, pointer=""):
    if isinstance(value, Reference):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from reference_positions(
                child, pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from reference_positions(child, pointer + "/" + str(index))
    elif isinstance(value, tuple):
        for child in value:
            yield from reference_positions(child, pointer)


def codebuild_reference_errors(path, values, *, findings=None, context_values=None):
    """Check source references before resolution or display can fail."""
    errors = {}
    rows = entries(values, "desired.row.")
    for identity, resource in entries(values, "desired.resource."):
        if resource["resourceType"] != "CodeBuild.Project":
            continue
        selected = [
            (rid, row) for rid, row in rows if rid.rpartition("-")[0] == identity
        ]
        context_rows = (
            entries(context_values, "desired.row.")
            if context_values is not None
            else rows
        )
        contexts = row_contexts(
            "CodeBuild.Project",
            [
                (rid, row)
                for rid, row in context_rows
                if rid.rpartition("-")[0] == identity
            ],
        )
        for rid, row in selected:
            prop = row["property"]
            if not prop.startswith("CodeBuild.Project.Environment"):
                continue
            for source_field in ("value", "document"):
                if source_field not in row:
                    continue
                try:
                    value, _ = _json(
                        "desired.row." + rid + "." + source_field, row[source_field]
                    )
                    occurrences = [(node.pointer, True) for node in nodes(value)]
                except (ValueError, TypeError):
                    continue  # JSON validation reports syntax errors independently.
                for pointer, linked in occurrences:
                    if not linked:
                        continue
                    field = receiving_property(prop, pointer)
                    context = context_at(value, prop, pointer, contexts.get(rid, {}))
                    if error := reference_error(field, context):
                        errors[rid, source_field, pointer] = (
                            f"Model={path}, Resource={resource['logicalId']} ({identity}), "
                            f"Name={context.get('Name', '')}, Type=PLAINTEXT, Property={field}: {error}"
                        )
    if findings is not None:
        for (row, source_field, pointer), message in errors.items():
            findings.add_diagnostic(
                Diagnostic.create(
                    findings.canonical_root,
                    code="codebuild.plaintext-reference",
                    cause_kind="input_invalid",
                    check_id="model.reference-policy",
                    service=service_scope(findings.canonical_root, path),
                    source_path=path,
                    location=f"desired.row.{row}.{source_field}{pointer}",
                    message=message,
                )
            )
    return errors


def has_reference(raw):
    """Only internal Resource references, including structured leaves, consume observations."""
    if not isinstance(raw, str):
        return any(nodes(raw))
    try:
        value = strict_json(literal(raw))
    except ValueError:
        return False
    return any(nodes(value))
