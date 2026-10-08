"""Model structure, design ownership, naming and catalog inputs."""


from __future__ import annotations
from collections import Counter
import re
from pathlib import Path
from validation_cache import memoized
from policy_tables import POLICY_FORMATS, rendered_design as rendered_policy_design, without_policy_tables
from design_catalog import design_material_files, DesignSchemaCatalog, api_snapshot_errors
from design_layout import (
    GROUPED, CHILD, HIDDEN_PROPERTIES, SECURITY_GROUP_TYPES, RESOURCE as RESOURCE_HEADING_PATTERN,
    expanded_display_rows, resource_anchor, resource_display_name, resource_heading_lines,
    resource_has_name_property, resource_logical_ids, resource_modes, STACK_DESIGN, layout_errors,
)
from security_group_tables import security_group_table_lines
from model_core import entries
from model_design import naming_errors
from model_files import MAX_LINES, read_model, model_parts
from validation_scope import scoped_files
import subprocess
import sys
from cloudformation_schema import snapshot_errors
from .project import LOWER_KEBAB_PATTERN

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
OVERVIEW_TYPE_HEADING_PATTERN = re.compile(
    r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+)$"
)
FORBIDDEN_DESIGN_METADATA_PATTERN = re.compile(
    r"^\s*-\s*(Environment|AWS account ID|AWS region|Purpose|Deployment state)\s*:",
    re.IGNORECASE,
)
FORBIDDEN_DESIGN_SECTION_PATTERN = re.compile(
    r"^#{1,6} +(Design decisions|Out of scope|Generated values|設計判断(?:事項)?|設計上の判断|設計上の決定|対象外|スコープ外|設計対象外|生成値|生成された値|デプロイ後生成値)(?:$|[:： -].*)",
    re.IGNORECASE,
)
JAPANESE_TEXT_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
MATERIAL_PATTERN = re.compile(
    r"^[A-Za-z0-9]+(?:\[\])?(?:\.[A-Za-z0-9]+(?:\[\])?)+=(?:IDENTIFIER_OUTPUT)?$"
)
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
    base = root / "model"
    listed = set()
    for path in scoped_files(root, "model", ".properties", scope):
        try:
            read_model(path)
            for file in {path, *model_parts(path)}:
                listed.add(file)
                findings.check(len(file.read_text(encoding="utf-8").splitlines()) <= MAX_LINES,
                           f"model file exceeds {MAX_LINES} lines; split with model_files.py: {findings.relative(file)}")
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid service model: {findings.relative(path)}: {error}")
    for path in base.rglob("*.properties"):
        parts = path.relative_to(base).parts
        if scope is not None and (len(parts) < 3 or (parts[0], parts[1], Path(parts[2]).stem) not in scope):
            continue
        findings.check(path in listed, f"model properties must be a service entrance or its indexed part: {findings.relative(path)}")


@memoized
def catalog_design_properties(
    root) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    resource_types: set[str] = set()
    property_owners: dict[str, set[str]] = {}
    identifier_outputs: dict[str, set[str]] = {}
    for path in design_material_files(root):
        resource_type = path.stem.replace("_", ".", 1)
        prefix = f"{resource_type}."
        resource_types.add(resource_type)
        for line in path.read_text(encoding="utf-8").splitlines():
            property_name, separator, marker = line.partition("=")
            if not separator or not property_name.startswith(prefix):
                continue
            property_path = property_name[len(prefix) :]
            property_owners.setdefault(property_path, set()).add(resource_type)
            property_owners.setdefault(property_name, set()).add(resource_type)
            if marker == "IDENTIFIER_OUTPUT" and property_name not in HIDDEN_PROPERTIES:
                identifier_outputs.setdefault(resource_type, set()).add(property_name)
    for resource_type, property_name in REQUIRED_NAME_PROPERTIES.items():
        if resource_type in resource_types:
            property_owners.setdefault(property_name, set()).add(resource_type)
    for property_name, resource_type in DESIGN_ONLY_PROPERTIES.items():
        if resource_type in resource_types:
            property_owners.setdefault(property_name, set()).add(resource_type)
    return resource_types, property_owners, identifier_outputs


def check_service_file(path: Path, service_id: str, owned_types: tuple[str, ...], *, findings) -> None:
    findings.check(LOWER_KEBAB_PATTERN.fullmatch(service_id) is not None, f"invalid service ID: {findings.relative(path)}: {service_id}")
    findings.check(service_id == path.stem, f"service ID does not match file stem: {findings.relative(path)}")
    for resource_type in owned_types:
        findings.check(
            (resource_type in SECURITY_GROUP_TYPES) == (service_id == "security-group"),
            f"Security Group resources must belong only to security-group: {findings.relative(path)}: {resource_type}",
        )


def markdown_service_metadata(
    path: Path, catalog_types: set[str]
, *, findings) -> tuple[str, tuple[str, ...]] | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    service_lines = [line for line in lines if line.startswith("- Design service ID:")]
    owned_lines = [line for line in lines if line.startswith("- Owned catalog resource types:")]
    findings.check(len(service_lines) == 1, f"Design service ID must appear exactly once: {findings.relative(path)}")
    findings.check(len(owned_lines) == 1, f"Owned catalog resource types must appear exactly once: {findings.relative(path)}")
    if len(service_lines) != 1 or len(owned_lines) != 1:
        return None

    service_match = MARKDOWN_SERVICE_ID_PATTERN.fullmatch(service_lines[0])
    owned_match = MARKDOWN_OWNED_TYPES_PATTERN.fullmatch(owned_lines[0])
    findings.check(service_match is not None, f"invalid Design service ID metadata: {findings.relative(path)}")
    findings.check(owned_match is not None, f"invalid Owned catalog resource types metadata: {findings.relative(path)}")
    if service_match is None or owned_match is None:
        return None

    service_id = service_match.group(1)
    owned_types = tuple(re.findall(r"`([^`]+)`", owned_match.group(1)))
    check_service_file(path, service_id, owned_types, findings=findings)
    findings.check(bool(owned_types), f"Owned catalog resource types must not be empty: {findings.relative(path)}")
    findings.check(len(owned_types) == len(set(owned_types)), f"duplicate owned catalog resource type: {findings.relative(path)}")
    for resource_type in owned_types:
        findings.check(resource_type in catalog_types, f"unknown owned catalog resource type: {findings.relative(path)}: {resource_type}")
    return service_id, owned_types


def model_service_metadata(
    path: Path, catalog_types: set[str]
, *, findings) -> tuple[str, tuple[str, ...]] | None:
    try:
        lines = read_model(path).splitlines()
    except (OSError, ValueError) as error:
        findings.check(False, f"invalid service model: {findings.relative(path)}: {error}")
        return None
    service_matches = [match for line in lines if (match := MODEL_SERVICE_ID_PATTERN.fullmatch(line))]
    owned_matches = [match for line in lines if (match := MODEL_OWNED_TYPES_PATTERN.fullmatch(line))]
    findings.check(len(service_matches) == 1, f"model service ID must appear exactly once: {findings.relative(path)}")
    findings.check(len(owned_matches) == 1, f"model owned catalog resource types must appear exactly once: {findings.relative(path)}")
    if len(service_matches) != 1 or len(owned_matches) != 1:
        return None

    service_key, service_id = service_matches[0].groups()
    owned_key, owned_value = owned_matches[0].groups()
    owned_types = tuple(owned_value.split(",")) if owned_value else ()
    check_service_file(path, service_id, owned_types, findings=findings)
    findings.check(service_key == service_id == owned_key, f"inconsistent model service metadata key: {findings.relative(path)}")
    findings.check(bool(owned_types), f"model owned catalog resource types must not be empty: {findings.relative(path)}")
    findings.check(len(owned_types) == len(set(owned_types)), f"duplicate model owned catalog resource type: {findings.relative(path)}")
    for resource_type in owned_types:
        findings.check(resource_type in catalog_types, f"unknown model owned catalog resource type: {findings.relative(path)}: {resource_type}")
    return service_id, owned_types


def check_design_service_ownership(
    markdown_paths: list[Path]
, *, findings, root) -> tuple[
    dict[Path, tuple[str, tuple[str, ...]]],
    set[str],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    catalog_types, catalog_property_owners, identifier_outputs = catalog_design_properties(root)
    metadata: dict[Path, tuple[str, tuple[str, ...]]] = {}
    owners: dict[tuple[str, str, str], Path] = {}
    docs_base = root / "docs" / "designs"
    model_base = root / "model"

    for markdown_path in markdown_paths:
        relative = markdown_path.relative_to(docs_base)
        model_path = (model_base / relative).with_suffix(".properties")
        markdown_metadata = markdown_service_metadata(markdown_path, catalog_types, findings=findings)
        model_metadata = model_service_metadata(model_path, catalog_types, findings=findings) if model_path.is_file() else None
        if markdown_metadata is None or model_metadata is None:
            continue
        findings.check(markdown_metadata == model_metadata, f"Markdown/model service metadata mismatch: {findings.relative(markdown_path)}")
        metadata[markdown_path] = markdown_metadata

        target = relative.parts[:2]
        if len(target) != 2:
            continue
        for resource_type in markdown_metadata[1]:
            owner_key = (target[0], target[1], resource_type)
            previous = owners.get(owner_key)
            findings.check(previous is None, f"duplicate catalog resource type ownership: {resource_type}: {findings.relative(previous) if previous else findings.relative(markdown_path)} and {findings.relative(markdown_path)}")
            owners.setdefault(owner_key, markdown_path)

    return metadata, catalog_types, catalog_property_owners, identifier_outputs


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def unquoted(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == "`" else value


def resource_property_path(resource_type: str, property_name: str) -> str:
    prefix = resource_type + "."
    return property_name[len(prefix) :] if property_name.startswith(prefix) else property_name


def is_policy_document_property(property_name: str) -> bool:
    return property_name in POLICY_FORMATS


def design_model_values(path: Path, *, design_sources, root) -> dict[str, str] | None:
    from design_layout import design_model_values
    sources = design_sources
    return sources[path] if path in sources else design_model_values(path, root)


def check_resource_layout(findings, root) -> None:
    errors = layout_errors(root)
    findings.check(not errors, "; ".join(errors) or "resource layout decisions are invalid")


def check_resource_names(service_metadata: dict[Path, tuple[str, tuple[str, ...]]], paths: list[Path] | None = None, *, design_sources, findings, root, scope) -> None:
    for path in design_files(root=root, scope=scope) if paths is None else paths:
        lines = resource_heading_lines(without_policy_tables(path.read_text(encoding="utf-8").splitlines()))
        try:
            identities = resource_logical_ids(lines)
            values = design_model_values(path, design_sources=design_sources, root=root)
            modes = resource_modes(lines, values)
            lines = security_group_table_lines(lines)
            lines = expanded_display_rows(lines)
            values = values or {}
            labels = {
                (resource.get("resourceType"), resource.get("logicalId"), label)
                for identity, resource in entries(values, "desired.resource.")
                if (label := values.get(f"display.resource.{identity}.label"))
                and label not in {"UNSET", "PENDING_DEPLOY"}
            }
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid resource identity: {findings.relative(path)}: {error}")
            continue
        anchor = ""
        current = None
        rows = []
        counts = Counter(match.group(1) for line in lines if (match := RESOURCE_HEADING_PATTERN.fullmatch(line)))

        def check_name() -> None:
            if current is None:
                return
            resource_type, display = current
            mode = modes.get(anchor, "CREATE")
            try:
                name = resource_display_name(resource_type, rows, display, mode)
            except ValueError as error:
                findings.check(False, f"{findings.relative(path)}: {error}")
                return
            for error in naming_errors(root, resource_type, rows, mode):
                findings.check(False, f"{findings.relative(path)}: {error}")
            findings.check(name is None or name not in {"", "UNSET", "PENDING_DEPLOY"}, f"resource display name must be confirmed: {findings.relative(path)}: {resource_type}")
            findings.check(name is None or display == name, f"resource heading must display resource name: {findings.relative(path)}: {resource_type}: {display} != {name}")
            if name is None:
                if display == resource_type:
                    findings.check(counts[resource_type] == 1 and resource_type not in GROUPED and not resource_has_name_property(root, resource_type, mode), f"resource type display requires a single nameless independent resource: {findings.relative(path)}: {resource_type}")
                confirmed_label = (resource_type, identities.get(current), display) in labels and not resource_has_name_property(root, resource_type, mode)
                findings.check(current in identities and (display == resource_type or display != identities[current] or confirmed_label), f"resource without a name requires a display label or resource type and hidden logical ID: {findings.relative(path)}: {display}")
            if path in service_metadata:
                expected = resource_anchor(service_metadata[path][0], display, resource_type)
                findings.check(anchor == expected, f"resource anchor must use display name: {findings.relative(path)}: expected {expected}")

        for line in [*lines, "### end"]:
            if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                check_name()
                current, rows = heading.groups(), []
            elif line.startswith("### "):
                check_name()
                current = None
            elif match := ANCHOR_PATTERN.fullmatch(line):
                check_name()
                current, anchor = None, match.group(1)
            elif current and line.startswith("| "):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 4 and cells[0].isdigit():
                    rows.append(cells)
                    if cells[1] == "KMS.Alias.AliasName" and path in service_metadata:
                        marker = CHILD.match(cells[3])
                        expected = resource_anchor(service_metadata[path][0], unquoted(cells[2]), "KMS.Alias")
                        findings.check(bool(marker and marker.group(1) == expected), f"KMS Alias anchor must use AliasName: {findings.relative(path)}: expected {expected}")


def check_policy_tables(paths, findings) -> None:
    for path in paths:
        try:
            findings.check(
                rendered_policy_design(path) == path.read_text(encoding="utf-8"),
                f"Policy tables or overview differ from design JSON/properties: {findings.relative(path)}",
            )
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid policy tables: {findings.relative(path)}: {error}")


def check_observed_values(paths: list[Path] | None = None, *, findings, root, scope) -> None:
    for path in scoped_files(root, "model", ".properties", scope) if paths is None else paths:
        if not path.is_file():
            continue
        try:
            lines = read_model(path).splitlines()
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid service model: {findings.relative(path)}: {error}")
            continue
        for line in lines:
            if line.startswith("observed."):
                findings.check(
                    re.search(r"\barn:aws[a-z-]*:", line, re.IGNORECASE) is None,
                    f"generated ARN persisted in observed model value: {findings.relative(path)}",
                )


def design_files(root, scope) -> list[Path]:
    return [path for path in scoped_files(root, "docs/designs", ".md", scope) if path.name != STACK_DESIGN]


def stack_design_files(root, scope) -> list[Path]:
    return [path for path in scoped_files(root, "docs/designs", ".md", scope) if path.name == STACK_DESIGN]


def check_api_design_catalog(findings, root):
    errors = api_snapshot_errors(root)
    findings.check(not errors, "; ".join(errors) or "API design catalog is invalid")


def check_catalog_inputs(findings, root, set_schema_catalog):
    result = subprocess.run(
        [sys.executable, str(root / "framework" / "scripts" / "update-catalog-lock.py")],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    findings.check(result.returncode == 0, result.stdout.strip() or "catalog lock check failed")

    schema_failures = snapshot_errors(root)
    findings.check(not schema_failures, "; ".join(schema_failures) or "CloudFormation schema snapshot check failed")
    api_failures = api_snapshot_errors(root)
    findings.check(not api_failures, "; ".join(api_failures) or "API design snapshot check failed")
    if not schema_failures and not api_failures:
        set_schema_catalog(DesignSchemaCatalog(root))

    for path in design_material_files(root):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        prefix = path.stem.replace("_", ".", 1) + "."
        findings.check(text.endswith("\n"), f"catalog file lacks final newline: {findings.relative(path)}")
        findings.check(len(lines) == len({line.partition("=")[0] for line in lines}), f"catalog properties must be unique; file order is display order: {findings.relative(path)}")
        for index, line in enumerate(lines):
            findings.check(MATERIAL_PATTERN.fullmatch(line) is not None, f"invalid catalog line: {findings.relative(path)}: {line}")
            findings.check(line.startswith(prefix), f"catalog prefix mismatch: {findings.relative(path)}: {line}")

