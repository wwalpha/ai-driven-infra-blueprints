"""Shared display relationships and identified children in resource tables."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aws_mapping_display as _imports_aws_mapping_display
import model.core as _imports_model_core
import model.display as _imports_model_display
import model.files as _imports_model_files
import model.identity as _imports_model_identity
import model.sources as _imports_model_sources
import model.validation as _imports_model_validation
import utils.aws_mappings as _imports_utils_aws_mappings
from model.core import ReferenceResolutionError, positive_integer
from utils.aws_catalogs import catalogs_for
from utils.input_cache import input_scope as input_scope
from utils.input_cache import input_text
from utils.reference_contracts import LINKED_LIST_PROPERTIES as LINKED_LIST_PROPERTIES
from utils.reference_contracts import SUBNET_LIST_PROPERTIES as SUBNET_LIST_PROPERTIES

import design.array_display as _dependency_array_display
import design.catalog as _imports_design_catalog
import design.services.codebuild
import design.services.codepipeline
import design.services.ec2.security_groups as _dependency_security_group_tables
import design.services.glue
from design.catalog import design_material_files
from design.common import catalog_property_order as catalog_property_order
from design.common import resource_heading_lines as resource_heading_lines
from design.common import subnet_list_items as subnet_list_items
from design.layout_schema import ALIGNMENT as ALIGNMENT
from design.layout_schema import ANCHOR as ANCHOR
from design.layout_schema import CHILD as CHILD
from design.layout_schema import CHILD_NAME as CHILD_NAME
from design.layout_schema import COMPACT_SOURCE
from design.layout_schema import DETAILS_HEADING as DETAILS_HEADING
from design.layout_schema import GROUPED as GROUPED
from design.layout_schema import GROUPED_RESOURCE_TYPES as GROUPED_RESOURCE_TYPES
from design.layout_schema import HEADER as HEADER
from design.layout_schema import (
    IMPLICIT_GROUPED_PROPERTIES as IMPLICIT_GROUPED_PROPERTIES,
)
from design.layout_schema import LAYOUT_PATH as LAYOUT_PATH
from design.layout_schema import LAYOUTS as LAYOUTS
from design.layout_schema import RESOURCE as RESOURCE
from design.layout_schema import RESOURCE_ID as RESOURCE_ID
from design.layout_schema import (
    RESOURCE_PROPERTY_PREFIXES as RESOURCE_PROPERTY_PREFIXES,
)
from design.layout_schema import STACK_DESIGN as STACK_DESIGN
from design.layout_schema import STACK_HEADER as STACK_HEADER
from design.layout_schema import SUBNET_LIST_SOURCE as SUBNET_LIST_SOURCE
from design.layout_schema import resource_anchor as resource_anchor
from design.services.cloudtrail import formal_rows as cloudtrail_formal_rows
from design.services.config import config_role_arn as config_role_arn
from design.services.config import is_import_role_arn as is_import_role_arn
from design.services.definitions.cloudtrail import (
    CLOUDTRAIL_DATA_RESOURCE as CLOUDTRAIL_DATA_RESOURCE,
)
from design.services.definitions.cloudtrail import (
    CLOUDTRAIL_FORMAL_DATA_RESOURCE as CLOUDTRAIL_FORMAL_DATA_RESOURCE,
)
from design.services.definitions.cloudtrail import (
    CLOUDTRAIL_RESOURCE_TYPES as CLOUDTRAIL_RESOURCE_TYPES,
)
from design.services.definitions.codebuild import (
    CODEBUILD_FORMAL_VARIABLE,
    CODEBUILD_VARIABLE,
)
from design.services.definitions.codebuild import (
    CODEBUILD_VPC_PROPERTIES as CODEBUILD_VPC_PROPERTIES,
)
from design.services.definitions.ec2 import SECURITY_GROUP_TYPES as SECURITY_GROUP_TYPES
from design.services.definitions.guardduty import GUARDDUTY_FEATURE as GUARDDUTY_FEATURE
from design.services.definitions.guardduty import (
    GUARDDUTY_FORMAL_FEATURE as GUARDDUTY_FORMAL_FEATURE,
)
from design.services.definitions.lambda_permission import (
    LAMBDA_PERMISSION as LAMBDA_PERMISSION,
)
from design.services.definitions.lambda_permission import (
    PERMISSION_METADATA as PERMISSION_METADATA,
)
from design.services.definitions.registry import HIDDEN_PROPERTIES as HIDDEN_PROPERTIES
from design.services.definitions.registry import IMPORT_PENDING_PROPERTIES
from design.services.definitions.registry import (
    REQUIRED_NAME_TAG_TYPES as REQUIRED_NAME_TAG_TYPES,
)
from design.services.definitions.registry import (
    RESOURCE_REFERENCE_PROPERTIES as RESOURCE_REFERENCE_PROPERTIES,
)
from design.services.definitions.secrets_manager import (
    ROTATION_SCHEDULE as ROTATION_SCHEDULE,
)
from design.services.ec2.display import ec2_formal_rows, name_tag_display_name
from design.services.guardduty import formal_rows as guardduty_formal_rows
from design.services.kms import alias_display_name
from design.services.lambda_permission import permission_rows as permission_rows


def is_service_role_reference(prop: str, value: str) -> bool:
    reference = RESOURCE_REFERENCE_PROPERTIES.get(prop)
    return bool(
        reference
        and reference[0] == "IAM.Role"
        and re.fullmatch(r"(`?)AWSService[A-Za-z0-9_+=,.@-]{1,54}\1", value)
    )


def is_import_pending_reference(prop: str, value: str) -> bool:
    return prop in IMPORT_PENDING_PROPERTIES and value == "Pending"


def resource_logical_ids(lines: list[str]) -> dict[str, str]:
    """Read hidden IDs before anchors without changing displayed headings."""
    identities = {}
    pending = ""
    anchored = ""
    for line in resource_heading_lines(lines):
        if not line.strip():
            continue
        if marker := RESOURCE_ID.fullmatch(line):
            if pending:
                raise ValueError("duplicate resource logical ID metadata")
            pending, anchored = marker.group(1), ""
        elif pending and ANCHOR.fullmatch(line) and not anchored:
            anchored = ANCHOR.fullmatch(line).group(1)
        elif pending and (RESOURCE.fullmatch(line)) and anchored:
            if anchored in identities or pending in identities.values():
                raise ValueError("duplicate resource logical ID metadata")
            identities[anchored] = pending
            pending, anchored = "", ""
        elif pending or line.startswith("<!-- resource-logical-id:"):
            raise ValueError(
                "resource logical ID metadata must precede its anchor and heading"
            )
    if pending:
        raise ValueError("resource logical ID metadata lacks its anchor and heading")
    return identities


def resource_name_fields(resource_type: str) -> list[str]:
    """Candidate resource names, excluding names of referenced resources."""
    if resource_type == "SSM.Association":
        return ["AssociationName"]  # Name identifies the referenced SSM document.
    kind = resource_type.split(".")[1]
    names = [
        kind + "Input.Name",
        kind + "Config.Name",
        "Name",
        "name",
        kind + "Name",
        kind + "Identifier",
        kind + "." + kind + "Name",
    ]
    if kind.endswith("Name"):
        names.append(kind)
    if resource_type == "EC2.SecurityGroup":
        names.append("GroupName")
    if resource_type == "IAM.ManagedPolicy":
        names.append("PolicyName")
    return names


def resource_mode(resource: dict[str, str]) -> str:
    mode = resource.get("resourceMode", "CREATE")
    if mode not in {"CREATE", "IMPORT"}:
        raise ValueError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    return mode


def design_model_values(path: Path, root: Path) -> dict[str, str] | None:
    """Read the authoritative service model, including indexed parts, if present."""
    properties = _imports_model_core.properties
    read_model = _imports_model_files.read_model
    model_exists = _imports_model_sources.model_exists
    try:
        relative = path.relative_to(root / "docs/designs")
    except ValueError:
        return None
    source = (root / "model" / relative).with_suffix(".properties")
    return properties(read_model(source)) if model_exists(source) else None


def resource_modes(
    lines: list[str], values: dict[str, str] | None = None
) -> dict[str, str]:
    """Read modes only from current authoritative Model values."""
    entries = _imports_model_core.entries
    display_anchor = _imports_model_identity.display_anchor
    return {
        display_anchor(resource): resource_mode(resource)
        for _, resource in entries(values or {}, "desired.resource.")
        if "resourceMode" in resource
    }


def configured_name_fields(root: Path, resource_type: str) -> list[str]:
    """Keep configured name candidates separate from generated identifiers."""
    outputs = catalogs_for(root).outputs(resource_type)
    return [
        field
        for field in resource_name_fields(resource_type)
        if resource_type + "." + field not in outputs
    ]


def resource_has_name_property(
    root: Path, resource_type: str, mode: str = "CREATE"
) -> bool:
    """Check the catalog, rather than treating an omitted optional name as nameless."""
    if (
        resource_type
        in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}
        | REQUIRED_NAME_TAG_TYPES
    ):
        return mode != "IMPORT"  # Only CREATE requires a Name tag.
    return bool(
        set(configured_name_fields(root, resource_type))
        & catalogs_for(root).selected(resource_type)
    )


def resource_display_name(
    resource_type: str,
    rows: list[list[str]],
    selected_label: str | None = None,
    mode: str = "CREATE",
    *,
    root: Path = LAYOUT_PATH.parents[2],
) -> str | None:
    """Find a selected root name; never invent an AWS name from an internal ID."""
    if resource_type == "KMS.Key":
        alias = alias_display_name(rows, selected_label)
        if alias is not None:
            return alias
    fields = {
        row[1].removeprefix(resource_type + "."): row[2].strip('`"') for row in rows
    }
    if resource_type in REQUIRED_NAME_TAG_TYPES:
        return name_tag_display_name(resource_type, rows, fields, mode)
    names = configured_name_fields(root, resource_type)
    for field in names:
        if field in fields and not fields[field].startswith("["):
            return fields[field]
    for tags in ("Tags", "HostedZoneTags"):
        for index, row in enumerate(rows[:-1]):
            if (
                row[1].removeprefix(resource_type + ".") == tags + "[].Key"
                and row[2].strip('`"') == "Name"
            ):
                value = rows[index + 1]
                if value[1].removeprefix(resource_type + ".") == tags + "[].Value":
                    return value[2].strip('`"')
        if tags in fields:
            try:
                values = json.loads(fields[tags])
            except ValueError:
                continue  # The schema validator reports malformed JSON.
            if isinstance(values, dict) and isinstance(values.get("Name"), str):
                return values["Name"]
    return None


def stack_deployment_policy(path: Path) -> int:
    lines = [line for line in input_text(path, encoding="utf-8").splitlines() if line]
    if len(lines) < 2 or lines[0] != "# CloudFormation stack 詳細設計":
        raise ValueError("invalid CloudFormation stack design header")
    match = re.fullmatch(r"<!-- max-concurrent-stacks: (.+) -->", lines[1])
    if not match:
        raise ValueError("invalid CloudFormation deployment policy")
    return positive_integer(match.group(1), "MaxConcurrentStacks")


def resource_display_selection(
    root: Path,
    resource_type: str,
    rows: list[list[str]],
    label: str | None,
    mode: str,
    count: int,
) -> tuple[str | None, str | None]:
    """Select a configured name, confirmed label or existing nameless-type display."""
    DesignSchemaCatalog = _imports_design_catalog.DesignSchemaCatalog
    selected_properties = _imports_design_catalog.selected_properties
    if GROUPED.get(resource_type, {}).get("display") == "rule-table":
        return label, None
    naming_errors = _imports_model_validation.naming_errors
    if errors := naming_errors(root, resource_type, rows, mode):
        raise ValueError("; ".join(errors))
    names = set(configured_name_fields(root, resource_type))
    catalog_names = names & selected_properties(root, resource_type)
    selected = [
        (row[1].removeprefix(resource_type + "."), row[2])
        for row in rows
        if row[1].removeprefix(resource_type + ".") in names
    ]
    catalog = DesignSchemaCatalog(root)
    for field, raw in selected:
        value = raw.strip('`"')
        if (
            not value.strip()
            or value.strip().lower()
            in {
                "unset",
                "pending",
                "pending_deploy",
                "tbd",
                "n/a",
                "none",
                "not-used",
                "not used",
                "unused",
                "未使用",
                "未確定",
            }
            or value.startswith("[")
            or "{{" in value
        ):
            raise ValueError(
                f"resource display name must be confirmed and non-empty: {resource_type}.{field}"
            )
        if field in catalog_names:
            errors = catalog.literal_errors(resource_type, field, value)
            if errors:
                raise ValueError(f"{resource_type}.{field}: " + "; ".join(errors))
    configured = resource_display_name(resource_type, rows, label, mode, root=root)
    if configured is not None:
        return configured, configured
    has_name = resource_has_name_property(root, resource_type, mode)
    if has_name:
        if mode != "IMPORT" or resource_type in {"IAM.Role", "CodeBuild.Project"}:
            raise ValueError(
                f"required Name is not selected; display label substitution is not allowed: {resource_type}"
            )
        missing = set()
        for field in catalog_names:
            parent, _, leaf = field.rpartition(".")
            schema = (
                catalog.property_schema(resource_type, parent)
                if parent
                else catalog.schema(resource_type)
            )
            schema = catalog._resolve(catalog.schema(resource_type), schema)
            if leaf in schema.get("required", []):
                missing.add(field)
        if missing:
            raise ValueError(
                f"required provider schema property missing: {resource_type}."
                + ", ".join(sorted(missing))
            )
    if label is not None and label != resource_type:
        if not label.strip() or label in {"UNSET", "PENDING_DEPLOY"}:
            raise ValueError(
                f"confirmed resource display label is missing: {resource_type}"
            )
        return label, None
    if not has_name and count == 1 and resource_type not in GROUPED:
        return resource_type, None
    if has_name:
        raise ValueError(
            f"confirmed resource display label is missing: {resource_type}"
        )
    return None, None


def stack_design(path: Path) -> list[dict[str, str]]:
    """Read a target's stack detailed design."""
    lines = [
        line
        for line in input_text(path, encoding="utf-8").splitlines()
        if line
        and not line.startswith(("<!-- templateBucket:", "<!-- templateKeyPrefix:"))
    ]
    stack_deployment_policy(path)
    if lines[2:5] != [
        "## Stack一覧",
        STACK_HEADER,
        "| ---: | ---: | --- | --- | --- | --- |",
    ]:
        raise ValueError("invalid CloudFormation stack design header")
    result = []
    end = next(
        (index for index in range(5, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    for line in lines[5:end]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if (
            not line.startswith("|")
            or not line.endswith("|")
            or len(cells) != 6
            or not all(cells)
        ):
            raise ValueError(f"invalid CloudFormation stack design row: {line}")
        if cells[0] != str(len(result) + 1):
            raise ValueError(
                f"CloudFormation stack design No. must be sequential: {line}"
            )
        positive_integer(cells[1], "DeployOrder")
        result.append(
            dict(
                zip(
                    ("deployOrder", "name", "template", "parameters", "comment"),
                    cells[1:],
                    strict=False,
                )
            )
        )
    if not result:
        raise ValueError("CloudFormation stack design table must not be empty")
    stack_delivery(path)
    return result


def stack_delivery(path: Path) -> dict[str, str]:
    """Read delivery authority from the current Stack Model."""
    lines = input_text(path, encoding="utf-8").splitlines()
    settings = set()
    for line in lines:
        if line.startswith(("<!-- templateBucket:", "<!-- templateKeyPrefix:")):
            match = re.fullmatch(
                r"<!-- (templateBucket|templateKeyPrefix): (.+) -->", line
            )
            if not match:
                raise ValueError("invalid S3 delivery setting comment")
            if match.group(1) in settings:
                raise ValueError("duplicate S3 delivery setting")
            settings.add(match.group(1))
    values = design_model_values(path, path.parents[4])
    if values is None:
        if settings or "## S3配置" in lines:
            raise ValueError(
                "S3 delivery settings require an authoritative Stack Model"
            )
        return {}
    return {
        key: value
        for key, value in values.items()
        if key.startswith("desired.artifact.")
        or key
        in {"desired.deployment.templateBucket", "desired.deployment.templateKeyPrefix"}
    }


def layout_errors(root: Path) -> list[str]:
    """Require an explicit display decision for every catalog resource."""
    definition_root = _imports_utils_aws_mappings.definition_root
    root = definition_root(root)
    errors = []
    try:
        layouts = json.loads(
            input_text(
                root / "framework" / "rules" / "resource-layout.json", encoding="utf-8"
            )
        )
    except (OSError, ValueError) as error:
        return [f"cannot read resource layout decisions: {error}"]
    if not isinstance(layouts, dict):
        return ["resource layout decisions must be an object"]
    catalog = {
        path.stem.replace("_", ".", 1): {
            line.partition("=")[0]
            for line in input_text(path, encoding="utf-8").splitlines()
        }
        for path in design_material_files(root)
    }
    if set(layouts) != set(catalog):
        errors.append(
            f"resource layout coverage mismatch: unclassified={sorted(set(catalog) - set(layouts))}, "
            f"stale={sorted(set(layouts) - set(catalog))}"
        )
    for name, rule in layouts.items():
        if rule == "independent":
            continue
        required = {"parent", "parentProperty", "maxCount", "identityProperty"}
        if not isinstance(rule, dict) or set(rule) not in (
            required,
            required | {"display"},
        ):
            errors.append(f"invalid resource layout decision: {name}")
            continue
        if "display" in rule and (
            rule["display"] != "rule-table"
            or name not in {"EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}
            or rule
            != {
                "parent": "EC2.SecurityGroup",
                "parentProperty": "GroupId",
                "maxCount": None,
                "identityProperty": "Id",
                "display": "rule-table",
            }
        ):
            errors.append(f"invalid Security Group rule table layout: {name}")
        parent = rule["parent"]
        if (
            not isinstance(parent, str)
            or parent not in catalog
            or layouts.get(parent) != "independent"
        ):
            errors.append(
                f"grouped parent must be an independent catalog resource: {name}: {parent}"
            )
        if f"{name}.{rule['parentProperty']}" not in catalog.get(name, set()):
            errors.append(f"grouped parent property is absent from catalog: {name}")
        identity = rule["identityProperty"]
        if identity is not None and f"{name}.{identity}" not in catalog.get(
            name, set()
        ):
            errors.append(f"grouped identity property is absent from catalog: {name}")
        if rule["maxCount"] != 1 and not (rule["maxCount"] is None and identity):
            errors.append(
                f"multiple grouped children require an identity property: {name}"
            )
    return errors


def catalog_order_errors(
    resource_type: str, rows: list[list[str]], root: Path | None = None
) -> list[str]:
    """Compare visible rows with the selection-list order, within each resource."""
    root = root or Path(__file__).resolve().parents[3]
    cached_order = catalog_property_order(root, resource_type)
    if cached_order is None:
        return [f"display order catalog is missing: {resource_type}"]
    order = dict(cached_order)
    design.services.codebuild.adjust_display_order(resource_type, order)
    previous = -1
    seen: set[str] = set()
    previous_property = ""
    for row in rows:
        prop = (
            row[1]
            if row[1].startswith(resource_type + ".")
            else resource_type + "." + row[1]
        )
        if prop not in order:
            continue  # Design-only fields and other grouped resources are separate.
        rank = order[prop]
        if rank < previous:
            array = prop.split("[]", 1)[0] + "[]" if "[]" in prop else ""
            if (
                not array
                or prop not in seen
                or not previous_property.startswith(array + ".")
            ):
                return [
                    f"resource rows must follow catalog file order: {resource_type}: {prop}"
                ]
            # A repeated field starts the next array element, not a global sort.
            seen = {item for item in seen if not item.startswith(array + ".")}
        seen.add(prop)
        previous = rank
        previous_property = prop
    return []


def linked_list_property(
    display: str, resource_type: str, root: Path | None = None
) -> tuple[str, str] | None:
    """Resolve only the final display index; leave enclosing object arrays intact."""
    match = re.fullmatch(r"(.+)\[([^\]]*)\]", display)
    if match:
        base = formal_property(match.group(1), resource_type, root)
        for prop in LINKED_LIST_PROPERTIES:
            if base == prop.removesuffix("[]"):
                return prop, match.group(2)
    return None


@input_scope
def expanded_display_rows(
    lines: list[str],
    root: Path | None = None,
    *,
    modes=None,
    reference_tables=(),
    _verified_reference=False,
) -> list[str]:
    """Restore compact resource rows to their catalog properties."""
    ROOT = _imports_aws_mapping_display.ROOT
    compact_group = _imports_aws_mapping_display.compact_group
    display_name = _imports_aws_mapping_display.display_name
    rules = _imports_aws_mapping_display.rules
    show = _imports_aws_mapping_display.show
    structural = _imports_aws_mapping_display.structural
    root = root or ROOT
    if any(
        "<!-- reference-rows:" in line or "<!-- reference-value:" in line
        for line in lines
    ):
        raise ValueError("obsolete Model reference metadata; regenerate Markdown")
    lines = resource_heading_lines(lines)
    modes = resource_modes(lines) if modes is None else modes
    anchor = ""
    mode = "CREATE"
    result = []
    index = 0
    resource_type = ""
    reference_errors = []
    while index < len(lines):
        if (
            lines[index] != HEADER
            or index + 1 >= len(lines)
            or lines[index + 1] != ALIGNMENT
        ):
            if match := ANCHOR.fullmatch(lines[index]):
                anchor = match.group(1)
            if heading := RESOURCE.fullmatch(lines[index]):
                resource_type = heading.group(1)
                mode = modes.get(anchor, "CREATE")
            elif lines[index].startswith("#"):
                resource_type = ""
            result.append(lines[index])
            index += 1
            continue
        start = index
        index += 2
        rows = []
        row_numbers = []
        codebuild_names = set()
        linked_list_counts: dict[str, int] = {}
        guardduty_names = set()
        cloudtrail_count = 0
        packed_pipeline = False
        changed = False
        normalized = False
        kind = ""
        # Generic array markers are removed before service-specific compact rows.
        stop = index
        source_rows = []
        while stop < len(lines) and lines[stop].startswith("|"):
            source_rows.append(
                [cell.strip() for cell in lines[stop].strip("|").split("|")]
            )
            stop += 1
        if any(len(row) != 4 for row in source_rows):
            raise ValueError("resource table row must have four cells")
        table = next(
            (table for table in reference_tables if table.anchor == anchor), None
        )
        if table is not None:
            if tuple(lines[start:stop]) != table.expected:
                raise ValueError(
                    "Markdown table differs from Model expected display: " + anchor
                )
            # Parse the actual, matched display before exposing Model semantic rows.
            expanded_display_rows(
                [
                    f'<a id="{anchor}"></a>',
                    f"### {resource_type}: reference",
                    *lines[start:stop],
                ],
                root,
                modes=modes,
                _verified_reference=True,
            )
            result.extend(table.semantic)
            index = stop
            continue
        restored = _dependency_array_display.restored_rows(
            source_rows, resource_type, root
        )
        restored = design.services.glue.restored_glue_argument_rows(
            restored, resource_type
        )
        if restored != source_rows:
            if [row[0] for row in source_rows] != [
                str(number) for number in range(1, len(source_rows) + 1)
            ]:
                raise ValueError("Array table numbering error")
            lines = [
                *lines[:index],
                *(
                    "| " + " | ".join([str(number), *row[1:]]) + " |"
                    for number, row in enumerate(restored, 1)
                ),
                *lines[stop:],
            ]
            changed = True
            kind = "Array"
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError("resource table row must have four cells")
            if "<!-- compact-source:" in cells[3]:
                marker = COMPACT_SOURCE.match(cells[3])
                if mode != "IMPORT" or marker is None:
                    raise ValueError(
                        "packed compact source requires IMPORT and valid metadata"
                    )
                source = json.loads(marker[1])
                if (
                    not isinstance(source, list)
                    or len(source) != 2
                    or not isinstance(source[0], list)
                    or type(source[1]) is not int
                    or source[1] < 1
                    or not source[0]
                    or any(
                        not isinstance(row, list)
                        or len(row) != 3
                        or any(not isinstance(cell, str) for cell in row)
                        for row in source[0]
                    )
                ):
                    raise ValueError("invalid packed compact source")
                original = [[cells[0], *row] for row in source[0]]
                display_rows = _imports_model_display.display_rows
                counts = {"data": cloudtrail_count}
                expected = display_rows(
                    resource_type, original, root, mode=mode, _counts=counts
                )
                cloudtrail_count = counts["data"]
                actual = [
                    [cell.strip() for cell in line.strip("|").split("|")]
                    for line in lines[index : index + source[1]]
                ]
                if len(expected) != source[1] or [row[1:] for row in actual] != [
                    row[1:] for row in expected
                ]:
                    raise ValueError("packed compact display differs from source")
                row_numbers.extend(row[0] for row in actual)
                rows.extend(original)
                packed_pipeline |= resource_type == "CodePipeline.Pipeline"
                index += source[1]
                changed, kind = True, "packed compact"
                continue
            row_numbers.append(cells[0])
            display_property = cells[1]
            if resource_type == "Lambda.Function" and display_property.startswith(
                "Lambda.Permission."
            ):
                raise ValueError(
                    "Lambda Permission must use Permission.* display properties"
                )
            if resource_type == "Lambda.Function" and display_property in {
                "Permission.Id",
                "Permission.FunctionName",
            }:
                raise ValueError(
                    "Lambda Permission Id and FunctionName must not be displayed"
                )
            prop = formal_property(cells[1], resource_type, root)
            if "<!-- subnet-list-source:" in cells[3] and not linked_list_property(
                display_property, resource_type, root
            ):
                raise ValueError(
                    "Subnet list source marker requires an indexed Subnet row"
                )
            if prop == "Config.ConfigurationRecorder.RoleARN" and display_property != (
                "RoleARN"
                if config_role_arn(prop, cells[2])
                else display_name(prop, resource_type, root)
            ):
                raise ValueError(
                    "ConfigurationRecorder RoleARN must use Mapping display name"
                )
            if prop in RESOURCE_REFERENCE_PROPERTIES:
                if (
                    mode != "IMPORT"
                    and not (
                        is_service_role_reference(prop, cells[2])
                        or is_import_pending_reference(prop, cells[2])
                    )
                    and not re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2])
                ):
                    raise ReferenceResolutionError(
                        f"{prop} must be a resource link",
                        property=prop,
                        reference=cells[2],
                    )
            owner = ".".join(prop.split(".")[:2])
            if (
                prop in rules(root, owner)
                and (owner == resource_type or owner in GROUPED)
                and owner not in SECURITY_GROUP_TYPES
                and not compact_group(prop)
                and prop not in LINKED_LIST_PROPERTIES
            ):
                configured = display_name(prop, resource_type, root)
                canonical = prop.removeprefix(resource_type + ".")
                if (
                    configured != canonical
                    and display_property in {prop, canonical}
                    and not config_role_arn(prop, cells[2])
                ):
                    raise ValueError(
                        f"formal property must use its Markdown display alias: {prop}"
                    )
            if (
                prop in rules(root, owner)
                and not show(prop, root)
                and not structural(prop)
            ):
                raise ValueError(f"property must not be displayed: {prop}")
            if prop in HIDDEN_PROPERTIES and not show(prop, root):
                raise ValueError(f"property must not be displayed: {prop}")
            if prop != cells[1]:
                normalized = True
                cells[1] = prop
            if prop.startswith(CODEBUILD_FORMAL_VARIABLE):
                raise ValueError(
                    "CodeBuild environment variables must use Variables.<Name> display rows"
                )
            if prop in LINKED_LIST_PROPERTIES:
                raise ValueError(
                    f"{prop} must use indexed one-resource-per-row display"
                )
            if prop in {
                GUARDDUTY_FORMAL_FEATURE + "Name",
                GUARDDUTY_FORMAL_FEATURE + "Status",
            }:
                raise ValueError(
                    "GuardDuty Features Name/Status must use Features.<Name> display rows"
                )
            if resource_type == "CloudTrail.Trail" and prop.startswith(
                CLOUDTRAIL_FORMAL_DATA_RESOURCE
            ):
                raise ValueError(
                    "CloudTrail DataResources Type/Values must use one target per display row"
                )
            if prop.startswith(CODEBUILD_VARIABLE):
                changed = True
                kind = "CodeBuild environment variable"
                try:
                    rows.extend(
                        design.services.codebuild.codebuild_formal_rows(
                            cells, codebuild_names, mode=mode, typed=_verified_reference
                        )
                    )
                except ReferenceResolutionError:
                    raise
                except design.services.codebuild.PlaintextReferenceError as error:
                    reference_errors.append(
                        f"Resource={resource_type}#{anchor}: {error}"
                    )
                except ValueError as error:
                    raise ValueError(
                        f"Resource={resource_type}#{anchor}: {error}"
                    ) from error
            elif item := linked_list_property(display_property, resource_type, root):
                list_prop, first_index = item
                expected = linked_list_counts.get(list_prop, 0) + 1
                if (
                    not re.fullmatch(r"[1-9][0-9]*", first_index)
                    or int(first_index) != expected
                ):
                    raise ValueError(
                        "Subnet/Security Group display indexes must start at 1 and be sequential per property"
                    )
                marker = SUBNET_LIST_SOURCE.match(cells[3])
                if "<!-- subnet-list-source:" in cells[3] and not marker:
                    raise ValueError("invalid Subnet list source marker")
                source = json.loads(marker.group(1)) if marker else None
                items = (
                    subnet_list_items(list_prop, source)
                    if source is not None
                    else [cells[2]]
                )
                if (
                    source is not None
                    and list_prop in CODEBUILD_VPC_PROPERTIES
                    and mode != "IMPORT"
                    and not _verified_reference
                ):
                    raise ReferenceResolutionError(
                        "CodeBuild VpcConfig value must be a resource link",
                        property=prop,
                        reference=cells[2],
                    )
                comment = cells[3][marker.end() :] if marker else cells[3]
                child = CHILD.match(comment)
                label = CHILD_NAME.match(comment[child.end() :]) if child else None
                # Rotation identity metadata occurs only on the first displayed Subnet.
                continuation_comment = (
                    comment[child.end() + label.end() :]
                    if label and list_prop.startswith(ROTATION_SCHEDULE + ".")
                    else comment
                )
                if (
                    source is None
                    and mode != "IMPORT"
                    and not _verified_reference
                    and not re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2])
                ):
                    raise ReferenceResolutionError(
                        "Subnet/Security Group value must be a resource link",
                        property=prop,
                        reference=cells[2],
                    )
                for offset, value in enumerate(items):
                    row = cells
                    if offset:
                        row = (
                            [
                                cell.strip()
                                for cell in lines[index + offset].strip("|").split("|")
                            ]
                            if index + offset < len(lines)
                            else []
                        )
                    if (
                        len(row) != 4
                        or linked_list_property(row[1], resource_type, root)
                        != (list_prop, str(expected + offset))
                        or row[2] != value
                        or (offset and row[3] != continuation_comment)
                    ):
                        raise ValueError(
                            "Subnet list display differs from its saved source value or comment"
                        )
                    if offset:
                        row_numbers.append(row[0])
                linked_list_counts[list_prop] = expected + len(items) - 1
                changed = True
                kind = "Subnet/Security Group list"
                cells[1], cells[2], cells[3] = (
                    list_prop,
                    source if source is not None else cells[2],
                    comment,
                )
                rows.append(cells)
                index += len(items) - 1
            elif prop.startswith(GUARDDUTY_FEATURE):
                changed = True
                kind = "GuardDuty Feature"
                rows.extend(guardduty_formal_rows(cells, guardduty_names))
            elif resource_type == "CloudTrail.Trail" and display_property.startswith(
                "EventSelectors.DataResources["
            ):
                rows.extend(
                    cloudtrail_formal_rows(
                        cells, display_property, cloudtrail_count, mode
                    )
                )
                cloudtrail_count += 1
                changed = True
                kind = "CloudTrail DataResources"
            else:
                rows.append(cells)
            index += 1
        if resource_type == "Lambda.Function" and any(
            row[1].startswith(LAMBDA_PERMISSION + ".")
            or "<!-- lambda-permission:" in row[3]
            for row in rows
        ):
            rows = permission_rows(rows)
            changed = True
            kind = "Lambda Permission"
        if resource_type == "CodePipeline.Pipeline" and not packed_pipeline:
            rows = design.services.codepipeline.pipeline_display_rows(rows)
            changed = True
            kind = "CodePipeline"
        if resource_type in REQUIRED_NAME_TAG_TYPES:
            rows = ec2_formal_rows(rows, resource_type)
            changed = True
            kind = resource_type
        for row in rows:
            owner = ".".join(row[1].split(".")[:2])
            if (
                row[1] in rules(root, owner)
                and not show(row[1], root)
                and not structural(row[1])
            ):
                raise ValueError(f"property must not be displayed: {row[1]}")
        if changed:
            if row_numbers != [
                str(number) for number in range(1, len(row_numbers) + 1)
            ]:
                raise ValueError(f"{kind} table numbering error")
            result.extend((HEADER, ALIGNMENT))
            result.extend(
                "| " + " | ".join([str(number), *cells[1:]]) + " |"
                for number, cells in enumerate(rows, 1)
            )
        elif normalized:
            result.extend((HEADER, ALIGNMENT))
            result.extend("| " + " | ".join(cells) + " |" for cells in rows)
        else:
            result.extend(lines[start:index])
    if reference_errors:
        raise design.services.codebuild.PlaintextReferenceError(
            "\n".join(reference_errors), lines=result
        )
    return result


def expanded_design(
    lines: list[str],
    *,
    normalized: bool = False,
    logical_ids: dict[tuple[str, str], str] | None = None,
    bound_anchors: dict[tuple[str, str], str] | None = None,
    root: Path | None = None,
    modes=None,
    reference_tables=(),
) -> tuple[list[str], dict[str, dict]]:
    """Expand identified children for model/link resolution; keep S3's flat model.

    Child anchors and logical IDs live in the first row's comment. Visible tables
    stay grouped; this in-memory expansion never rewrites the source Markdown.
    """
    identities = resource_logical_ids(lines) if logical_ids is None else logical_ids
    lines = [line for line in lines if not RESOURCE_ID.fullmatch(line)]
    if not normalized:
        lines = _dependency_security_group_tables.security_group_table_lines(
            lines, root
        )
    lines = expanded_display_rows(
        lines, root, modes=modes, reference_tables=reference_tables
    )
    result: list[str] = []
    children: dict[str, dict] = {}
    parent_type = parent_id = parent_anchor = pending_anchor = ""
    child_names: set[tuple[str, str]] = set()
    logical_ids: set[str] = set()
    grouped_tables: set[str] = set()
    anchors = ANCHOR.findall("\n".join(lines))
    if len(anchors) != len(set(anchors)):
        raise ReferenceResolutionError("duplicate resource anchor")
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("- Design service ID: "):
            _ = line.split("`")[1]
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        if heading := RESOURCE.fullmatch(line):
            parent_type, parent_id = heading.groups()
            parent_id = identities.get(pending_anchor, parent_id)
            parent_anchor = pending_anchor
            pending_anchor = ""
            if parent_id in logical_ids:
                raise ValueError(f"duplicate resource logical ID: {parent_id}")
            logical_ids.add(parent_id)
        elif line.startswith("#"):
            parent_type = ""
        if line != HEADER:
            if "<!-- logical-id:" in line:
                raise ValueError(
                    "child identity marker must be in a resource table row"
                )
            result.append(line)
            index += 1
            continue
        if index + 1 >= len(lines) or lines[index + 1] != ALIGNMENT:
            raise ValueError("invalid resource table alignment")
        if parent_type in GROUPED_RESOURCE_TYPES:
            if parent_anchor in grouped_tables:
                raise ValueError("grouped parent must have exactly one detail table")
            grouped_tables.add(parent_anchor)
        result.extend((HEADER, ALIGNMENT))
        index += 2
        parent_rows = []
        table_children: list[dict] = []
        counts: dict[str, int] = {}
        single_properties: set[str] = set()
        active_child = None
        grouped_started = False
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError("resource table row must have four cells")
            prop = cells[1]
            resource_type = ".".join(prop.split(".")[:2])
            rule = GROUPED.get(resource_type)
            marker = CHILD.match(cells[3])
            if rule and resource_type != parent_type:
                if parent_type != rule["parent"]:
                    raise ValueError(
                        f"grouped resource has wrong parent: {resource_type}: {parent_type}"
                    )
                grouped_started = True
                if (
                    prop == f"{resource_type}.{rule['parentProperty']}"
                    and resource_type not in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}
                ):
                    raise ValueError(
                        f"{prop} must be omitted from its enclosing {parent_type} table"
                    )
                identity = rule["identityProperty"]
                if identity:
                    hidden_identity = f"{resource_type}.{identity}" in HIDDEN_PROPERTIES
                    if (
                        prop == f"{resource_type}.{identity}"
                        or hidden_identity
                        and marker
                    ):
                        if not marker:
                            raise ValueError(
                                f"grouped identity row requires anchor and logical ID: {prop}"
                            )
                        anchor, logical_id = marker.groups()
                        name = cells[2].strip("`")
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            label = CHILD_NAME.match(cells[3][marker.end() :])
                            if not label or label.group(1).strip() in {
                                "",
                                "UNSET",
                                "PENDING_DEPLOY",
                            }:
                                raise ValueError(
                                    f"{resource_type}: {logical_id}: confirmed display name required on {prop}"
                                )
                            name = label.group(1)
                        if anchor in children:
                            raise ReferenceResolutionError("duplicate resource anchor")
                        expected = (bound_anchors or {}).get(
                            (resource_type, logical_id)
                        )
                        if (
                            expected is not None and anchor != expected
                        ) or logical_id in logical_ids:
                            raise ValueError(
                                f"invalid or duplicate grouped logical ID/anchor: {logical_id}"
                            )
                        logical_ids.add(logical_id)
                        pending_rule = (
                            rule.get("display") == "rule-table"
                            and name == "PENDING_DEPLOY"
                        )
                        if not pending_rule and (resource_type, name) in child_names:
                            raise ValueError(
                                f"duplicate grouped identity value: {resource_type}: {name}"
                            )
                        if not pending_rule:
                            child_names.add((resource_type, name))
                        active_child = {
                            "resourceType": resource_type,
                            "logicalId": logical_id,
                            "anchor": anchor,
                            "parentLogicalId": parent_id,
                            "parentAnchor": parent_anchor,
                            "parentProperty": f"{resource_type}.{rule['parentProperty']}",
                            "rows": [],
                        }
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            active_child["displayName"] = name
                        children[anchor] = active_child
                        table_children.append(active_child)
                        counts[resource_type] = counts.get(resource_type, 0) + 1
                    elif (
                        marker
                        or not active_child
                        or active_child["resourceType"] != resource_type
                    ):
                        raise ValueError(
                            "grouped child rows require anchor and logical ID"
                            if hidden_identity
                            else f"grouped child rows must start with {resource_type}.{identity}"
                        )
                    if marker:
                        cells[3] = cells[3][marker.end() :]
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            cells[3] = cells[3][label.end() :]
                    if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                        if (
                            any(row[1] == prop for row in active_child["rows"])
                            and "[]" not in prop
                        ):
                            raise ValueError(
                                f"{resource_type}: {active_child['logicalId']}: duplicate property: {prop}"
                            )
                        if prop == active_child["parentProperty"]:
                            reference = re.fullmatch(
                                r"\[[^\]]+\]\(#([^)]*)\)", cells[2]
                            )
                            if not reference or reference.group(1) != parent_anchor:
                                raise ReferenceResolutionError(
                                    f"{resource_type}: {active_child['logicalId']}: {prop} must reference enclosing {parent_type}: {parent_id}"
                                )
                    active_child["rows"].append(cells)
                else:
                    if marker or "<!-- logical-id:" in cells[3]:
                        raise ValueError(
                            "unidentified grouped child must not have an identity marker"
                        )
                    if prop in single_properties:
                        raise ValueError(
                            f"duplicate property in single grouped child: {prop}"
                        )
                    single_properties.add(prop)
                    counts[resource_type] = 1
                    parent_rows.append(cells)
            else:
                if marker or "<!-- logical-id:" in cells[3]:
                    raise ValueError(
                        "child identity marker is only allowed on a grouped identity row"
                    )
                if grouped_started:
                    raise ValueError(f"grouped rows must follow {parent_type} rows")
                parent_rows.append(cells)
                active_child = None
            index += 1
        for resource_type, count in counts.items():
            maximum = GROUPED[resource_type]["maxCount"]
            if maximum is not None and count > maximum:
                raise ValueError(f"too many grouped children: {resource_type}")
        for number, cells in enumerate(parent_rows, 1):
            result.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
        for child in table_children:
            if child["resourceType"] in {
                ROTATION_SCHEDULE,
                LAMBDA_PERMISSION,
            } and not any(row[1] == child["parentProperty"] for row in child["rows"]):
                raise ValueError(
                    f"{child['resourceType']}: {child['logicalId']}: required property missing: {child['parentProperty']}"
                )
            result.extend(
                (
                    "",
                    f'<a id="{child["anchor"]}"></a>',
                    f"### {child['resourceType']}: {child['logicalId']}",
                    "",
                    HEADER,
                    ALIGNMENT,
                )
            )
            for number, cells in enumerate(child["rows"], 1):
                result.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
    return result, children


@input_scope
def formal_property(display: str, resource_type: str, root: Path | None = None) -> str:
    """Restore the resource type omitted from a detail table's Property column."""
    ROOT = _imports_aws_mapping_display.ROOT
    formal_name = _imports_aws_mapping_display.formal_name
    if resource_type and (formal := formal_name(display, resource_type, root or ROOT)):
        return formal
    if resource_type == "Lambda.Function" and display.startswith("Permission."):
        return "Lambda." + display
    if display.startswith(RESOURCE_PROPERTY_PREFIXES):
        return display
    return resource_type + "." + display if resource_type else display
