"""Reference metadata describes saved text; reads never regenerate consumer values."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback
from pathlib import PurePosixPath

import utils.reference_contracts as _imports_reference_contracts
from utils.json_format import strict_json
from utils.model_addresses import resource_address as resource_address

import model.change_scope as change_plan
import model.core as _imports_model_core
import model.dependency_index as dependency_index
import model.format as _imports_model_projection
import model.identity as _imports_model_identity
import model.importing.scope as _imports_model_importing_scope
import model.sources as source_models
from model.core import ReferenceDiagnosticError, entries, literal
from model.format import LINKS as LINKS
from model.format import json_field, owner
from model.format import link_scope as link_scope
from model.reference_nodes import is_reference, nodes, parse, resolve

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
    "valueSelector",
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
            if mode not in {"link", "name", "identifier"} or len(scope.parts) != 3:
                raise ValueError("invalid resource reference format/scope: " + identity)
            if mode == "link":
                forbidden.add("property")
            else:
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
        if spec["labelPolicy"] not in {"fixed", "resource-id", "display-name", "none"}:
            raise ValueError("invalid reference labelPolicy: " + identity)
        if mode != "link" and spec["labelPolicy"] != "none":
            raise ValueError(
                "non-link reference requires labelPolicy none: " + identity
            )
        if "valueSelector" in spec:
            prop = values.get(key.rsplit(".", 1)[0] + ".property", "")
            if (
                kind != "resource"
                or mode != "link"
                or spec.get("resourceType") != "EC2.VPCEndpoint"
                or not re.fullmatch(r"desired\.row\.[^.]+\.value", key)
                or not re.fullmatch(
                    r"Route53\.RecordSet\.ResourceRecords(?:\[(?:[1-9][0-9]*)?\])?",
                    prop,
                )
                or re.fullmatch(
                    r"dns-entry\[(0|[1-9][0-9]*)\]\.dns-name", spec["valueSelector"]
                )
                is None
            ):
                raise ValueError(
                    "valueSelector requires a Route53 Endpoint DNS link and explicit entry index: "
                    + identity
                )
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
                else source_models.raw_model(scope, reads)
                if change_plan.active()
                else source_models._source_snapshot(scope, reads)
            )
    return cache[scope.path]


def _link_scope(snapshot, filename):
    scope = snapshot.scope
    return link_scope(scope.environment, scope.target, scope.service, filename)


def _callback_usages_producer_for(cache, producers, reads, snapshot, /, scope):
    if scope not in producers:
        producers[scope] = _producer(snapshot, scope, reads, cache)
    return producers[scope]


def _callback_usages_fixed(indexes, producer_for, resource_index, /, scope, logical):
    if scope in indexes:
        match = indexes[scope].get(logical)
        return match[0] if match else None
    producer = producer_for(scope)
    if producer is None:
        return None
    if scope not in indexes:
        indexes[scope] = resource_index(producer.authoritative)
    match = indexes[scope].get(logical)
    return match[0] if match else None


def usages(
    snapshot,
    read_context=None,
    *,
    _cache=None,
    _producer_scope=None,
    _coalesce=True,
    _typed=True,
    _diagnostics=None,
):
    """Extract saved Resource links and declared literal dependencies."""
    anchor_index = _imports_model_identity.anchor_index
    parse_reference = _imports_model_identity.parse_reference
    reference_tokens = _imports_model_identity.reference_tokens
    resource_index = _imports_model_identity.resource_index
    values, result = snapshot.authoritative, []
    reads = read_context or source_models._invocation_reads(snapshot.scope.root)
    cache = {snapshot.scope.path: snapshot} if _cache is None else _cache
    indexes, anchors, producers = {}, {}, {}

    producer_for = _bind_framework_callback(
        _callback_usages_producer_for, cache, producers, reads, snapshot
    )

    fixed = _bind_framework_callback(
        _callback_usages_fixed, indexes, producer_for, resource_index
    )

    resolver = _imports_model_identity.Resolver(snapshot.scope.root, reads)
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
    positions = {
        (
            u.consumer_key,
            u.pointer,
            u.start,
            u.end,
            u.producer_scope,
            u.producer_id,
            u.logical_id,
        )
        for u in result
        if u.producer_kind == "resource" and specs[u.metadata_id]["format"] == "link"
    }
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
        if key.startswith("desired.row.") and values.get(
            key.rsplit(".", 1)[0] + ".property", ""
        ).endswith(".Description"):
            continue
        for pointer, leaf in string_leaves(value):
            for match in reference_tokens(leaf):
                environment, target, service, anchor = parse_reference(
                    match[0], snapshot.scope
                )
                scope = "/".join((environment, target, service))
                if _producer_scope is not None and scope != _producer_scope:
                    continue
                producer = producer_for(scope)
                if producer is not None and scope not in anchors:
                    resource_index(producer.authoritative)
                    anchors[scope] = anchor_index(producer.authoritative)
                matches = anchors.get(scope, {}).get(anchor, ())
                rid, resource = matches[0] if len(matches) == 1 else (None, {})
                logical = resource.get("logicalId")
                position = (
                    key,
                    pointer if structured else None,
                    match.start(),
                    match.end(),
                    scope,
                    rid,
                )
                if not _coalesce or (*position, logical) not in positions:
                    result.append(
                        Usage(
                            *position[:4],
                            match[0],
                            scope,
                            "resource",
                            rid,
                            logical_id=logical,
                        )
                    )
    return tuple(result)


def _callback_diagnose_producer_entries(parsed, /, producer, prefix):
    key = (id(producer), prefix)
    if key not in parsed:
        result = entries(producer.authoritative, prefix)
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
        elif spec:
            ReferenceResolutionError = _imports_model_core.ReferenceResolutionError
            anchor_index = _imports_model_identity.anchor_index
            parse_reference = _imports_model_identity.parse_reference
            select_anchor = _imports_model_identity.select_anchor
            address = parse_reference(usage.text, snapshot.scope)
            expected = (
                producer.scope.environment,
                producer.scope.target,
                producer.scope.service,
            )
            if address[:3] != expected:
                _callback_diagnose_warn(
                    usage,
                    warnings,
                    "declared producer differs from the saved link; both meanings are retained",
                )
                continue
            else:
                key = (id(producer), "anchors")
                if key not in parsed:
                    parsed[key] = anchor_index(values)
                try:
                    number, _ = select_anchor(parsed[key], address[3], usage.text)
                    if number != identity:
                        _callback_diagnose_warn(
                            usage,
                            warnings,
                            "declared producer differs from the saved link; both meanings are retained",
                        )
                        continue
                except ReferenceResolutionError as error:
                    _callback_diagnose_warn(usage, warnings, str(error))
                    continue
        if (
            errors is not None
            and usage.consumer_key.startswith("desired.row.")
            and usage.consumer_key.endswith(".value")
            and spec.get("format", "link") == "link"
        ):
            row = usage.consumer_key.rsplit(".", 1)[0]
            if row + ".document" not in snapshot.authoritative:
                contract = _imports_reference_contracts.contract
                prop = snapshot.authoritative[row + ".property"]
                expected = contract(prop)
                if expected and resource["resourceType"] not in expected:
                    errors.append(
                        f"Resource reference type mismatch: Property={prop}, "
                        f"Consumer={usage.consumer_key}, Element={usage.text!r}, "
                        f"Position={usage.start}:{usage.end}, Pointer={usage.pointer!r}, "
                        f"ExpectedResourceType={'|'.join(expected)}, ActualResourceType={resource['resourceType']}"
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
    scopes = [
        source_models.scope_for(path)
        for path in dependency_index.consumers(
            snapshot.scope.root,
            {address},
            {(snapshot.scope.environment, snapshot.scope.target, logical)},
        )
    ]
    with read_consumers(
        {(scope.environment, scope.target, scope.service) for scope in scopes}
    ):
        for scope in scopes:
            consumer = source_models.raw_model(scope, reads)
            relevant_warnings, _ = diagnose(consumer, reads, _producer_scope=address)
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
                    usage.producer_id == producer_id or usage.logical_id == producer_id
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
        link = LINKS.fullmatch(usage.text)
        record = Reference(
            address,
            usage.producer_kind,
            spec.get("resourceType"),
            "model" if usage.attribute else spec.get("format", "link"),
            usage.attribute or spec.get("property"),
            link[1] if link else None,
            spec.get("labelPolicy"),
            spec.get("contextProperty")
            if usage.producer_kind == "context"
            else usage.logical_id
            if producer_id is None
            else None,
            spec.get("valueSelector"),
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
