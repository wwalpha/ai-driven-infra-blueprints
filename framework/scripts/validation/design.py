"""Model structure, design ownership, naming and catalog inputs."""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from functools import partial as _bind_framework_callback
from pathlib import Path

import aws_mapping_display as _imports_aws_mapping_display
import design.document as _design_document
import design.layout as _dependency_design_layout
import design.layout as _imports_design_layout
import design.policy_tables as _dependency_policy_tables
import design.services.ec2.security_groups as _dependency_security_group_tables
import model.files as _dependency_model_files
import model.projection as _dependency_model_projection
import model.render as _imports_model_render
import model.sources as _dependency_model_sources
import model.sources as _imports_model_sources
import utils.aws_catalogs as _imports_utils_aws_catalogs
import validation_scope as _dependency_validation_scope
from design.catalog import (
    DesignSchemaCatalog,
    api_snapshot_errors,
    design_material_files,
)
from design.layout_schema import CHILD, GROUPED, STACK_DESIGN
from design.layout_schema import RESOURCE as RESOURCE_HEADING_PATTERN
from design.services.codebuild import PlaintextReferenceError
from design.services.definitions.ec2 import SECURITY_GROUP_TYPES
from design.services.definitions.registry import HIDDEN_PROPERTIES, POLICY_FORMATS
from model.core import (
    ReferenceDiagnosticError,
    ReferenceResolutionError,
    entries,
    properties,
)
from utils.cloudformation.schema import material_files, snapshot_errors
from utils.input_cache import input_scope, input_text, memoized
from utils.project_targets import LOWER_KEBAB_PATTERN

from .diagnostics import (
    Diagnostic,
    display_diagnostics,
    plaintext_diagnostics,
    service_scope,
)
from .findings import FindingsError

TABLE_HEADER = "| No. | Property | Value | Source / Comment |"
TABLE_ALIGNMENT = "| ---: | --- | --- | --- |"
ANCHOR_PATTERN = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
VALUE_LINK_PATTERN = re.compile(r"^\[[^\]]+\]\(([^)#]+)\)$")
RESOURCE_LINK_PATTERN = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")
MARKDOWN_SERVICE_ID_PATTERN = re.compile(r"^- Design service ID: `([^`]+)`$")
MARKDOWN_OWNED_TYPES_PATTERN = re.compile(
    r"^- Owned catalog resource types: (`[^`]+`(?:, `[^`]+`)*)$"
)
MODEL_SERVICE_ID_PATTERN = re.compile(r"^desired\.service\.(.+)\.serviceId=(.*)$")
MODEL_OWNED_TYPES_PATTERN = re.compile(
    r"^desired\.service\.(.+)\.ownedCatalogResourceTypes=(.*)$"
)
OVERVIEW_HEADING = "## リソース一覧"
OVERVIEW_TYPE_HEADING_PATTERN = re.compile(r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+)$")
FORBIDDEN_DESIGN_METADATA_PATTERN = re.compile(
    r"^\s*-\s*(Environment|AWS account ID|AWS region|Purpose|Deployment state)\s*:",
    re.IGNORECASE,
)
FORBIDDEN_DESIGN_SECTION_PATTERN = re.compile(
    r"^#{1,6} +(Design decisions|Out of scope|Generated values|設計判断(?:事項)?|設計上の判断|設計上の決定|対象外|スコープ外|設計対象外|生成値|生成された値|デプロイ後生成値)(?:$|[:： -].*)",
    re.IGNORECASE,
)
JAPANESE_TEXT_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
REQUIRED_NAME_PROPERTIES = {
    "EC2.FlowLog": "EC2.FlowLog.Name",
    "EC2.RouteTable": "EC2.RouteTable.Name",
    "EC2.Subnet": "EC2.Subnet.Name",
    "EC2.VPC": "EC2.VPC.Name",
}
GROUPED_CHILD_RESOURCE_TYPES = set(GROUPED)
DESIGN_ONLY_PROPERTIES = {"S3.Bucket.Region": "S3.Bucket"}
S3_KMS_MASTER_KEY_ID = (
    "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]"
    ".ServerSideEncryptionByDefault.KMSMasterKeyID"
)


def check_model_files(findings, root, scope) -> None:
    for path in _dependency_validation_scope.scoped_files(
        root, "model", ".properties", scope
    ):
        try:
            load_model = _imports_model_sources.load_model
            analysis = load_model(path)
            if analysis is None:
                raise ValueError("missing service model")
            for warning in analysis.warnings:
                findings.warn(warning)
        except ReferenceDiagnosticError as error:
            findings.warn(error, model=str(path))
        except (OSError, ValueError) as error:
            findings.check(
                False, f"invalid service model: {findings.relative(path)}: {error}"
            )


@memoized
def catalog_design_properties(
    root,
) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    catalogs_for = _imports_utils_aws_catalogs.catalogs_for
    types, owners, outputs = catalogs_for(root).design_properties()
    resource_types = set(types)
    property_owners = {key: set(value) for key, value in owners.items()}
    identifier_outputs = {
        key: set(value) - HIDDEN_PROPERTIES
        for key, value in outputs.items()
        if value - HIDDEN_PROPERTIES
    }
    for resource_type, property_name in REQUIRED_NAME_PROPERTIES.items():
        if resource_type in resource_types:
            property_owners.setdefault(property_name, set()).add(resource_type)
    for property_name, resource_type in DESIGN_ONLY_PROPERTIES.items():
        if resource_type in resource_types:
            property_owners.setdefault(property_name, set()).add(resource_type)
    return resource_types, property_owners, identifier_outputs


def check_service_file(
    path: Path, service_id: str, owned_types: tuple[str, ...], *, findings
) -> None:
    findings.check(
        LOWER_KEBAB_PATTERN.fullmatch(service_id) is not None,
        f"invalid service ID: {findings.relative(path)}: {service_id}",
    )
    findings.check(
        service_id == path.stem,
        f"service ID does not match file stem: {findings.relative(path)}",
    )
    for resource_type in owned_types:
        findings.check(
            (resource_type in SECURITY_GROUP_TYPES) == (service_id == "security-group"),
            f"Security Group resources must belong only to security-group: {findings.relative(path)}: {resource_type}",
        )


def markdown_service_metadata(
    path: Path, catalog_types: set[str], *, findings
) -> tuple[str, tuple[str, ...]] | None:
    lines = input_text(path, encoding="utf-8").splitlines()
    service_lines = [line for line in lines if line.startswith("- Design service ID:")]
    owned_lines = [
        line for line in lines if line.startswith("- Owned catalog resource types:")
    ]
    findings.check(
        len(service_lines) == 1,
        f"Design service ID must appear exactly once: {findings.relative(path)}",
    )
    findings.check(
        len(owned_lines) == 1,
        f"Owned catalog resource types must appear exactly once: {findings.relative(path)}",
    )
    if len(service_lines) != 1 or len(owned_lines) != 1:
        return None

    service_match = MARKDOWN_SERVICE_ID_PATTERN.fullmatch(service_lines[0])
    owned_match = MARKDOWN_OWNED_TYPES_PATTERN.fullmatch(owned_lines[0])
    findings.check(
        service_match is not None,
        f"invalid Design service ID metadata: {findings.relative(path)}",
    )
    findings.check(
        owned_match is not None,
        f"invalid Owned catalog resource types metadata: {findings.relative(path)}",
    )
    if service_match is None or owned_match is None:
        return None

    service_id = service_match.group(1)
    owned_types = tuple(re.findall(r"`([^`]+)`", owned_match.group(1)))
    check_service_file(path, service_id, owned_types, findings=findings)
    findings.check(
        bool(owned_types),
        f"Owned catalog resource types must not be empty: {findings.relative(path)}",
    )
    findings.check(
        len(owned_types) == len(set(owned_types)),
        f"duplicate owned catalog resource type: {findings.relative(path)}",
    )
    for resource_type in owned_types:
        findings.check(
            resource_type in catalog_types,
            f"unknown owned catalog resource type: {findings.relative(path)}: {resource_type}",
        )
    return service_id, owned_types


def model_service_metadata(
    path: Path, catalog_types: set[str], *, findings, values=None
) -> tuple[str, tuple[str, ...]] | None:
    try:
        lines = (
            read_model(path)
            if values is None
            else "".join(f"{k}={v}\n" for k, v in values.items())
        ).splitlines()
    except ReferenceResolutionError as error:
        findings.warn(error)
        return None
    except (OSError, ValueError) as error:
        findings.check(
            False, f"invalid service model: {findings.relative(path)}: {error}"
        )
        return None
    service_matches = [
        match for line in lines if (match := MODEL_SERVICE_ID_PATTERN.fullmatch(line))
    ]
    owned_matches = [
        match for line in lines if (match := MODEL_OWNED_TYPES_PATTERN.fullmatch(line))
    ]
    findings.check(
        len(service_matches) == 1,
        f"model service ID must appear exactly once: {findings.relative(path)}",
    )
    findings.check(
        len(owned_matches) == 1,
        f"model owned catalog resource types must appear exactly once: {findings.relative(path)}",
    )
    if len(service_matches) != 1 or len(owned_matches) != 1:
        return None

    service_key, service_id = service_matches[0].groups()
    owned_key, owned_value = owned_matches[0].groups()
    owned_types = tuple(owned_value.split(",")) if owned_value else ()
    check_service_file(path, service_id, owned_types, findings=findings)
    findings.check(
        service_key == service_id == owned_key,
        f"inconsistent model service metadata key: {findings.relative(path)}",
    )
    findings.check(
        bool(owned_types),
        f"model owned catalog resource types must not be empty: {findings.relative(path)}",
    )
    findings.check(
        len(owned_types) == len(set(owned_types)),
        f"duplicate model owned catalog resource type: {findings.relative(path)}",
    )
    for resource_type in owned_types:
        findings.check(
            resource_type in catalog_types,
            f"unknown model owned catalog resource type: {findings.relative(path)}: {resource_type}",
        )
    return service_id, owned_types


def check_design_service_ownership(
    markdown_paths: list[Path],
    *,
    findings,
    root,
    design_sources=None,
    definitions_root=None,
) -> tuple[
    dict[Path, tuple[str, tuple[str, ...]]],
    set[str],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    catalog_types, catalog_property_owners, identifier_outputs = (
        catalog_design_properties(definitions_root or root)
    )
    metadata: dict[Path, tuple[str, tuple[str, ...]]] = {}
    owners: dict[tuple[str, str, str], Path] = {}
    docs_base = root / "docs" / "designs"
    model_base = root / "model"

    for markdown_path in markdown_paths:
        relative = markdown_path.relative_to(docs_base)
        model_path = (model_base / relative).with_suffix(".properties")
        markdown_metadata = markdown_service_metadata(
            markdown_path, catalog_types, findings=findings
        )
        model_metadata = (
            model_service_metadata(
                model_path,
                catalog_types,
                findings=findings,
                values=(design_sources or {}).get(markdown_path),
            )
            if _dependency_model_sources.model_exists(model_path)
            else None
        )
        if markdown_metadata is None or model_metadata is None:
            continue
        findings.check(
            markdown_metadata == model_metadata,
            f"Markdown/model service metadata mismatch: {findings.relative(markdown_path)}",
        )
        metadata[markdown_path] = markdown_metadata

        target = relative.parts[:2]
        if len(target) != 2:
            continue
        for resource_type in markdown_metadata[1]:
            owner_key = (target[0], target[1], resource_type)
            previous = owners.get(owner_key)
            findings.check(
                previous is None,
                f"duplicate catalog resource type ownership: {resource_type}: {findings.relative(previous) if previous else findings.relative(markdown_path)} and {findings.relative(markdown_path)}",
            )
            owners.setdefault(owner_key, markdown_path)

    return metadata, catalog_types, catalog_property_owners, identifier_outputs


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def unquoted(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == "`" else value


def resource_property_path(resource_type: str, property_name: str) -> str:
    prefix = resource_type + "."
    return (
        property_name[len(prefix) :]
        if property_name.startswith(prefix)
        else property_name
    )


def is_policy_document_property(property_name: str) -> bool:
    return property_name in POLICY_FORMATS


def design_model_values(path: Path, *, design_sources, root) -> dict[str, str] | None:
    design_model_values = _imports_design_layout.design_model_values
    sources = design_sources
    return sources[path] if path in sources else design_model_values(path, root)


def check_resource_layout(findings, root) -> None:
    errors = _dependency_design_layout.layout_errors(root)
    findings.check(
        not errors, "; ".join(errors) or "resource layout decisions are invalid"
    )


def _callback_check_resource_names_check_name(
    anchor,
    bound_anchors,
    counts,
    current,
    definitions_root,
    findings,
    identities,
    model_anchors,
    modes,
    path,
    resources,
    root,
    rows,
    service_metadata,
    values,
    /,
) -> None:
    if current is None:
        return
    resource_type, display = current
    mode = modes.get(anchor, "CREATE")
    label = None
    if values:
        key = (resource_type, identities.get(anchor))
        matched = resources.get(key)
        if not matched or model_anchors.get(anchor, key) != key:
            findings.add_diagnostic(
                Diagnostic.create(
                    root,
                    code="design.identity.invalid",
                    check_id="design.identity",
                    service=service_scope(root, path),
                    source_path=path,
                    location=anchor,
                    message=f"hidden logical ID missing or mismatched with authoritative resource at anchor: {findings.relative(path)}: {resource_type}: {anchor}",
                )
            )
            return
        label = values.get(f"display.resource.{matched[0]}.label")
    elif display != resource_type:
        label = display
    try:
        validation_rows = _imports_aws_mapping_display.validation_rows
        semantic = validation_rows(
            rows,
            values,
            resource_type,
            identities.get(anchor, current[1]),
            definitions_root,
            scope=(*path.parent.parts[-2:], path.stem),
        )
        if values:
            display_name = _imports_model_render.display_name
            resource_presentation = _imports_model_render.resource_presentation
            Scope = _imports_model_sources.Scope
            name, configured = display_name(
                values, matched[0], matched[1], semantic, definitions_root
            )
            expected, _, _ = resource_presentation(
                values,
                matched[0],
                matched[1],
                definitions_root,
                scope=Scope(root, *path.parent.parts[-2:], path.stem),
            )
            if name != expected:
                raise ValueError(
                    f"resource display name does not match authoritative Model: {resource_type}: {name} != {expected}"
                )
        else:
            name, configured = _dependency_design_layout.resource_display_selection(
                definitions_root,
                resource_type,
                semantic,
                label,
                mode,
                counts[resource_type],
            )
    except ReferenceResolutionError as error:
        findings.warn(error)
        return
    except ValueError as error:
        findings.check(False, f"{findings.relative(path)}: {error}")
        return
    findings.check(
        name is None or name not in {"", "UNSET", "PENDING_DEPLOY"},
        f"resource display name must be confirmed: {findings.relative(path)}: {resource_type}",
    )
    findings.check(
        name is None or display == name,
        f"resource heading must display {'resource name' if configured is not None else 'authoritative display label'}: {findings.relative(path)}: {resource_type}: {display} != {name}",
    )
    if name is None:
        findings.check(
            False,
            f"resource type display requires a single nameless independent resource or confirmed display label: {findings.relative(path)}: {resource_type}",
        )
    elif configured is None and not values:
        findings.check(
            anchor in identities and display != identities[anchor],
            f"resource without a name requires a display label or resource type and hidden logical ID: {findings.relative(path)}: {display}",
        )
    if path in service_metadata:
        expected = bound_anchors.get(
            (resource_type, identities.get(anchor)),
            _dependency_design_layout.resource_anchor(
                service_metadata[path][0], display, resource_type
            ),
        )
        message = f"resource anchor must match saved Model anchor: {findings.relative(path)}: expected {expected}"
        if values and anchor != expected:
            findings.add_diagnostic(
                Diagnostic.create(
                    root,
                    code="design.identity.invalid",
                    check_id="design.identity",
                    service=service_scope(root, path),
                    source_path=path,
                    location=anchor,
                    message=message,
                )
            )
        else:
            findings.warn(anchor == expected, message)


@input_scope
def check_resource_names(
    service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
    paths: list[Path] | None = None,
    *,
    design_sources,
    findings,
    root,
    scope,
    definitions_root=None,
    check_display=True,
) -> None:
    definitions_root = definitions_root or root
    for path in design_files(root=root, scope=scope) if paths is None else paths:
        lines = _dependency_design_layout.resource_heading_lines(
            _dependency_policy_tables.without_policy_tables(
                input_text(path, encoding="utf-8").splitlines()
            )
        )
        try:
            identities = _dependency_design_layout.resource_logical_ids(lines)
            values = design_model_values(path, design_sources=design_sources, root=root)
            bound_anchors = (
                _dependency_model_projection.bound_resource_anchors(path)
                if values is None
                else {}
            )
            bound_anchors.update(
                {
                    (resource["resourceType"], resource["logicalId"]): resource[
                        "anchor"
                    ]
                    for _, resource in entries(values or {}, "desired.resource.")
                    if resource.get("anchor")
                }
            )
            modes = _dependency_design_layout.resource_modes(lines, values)
            reference_tables = (
                _design_document.model_reference_tables(
                    path,
                    input_text(path, encoding="utf-8"),
                    tuple((values or {}).items()),
                    definitions_root,
                )
                if check_display
                else ()
            )
            lines = _dependency_security_group_tables.security_group_table_lines(
                lines, definitions_root
            )
            lines = _dependency_design_layout.expanded_display_rows(
                lines, definitions_root, modes=modes, reference_tables=reference_tables
            )
            values = values or {}
            resources = {
                (resource["resourceType"], resource["logicalId"]): (identity, resource)
                for identity, resource in entries(values, "desired.resource.")
            }
            model_anchors = {
                resource["anchor"]: key for key, (_, resource) in resources.items()
            }
        except ReferenceDiagnosticError as error:
            findings.warn(error)
            continue
        except _design_document.DisplayMismatchError as error:
            causes = list(
                display_diagnostics(root, path, error, "design.identity.display")
            )
            for diagnostic in causes:
                findings.add_diagnostic(diagnostic)
            scope = {(*path.parent.parts[-2:], path.stem)}
            entry = dict(
                code="design.identity.dependency",
                reason="display",
                status="NOT_RUN",
                scope=["/".join(item) for item in scope],
                cause_keys=[item.cause_key for item in causes],
                checks=["resource names and identity after display expansion"],
                complete=False,
            )
            findings.unverified.append(entry)
            findings.result("design.identity", scope).metadata.update(
                complete=False, reason="display", unverified=[entry]
            )
            continue
        except FindingsError as error:
            findings.include_diagnostics(error.findings)
            continue
        except PlaintextReferenceError as error:
            for diagnostic in plaintext_diagnostics(
                findings.canonical_root, path, error
            ):
                findings.add_diagnostic(diagnostic)
            continue
        except _design_document.SavedIdentityError as error:
            findings.add_diagnostic(
                Diagnostic.create(
                    root,
                    code="design.identity.invalid",
                    check_id="design.identity",
                    service=service_scope(root, path),
                    source_path=path,
                    message=f"invalid resource identity: {findings.relative(path)}: {error}",
                )
            )
            continue
        except (OSError, ValueError) as error:
            findings.processing_failure(
                "design.identity", {(*path.parent.parts[-2:], path.stem)}, error
            )
            continue
        anchor = ""
        current = None
        rows = []
        counts = Counter(
            match.group(1)
            for line in lines
            if (match := RESOURCE_HEADING_PATTERN.fullmatch(line))
        )

        for line in [*lines, "### end"]:
            if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                _callback_check_resource_names_check_name(
                    anchor,
                    bound_anchors,
                    counts,
                    current,
                    definitions_root,
                    findings,
                    identities,
                    model_anchors,
                    modes,
                    path,
                    resources,
                    root,
                    rows,
                    service_metadata,
                    values,
                )
                current, rows = heading.groups(), []
            elif line.startswith("### "):
                _callback_check_resource_names_check_name(
                    anchor,
                    bound_anchors,
                    counts,
                    current,
                    definitions_root,
                    findings,
                    identities,
                    model_anchors,
                    modes,
                    path,
                    resources,
                    root,
                    rows,
                    service_metadata,
                    values,
                )
                current = None
            elif match := ANCHOR_PATTERN.fullmatch(line):
                _callback_check_resource_names_check_name(
                    anchor,
                    bound_anchors,
                    counts,
                    current,
                    definitions_root,
                    findings,
                    identities,
                    model_anchors,
                    modes,
                    path,
                    resources,
                    root,
                    rows,
                    service_metadata,
                    values,
                )
                current, anchor = None, match.group(1)
            elif current and line.startswith("| "):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 4 and cells[0].isdigit():
                    rows.append(cells)
                    if cells[1] == "KMS.Alias.AliasName" and path in service_metadata:
                        marker = CHILD.match(cells[3])
                        expected = bound_anchors.get(
                            ("KMS.Alias", marker.group(2) if marker else None),
                            marker.group(1) if marker else None,
                        )
                        findings.check(
                            bool(marker and marker.group(1) == expected),
                            f"KMS Alias anchor must match saved Model anchor: {findings.relative(path)}: expected {expected}",
                        )


def check_policy_tables(paths, findings, *, definitions_root=None) -> None:
    for path in paths:
        try:
            findings.check(
                _dependency_policy_tables.rendered_design(
                    path, definitions_root=definitions_root
                )
                == input_text(path, encoding="utf-8"),
                f"Policy tables or overview differ from design JSON/properties: {findings.relative(path)}",
            )
        except ReferenceResolutionError as error:
            findings.warn(error)
        except (OSError, ValueError) as error:
            findings.check(
                False, f"invalid policy tables: {findings.relative(path)}: {error}"
            )


def check_observed_values(
    paths: list[Path] | None = None, *, findings, root, scope, design_sources=None
) -> None:
    for path in (
        _dependency_validation_scope.scoped_files(root, "model", ".properties", scope)
        if paths is None
        else paths
    ):
        try:
            if not _dependency_model_sources.model_exists(path):
                continue
            view = (
                root / "docs/designs" / path.relative_to(root / "model")
            ).with_suffix(".md")
            values = (design_sources or {}).get(view)
            if values is None:
                values = properties(read_model(path))
        except ReferenceResolutionError as error:
            findings.warn(error)
            continue
        except (OSError, ValueError) as error:
            findings.check(
                False, f"invalid service model: {findings.relative(path)}: {error}"
            )
            continue
        for key, value in values.items():
            if key.startswith("observed.row.") and key.endswith(".value"):
                owner = key.split(".")[2].rpartition("-")[0]
                findings.check(
                    values.get(f"desired.resource.{owner}.resourceMode") == "IMPORT"
                    or re.search(r"\barn:aws[a-z-]*:", value, re.IGNORECASE) is None,
                    f"generated ARN persisted in observed model value: {findings.relative(path)}",
                )


def design_files(root, scope) -> list[Path]:
    return [
        path
        for path in _dependency_validation_scope.scoped_files(
            root, "docs/designs", ".md", scope
        )
        if path.name != STACK_DESIGN
    ]


def stack_design_files(root, scope) -> list[Path]:
    return [
        path
        for path in _dependency_validation_scope.scoped_files(
            root, "docs/designs", ".md", scope
        )
        if path.name == STACK_DESIGN
    ]


def check_api_design_catalog(findings, root):
    errors = api_snapshot_errors(root)
    findings.check(not errors, "; ".join(errors) or "API design catalog is invalid")


def _callback_check_catalog_inputs_schema_check(findings, root, /):
    errors = snapshot_errors(root)
    findings.check(
        not errors, "; ".join(errors) or "CloudFormation schema snapshot check failed"
    )


def check_catalog_inputs(findings, root, set_schema_catalog, scope=None):
    result = subprocess.run(
        [
            sys.executable,
            str(root / "framework" / "scripts" / "update-catalog-lock.py"),
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    findings.check(
        result.returncode == 0, result.stdout.strip() or "catalog lock check failed"
    )

    schema_check = _bind_framework_callback(
        _callback_check_catalog_inputs_schema_check, findings, root
    )
    schema = findings.evaluate(
        "framework.cloudformation-schema-catalog", scope, schema_check
    )
    api = findings.evaluate(
        "framework.api-design-catalog",
        scope,
        lambda: check_api_design_catalog(findings, root),
    )
    if schema.status == api.status == "PASS":
        set_schema_catalog(DesignSchemaCatalog(root))

    aws_materials = set(material_files(root))
    for path in design_material_files(root):
        text = input_text(path, encoding="utf-8")
        findings.check(
            text.endswith("\n"),
            f"catalog file lacks final newline: {path.relative_to(root).as_posix()}",
        )
        if path in aws_materials:
            lines = text.splitlines()
            findings.check(
                len(lines) == len({line.partition("=")[0] for line in lines}),
                f"catalog properties must be unique; file order is display order: {path.relative_to(root).as_posix()}",
            )


def read_model(path):
    return _dependency_model_files.read_model(path)
