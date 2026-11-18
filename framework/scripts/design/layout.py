"""Shared display relationships and identified children in resource tables."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aws_mapping_display as _imports_aws_mapping_display
import model.core as _imports_model_core
import model.display as _imports_model_display
import model.identity as _imports_model_identity
import model.sources as _imports_model_sources
import utils.aws_mappings as _imports_utils_aws_mappings
from contracts.model import (
    MODEL_PENDING_DEPLOY,
    MODEL_UNSET,
    RESOURCE_LOGICAL_ID_KEY,
    RESOURCE_MODE_CREATE,
    RESOURCE_MODE_IMPORT,
    RESOURCE_TYPE_KEY,
)
from contracts.repository import DESIGNS_DIRECTORY
from model.core import ReferenceResolutionError, literal, positive_integer
from model.reference_nodes import nodes
from services.cloudtrail.design import (
    CLOUDTRAIL_DATA_RESOURCE as CLOUDTRAIL_DATA_RESOURCE,
)
from services.cloudtrail.design import (
    CLOUDTRAIL_FORMAL_DATA_RESOURCE as CLOUDTRAIL_FORMAL_DATA_RESOURCE,
)
from services.cloudtrail.design import (
    CLOUDTRAIL_RESOURCE_TYPES as CLOUDTRAIL_RESOURCE_TYPES,
)
from services.codebuild.design import (
    CODEBUILD_VPC_PROPERTIES as CODEBUILD_VPC_PROPERTIES,
)
from services.contracts import DisplayReferenceError, DisplayRowError, RestoredRowGroup
from services.ec2.design import SECURITY_GROUP_TYPES as SECURITY_GROUP_TYPES
from services.guardduty.design import GUARDDUTY_FEATURE as GUARDDUTY_FEATURE
from services.guardduty.design import (
    GUARDDUTY_FORMAL_FEATURE as GUARDDUTY_FORMAL_FEATURE,
)
from services.lambda_.design import (
    LAMBDA_PERMISSION as LAMBDA_PERMISSION,
)
from services.lambda_.design import (
    PERMISSION_METADATA as PERMISSION_METADATA,
)
from services.reference_engine import REFERENCES
from services.registry import REGISTRY
from services.secrets_manager.design import (
    ROTATION_SCHEDULE as ROTATION_SCHEDULE,
)
from utils.aws_catalogs import catalogs_for
from utils.input_cache import input_scope as input_scope
from utils.input_cache import input_text
from validation.diagnostics import InputValidationError

import design.array_display as _imports_array_display
import design.catalog as _imports_design_catalog
import model as _model_api
from design.catalog import design_material_files
from design.common import catalog_property_order as catalog_property_order
from design.common import resource_heading_lines as resource_heading_lines
from design.common import subnet_list_items as subnet_list_items
from design.layout_schema import ALIGNMENT as ALIGNMENT
from design.layout_schema import ANCHOR as ANCHOR
from design.layout_schema import CHILD as CHILD
from design.layout_schema import CHILD_NAME as CHILD_NAME
from design.layout_schema import COMPACT_SOURCE, SavedIdentityError
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
from design.layout_schema import resource_anchor as resource_anchor

HIDDEN_PROPERTIES = REGISTRY.design_tables.get("HIDDEN_PROPERTIES", frozenset())
IMPORT_PENDING_PROPERTIES = REGISTRY.design_tables.get(
    "IMPORT_PENDING_PROPERTIES", frozenset()
)
REQUIRED_NAME_TAG_TYPES = REGISTRY.design_tables.get(
    "REQUIRED_NAME_TAG_TYPES", frozenset()
)
RESOURCE_REFERENCE_PROPERTIES = REGISTRY.design_tables.get(
    "RESOURCE_REFERENCE_PROPERTIES", {}
)


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
                raise SavedIdentityError("duplicate resource logical ID metadata")
            pending, anchored = marker.group(1), ""
        elif pending and ANCHOR.fullmatch(line) and not anchored:
            anchored = ANCHOR.fullmatch(line).group(1)
        elif pending and (RESOURCE.fullmatch(line)) and anchored:
            if anchored in identities or pending in identities.values():
                raise SavedIdentityError("duplicate resource logical ID metadata")
            identities[anchored] = pending
            pending, anchored = "", ""
        elif pending or line.startswith("<!-- resource-logical-id:"):
            raise SavedIdentityError(
                "resource logical ID metadata must precede its anchor and heading"
            )
    if pending:
        raise SavedIdentityError(
            "resource logical ID metadata lacks its anchor and heading"
        )
    return identities


def resource_name_fields(resource_type: str) -> list[str]:
    """Candidate resource names, excluding names of referenced resources."""
    design = (REGISTRY.design(resource_type) or {}) if resource_type in REGISTRY else {}
    fields = design.get("RESOURCE_NAME_FIELDS", {})
    if resource_type in fields:
        return list(fields[resource_type])
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
    return names + list(
        design.get("ADDITIONAL_RESOURCE_NAME_FIELDS", {}).get(resource_type, ())
    )


def resource_mode(resource: dict[str, str]) -> str:
    mode = resource.get("resourceMode", RESOURCE_MODE_CREATE)
    if mode not in {RESOURCE_MODE_CREATE, RESOURCE_MODE_IMPORT}:
        raise ValueError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    return mode


def design_model_values(path: Path, root: Path) -> dict[str, str] | None:
    """Read the authoritative service model, including indexed parts, if present."""
    load_model = _imports_model_sources.load_model
    model_exists = _imports_model_sources.model_exists
    try:
        relative = path.relative_to(root / DESIGNS_DIRECTORY)
    except ValueError:
        return None
    source = (root / "model" / relative).with_suffix(".properties")
    return load_model(source).values if model_exists(source) else None


def resource_modes(
    lines: list[str], values: dict[str, str] | None = None
) -> dict[str, str]:
    """Read modes only from current authoritative Model values."""
    display_anchor = _imports_model_identity.display_anchor
    return {
        display_anchor(resource): resource_mode(resource)
        for _, resource in _model_api.ModelView(values or {}).resources()
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
    root: Path, resource_type: str, mode: str = RESOURCE_MODE_CREATE
) -> bool:
    """Check the catalog, rather than treating an omitted optional name as nameless."""
    design = (REGISTRY.design(resource_type) or {}) if resource_type in REGISTRY else {}
    if (
        resource_type in design.get("REQUIRED_CREATE_NAME_TYPES", ())
        or resource_type in REQUIRED_NAME_TAG_TYPES
    ):
        return mode != RESOURCE_MODE_IMPORT  # Only CREATE requires a Name tag.
    return bool(
        set(configured_name_fields(root, resource_type))
        & catalogs_for(root).selected(resource_type)
    )


def resource_display_name(
    resource_type: str,
    rows: list[list[str]],
    selected_label: str | None = None,
    mode: str = RESOURCE_MODE_CREATE,
    *,
    root: Path = LAYOUT_PATH.parents[2],
) -> str | None:
    """Find a selected root name; never invent an AWS name from an internal ID."""
    extension = REGISTRY.presentation(resource_type)
    if extension.selected_name is not None:
        alias = extension.selected_name(rows, selected_label)
        if alias is not None:
            return alias
    fields = {
        row[1].removeprefix(resource_type + "."): row[2].strip('`"') for row in rows
    }
    if extension.name_tag is not None:
        return extension.name_tag(resource_type, rows, fields, mode)
    names = configured_name_fields(root, resource_type)
    for field in names:
        if field in fields and not fields[field].startswith("["):
            return fields[field]
    for tags in ("Tags", "HostedZoneTags"):
        paths = [
            row[1].removeprefix(resource_type + ".")
            for row in rows
            if row[1].removeprefix(resource_type + ".").startswith(tags + "[].")
        ]
        if paths != [tags + "[].Key", tags + "[].Value"] * (len(paths) // 2):
            raise ValueError(
                f"{resource_type} tags require corresponding Key/Value rows"
            )
        keys = [
            index
            for index, row in enumerate(rows)
            if row[1].removeprefix(resource_type + ".") == tags + "[].Key"
            and row[2].strip('`"') == "Name"
        ]
        if len(keys) > 1:
            raise ValueError(f"{resource_type} requires exactly one {tags}[].Key=Name")
        if keys:
            index = keys[0] + 1
            if (
                index >= len(rows)
                or rows[index][1].removeprefix(resource_type + ".") != tags + "[].Value"
            ):
                raise ValueError(
                    f"{resource_type} Name tag requires the corresponding {tags}[].Value"
                )
            return rows[index][2].strip('`"')
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


def confirmed_display_name(raw):
    value = raw.strip('`"')
    return (
        bool(value.strip())
        and value.strip().lower()
        not in {
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
        and not value.startswith("[")
        and "{{" not in value
    )


def resource_display_selection(
    root: Path,
    resource_type: str,
    rows: list[list[str]],
    label: str | None,
    mode: str,
    count: int,
    *,
    fallback: str | None = None,
) -> tuple[str | None, str | None]:
    """Select a configured name, confirmed label or existing nameless-type display."""
    DesignSchemaCatalog = _imports_design_catalog.DesignSchemaCatalog
    selected_properties = _imports_design_catalog.selected_properties
    if GROUPED.get(resource_type, {}).get("display") == "rule-table":
        return label, None
    names = set(configured_name_fields(root, resource_type))
    catalog_names = names & selected_properties(root, resource_type)
    selected = [
        (row[1].removeprefix(resource_type + "."), row[2])
        for row in rows
        if row[1].removeprefix(resource_type + ".") in names
    ]
    if fallback is None:
        for field, raw in selected:
            if not confirmed_display_name(raw):
                raise InputValidationError(
                    f"resource display name must be confirmed and non-empty: {resource_type}.{field}"
                )
    configured = resource_display_name(resource_type, rows, label, mode, root=root)
    if configured is not None and (
        fallback is None or confirmed_display_name(configured)
    ):
        return configured, configured
    has_name = resource_has_name_property(root, resource_type, mode)
    if has_name and fallback is None:
        catalog = DesignSchemaCatalog(root)
        design = (
            (REGISTRY.design(resource_type) or {}) if resource_type in REGISTRY else {}
        )
        if mode != RESOURCE_MODE_IMPORT or resource_type in design.get(
            "REQUIRED_IMPORT_NAME_TYPES", ()
        ):
            raise InputValidationError(
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
            raise InputValidationError(
                f"required provider schema property missing: {resource_type}."
                + ", ".join(sorted(missing))
            )
    if (
        label is not None
        and label != resource_type
        and (fallback is None or confirmed_display_name(label))
    ):
        if not label.strip() or label in {MODEL_UNSET, MODEL_PENDING_DEPLOY}:
            raise InputValidationError(
                f"confirmed resource display label is missing: {resource_type}"
            )
        return label, None
    if not has_name and count == 1 and resource_type not in GROUPED:
        return resource_type, None
    if fallback is not None:
        return fallback, None
    if has_name:
        raise InputValidationError(
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
        if _model_api.key_kind(key) == ("desired", "artifact")
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
        if "display" in rule:
            design = (REGISTRY.design(name) or {}) if name in REGISTRY else {}
            expected = design.get("RULE_TABLE_LAYOUTS", {}).get(name)
            if rule != expected:
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
    resource_type: str,
    rows: list[list[str]],
    root: Path | None = None,
    *,
    verified_display: bool = False,
) -> list[str]:
    """Check order not already proven by equality with the numbered projection."""
    root = root or Path(__file__).resolve().parents[3]
    cached_order = catalog_property_order(root, resource_type)
    if cached_order is None:
        return [f"display order catalog is missing: {resource_type}"]
    order = dict(cached_order)
    extension = REGISTRY.presentation(resource_type)
    if extension.validate_adjusted_order and extension.adjust_order is not None:
        extension.adjust_order(resource_type, order)
    if not verified_display and extension.validate_order is not None:
        errors = extension.validate_order(resource_type, rows, order)
        if errors:
            return errors
    array_order = {}
    if verified_display:
        for prop, rank in order.items():
            if "[]" in prop:
                array_order.setdefault(prop.split("[]", 1)[0], rank)
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
        rank = array_order.get(prop.split("[]", 1)[0], order[prop])
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
        for prop in (base, base + "[]"):
            if REFERENCES.linked_list_kind(prop) is not None:
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
        "<!-- reference-rows:" in line
        or "<!-- reference-value:" in line
        or "<!-- subnet-list-source:" in line
        for line in lines
    ):
        raise ValueError("obsolete Model reference metadata; regenerate Markdown")
    lines = resource_heading_lines(lines)
    modes = resource_modes(lines) if modes is None else modes
    anchor = ""
    mode = RESOURCE_MODE_CREATE
    result = []
    index = 0
    resource_type = ""
    reference_errors = []
    reference_error_class = DisplayReferenceError
    reference_positions = []
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
                mode = modes.get(anchor, RESOURCE_MODE_CREATE)
            elif lines[index].startswith("#"):
                resource_type = ""
            result.append(lines[index])
            index += 1
            continue
        start = index
        index += 2
        rows = []
        row_numbers = []
        extension = REGISTRY.presentation(resource_type)
        names = set()
        linked_list_counts: dict[str, int] = {}
        counts = {"data": 0}
        packed_table = False
        changed = False
        normalized = False
        kind = ""
        # Model projections supply exact rows before service-specific parsing.
        stop = index
        source_rows = []
        while stop < len(lines) and lines[stop].startswith("|"):
            source_rows.append(
                [cell.strip() for cell in lines[stop].strip("|").split("|")]
            )
            stop += 1
        if any(len(row) != 4 for row in source_rows):
            raise ValueError("resource table row must have four cells")
        if resource_type != "Glue.Job" and any(
            "<!-- glue-arguments-source:" in row[3] for row in source_rows
        ):
            raise ValueError("Glue argument source requires a Glue.Job resource")
        table = next(
            (table for table in reference_tables if table.anchor == anchor), None
        )
        if table is not None:
            if tuple(lines[start:stop]) != table.expected:
                raise ValueError(
                    "Markdown table differs from Model expected display: " + anchor
                )
            expanded_display_rows(
                [
                    f'<a id="{anchor}"></a>',
                    f"### {resource_type}: reference",
                    *table.baseline,
                ],
                root,
                modes=modes,
                _verified_reference=True,
            )
            result.extend(table.semantic)
            index = stop
            continue
        if _verified_reference and any(
            any(nodes(_imports_model_core.literal(row[2]))) for row in source_rows
        ):
            # Exact Model equality already proved these symbolic rows before restoration.
            result.extend(lines[start:stop])
            index = stop
            continue
        restored = (
            extension.restore_raw(source_rows, resource_type, mode=mode)
            if extension.restore_raw is not None
            else source_rows
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
            kind = extension.restore_label or resource_type
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError("resource table row must have four cells")
            if "<!-- compact-source:" in cells[3]:
                marker = COMPACT_SOURCE.match(
                    cells[3]
                    + (
                        " "
                        if extension.indexed_packed and cells[3].endswith("-->")
                        else ""
                    )
                )
                if mode != RESOURCE_MODE_IMPORT or marker is None:
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
                original = [
                    [str(number), *row] for number, row in enumerate(source[0], 1)
                ]
                display_rows = _imports_model_display.display_rows
                expected = display_rows(
                    resource_type, original, root, mode=mode, _counts=counts
                )
                if extension.indexed_packed:
                    if not _verified_reference:
                        expected = _imports_array_display.indexed_rows(
                            expected, resource_type, root
                        )
                    expected[0][3] = expected[0][3].strip()
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
                packed_table |= extension.indexed_packed
                index += source[1]
                changed, kind = True, "packed compact"
                continue
            row_numbers.append(cells[0])
            display_property = cells[1]
            if extension.validate_display_property is not None:
                extension.validate_display_property(display_property)
            prop = formal_property(display_property, resource_type, root)
            alias = (
                extension.literal_link_label(prop, cells[2])
                if extension.literal_link_label
                else None
            )
            if prop in extension.import_link_required and display_property != (
                alias or display_name(prop, resource_type, root)
            ):
                raise ValueError(extension.literal_link_alias_error)
            if prop in RESOURCE_REFERENCE_PROPERTIES:
                if (
                    mode != RESOURCE_MODE_IMPORT
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
                and REFERENCES.linked_list_kind(prop) is None
            ):
                configured = display_name(prop, resource_type, root)
                canonical = prop.removeprefix(resource_type + ".")
                if (
                    configured != canonical
                    and display_property in {prop, canonical}
                    and alias is None
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
            if REFERENCES.linked_list_kind(prop) is not None and not (
                _verified_reference
                and re.fullmatch(r"\[\s*\]", literal(cells[2]).strip())
            ):
                raise ValueError(
                    f"{prop} must use indexed one-resource-per-row display"
                )
            group = None
            if extension.restore_group is not None:
                try:
                    group = extension.restore_group(
                        cells,
                        display_property,
                        mode=mode,
                        counts=counts,
                        names=names,
                        verified=_verified_reference,
                    )
                except ReferenceResolutionError:
                    raise
                except DisplayReferenceError as error:
                    message = f"Resource={resource_type}#{anchor}: {error}"
                    reference_error_class = type(error)
                    reference_errors.append(message)
                    reference_positions.extend(
                        dict(position, anchor=anchor, message=message)
                        for position in error.positions
                    )
                    group = RestoredRowGroup([], "reference")
                except DisplayRowError as error:
                    raise ValueError(
                        f"Resource={resource_type}#{anchor}: {error}"
                    ) from error
            if group is not None:
                rows.extend(group.rows)
                changed, kind = True, group.label
            elif item := linked_list_property(display_property, resource_type, root):
                list_prop, first_index = item
                if not _verified_reference:
                    raise ValueError("indexed array display requires Model source rows")
                expected = linked_list_counts.get(list_prop, 0) + 1
                if (
                    not re.fullmatch(r"[1-9][0-9]*", first_index)
                    or int(first_index) != expected
                ):
                    raise ValueError(
                        "Subnet/Security Group display indexes must start at 1 and be sequential per property"
                    )
                linked_list_counts[list_prop] = expected
                changed = True
                kind = "Subnet/Security Group list"
                cells[1] = list_prop
                rows.append(cells)
            else:
                rows.append(cells)
            index += 1
        if extension.restore_children is not None:
            restored = extension.restore_children(rows)
            if restored is not None:
                rows = restored
                changed = True
                kind = extension.restore_label or resource_type
        if extension.restore_formal is not None and not packed_table:
            rows = extension.restore_formal(rows, resource_type, mode=mode)
            changed = True
            kind = extension.restore_label or resource_type
        for row in rows:
            if not _verified_reference and re.search(r"\[\d+\]", row[1]):
                raise ValueError("indexed array display requires Model source rows")
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
        raise reference_error_class(
            "\n".join(reference_errors),
            lines=result,
            positions=tuple(reference_positions),
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
        kinds = dict.fromkeys(
            match[1] for line in lines if (match := RESOURCE.fullmatch(line))
        )
        for kind in kinds:
            restore = REGISTRY.presentation(kind).restore_document_tables
            if restore is not None:
                lines = restore(lines, root)
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
                named_child = REGISTRY.presentation(resource_type).named_child
                if (
                    prop == f"{resource_type}.{rule['parentProperty']}"
                    and named_child is None
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
                        if named_child is not None:
                            label = CHILD_NAME.match(cells[3][marker.end() :])
                            if not label or label.group(1).strip() in {
                                "",
                                MODEL_UNSET,
                                MODEL_PENDING_DEPLOY,
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
                            and name == MODEL_PENDING_DEPLOY
                        )
                        if not pending_rule and (resource_type, name) in child_names:
                            raise ValueError(
                                f"duplicate grouped identity value: {resource_type}: {name}"
                            )
                        if not pending_rule:
                            child_names.add((resource_type, name))
                        active_child = {
                            RESOURCE_TYPE_KEY: resource_type,
                            RESOURCE_LOGICAL_ID_KEY: logical_id,
                            "anchor": anchor,
                            "parentLogicalId": parent_id,
                            "parentAnchor": parent_anchor,
                            "parentProperty": f"{resource_type}.{rule['parentProperty']}",
                            "rows": [],
                        }
                        if named_child is not None:
                            active_child["displayName"] = name
                        children[anchor] = active_child
                        table_children.append(active_child)
                        counts[resource_type] = counts.get(resource_type, 0) + 1
                    elif (
                        marker
                        or not active_child
                        or active_child[RESOURCE_TYPE_KEY] != resource_type
                    ):
                        raise ValueError(
                            "grouped child rows require anchor and logical ID"
                            if hidden_identity
                            else f"grouped child rows must start with {resource_type}.{identity}"
                        )
                    if marker:
                        cells[3] = cells[3][marker.end() :]
                        if named_child is not None:
                            cells[3] = cells[3][label.end() :]
                    if named_child is not None:
                        if (
                            any(row[1] == prop for row in active_child["rows"])
                            and "[]" not in prop
                        ):
                            raise ValueError(
                                f"{resource_type}: {active_child[RESOURCE_LOGICAL_ID_KEY]}: duplicate property: {prop}"
                            )
                        if prop == active_child["parentProperty"]:
                            reference = re.fullmatch(
                                r"\[[^\]]+\]\(#([^)]*)\)", cells[2]
                            )
                            typed = tuple(nodes(literal(cells[2])))
                            matches_parent = (
                                len(typed) == 1 and typed[0].logical_id == parent_id
                                if typed
                                else reference is not None
                                and reference.group(1) == parent_anchor
                            )
                            if not matches_parent:
                                raise ReferenceResolutionError(
                                    f"{resource_type}: {active_child[RESOURCE_LOGICAL_ID_KEY]}: {prop} must reference enclosing {parent_type}: {parent_id}"
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
            named_child = REGISTRY.presentation(child[RESOURCE_TYPE_KEY]).named_child
            if (
                named_child
                and named_child.require_restored_parent
                and not any(row[1] == child["parentProperty"] for row in child["rows"])
            ):
                raise ValueError(
                    f"{child[RESOURCE_TYPE_KEY]}: {child[RESOURCE_LOGICAL_ID_KEY]}: required property missing: {child['parentProperty']}"
                )
            result.extend(
                (
                    "",
                    f'<a id="{child["anchor"]}"></a>',
                    f"### {child[RESOURCE_TYPE_KEY]}: {child[RESOURCE_LOGICAL_ID_KEY]}",
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
    for child_type in REGISTRY.presentation(resource_type).child_property_prefixes:
        namespace, child = child_type.split(".", 1)
        if display.startswith(child + "."):
            qualified = namespace + "." + display
            return formal_name(qualified, resource_type, root or ROOT) or qualified
    if display.startswith(RESOURCE_PROPERTY_PREFIXES):
        return display
    return resource_type + "." + display if resource_type else display
