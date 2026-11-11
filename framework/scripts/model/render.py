"""Render detailed designs from authoritative service properties."""

from __future__ import annotations

import html
import json
from collections import Counter
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace as _CallbackState

import aws_mapping_display as _dependency_aws_mapping_display
import design.array_display as _dependency_array_display
import design.layout as _dependency_design_layout
import design.policy_tables as _dependency_policy_tables
import design.policy_tables as _imports_policy_tables
import design.services.cloudtrail as _cloudtrail_presentation
import design.services.codepipeline as _codepipeline_presentation
import design.services.ec2.security_groups as _ec2_security_groups
from contracts.model import (
    MODEL_PENDING_DEPLOY,
    MODEL_UNSET,
    RESOURCE_LOGICAL_ID_KEY,
    RESOURCE_MODE_CREATE,
    RESOURCE_TYPE_KEY,
)
from contracts.repository import DESIGNS_DIRECTORY
from design.catalog import DesignSchemaCatalog as DesignSchemaCatalog
from design.layout_schema import GROUPED
from design.layout_schema import resource_anchor as resource_anchor
from design.services.definitions.lambda_permission import LAMBDA_PERMISSION
from design.services.definitions.quicksight import (
    RESOURCE_REFERENCE_PROPERTIES as QUICKSIGHT_LINK_PROPERTIES,
)
from design.services.definitions.registry import HIDDEN_PROPERTIES
from design.services.definitions.secrets_manager import ROTATION_SCHEDULE
from sync_files import changed_files
from task_contract_core import task_read_scope
from utils.aws_catalogs import catalog_outputs as catalog_outputs
from utils.input_cache import (
    input_bytes,
    input_is_file,
    input_recorder,
    input_scope,
    input_select,
    recording_inputs,
)
from utils.json_format import policy_json
from validation.diagnostics import InputValidationError

import model.display as _dependency_model_display
import model.files as _imports_model_files
import model.identity as _imports_model_identity
import model.projection as _dependency_model_projection
import model.projection as _imports_model_projection
import model.reference_presentation as _reference_presentation
import model.references as _model_references
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources
from model.change_scope import change_reads
from model.core import (
    ARTIFACT_FIELDS,
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    deployment_settings,
    entries,
    require_reference_diagnostics,
    stack_model,
)
from model.core import (
    properties as properties,
)
from model.format import JSON_LINK
from model.reference_nodes import parse, resolve
from model.references import _json as parse_reference_field


def stack_markdown(
    path, values, root, *, definitions_root=None, validate_delivery=True
):
    reference_display = _imports_model_projection.reference_display
    limit, stacks = stack_model(values)
    settings, artifacts = deployment_settings(values)
    displayed = reference_display(values, path, root)
    presentation = _reference_presentation.Presentation(values, path, root)
    display_artifacts = dict(entries(displayed, "desired.artifact."))
    for artifact in display_artifacts.values():
        artifact["bucket"] = (
            presentation.link(
                parse(artifact["bucket"]),
                position=_reference_presentation.Position("", "value", ""),
                field="S3.BucketPolicy.Bucket",
            )
            or artifact["bucket"]
        )
    displayed_settings = dict(settings)
    if settings and _model_references.has_reference(settings["templateBucket"]):
        displayed_settings["templateBucket"] = (
            presentation.link(
                parse(settings["templateBucket"]),
                position=_reference_presentation.Position("", "value", ""),
                field="S3.BucketPolicy.Bucket",
            )
            or settings["templateBucket"]
        )
    delivery = []
    if artifacts:
        delivery = [
            "",
            "## S3配置",
            "",
            "### 配置ファイル",
            "",
            "| No. | StackName | Resource | Property | Source | Bucket | KeyPrefix |",
            "| ---: | --- | --- | --- | --- | --- | --- |",
        ]
        delivery += [
            "| "
            + " | ".join(
                [str(number)]
                + [display_artifacts[identity][field] for field in ARTIFACT_FIELDS]
            )
            + " |"
            for number, (identity, artifact) in enumerate(artifacts, 1)
        ]
    if (
        settings
        and validate_delivery
        and _model_references.has_reference(settings["templateBucket"])
    ):
        _dependency_model_projection.deployment_bucket(
            settings["templateBucket"], path, root
        )
    if validate_delivery:
        for _, artifact in artifacts:
            _dependency_model_projection.deployment_bucket(
                artifact["bucket"], path, root
            )
    return (
        "\n".join(
            [
                "# CloudFormation stack 詳細設計",
                "",
                f"<!-- max-concurrent-stacks: {limit} -->",
                "",
                *[
                    f"<!-- {field}: {value} -->"
                    for field, value in displayed_settings.items()
                ],
                "## Stack一覧",
                "",
                "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |",
                "| ---: | ---: | --- | --- | --- | --- |",
                *[
                    "| "
                    + " | ".join(
                        [
                            str(number),
                            stack["deployOrder"],
                            stack["name"],
                            stack["template"],
                            stack["parameters"],
                            values[f"display.stack.{identity}.comment"],
                        ]
                    )
                    + " |"
                    for number, (identity, stack) in enumerate(stacks, 1)
                ],
                *delivery,
            ]
        )
        + "\n"
    )


def display_name(
    values,
    identity,
    resource,
    rows,
    root,
    *,
    projection=False,
    resource_count: int | None = None,
) -> tuple[str | None, str | None]:
    """Pure final display selection, shared by rendering and reference diagnostics."""
    kind = resource[RESOURCE_TYPE_KEY]
    label = values.get(f"display.resource.{identity}.label")
    if GROUPED.get(kind, {}).get("display") == "rule-table":
        return label or resource[RESOURCE_LOGICAL_ID_KEY], None
    mode = _dependency_design_layout.resource_mode(resource)
    count = (
        sum(
            item[RESOURCE_TYPE_KEY] == kind
            for _, item in entries(values, "desired.resource.")
        )
        if resource_count is None
        else resource_count
    )
    return _dependency_design_layout.resource_display_selection(
        root,
        kind,
        rows,
        label,
        mode,
        count,
        fallback=resource[RESOURCE_LOGICAL_ID_KEY] if projection else None,
    )


def resource_presentation(
    values,
    identity,
    resource,
    root,
    *,
    scope=None,
    projection=False,
    resource_count: int | None = None,
):
    kind = resource[RESOURCE_TYPE_KEY]
    rows = _dependency_model_display.catalog_display_rows(
        _dependency_model_projection.resource_rows(values, identity, kind, root),
        kind,
        root,
    )
    try:
        name, configured = display_name(
            values,
            identity,
            resource,
            _dependency_model_projection.resource_display_rows(
                values, identity, resource, root, scope=scope
            ),
            root,
            projection=projection,
            resource_count=resource_count,
        )
    except InputValidationError as error:
        if scope is not None:
            error.source_path = error.source_path or scope.path
        raise
    return name, configured, rows


def _callback_resource_details_inspect(
    _state_resource_details_122,
    by_anchor,
    details,
    names,
    owned,
    root,
    scope,
    values,
    /,
):
    display_anchor = _imports_model_identity.display_anchor
    pass
    kind = _state_resource_details_122.resource[RESOURCE_TYPE_KEY]
    if kind not in owned:
        raise InputValidationError(f"resource is outside service ownership: {kind}")
    name, configured_name, rows = resource_presentation(
        values,
        _state_resource_details_122.identity,
        _state_resource_details_122.resource,
        root,
        scope=scope,
    )
    if configured_name is None and name is None:
        raise InputValidationError(
            f"resource type display requires a single nameless independent resource: {kind}"
        )
    if not name or name in {MODEL_UNSET, MODEL_PENDING_DEPLOY}:
        raise InputValidationError(
            f"confirmed resource display label is missing: {kind}: {_state_resource_details_122.identity}"
        )
    anchor = display_anchor(_state_resource_details_122.resource)
    _state_resource_details_122.resource = {
        **_state_resource_details_122.resource,
        "anchor": anchor,
    }
    derived = anchor
    if anchor in by_anchor:
        raise ReferenceResolutionError("duplicate Resource display anchor: " + anchor)
    names.add(derived)
    item = (
        _state_resource_details_122.identity,
        _state_resource_details_122.resource,
        name,
        rows,
    )
    by_anchor[anchor] = item
    details.append(item)


def resource_details(
    values, root, service, owned, resources, bound_anchors, *, findings=None, scope=None
):
    _state_resource_details_122 = _CallbackState()
    by_anchor = {}
    names = set()
    details = []
    for (
        _state_resource_details_122.identity,
        _state_resource_details_122.resource,
    ) in resources:
        inspect = _bind_framework_callback(
            _callback_resource_details_inspect,
            _state_resource_details_122,
            by_anchor,
            details,
            names,
            owned,
            root,
            scope,
            values,
        )
        if findings is None:
            inspect()
        else:
            findings.evaluate(
                "model.resource." + _state_resource_details_122.identity, None, inspect
            )
    return details, by_anchor


def grouped_resources(values, details, by_anchor, *, scope=None):
    resolver = _imports_model_projection.reference_resolver(values, scope, scope.root)
    by_logical = {item[1][RESOURCE_LOGICAL_ID_KEY]: item for item in details}
    grouped: dict[str, list] = {}
    for item in details:
        identity, resource, name, rows = item
        if resource[RESOURCE_TYPE_KEY] not in GROUPED:
            continue
        kind = resource[RESOURCE_TYPE_KEY]
        rule = GROUPED[kind]
        for field in ("parentReference", "parentProperty"):
            if not resource.get(field):
                raise InputValidationError(
                    f"{kind}: {resource[RESOURCE_LOGICAL_ID_KEY]}: required metadata missing: desired.resource.{identity}.{field} ({kind}.{rule['parentProperty']})"
                )
        node = parse(resource["parentReference"])
        snapshot, _, target, _ = resolve(
            node, scope, resolver, field=resource["parentProperty"]
        )
        parent = by_logical.get(node.logical_id) if snapshot.scope == scope else None
        if resource["parentProperty"] != kind + "." + rule["parentProperty"]:
            raise InputValidationError("invalid grouped parentProperty: " + identity)
        if not parent or parent[1][RESOURCE_TYPE_KEY] != rule["parent"]:
            raise ReferenceResolutionError(
                f"{kind}: {resource[RESOURCE_LOGICAL_ID_KEY]}: invalid grouped parent: parentReference / parentProperty ({kind}.{rule['parentProperty']})"
            )
        if kind in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
            parent_rows = [
                row
                for row_id, row in entries(values, "desired.row.")
                if row_id.startswith(identity + "-")
                and row.get("property") == resource["parentProperty"]
            ]
            if len(parent_rows) != 1:
                raise InputValidationError(
                    f"{kind}: {resource[RESOURCE_LOGICAL_ID_KEY]}: {resource['parentProperty']} requires exactly one formal row matching parentReference"
                )
            same = parse(parent_rows[0]["value"]) == node
            if not same:
                raise ReferenceResolutionError(
                    "grouped formal row does not match parentReference",
                    resource=identity,
                    property=resource["parentProperty"],
                )
            if kind + ".Id" not in HIDDEN_PROPERTIES and (
                not rows or rows[0][1] != kind + ".Id"
            ):
                raise InputValidationError(
                    f"{kind}: {resource[RESOURCE_LOGICAL_ID_KEY]}: required first property: {kind}.Id"
                )
        grouped.setdefault(parent[0], []).append(item)
        maximum = rule["maxCount"]
        if (
            maximum is not None
            and sum(child[1][RESOURCE_TYPE_KEY] == kind for child in grouped[parent[0]])
            > maximum
        ):
            raise InputValidationError(
                f"{kind}: {resource[RESOURCE_LOGICAL_ID_KEY]}: too many grouped children for {parent[1][RESOURCE_LOGICAL_ID_KEY]}: {resource['parentProperty']}"
            )
    return grouped


def resource_table_lines(
    resource,
    name,
    rows,
    children,
    root,
    *,
    references=None,
    formal=False,
    indexed=True,
    json_cells=None,
    documents=None,
    presentation=None,
):
    sources = references or {}
    source = sources.get(resource.get(RESOURCE_LOGICAL_ID_KEY))
    if formal:
        originals = {
            row[0]: row
            for item in sources.values()
            for row in item.rows
            if row[0] in item.reference_ids
        }
        rows = [list(originals.get(row[0], row)) for row in rows]
        children = [
            (
                rid,
                child,
                child_name,
                [list(originals.get(row[0], row)) for row in child_rows],
            )
            for rid, child, child_name, child_rows in children
        ]
    selected = _dependency_aws_mapping_display.selected_rows(rows, root)
    if resource[RESOURCE_TYPE_KEY] == "CodePipeline.Pipeline":
        _codepipeline_presentation.validate_selection(rows, selected)
    expected = Counter(row[0] for row in selected)
    for _, _, _, child_rows in children:
        expected.update(
            row[0]
            for row in _dependency_aws_mapping_display.selected_rows(child_rows, root)
        )
    if any(count != 1 for count in expected.values()):
        raise ValueError("duplicate selected Model row IDs")
    consumed = []
    output = []
    kind = resource[RESOURCE_TYPE_KEY]
    if kind == "EC2.SecurityGroup":
        rules = [
            (child, _dependency_aws_mapping_display.selected_rows(child_rows, root))
            for _, child, _, child_rows in children
        ]
        output += _ec2_security_groups.sg_tables(
            _dependency_aws_mapping_display.selected_rows(rows, root),
            [(child, rows) for child, rows in rules if rows],
            root,
            consumed=consumed,
        )
    else:
        display = (
            [
                list(row)
                for row in _dependency_aws_mapping_display.selected_rows(rows, root)
            ]
            if formal
            else display_rows(
                kind,
                rows,
                root,
                mode=_dependency_design_layout.resource_mode(resource),
                consumed=consumed,
                references=source.reference_ids if source else None,
            )
        )
        if formal:
            consumed.extend(row[0] for row in display)
        elif indexed:
            display = _dependency_array_display.compact_tag_rows(display)
        for _, child, child_name, child_rows in children:
            child_rows = _dependency_aws_mapping_display.selected_rows(child_rows, root)
            if not child_rows:
                continue
            if child[RESOURCE_TYPE_KEY] == ROTATION_SCHEDULE:
                child_rows = [
                    [
                        rid,
                        prop,
                        f"[{name}](#{resource['anchor']})"
                        if prop == child["parentProperty"]
                        else value,
                        comment,
                    ]
                    for rid, prop, value, comment in child_rows
                ]
            child_source = sources.get(child[RESOURCE_LOGICAL_ID_KEY])
            child_display = (
                [list(row) for row in child_rows]
                if formal
                else display_rows(
                    kind
                    if child[RESOURCE_TYPE_KEY] == ROTATION_SCHEDULE
                    else child[RESOURCE_TYPE_KEY],
                    child_rows,
                    root,
                    mode=_dependency_design_layout.resource_mode(child),
                    consumed=consumed,
                    references=child_source.reference_ids if child_source else None,
                )
            )
            if formal:
                consumed.extend(row[0] for row in child_display)
            elif indexed:
                child_display = _dependency_array_display.compact_tag_rows(
                    child_display
                )
            if not formal and child[RESOURCE_TYPE_KEY] != ROTATION_SCHEDULE:
                for row in child_display:
                    row[1] = child[RESOURCE_TYPE_KEY] + "." + row[1]
            if not formal and child[RESOURCE_TYPE_KEY] == LAMBDA_PERMISSION:
                hidden = [
                    row[1:]
                    for row in child_rows
                    if row[1]
                    in {LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"}
                ]
                child_display = [
                    row
                    for row in child_display
                    if row[1]
                    not in {
                        LAMBDA_PERMISSION + ".Id",
                        LAMBDA_PERMISSION + ".FunctionName",
                    }
                ]
                metadata = json.dumps(
                    [child_name, hidden], ensure_ascii=False, separators=(",", ":")
                )
                for char in "<>|()":
                    metadata = metadata.replace(char, "\\u%04x" % ord(char))
                for row in child_display:
                    row[1] = row[1].removeprefix("Lambda.")
                child_display[0][3] = (
                    f"<!-- lambda-permission: {metadata} --> " + child_display[0][3]
                )
            prefix = f'<a id="{child["anchor"]}"></a><!-- logical-id: {child[RESOURCE_LOGICAL_ID_KEY]} --> '
            if (
                child[RESOURCE_TYPE_KEY] == ROTATION_SCHEDULE
                or formal
                and child[RESOURCE_TYPE_KEY] == LAMBDA_PERMISSION
            ):
                prefix += child_name + "："
            child_display[0][3] = prefix + child_display[0][3]
            display += child_display
        if not formal and indexed:
            display = _dependency_array_display.indexed_rows(display, kind, root)
        if not formal and kind == "SecretsManager.Secret":
            for row in display:
                if row[1].startswith(ROTATION_SCHEDULE + "."):
                    row[1] = row[1].removeprefix("SecretsManager.")
        if json_cells is not None:
            display = collapse_json_cells(
                display, resource["anchor"], json_cells, documents, presentation
            )
        output += _dependency_model_display.row_table(display)
    if Counter(consumed) != expected:
        raise ValueError(
            "selected display rows were omitted or consumed more than once"
        )
    return output


def _task_root(path, *args, **kwargs):
    return _imports_model_sources.design_project_root(path)


@input_scope
def markdown_for(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    definitions_root: Path | None = None,
    warnings=None,
    generated_documents=None,
) -> str:
    """Generate a View; Model quality belongs to Change or Full Validation."""
    return render_validated_model(
        path,
        values,
        root,
        definitions_root=definitions_root,
        warnings=warnings,
        generated_documents=generated_documents,
    )


@task_read_scope(root=_task_root)
def render_validated_model(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    definitions_root: Path | None = None,
    warnings=None,
    generated_documents=None,
) -> str:
    """Render structure and references without Model quality validation."""
    return generate_markdown(
        path,
        values,
        definitions_root or root,
        warnings=warnings,
        generated_documents=generated_documents,
    )


@task_read_scope(root=_task_root)
@input_scope
def generate_markdown(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    reference_tables=None,
    reference_values=None,
    warnings=None,
    generated_documents=None,
) -> str:
    """Render selected values; reference_values supplies the complete candidate context."""
    reference_values = values if reference_values is None else reference_values
    if path.stem == "cloudformation-stacks":
        return stack_markdown(path, values, path.parents[4], validate_delivery=False)
    return _generate_markdown(
        path,
        values,
        root,
        reference_tables=reference_tables,
        reference_values=reference_values,
        warnings=warnings,
        generated_documents=generated_documents,
    )


@input_scope
def _generate_markdown(
    path,
    values,
    root,
    *,
    reference_tables=None,
    reference_values=None,
    warnings=None,
    generated_documents=None,
):
    """Draw only values checked by the enclosing public generation entry."""
    reference_display = _imports_model_projection.reference_display
    scope_for = _imports_model_sources.scope_for
    references = _dependency_model_display.reference_rows(values)
    presentation = _reference_presentation.Presentation(
        values,
        path,
        path.parents[4],
        reference_values=reference_values,
        service_presentation=_cloudtrail_presentation
        if path.stem == "cloudtrail"
        else None,
    )
    values = reference_display(
        values,
        path,
        path.parents[4],
        reference_values=reference_values,
        resolver=presentation.resolver,
        warnings=warnings,
    )
    service = path.stem
    owned = values.get(
        f"desired.service.{service}.ownedCatalogResourceTypes", ""
    ).split(",")
    details = []
    # Partial Views retain the full candidate's naming context without rendering its other rows.
    resource_counts = Counter(
        resource[RESOURCE_TYPE_KEY]
        for _, resource in entries(
            values if reference_values is None else reference_values,
            "desired.resource.",
        )
    )
    for identity, resource in entries(values, "desired.resource."):
        kind = resource[RESOURCE_TYPE_KEY]
        Scope = _imports_model_sources.Scope
        scope = Scope(
            path.parents[4], path.parent.parent.name, path.parent.name, path.stem
        )
        name, _, rows = resource_presentation(
            values,
            identity,
            resource,
            root,
            scope=scope,
            projection=True,
            resource_count=resource_counts[kind],
        )
        name = name or kind
        display_anchor = _imports_model_identity.display_anchor
        resource = {**resource, "anchor": display_anchor(resource)}
        details.append((identity, resource, name, rows))
    by_anchor = {item[1]["anchor"]: item for item in details}
    scope = scope_for(
        (
            path.parents[4]
            / "model"
            / path.relative_to(path.parents[4] / DESIGNS_DIRECTORY)
        ).with_suffix(".properties")
    )
    grouped = grouped_resources(reference_values, details, by_anchor, scope=scope)
    if generated_documents is None:
        generated_documents = project_view_documents(
            presentation.values,
            presentation.scope,
            presentation.root,
            resolver=presentation.resolver,
            warnings=warnings,
        )
    documents = document_views(presentation.values, generated_documents)
    return render_markdown(
        path,
        values,
        root,
        owned,
        details,
        grouped,
        documents=documents,
        references=references,
        reference_tables=reference_tables,
        presentation=presentation,
    )


def service_note_markdown(values):
    """Render the service-owned suffix separately from Resource displays."""
    return "".join(
        "\n\n" + note["text"] for _, note in entries(values, "desired.note.")
    )


def render_markdown(
    path,
    values,
    root,
    owned,
    details,
    grouped,
    *,
    documents=None,
    references=None,
    reference_tables=None,
    presentation=None,
):
    children = {item[0] for items in grouped.values() for item in items}
    independent = [item for item in details if item[0] not in children]
    output = [values["display.service.title"], "", "## リソース一覧"]
    for kind in dict.fromkeys(item[1][RESOURCE_TYPE_KEY] for item in independent):
        items = [item for item in independent if item[1][RESOURCE_TYPE_KEY] == kind]
        output += [
            "",
            "### " + kind,
            "",
            *_dependency_policy_tables.table(
                ["No.", "ResourceName", "Comment"],
                [
                    [
                        str(number),
                        f"[{name}](#{resource['anchor']})",
                        values[f"display.resource.{identity}.comment"],
                    ]
                    for number, (identity, resource, name, _) in enumerate(items, 1)
                ],
                numbered=True,
            ),
        ]
    output += ["", "## リソース詳細"]
    for identity, resource, name, rows in independent:
        kind = resource[RESOURCE_TYPE_KEY]
        heading = (
            f"### {kind}"
            if name == kind
            and _dependency_design_layout.resource_display_name(
                kind,
                rows,
                mode=_dependency_design_layout.resource_mode(resource),
                root=root,
            )
            is None
            else f"### {kind}: {name}"
        )
        output += [
            "",
            f"<!-- resource-logical-id: {resource[RESOURCE_LOGICAL_ID_KEY]} -->",
            f'<a id="{resource["anchor"]}"></a>',
            "",
            heading,
            "",
        ]
        children = grouped.get(identity, [])
        json_cells = {}
        linked = presentation is not None and bool(presentation.marker_links)
        table = resource_table_lines(
            resource,
            name,
            presentation.rows(rows) if linked else rows,
            [
                (rid, child, child_name, presentation.rows(child_rows))
                for rid, child, child_name, child_rows in children
            ]
            if linked
            else children,
            root,
            references=references,
            json_cells=json_cells,
            documents=documents,
            presentation=presentation if linked else None,
        )
        if linked:
            table = presentation.lines(table, table)
        output += table
        sources = (
            tuple(
                references[item[RESOURCE_LOGICAL_ID_KEY]]
                for item in [resource, *(child[1] for child in children)]
            )
            if references
            else ()
        )
        if reference_tables is not None:
            semantic = resource_table_lines(
                resource, name, rows, children, root, references=references, formal=True
            )
            # QuickSight Principal must remain a link when the parser checks this table.
            quicksight_links = (
                presentation is not None and kind == "QuickSight.DataSource"
            )
            baseline = resource_table_lines(
                resource,
                name,
                [
                    presentation.rows([row])[0]
                    if row[1] in QUICKSIGHT_LINK_PROPERTIES
                    else row
                    for row in rows
                ]
                if quicksight_links
                else rows,
                children,
                root,
                references=references,
                indexed=False,
            )
            if quicksight_links:
                baseline = presentation.lines(baseline, baseline)
            reference_tables.append(
                _dependency_model_display.ReferenceTable(
                    resource["anchor"],
                    sources,
                    tuple(table),
                    tuple(semantic),
                    tuple(baseline),
                )
            )
        if json_cells:
            start, end = (
                (_imports_policy_tables.IAM_START, _imports_policy_tables.IAM_END)
                if kind == "IAM.Role"
                else (_imports_policy_tables.START, _imports_policy_tables.END)
            )
            output += ["", start]
            for anchor, title, label, document, _ in json_cells.values():
                output += [
                    "",
                    f'<a id="{anchor}"></a>',
                    "",
                    f"#### {html.escape(title)}",
                    "",
                    "<details>",
                    f"<summary>{html.escape(label)}</summary>",
                    "",
                    "```json",
                    json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False),
                    "```",
                    "",
                    "</details>",
                ]
            output += ["", end]
        if kind == "Macie.ClassificationJob":
            definitions = [row for row in rows if row[1] == kind + ".s3JobDefinition"]
            if definitions:
                row_id = definitions[0][0]
                raw = (
                    values[f"desired.row.{row_id}.document"]
                    if f"desired.row.{row_id}.document" in values
                    else _dependency_policy_tables.literal(
                        values[f"desired.row.{row_id}.value"]
                    )
                )
                document = policy_json(raw)
                if "bucketDefinitions" in document:
                    mappings = [
                        [
                            f"[{name}](#{resource['anchor']})",
                            f"`{group['accountId']}`",
                            f"`{bucket}`",
                        ]
                        for group in document["bucketDefinitions"]
                        for bucket in group["buckets"]
                    ]
                    output += [
                        "",
                        "#### 対象S3 bucket",
                        "",
                        *_dependency_policy_tables.table(
                            ["Job", "AWS account ID", "Bucket"], mappings
                        ),
                    ]
    return "\n".join(output) + service_note_markdown(values) + "\n"


def collapse_json_cells(rows, anchor_prefix, cells, documents, presentation):
    """Collapse visible JSON cells after applying service-specific table layouts."""
    result = []
    for index, (rid, prop, value, comment) in enumerate(rows):
        if rid in documents:
            cells[index] = documents[rid]
        elif presentation is None or not any(
            marker in value for marker in presentation.marker_links
        ):
            raw = _dependency_policy_tables.literal(value)
            if raw.lstrip().startswith(("{", "[")):
                try:
                    raw = policy_json(raw)
                except json.JSONDecodeError:
                    pass  # Markdown links and other textual settings may start with '['.
            if isinstance(raw, (dict, list)) and raw:
                cells[index] = (
                    f"{anchor_prefix}-json-{rid}-{index + 1}",
                    f"JSON：{prop}",
                    prop,
                    raw,
                    "JSON",
                )
        if index in cells:
            anchor, _, _, _, label = cells[index]
            value = f"[{label}](#{anchor})"
        result.append([rid, prop, value, comment])
    anchors = [cell[0] for cell in cells.values()]
    if len(anchors) != len(set(anchors)):
        raise ValueError("duplicate JSON display anchor: " + anchor_prefix)
    return result


def document_views(values, documents):
    """Retain policy labels and anchors previously shown in generated designs."""
    policy_tables = _imports_policy_tables
    result = {}
    rows_by_resource = _imports_model_files.resource_row_index(values)
    for identity, resource in entries(values, "desired.resource."):
        rows = rows_by_resource[identity]
        for position, (rid, row) in enumerate(rows):
            if rid not in documents:
                continue
            prop = row["property"]
            label, target = policy_tables.JSON_LINK.fullmatch(row["value"]).groups()
            link_label = label.removesuffix(".json")
            trust = prop == "IAM.Role.AssumeRolePolicyDocument"
            inline = prop in policy_tables.INLINE_POLICY_DOCUMENTS
            if (
                inline
                and position
                and rows[position - 1][1]["property"]
                == prop.removesuffix("PolicyDocument") + "PolicyName"
            ):
                label = policy_tables.literal(rows[position - 1][1]["value"])
            if trust:
                suffix, kind = "trust", "信頼ポリシー"
            elif inline:
                suffix, kind = (
                    "inline-" + policy_tables.artifact_id(label),
                    "インラインポリシー",
                )
            elif prop in policy_tables.POLICY_FORMATS:
                suffix = "policy-" + policy_tables.artifact_id(Path(target).stem)
                kind = (
                    "ポリシー設定"
                    if policy_tables.POLICY_FORMATS[prop] == "settings"
                    else "ポリシー"
                )
            else:
                suffix, kind = f"json-{rid}", "JSON"
            result[rid] = (
                f"{resource['anchor']}-{suffix}",
                f"{kind}：{label}",
                Path(label).stem,
                policy_tables.order_policy_statements(documents[rid], prop),
                link_label,
            )
    return result


def project_view_documents(
    values, scope, root, *, resolver=None, warnings=None, strict=False
):
    """Resolve structured settings in memory and retain Model link ownership checks."""
    resolver = resolver or _imports_model_projection.reference_resolver(
        values, scope, root
    )
    path = (
        root
        / DESIGNS_DIRECTORY
        / scope.environment
        / scope.target
        / (scope.service + ".md")
    )
    sources = {}
    projected_by_path = {}
    documents = {}
    diagnostics = []
    for rid, row in entries(values, "desired.row."):
        field = "document" if "document" in row else "value"
        link = JSON_LINK.fullmatch(row["value"])
        if field == "document" and link is None:
            raise ValueError(f"JSON document requires an artifact link: {rid}")
        if link and field != "document":
            raise ValueError(f"authoritative JSON document missing: {path.name}: {rid}")
        key = f"desired.row.{rid}.{field}"
        if link:
            artifact = (path.parent / link[1]).resolve()
            _imports_model_sources.safe(root, path.parent / link[1])
            if artifact.parent != path.with_suffix("").resolve():
                raise ValueError(f"JSON artifact must belong to owning service: {rid}")
            raw = policy_json(row[field])
            if sources.setdefault(artifact, raw) != raw:
                raise ValueError(
                    f"conflicting authoritative JSON documents: {artifact.name}"
                )
        else:
            if not strict:
                continue
            raw, structured = parse_reference_field(key, row[field])
            if not structured:
                continue
        try:
            projected = _imports_model_projection.generated_document(
                raw,
                root,
                property_name=row["property"],
                scope=scope,
                resolver=resolver,
                logical_id=values.get(
                    f"desired.resource.{rid.rpartition('-')[0]}.logicalId"
                ),
                model_key=key,
                context=_imports_model_projection.reference_context_for(
                    values, rid, row, raw, "", root
                ),
                warnings=warnings,
            )
        except ReferenceDiagnosticError as error:
            diagnostics.extend(error.diagnostics)
            continue
        if link:
            if not isinstance(projected, dict):
                raise ValueError(f"JSON document must be an object: {rid}")
            if projected_by_path.setdefault(artifact, projected) != projected:
                raise ValueError(
                    f"conflicting projected JSON documents: {artifact.name}"
                )
            documents[rid] = projected
    require_reference_diagnostics(diagnostics)
    if warnings is not None:
        warnings.extend(d for d in diagnostics if d not in warnings)
    return documents


@task_read_scope(root=_task_root)
@change_reads()
def generate_files(path, values, root, *, warnings=None):
    """Return the generated Markdown, including its projected JSON settings."""
    return {
        path: stack_markdown(path, values, root, validate_delivery=False)
        if entries(values, "desired.stack.")
        else _generate_markdown(
            path,
            values,
            root,
            reference_values=values,
            warnings=warnings,
        )
    }


def render_model(snapshot, context):
    root = snapshot.scope.root
    if context is not None and context.root != root:
        raise ValueError("render context belongs to another Model root")
    context = context if context is not None else input_recorder(root)
    document = (
        root
        / DESIGNS_DIRECTORY
        / snapshot.scope.environment
        / snapshot.scope.target
        / (snapshot.scope.service + ".md")
    )
    with recording_inputs(context):
        return generate_files(document, snapshot.values, root)


def owned_artifacts(path, values):
    """Return existing legacy files that the service may retire during publication."""
    root = path.parents[4]
    result = set()
    for _, row in entries(values, "desired.row."):
        link = JSON_LINK.fullmatch(row.get("value", ""))
        if "document" not in row or link is None:
            continue
        artifact = path.parent / link[1]
        if artifact.parent != path.with_suffix(""):
            continue
        _imports_model_sources.safe(root, artifact)
        if input_is_file(artifact):
            result.add(artifact)
    return result


def view_plan(path, values, root, managed):
    """Plan one display transaction without taking ownership of unrelated JSON."""
    inputs = {
        p: input_bytes(p)
        for p in input_select(
            path.with_suffix(""), "*.json", recursive=True, kinds=("file", "symlink")
        )
    }
    inputs[path] = input_bytes(path) if input_is_file(path) else None
    for file in inputs.keys() | managed:
        _dependency_model_sources.safe(root, file)
        if file != path and file.parent != path.with_suffix("").resolve():
            raise ValueError("JSON artifact must belong to owning service")
    files = generate_files(path, values, root)
    return {
        **changed_files(files),
        **{file: None for file in managed - files.keys() if file.is_file()},
    }, inputs


_COMPAT_ROOT = Path(__file__).resolve().parents[3]


def display_rows(
    kind: str,
    rows: list[list[str]],
    root: Path = _COMPAT_ROOT,
    *,
    mode=RESOURCE_MODE_CREATE,
    _counts=None,
    consumed: list[str] | None = None,
    references=None,
):
    return _dependency_model_display.display_rows(
        kind,
        rows,
        root,
        mode=mode,
        _counts=_counts,
        consumed=consumed,
        references=references,
    )
