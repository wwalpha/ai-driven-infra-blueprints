"""Derived execution/display fields; never serialize these into Model authority."""

import copy
import json
import re
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import design.document as _dependency_design_document
import json_intrinsics as _imports_json_intrinsics
import utils.json_format as _imports_utils_json_format
from design.catalog import design_material_files
from design.layout_schema import RESOURCE
from design.services.definitions.registry import HIDDEN_PROPERTIES
from utils.aws_catalogs import catalog_outputs as catalog_outputs
from utils.input_cache import input_is_file, input_text, memo_table, memoized
from utils.json_format import (
    policy_json,
)
from utils.reference_contracts import reference_attribute as reference_attribute

import model.environment_values as environment_values
import model.identity as _dependency_model_identity
import model.identity as _imports_model_identity
import model.importing.sources as _imports_model_importing_sources
import model.references as _imports_model_references
import model.sources as _imports_model_sources
import model.validation as _model_validation
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
    project,
    receiving_property,
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


def linked_resource(
    path: Path,
    value: str,
    *,
    design_index: "_dependency_design_document.DesignIndex | None" = None,
) -> tuple[str, str] | None:
    match = RESOURCE_LINK.fullmatch(value)
    if not match:
        return None
    _, target_text, fragment = match.groups()
    target = path if not target_text else path.parent / target_text
    if not input_is_file(target):
        return None
    pending_anchor = ""
    view = (
        (design_index or _dependency_design_document.DesignIndex())
        .get(target)
        .view(frozenset({fragment}))
    )
    identities = view.logical_ids
    lines, _ = view.expanded
    for line in lines:
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        elif resource := RESOURCE.fullmatch(line):
            if pending_anchor == fragment:
                return resource.group(1), identities.get(
                    pending_anchor, resource.group(2)
                )
            pending_anchor = ""
    return None


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
    rows = entries(snapshot.authoritative, "desired.row.")
    names = [
        literal(row.get("value", ""))
        for rid, row in rows
        if rid.rpartition("-")[0] == identity
        and row.get("property") == "S3.Bucket.BucketName"
    ]
    if len(names) != 1 or not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", names[0]
    ):
        raise ReferenceResolutionError(
            "deployment bucket requires one confirmed BucketName"
        )
    return names[0]


def observed_value(row_id, row, observed, outputs):
    has_reference = _imports_model_importing_sources.has_reference
    LINKS = _imports_model_references.LINKS
    value = row["value"]
    if observed is not None:
        if link := LINK.fullmatch(value):
            value = (
                observed
                if row["property"] in outputs
                else f"[{literal(observed)}]({link.group(2)}#{link.group(3)})"
            )
        elif has_reference(value) or LINKS.search(value):
            pass  # Structured link labels retain their native string/list shape.
        else:
            raise ValueError(
                f"observed value requires a desired logical reference: {row_id}"
            )
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


def _resource_row_entries(values):
    cache = _resource_row_cache.get()
    if cache is None:
        cache = memo_table()
    if cache is None or not isinstance(values, SnapshotValues):
        return entries(values, "desired.row.")
    key = (_resource_row_entries, id(values))
    if key not in cache:
        cache[key] = (
            values,
            tuple(
                (identity, MappingProxyType(row))
                for identity, row in entries(values, "desired.row.")
            ),
        )
    return cache[key][1]


def resource_rows(
    values: dict[str, str], identity: str, kind: str, root: Path
) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in _resource_row_entries(values):
        if not row_id.startswith(identity + "-"):
            continue
        if (
            set(row) - {"property", "value", "comment", "document"}
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
            parse_reference = _imports_model_identity.parse_reference
            parent = child.get("parentReference", "")
            link = LINK.fullmatch(parent)
            same = (
                link is not None
                and link[3] == resource["anchor"]
                and (
                    not link[2]
                    or scope is not None
                    and parse_reference(parent, scope)[:3]
                    == (scope.environment, scope.target, scope.service)
                )
            )
            if child["resourceType"] == "KMS.Alias" and same:
                rows += resource_rows(values, child_id, child["resourceType"], root)
    return rows


def reference_display(values, path, root, *, reference_values=None):
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
    resolver = reference_resolver(
        values if reference_values is None else reference_values, scope, root
    )
    rows = dict(entries(values, "desired.row."))
    for key, value in values.items():
        if key.startswith("desired.row.") and key.endswith((".document", ".value")):
            raw, structured = _imports_model_references._json(key, value)
            if not structured or key.endswith(".value") and not any(nodes(raw)):
                continue
            pending = []
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
                pending=pending,
                context=_model_validation.reference_context_for(
                    reference_values if reference_values is not None else values,
                    key.split(".")[2],
                    rows[key.split(".")[2]],
                    raw,
                    "",
                    root,
                ),
            )
            result[key] = json.dumps(displayed, ensure_ascii=False)
            if key.endswith(".value") and isinstance(displayed, str):
                result[key] = "`" + displayed + "`"
            elif key.endswith(".value") and value.startswith("`"):
                result[key] = "`" + result[key] + "`"
            if key.endswith(".document") and pending:
                result[key.removesuffix("document") + "value"] = "`PENDING_DEPLOY`"
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
        scope=scope, authoritative=values, dependencies={}
    )
    resolver.models.update(resolver.overrides)
    return resolver


def _resolved_document_value(resolutions, node):
    return resolutions[node].value


def _display_document_value(resolutions, node):
    result = resolutions[node]
    return "PENDING_DEPLOY" if result.status == "pending_deploy" else result.value


def display_document(document, root, *, pending=None, **contract):
    """Allow proven deployment waits only in the display projection."""
    resolutions, diagnostics = document_references(document, **contract)
    if any(d["category"] != "REFERENCE_PENDING_DEPLOY" for d in diagnostics):
        require_reference_diagnostics(diagnostics)
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


def pending_documents(values, scope, root):
    """Return exact artifact rows whose only unresolved values are CREATE/IMPORT waits."""
    resolver = reference_resolver(values, scope, root)
    pending = {}
    for rid, row in entries(values, "desired.row."):
        if "document" not in row:
            continue
        diagnostics = []
        document = display_document(
            policy_json(row["document"]),
            root,
            resolver=resolver,
            scope=scope,
            property_name=row["property"],
            logical_id=values.get(
                f"desired.resource.{rid.rpartition('-')[0]}.logicalId"
            ),
            model_key=f"desired.row.{rid}.document",
            pending=diagnostics,
        )
        if not isinstance(document, dict):
            raise ValueError("JSON document must be an object: " + rid)
        if diagnostics:
            pending[rid] = diagnostics
    return pending


def pending_artifact_links(values, scope, root):
    pending = pending_documents(values, scope, root)
    counts, links = Counter(), {}
    for rid, row in entries(values, "desired.row."):
        anchor = values.get(f"desired.resource.{rid.rpartition('-')[0]}.anchor")
        key = (anchor, row["property"])
        counts[key] += 1
        if rid in pending:
            match = JSON_LINK.fullmatch(row["value"])
            if match is None:
                raise ValueError(
                    "pending JSON document requires an artifact link: " + rid
                )
            path = (
                root
                / "docs/designs"
                / scope.environment
                / scope.target
                / (scope.service + ".md")
            )
            artifact = path.parent / match[1]
            _imports_model_sources.safe(root, artifact)
            if artifact.resolve().parent != path.with_suffix("").resolve():
                raise ValueError(
                    "pending JSON artifact must belong to owning service: " + rid
                )
            links[(*key, counts[key])] = row["value"]
    return links


def restore_pending_artifact_links(rows, anchor, links):
    """Semantic validators still check artifact names/placement for proven waits."""
    counts, result = Counter(), []
    for row in rows:
        counts[row[1]] += 1
        link = links.get((anchor, row[1], counts[row[1]]))
        result.append(
            [*row[:2], link, *row[3:]]
            if link and literal(row[2]) == "PENDING_DEPLOY"
            else list(row)
        )
    return result


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
            expected_context = _model_validation.reference_context_for(
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
        if result.status != "resolved":
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
    """Materialize confirmed Model references only in the generated artifact."""
    resolutions, diagnostics = document_references(
        document,
        resolver=resolver,
        scope=scope,
        property_name=property_name,
        logical_id=logical_id,
        model_key=model_key,
        context=context,
    )
    require_reference_diagnostics(diagnostics)
    resolved = project(document, partial(_resolved_document_value, resolutions))
    if property_name and any(
        value == "PENDING_DEPLOY" for _, value in environment_values._leaves(resolved)
    ):
        kind = ".".join(property_name.split(".")[:2])
        pending = [
            item
            for item in environment_values.inspect(
                kind,
                property_name,
                resolved,
                environment_values.mapping_for(root, kind),
                context=context,
            )
            if item.value == "PENDING_DEPLOY"
        ]
        if pending:
            raise ReferenceResolutionError(
                "environment artifact requires confirmed Values",
                category="REFERENCE_PENDING_DEPLOY",
                code="ENVIRONMENT_VALUE_PENDING",
                model=str(scope.path),
                modelKey=model_key,
                property=property_name,
                pointer=pending[0].pointer,
            )
    return execution_document(
        resolved,
        root,
        property_name=property_name,
        scope=scope,
        logical_id=logical_id,
        warnings=warnings,
    )
