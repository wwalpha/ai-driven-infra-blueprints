"""Render detailed designs from authoritative service properties."""

from __future__ import annotations

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
import design.services.ec2.security_groups as _ec2_security_groups
from design.catalog import DesignSchemaCatalog as DesignSchemaCatalog
from design.layout_schema import GROUPED, SUBNET_LIST_SOURCE
from design.layout_schema import resource_anchor as resource_anchor
from design.services.definitions.lambda_permission import LAMBDA_PERMISSION
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
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources
from model.change_scope import change_reads
from model.core import (
    ARTIFACT_FIELDS,
    LINK,
    ReferenceResolutionError,
    deployment_settings,
    entries,
    stack_model,
)
from model.core import (
    properties as properties,
)
from model.format import JSON_LINK


def stack_markdown(
    path, values, root, *, definitions_root=None, validate_delivery=True
):
    reference_display = _imports_model_projection.reference_display
    limit, stacks = stack_model(values)
    settings, artifacts = deployment_settings(values)
    displayed = reference_display(values, path, root)
    display_artifacts = dict(entries(displayed, "desired.artifact."))
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
    if settings and validate_delivery:
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
                *[f"<!-- {field}: {value} -->" for field, value in settings.items()],
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
    kind = resource["resourceType"]
    label = values.get(f"display.resource.{identity}.label")
    if GROUPED.get(kind, {}).get("display") == "rule-table":
        return label or resource["logicalId"], None
    mode = _dependency_design_layout.resource_mode(resource)
    if mode == "IMPORT" and kind not in {"IAM.Role", "CodeBuild.Project"}:
        # Resolve a saved self-reference from its observation, never from its link label.
        local = {""} | {
            value + ".md"
            for key, value in values.items()
            if key.startswith("desired.service.") and key.endswith(".serviceId")
        }
        rows = [list(row) for row in rows]
        for row in rows:
            field = row[1].removeprefix(kind + ".")
            link = LINK.fullmatch(row[2])
            if (
                field in _dependency_design_layout.resource_name_fields(kind)
                and link
                and link[2] in local
                and link[3] == resource["anchor"]
            ):
                matches = [
                    rid
                    for rid, item in entries(values, "desired.row.")
                    if rid.startswith(identity + "-")
                    and item.get("property") == kind + "." + field
                    and (source_link := LINK.fullmatch(item.get("value", "")))
                    and source_link.groups()[1:] == link.groups()[1:]
                ]
                if len(matches) == 1:
                    row[2] = values.get(f"observed.row.{matches[0]}.value", row[2])
    count = (
        sum(
            item["resourceType"] == kind
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
        fallback=resource["logicalId"] if projection else None,
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
    kind = resource["resourceType"]
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
    kind = _state_resource_details_122.resource["resourceType"]
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
    if not name or name in {"UNSET", "PENDING_DEPLOY"}:
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
    grouped: dict[str, list] = {}
    for item in details:
        identity, resource, name, rows = item
        if resource["resourceType"] not in GROUPED:
            continue
        kind = resource["resourceType"]
        rule = GROUPED[kind]
        for field in ("parentReference", "parentProperty"):
            if not resource.get(field):
                raise InputValidationError(
                    f"{kind}: {resource['logicalId']}: required metadata missing: desired.resource.{identity}.{field} ({kind}.{rule['parentProperty']})"
                )
        link = LINK.fullmatch(resource["parentReference"])
        parse_reference = _imports_model_identity.parse_reference
        local = link and (
            not link[2]
            or scope is not None
            and parse_reference(link[0], scope)[:3]
            == (scope.environment, scope.target, scope.service)
        )
        parent = by_anchor.get(link[3]) if local else None
        if resource["parentProperty"] != kind + "." + rule["parentProperty"]:
            raise InputValidationError("invalid grouped parentProperty: " + identity)
        if not parent or parent[1]["resourceType"] != rule["parent"]:
            raise ReferenceResolutionError(
                f"{kind}: {resource['logicalId']}: invalid grouped parent: parentReference / parentProperty ({kind}.{rule['parentProperty']})"
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
                    f"{kind}: {resource['logicalId']}: {resource['parentProperty']} requires exactly one formal row matching parentReference"
                )
            row_link = LINK.fullmatch(parent_rows[0].get("value", ""))
            same = (
                parse_reference(row_link[0], scope) == parse_reference(link[0], scope)
                if scope is not None and row_link
                else bool(
                    row_link
                    and row_link[3] == link[3]
                    and not row_link[2]
                    and not link[2]
                )
            )
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
                    f"{kind}: {resource['logicalId']}: required first property: {kind}.Id"
                )
        grouped.setdefault(parent[0], []).append(item)
        maximum = rule["maxCount"]
        if (
            maximum is not None
            and sum(child[1]["resourceType"] == kind for child in grouped[parent[0]])
            > maximum
        ):
            raise InputValidationError(
                f"{kind}: {resource['logicalId']}: too many grouped children for {parent[1]['logicalId']}: {resource['parentProperty']}"
            )
    return grouped


def resource_table_lines(
    resource, name, rows, children, root, *, references=None, formal=False, indexed=True
):
    sources = references or {}
    source = sources.get(resource.get("logicalId"))
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
    expected = Counter(
        row[0] for row in _dependency_aws_mapping_display.selected_rows(rows, root)
    )
    for _, _, _, child_rows in children:
        expected.update(
            row[0]
            for row in _dependency_aws_mapping_display.selected_rows(child_rows, root)
        )
    if any(count != 1 for count in expected.values()):
        raise ValueError("duplicate selected Model row IDs")
    consumed = []
    output = []
    kind = resource["resourceType"]
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
        for _, child, child_name, child_rows in children:
            child_rows = _dependency_aws_mapping_display.selected_rows(child_rows, root)
            if not child_rows:
                continue
            if child["resourceType"] == ROTATION_SCHEDULE:
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
            child_source = sources.get(child["logicalId"])
            child_display = (
                [list(row) for row in child_rows]
                if formal
                else display_rows(
                    kind
                    if child["resourceType"] == ROTATION_SCHEDULE
                    else child["resourceType"],
                    child_rows,
                    root,
                    mode=_dependency_design_layout.resource_mode(child),
                    consumed=consumed,
                    references=child_source.reference_ids if child_source else None,
                )
            )
            if formal:
                consumed.extend(row[0] for row in child_display)
            if not formal and child["resourceType"] != ROTATION_SCHEDULE:
                for row in child_display:
                    row[1] = child["resourceType"] + "." + row[1]
            if not formal and child["resourceType"] == LAMBDA_PERMISSION:
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
            prefix = f'<a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --> '
            if (
                child["resourceType"] == ROTATION_SCHEDULE
                or formal
                and child["resourceType"] == LAMBDA_PERMISSION
            ):
                prefix += child_name + "："
            comment = child_display[0][3]
            source = SUBNET_LIST_SOURCE.match(comment)
            child_display[0][3] = (
                (source.group(0) if source else "")
                + prefix
                + (comment[source.end() :] if source else comment)
            )
            display += child_display
        if not formal and indexed:
            display = _dependency_array_display.indexed_rows(display, kind, root)
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
) -> str:
    """Generate a View; Model quality belongs to Change or Full Validation."""
    return render_validated_model(path, values, root, definitions_root=definitions_root)


@task_read_scope(root=_task_root)
def render_validated_model(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    definitions_root: Path | None = None,
) -> str:
    """Render structure and references without Model quality validation."""
    return generate_markdown(path, values, definitions_root or root)


@task_read_scope(root=_task_root)
@input_scope
def generate_markdown(
    path: Path,
    values: dict[str, str],
    root: Path,
    *,
    reference_tables=None,
    reference_values=None,
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
    )


@input_scope
def _generate_markdown(
    path, values, root, *, reference_tables=None, reference_values=None, warnings=None
):
    """Draw only values checked by the enclosing public generation entry."""
    reference_display = _imports_model_projection.reference_display
    scope_for = _imports_model_sources.scope_for
    references = _dependency_model_display.reference_rows(values)
    presentation = _reference_presentation.Presentation(
        values, path, path.parents[4], reference_values=reference_values
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
        resource["resourceType"]
        for _, resource in entries(
            values if reference_values is None else reference_values,
            "desired.resource.",
        )
    )
    for identity, resource in entries(values, "desired.resource."):
        kind = resource["resourceType"]
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
            / path.relative_to(path.parents[4] / "docs/designs")
        ).with_suffix(".properties")
    )
    grouped = grouped_resources(values, details, by_anchor, scope=scope)
    return render_markdown(
        path,
        values,
        root,
        owned,
        details,
        grouped,
        model_policy_views(values, presentation=presentation),
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
    policy_views=None,
    *,
    references=None,
    reference_tables=None,
    presentation=None,
):
    service = path.stem
    children = {item[0] for items in grouped.values() for item in items}
    independent = [item for item in details if item[0] not in children]
    output = [
        values["display.service.title"],
        "",
        f"- Design service ID: `{service}`",
        "- Owned catalog resource types: " + ", ".join(f"`{kind}`" for kind in owned),
    ]
    output += ["", "## リソース一覧"]
    for kind in dict.fromkeys(item[1]["resourceType"] for item in independent):
        items = [item for item in independent if item[1]["resourceType"] == kind]
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
        kind = resource["resourceType"]
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
            f"<!-- resource-logical-id: {resource['logicalId']} -->",
            f'<a id="{resource["anchor"]}"></a>',
            "",
            heading,
            "",
        ]
        children = grouped.get(identity, [])
        table = resource_table_lines(
            resource, name, rows, children, root, references=references
        )
        baseline = table
        if presentation is not None and any(
            ref.link for ref in presentation.references.values()
        ):
            marked = resource_table_lines(
                resource,
                name,
                presentation.rows(rows),
                [
                    (rid, child, child_name, presentation.rows(child_rows))
                    for rid, child, child_name, child_rows in children
                ],
                root,
                references=references,
            )
            table = presentation.lines(baseline, marked)
        output += table
        sources = (
            tuple(
                references[item["logicalId"]]
                for item in [resource, *(child[1] for child in children)]
            )
            if references
            else ()
        )
        if reference_tables is not None:
            semantic = resource_table_lines(
                resource, name, rows, children, root, references=references, formal=True
            )
            reference_tables.append(
                _dependency_model_display.ReferenceTable(
                    resource["anchor"],
                    sources,
                    tuple(table),
                    tuple(semantic),
                    tuple(
                        resource_table_lines(
                            resource,
                            name,
                            rows,
                            children,
                            root,
                            references=references,
                            indexed=False,
                        )
                    ),
                )
            )
        output += (policy_views or {}).get(identity, [])
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


def model_policy_views(values, *, presentation=None):
    END = _imports_policy_tables.END
    IAM_END = _imports_policy_tables.IAM_END
    IAM_START = _imports_policy_tables.IAM_START
    INLINE_POLICY_DOCUMENTS = _imports_policy_tables.INLINE_POLICY_DOCUMENTS
    JSON_LINK = _imports_policy_tables.JSON_LINK
    POLICY_FORMATS = _imports_policy_tables.POLICY_FORMATS
    START = _imports_policy_tables.START
    Policy = _imports_policy_tables.Policy
    artifact_id = _imports_policy_tables.artifact_id
    policy_document_lines = _imports_policy_tables.policy_document_lines

    resource_row_index = _imports_model_files.resource_row_index

    result = {}
    rows_by_resource = resource_row_index(values)
    for identity, resource in entries(values, "desired.resource."):
        policies = []
        rows = rows_by_resource[identity]
        for position, (row_id, row) in enumerate(rows):
            prop = row["property"]
            link = JSON_LINK.fullmatch(
                presentation.values.get(f"desired.row.{row_id}.value", "")
                if presentation is not None
                else row.get("value", "")
            )
            if prop not in POLICY_FORMATS or not link or "document" not in row:
                continue
            label, target = link.groups()
            trust = prop == "IAM.Role.AssumeRolePolicyDocument"
            inline = prop in INLINE_POLICY_DOCUMENTS
            if (
                inline
                and position
                and rows[position - 1][1]["property"]
                == prop.removesuffix("PolicyDocument") + "PolicyName"
            ):
                label = _dependency_policy_tables.literal(
                    rows[position - 1][1]["value"]
                )
            suffix = (
                "trust"
                if trust
                else "inline-" + artifact_id(label)
                if inline
                else "policy-" + artifact_id(Path(target).stem)
            )
            kind = (
                "信頼ポリシー"
                if trust
                else "インラインポリシー"
                if inline
                else "ポリシー設定"
                if POLICY_FORMATS[prop] == "settings"
                else "ポリシー"
            )
            policy = Policy(
                label, target, resource["anchor"] + "-" + suffix, kind, prop
            )
            document = json.loads(row["document"])
            lines = policy_document_lines(document, policy)
            if presentation is not None:
                marked = presentation.document(row_id, "document", document)
                lines = presentation.lines(lines, policy_document_lines(marked, policy))
            policies.extend(["", *lines])
        if policies:
            start, end = (
                (IAM_START, IAM_END)
                if resource["resourceType"] == "IAM.Role"
                else (START, END)
            )
            result[identity] = ["", start, *policies, "", end]
    return result


@task_read_scope(root=_task_root)
@change_reads()
def generate_files(path, values, root, *, warnings=None):
    """Project AWS JSON in memory without changing authoritative Model references."""
    safe = _imports_model_sources.safe
    scope_for = _imports_model_sources.scope_for
    scope = scope_for(
        (root / "model" / path.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
    )
    resolver = _imports_model_projection.reference_resolver(values, scope, root)
    artifacts = {}
    for identity, row in entries(values, "desired.row."):
        if "document" not in row:
            continue
        match = JSON_LINK.fullmatch(row.get("value", ""))
        if not match:
            raise ValueError("JSON document requires an artifact link: " + identity)
        safe(root, path.parent / match[1])
        artifact = (path.parent / match[1]).resolve()
        safe(root, artifact)
        if artifact.parent != path.with_suffix("").resolve():
            raise ValueError("JSON artifact must belong to owning service")
        raw_document = policy_json(row["document"])
        document = _imports_model_projection.generated_document(
            raw_document,
            root,
            property_name=row["property"],
            model_key=f"desired.row.{identity}.document",
            resolver=resolver,
            scope=scope,
            logical_id=values.get(
                f"desired.resource.{identity.rpartition('-')[0]}.logicalId"
            ),
            context=_imports_model_projection.reference_context_for(
                values, identity, row, raw_document, "", root
            ),
            warnings=warnings,
        )
        if not isinstance(document, dict):
            raise ValueError("JSON document must be an object: " + identity)
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        if artifact in artifacts and artifacts[artifact] != content:
            raise ValueError("conflicting authoritative JSON documents")
        artifacts[artifact] = content
    artifacts[path] = (
        stack_markdown(path, values, root, validate_delivery=False)
        if entries(values, "desired.stack.")
        else _generate_markdown(
            path, values, root, reference_values=values, warnings=warnings
        )
    )
    return artifacts


def render_model(snapshot, context):
    root = snapshot.scope.root
    if context is not None and context.root != root:
        raise ValueError("render context belongs to another Model root")
    context = context if context is not None else input_recorder(root)
    document = (
        root
        / "docs/designs"
        / snapshot.scope.environment
        / snapshot.scope.target
        / (snapshot.scope.service + ".md")
    )
    with recording_inputs(context):
        return generate_files(document, snapshot.values, root)


def owned_artifacts(path, values):
    return {
        (path.parent / link[1]).resolve()
        for _, row in entries(values, "desired.row.")
        if "document" in row
        and (link := JSON_LINK.fullmatch(row.get("value", "")))
        and (path.parent / link[1]).resolve().parent == path.with_suffix("").resolve()
    }


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
    if any(
        file in inputs
        and file != path
        and file not in managed
        and inputs[file] != text.encode("utf-8")
        for file, text in files.items()
    ):
        raise ValueError("unowned JSON output collision")
    inputs.update(
        {
            file: input_bytes(file) if input_is_file(file) else None
            for file in files
            if file not in inputs
        }
    )
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
    mode="CREATE",
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
