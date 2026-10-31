"""Derived execution/display fields; never serialize these into Model authority."""

import copy
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import design.array_display as _imports_array_display
import design.services.codepipeline as _imports_codepipeline
import json_intrinsics as _imports_json_intrinsics
import utils.json_format as _imports_utils_json_format
from design.catalog import design_material_files
from design.services.definitions.registry import HIDDEN_PROPERTIES
from utils.aws_catalogs import catalog_outputs as catalog_outputs
from utils.input_cache import input_is_file, input_text, memo_table, memoized
from utils.reference_contracts import action_contexts, row_contexts
from utils.reference_contracts import reference_attribute as reference_attribute

import model.environment_values as environment_values
import model.identity as _dependency_model_identity
import model.identity as _imports_model_identity
import model.references as _imports_model_references
import model.sources as _imports_model_sources
from model.core import (
    LINK,
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    SnapshotValues,
    entries,
    literal,
    require_reference_diagnostics,
    validate_bucket_reference,
)
from model.format import JSON_LINK as JSON_LINK
from model.format import REFERENCE_NAME_SUFFIXES as REFERENCE_NAME_SUFFIXES
from model.format import RESOURCE_LINK as RESOURCE_LINK
from model.reference_nodes import (
    context_at,
    nodes,
    parse,
    project,
    receiving_property,
    reference_document,
)
from model.reference_values import reference_value

ANCHOR = re.compile(r'^<a\s+id="([^"]+)"\s*></a>$')


@memoized
def identifier_outputs(root: Path) -> dict[str, set[str]]:
    outputs: dict[str, set[str]] = {}
    for path in design_material_files(root):
        resource_type = path.stem.replace("_", ".", 1)
        outputs[resource_type] = {
            line.partition("=")[0]
            for line in input_text(path, encoding="utf-8").splitlines()
            if line.endswith("=IDENTIFIER_OUTPUT")
            and line.partition("=")[0] not in HIDDEN_PROPERTIES
        }
    return outputs


def bound_stack_names(path):
    stack_snapshot = _imports_model_sources.stack_snapshot
    return {
        stack["placementName"]: stack["name"]
        for _, stack in entries(stack_snapshot(path).authoritative, "desired.stack.")
    }


def bound_resource_anchors(path):
    display_anchor = _imports_model_identity.display_anchor
    load_model = _imports_model_sources.load_model
    path = Path(path).absolute()
    if (
        len(path.parents) >= 5
        and path.parents[2].name == "designs"
        and path.parents[3].name == "docs"
    ):
        path = (
            path.parents[4]
            / "model"
            / path.parents[1].name
            / path.parent.name
            / (path.stem + ".properties")
        )
    if path.suffix != ".properties" or not input_is_file(path):
        return {}
    return {
        (resource["resourceType"], resource["logicalId"]): display_anchor(resource)
        for _, resource in entries(load_model(path).authoritative, "desired.resource.")
    }


def is_import_expression(prop: str, raw_value: str, design: Path) -> bool:
    """Validate the narrow Model ImportValue notation, not arbitrary CFn/YAML."""
    value = literal(raw_value)
    link = re.fullmatch(r"\[([^\]]+)\]\(([^)]*)\)", value)
    expression = link[1] if link else value
    hosted_zone = prop == "Route53.RecordSet.AliasTarget.HostedZoneId"
    if not (
        expression.startswith(("Fn::", "Ref:"))
        or hosted_zone
        and ("Fn::" in value or "${" in value or expression.startswith("!"))
        or hosted_zone
        and value.startswith("[")
        and LINK.fullmatch(value) is None
    ):
        return False
    if (
        not hosted_zone
        or re.fullmatch(r"Fn::ImportValue: [A-Z][A-Za-z0-9]*\$\{Suffix\}", expression)
        is None
    ):
        raise ValueError("invalid or unsupported Model ImportValue expression: " + prop)
    if link:
        if (
            raw_value != value
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md", link[2]) is None
        ):
            raise ValueError(
                "ImportValue link requires a same-target service Markdown filename"
            )
        target = (design.parent / link[2]).resolve()
        if target.parent != design.parent.resolve() or not input_is_file(target):
            raise ValueError(
                "ImportValue link requires an existing same-target service design: "
                + link[2]
            )
    return True


def deployment_bucket(reference: str, path: Path, root: Path) -> str:
    """Resolve the confirmed name from the referenced authoritative S3 model."""
    scope_for = _imports_model_sources.scope_for
    validate_bucket_reference(reference)
    snapshot, identity, resource = _dependency_model_identity.Resolver(root).resolve(
        reference,
        scope_for(
            (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
                ".properties"
            )
            if path.is_relative_to(root / "docs/designs")
            else path
        ),
    )
    if resource["resourceType"] != "S3.Bucket":
        raise ReferenceResolutionError("deployment bucket must identify one S3.Bucket")
    result = reference_value(
        reference_resolver(snapshot.authoritative, snapshot.scope, root),
        snapshot.scope,
        parse(reference),
        field="S3.BucketPolicy.Bucket",
    )
    if result.status != "resolved" or not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", str(result.value)
    ):
        raise ReferenceResolutionError(
            "deployment bucket requires one confirmed BucketName"
        )
    return result.value


def observed_value(row_id, row, observed, outputs):
    value = row["value"]
    if observed is not None:
        if not _imports_model_references.has_reference(value):
            raise ValueError(
                f"observed value requires a desired logical reference: {row_id}"
            )
        if row["property"] in outputs:
            return observed
    return value


_resource_row_cache = ContextVar("resource_row_cache", default=None)


@contextmanager
def resource_row_scope():
    """Reuse parsed rows only within one generation, including nested invocations."""
    token = _resource_row_cache.set({})
    try:
        yield
    finally:
        _resource_row_cache.reset(token)


def _resource_row_entries(values, identity=None):
    cache = _resource_row_cache.get()
    if cache is None:
        cache = memo_table()
    if cache is None or not isinstance(values, SnapshotValues):
        rows = entries(values, "desired.row.")
        return (
            rows
            if identity is None
            else tuple(
                (rid, row) for rid, row in rows if rid.startswith(identity + "-")
            )
        )
    key = (_resource_row_entries, id(values))
    if key not in cache:
        cache[key] = (
            values,
            tuple(
                (identity, MappingProxyType(row))
                for identity, row in entries(values, "desired.row.")
            ),
        )
        groups = {}
        for rid, row in cache[key][1]:
            groups.setdefault(rid.rpartition("-")[0], []).append((rid, row))
        cache[key] = (*cache[key], groups)
    return cache[key][1] if identity is None else cache[key][2].get(identity, ())


def resource_rows(
    values: dict[str, str], identity: str, kind: str, root: Path
) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in _resource_row_entries(values, identity):
        if (
            set(row) - {"property", "value", "comment", "document", "valueShape"}
            or not {"property", "value", "comment"} <= row.keys()
        ):
            raise ValueError(f"invalid resource row: {row_id}")
        observed = values.get(f"observed.row.{row_id}.value")
        value = observed_value(row_id, row, observed, outputs)
        rows.append([row_id, row["property"], value, row["comment"]])
    return rows


def design_target(path: Path, root: Path) -> dict:
    project = root / "project.json"
    if input_is_file(project) and path.is_relative_to(root / "docs/designs"):
        relative = path.parent.relative_to(root / "docs/designs")
        if len(relative.parts) == 2:
            environment, directory = relative.parts
            return next(
                (
                    item
                    for item in json.loads(input_text(project, encoding="utf-8")).get(
                        "targets", []
                    )
                    if item.get("environment") == environment
                    and item.get("alias", item.get("awsAccountId")) == directory
                ),
                {},
            )
    return {}


def resource_display_rows(
    values: dict[str, str],
    identity: str,
    resource: dict[str, str],
    root: Path,
    *,
    scope=None,
) -> list[list[str]]:
    """Include a Key's own grouped aliases when resolving its display name."""
    rows = resource_rows(values, identity, resource["resourceType"], root)
    if resource["resourceType"] == "KMS.Key":
        for child_id, child in entries(values, "desired.resource."):
            parent = child.get("parentReference")
            same = (
                parent is not None and parse(parent).logical_id == resource["logicalId"]
            )
            if child["resourceType"] == "KMS.Alias" and same:
                rows += resource_rows(values, child_id, child["resourceType"], root)
    return rows


def reference_display(
    values, path, root, *, reference_values=None, resolver=None, warnings=None
):
    """Preserve saved links/anchors and project only execution documents for display."""
    scope_for = _imports_model_sources.scope_for
    model_path = (
        (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
        if path.is_relative_to(root / "docs/designs")
        else path
    )
    scope = scope_for(model_path)
    result = dict(values)
    resolver = resolver or reference_resolver(
        values if reference_values is None else reference_values, scope, root
    )
    rows = dict(entries(values, "desired.row."))
    for key, value in values.items():
        if key.startswith("desired.row.") and key.endswith((".document", ".value")):
            raw, structured = _imports_model_references._json(key, value)
            if not structured or key.endswith(".value") and not any(nodes(raw)):
                continue
            displayed = display_document(
                raw,
                root,
                resolver=resolver,
                property_name=values[key.rsplit(".", 1)[0] + ".property"],
                scope=scope,
                logical_id=values.get(
                    f"desired.resource.{key.split('.')[2].rpartition('-')[0]}.logicalId"
                ),
                model_key=key,
                context=reference_context_for(
                    reference_values if reference_values is not None else values,
                    key.split(".")[2],
                    rows[key.split(".")[2]],
                    raw,
                    "",
                    root,
                ),
            )
            result[key] = json.dumps(displayed, ensure_ascii=False)
            if key.endswith(".value"):
                result.pop("observed.row." + key.split(".")[2] + ".value", None)
            if key.endswith(".value") and isinstance(displayed, str):
                result[key] = "`" + displayed + "`"
            elif key.endswith(".value") and value.startswith("`"):
                result[key] = "`" + result[key] + "`"
    if isinstance(values, SnapshotValues):
        return SnapshotValues(result)
    return result


def execution_document(
    document, root, *, property_name=None, scope=None, logical_id=None, warnings=None
):
    """Project design JSON; unresolved CFn expressions retain their authored structure."""
    AwsDocumentError = _imports_utils_json_format.AwsDocumentError

    try:
        project_document = _imports_json_intrinsics.project_document
        document = project_document(
            document,
            warnings=warnings,
            property_name=property_name,
            model_path=scope.path if scope else root,
            logical_id=logical_id,
        )
        projected = document
    except AwsDocumentError as error:
        raise ValueError(
            f"Model={scope.path if scope else root}, Resource logicalId={logical_id}, "
            f"Property={property_name}; {error}"
        ) from error
    return projected


def reference_resolver(values, scope, root):
    resolver = _imports_model_identity.Resolver(
        root, _imports_model_sources._invocation_reads(root)
    )
    resolver.overrides[scope.path] = SimpleNamespace(
        scope=scope,
        authoritative=values,
        dependencies={},
    )
    resolver.models.update(resolver.overrides)
    return resolver


def _resolved_document_value(resolutions, node):
    result = resolutions.get(node)
    return (
        result.value
        if result is not None and result.status == "resolved"
        else "PENDING_DEPLOY"
        if result is not None and result.status == "pending_deploy"
        else reference_document(node)
    )


def _display_document_value(resolutions, node):
    result = resolutions.get(node)
    return (
        result.value
        if result is not None and result.status == "resolved"
        else reference_document(node)
    )


def display_document(document, root, *, pending=None, **contract):
    """Display resolved values where available; retain every unresolved declaration."""
    resolutions, diagnostics = document_references(document, **contract)
    if pending is not None:
        pending.extend(diagnostics)
    # Check the authored structure before replacing reference leaves for display.
    execution_document(
        document,
        root,
        property_name=contract.get("property_name"),
        scope=contract["scope"],
    )
    return execution_document(
        project(document, partial(_display_document_value, resolutions)),
        root,
        property_name=contract.get("property_name"),
        scope=contract["scope"],
        logical_id=contract.get("logical_id"),
    )


def document_references(
    document,
    *,
    resolver,
    scope,
    property_name=None,
    logical_id=None,
    model_key=None,
    context=None,
    excluded_references=(),
):
    """Evaluate typed references without generating a display or document."""
    resolver.refresh()
    cache = memo_table()
    values = resolver.models.get(scope.path)
    values = getattr(values, "authoritative", None)
    key = None
    if (
        cache is not None
        and isinstance(values, SnapshotValues)
        and model_key in values
        and resolver.models.get(scope.path) is resolver.overrides.get(scope.path)
    ):
        key = (
            document_references,
            resolver.reads,
            resolver.reference_revision,
            scope,
            id(values),
            property_name,
            logical_id,
            model_key,
            tuple(excluded_references),
        )
        previous = cache.get(key)
        if previous is not None:
            _, original, receiving_context, result = previous
            if original == document and receiving_context == context:
                return copy.deepcopy(result)
    diagnostics = []
    references = list(nodes(document, errors=diagnostics))
    if not references and not diagnostics:
        return {}, []
    if key is not None:
        expected, structured = _imports_model_references._json(
            model_key, values[model_key]
        )
        row_id = model_key.split(".")[2]
        row = {"property": values.get(f"desired.row.{row_id}.property")}
        expected_context = None
        if property_name is not None and row["property"] is not None:
            expected_context = reference_context_for(
                values, row_id, row, expected, "", scope.root
            )
        if (
            not structured
            or expected != document
            or expected_context != context
            or property_name is not None
            and property_name != row.get("property")
            or logical_id is not None
            and logical_id
            != values.get(f"desired.resource.{row_id.rpartition('-')[0]}.logicalId")
        ):
            key = None
    resolutions = {}
    for node in references:
        if node.pointer in excluded_references:
            continue
        try:
            result = reference_value(
                resolver,
                scope,
                node,
                field=receiving_property(property_name, node.pointer)
                if property_name
                else None,
                property_name=property_name,
                context=context_at(document, property_name, node.pointer, context)
                if property_name
                else None,
            )
        except ReferenceDiagnosticError as error:
            diagnostics.extend(error.diagnostics)
            continue
        resolutions[node] = result
        if result.status not in {"resolved", "logical_only"}:
            diagnostics.append(result.diagnostic)
    for diagnostic in diagnostics:
        diagnostic.update(
            model=str(scope.path),
            resourceLogicalId=logical_id,
            property=property_name,
            modelKey=model_key,
            source=f"docs/designs/{scope.environment}/{scope.target}/{scope.service}.md",
            scope=f"{scope.environment}/{scope.target}/{scope.service}",
        )
    if key is not None:
        cache[key] = (
            values,
            copy.deepcopy(document),
            copy.deepcopy(context),
            copy.deepcopy((resolutions, diagnostics)),
        )
    return resolutions, diagnostics


def design_document(document, root, *, warnings=None, **contract):
    """Keep authored design JSON; Model validation owns its reference contracts."""
    return document


def _pending_document_values(document, pointer=""):
    for position, value in environment_values._leaves(document, pointer):
        if value == "PENDING_DEPLOY":
            yield position
        elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
            try:
                encoded = _imports_utils_json_format.policy_json(value)
            except ValueError:
                continue
            yield from _pending_document_values(encoded, position)


def generated_document(
    document,
    root,
    *,
    resolver,
    scope,
    property_name=None,
    logical_id=None,
    model_key=None,
    context=None,
    warnings=None,
):
    """Project a JSON View; reference waits never certify or prevent AWS execution."""
    resolutions, diagnostics = document_references(
        document,
        resolver=resolver,
        scope=scope,
        property_name=property_name,
        logical_id=logical_id,
        model_key=model_key,
        context=context,
    )
    if any(
        d["category"] not in {"REFERENCE_PENDING_DEPLOY", "REFERENCE_UNRESOLVED"}
        for d in diagnostics
    ):
        require_reference_diagnostics(diagnostics)
    if warnings is not None:
        warnings.extend(d for d in diagnostics if d not in warnings)
    resolved = project(document, partial(_resolved_document_value, resolutions))
    projected = execution_document(
        resolved,
        root,
        property_name=property_name,
        scope=scope,
        logical_id=logical_id,
        warnings=warnings,
    )
    for pending in _pending_document_values(projected):
        if warnings is None or any(d.get("pointer") == pending for d in diagnostics):
            continue
        diagnostic = ReferenceResolutionError(
            "JSON View contains PENDING_DEPLOY",
            category="REFERENCE_PENDING_DEPLOY",
            code="REFERENCE_PENDING_DEPLOY",
            model=str(scope.path),
            resourceLogicalId=logical_id,
            modelKey=model_key,
            property=property_name,
            pointer=pending,
            scope=f"{scope.environment}/{scope.target}/{scope.service}",
        ).diagnostic
        if diagnostic not in warnings:
            warnings.append(diagnostic)
    return projected


def configuration_contexts(values, number, root):
    """Index action membership without parsing Configuration documents."""
    kind = "CodePipeline.Pipeline"
    rows = [
        [
            rid,
            row["property"].removeprefix(kind + "."),
            row["value"],
            row.get("comment", ""),
        ]
        for rid, row in entries(values, "desired.row.")
        if rid.rpartition("-")[0] == number
    ]
    indexed = _imports_array_display.indexed_rows(
        _imports_codepipeline.pipeline_membership(rows), kind, root
    )
    contexts = action_contexts(
        [(rid, {"property": prop, "value": value}) for rid, prop, value, _ in indexed]
    )
    return {
        rid: contexts.get(prop.rsplit(".Configuration", 1)[0], {})
        for rid, prop, _, _ in indexed
        if prop.endswith(".Configuration") or ".Configuration." in prop
    }


def configuration_context(values, row_id, root):
    return configuration_contexts(values, row_id.rpartition("-")[0], root).get(
        row_id, {}
    )


def reference_context_for(
    values, row_id, row, value, pointer, root, *, configuration_contexts_by_row=None
):
    """Share the existing split-row and nested JSON receiving-context contract."""
    context = (
        (
            configuration_context(values, row_id, root)
            if configuration_contexts_by_row is None
            else configuration_contexts_by_row.get(row_id, {})
        )
        if row["property"].startswith(
            "CodePipeline.Pipeline.Stages[].Actions[].Configuration"
        )
        and not isinstance(value, list)
        else None
    )
    if context is None:
        kind = ".".join(row["property"].split(".")[:2])
        number = row_id.rpartition("-")[0]
        contexts = row_contexts(
            kind,
            [
                (rid, item)
                for rid, item in _resource_row_entries(values)
                if rid.rpartition("-")[0] == number
            ],
        )
        prop = row["property"].removeprefix(kind + ".")
        context = contexts.get(
            row_id, contexts.get(prop, contexts.get(prop.rsplit(".", 1)[0]))
        )
    context = context_at(value, row["property"], pointer, context)
    return context


def validate_json_documents(
    values,
    model_path,
    *,
    warnings=None,
    excluded_references=(),
    reference_values=None,
    context_values=None,
):
    """Generation structure/reference checks, independent of Model quality rules."""
    reference_tokens = _imports_model_identity.reference_tokens
    _json = _imports_model_references._json
    string_leaves = _imports_model_references.string_leaves
    path = Path(model_path)
    if path.suffix == ".md" and path.parents[2].name == "designs":
        path = (
            path.parents[4]
            / "model"
            / path.relative_to(path.parents[4] / "docs/designs")
        ).with_suffix(".properties")
    resolver = None
    diagnostics = []
    context_source = values if context_values is None else context_values
    pipeline_contexts = {}
    for row_id, row in entries(values, "desired.row."):
        if not {"property", "value"} <= row.keys():
            raise ValueError("invalid resource row: " + row_id)
        for field in ("value", "document"):
            if field not in row:
                continue
            value, structured = _json(f"desired.row.{row_id}.{field}", row[field])
            if not structured:
                if any(nodes(value)):
                    raise ValueError(
                        "JSON Model references in .value require the existing JSON backtick notation"
                    )
                continue
            if resolver is None:
                scope = _imports_model_sources.scope_for(path)
                resolver = reference_resolver(
                    values if reference_values is None else reference_values,
                    scope,
                    scope.root,
                )
            number = row_id.rpartition("-")[0]
            if (
                row["property"].startswith(
                    "CodePipeline.Pipeline.Stages[].Actions[].Configuration"
                )
                and number not in pipeline_contexts
            ):
                pipeline_contexts[number] = configuration_contexts(
                    context_source, number, scope.root
                )
            _, row_diagnostics = document_references(
                value,
                resolver=resolver,
                scope=scope,
                property_name=row["property"],
                logical_id=values.get(
                    f"desired.resource.{row_id.rpartition('-')[0]}.logicalId"
                ),
                model_key=f"desired.row.{row_id}.{field}",
                context=reference_context_for(
                    context_source,
                    row_id,
                    row,
                    value,
                    "",
                    scope.root,
                    configuration_contexts_by_row=pipeline_contexts.get(number),
                ),
                excluded_references=tuple(
                    pointer
                    for identity, source_field, pointer in excluded_references
                    if (identity, source_field) == (row_id, field)
                ),
            )
            diagnostics.extend(row_diagnostics)
            number = row_id.rpartition("-")[0]
            resource = values.get(f"desired.resource.{number}.logicalId", number)
            for pointer, text in string_leaves(value):
                if (row_id, field, pointer) in excluded_references:
                    continue
                if any(reference_tokens(text)):
                    raise ValueError(
                        f"JSON setting contains a Markdown Resource link: Model={model_path}, "
                        f"Resource={resource} ({number}), Property={row['property']}, "
                        f"JSON Pointer={pointer!r}; use confirmed AWS values and external desired.reference metadata"
                    )
            _imports_json_intrinsics.validate_document(
                value,
                warnings=warnings,
                model_path=model_path,
                logical_id=resource,
                property_name=row["property"],
            )

    try:
        require_reference_diagnostics(diagnostics)
    except ReferenceResolutionError as error:
        if warnings is not None:
            warnings.extend(error.diagnostics)
