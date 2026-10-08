"""Design table/schema validation and linked artifact collection."""


from __future__ import annotations
import json
import re
from pathlib import Path
from policy_tables import iam_role_policy_artifact_filename
from design_catalog import property_paths_with_parents
from macie_bucket_tables import job_bucket_tables
from design_layout import (
    SUBNET_LIST_PROPERTIES, DISPLAY_PROPERTY_ALIASES, GROUPED, REQUIRED_NAME_TAG_TYPES,
    is_service_role_reference, SECURITY_GROUP_TYPES, GROUPED_RESOURCE_TYPES,
    IMPLICIT_GROUPED_PROPERTIES, RESOURCE as RESOURCE_HEADING_PATTERN, expanded_display_rows,
    expanded_design, resource_anchor, resource_display_name, resource_heading_lines,
    resource_logical_ids, resource_modes, catalog_order_errors,
)
from security_group_tables import security_group_table_lines
from model_core import properties
from .design import (
    ANCHOR_PATTERN, DESIGN_ONLY_PROPERTIES, FORBIDDEN_DESIGN_METADATA_PATTERN,
    FORBIDDEN_DESIGN_SECTION_PATTERN, GROUPED_CHILD_RESOURCE_TYPES, JAPANESE_TEXT_PATTERN,
    LINK_PATTERN, LOWER_KEBAB_PATTERN, REQUIRED_NAME_PROPERTIES, RESOURCE_LINK_PATTERN,
    S3_KMS_MASTER_KEY_ID, TABLE_ALIGNMENT, TABLE_HEADER, VALUE_LINK_PATTERN, design_files,
    design_model_values, is_policy_document_property, resource_property_path, unquoted,
)

def check_cidr_value(path: Path, property_name: str, value: str, *, findings) -> None:
    findings.check(
        not ("cidr" in property_name.lower() and "PENDING_DEPLOY" in value.upper()),
        f"CIDR must not use PENDING_DEPLOY: {findings.relative(path)}: {property_name}",
    )


def check_generated_identifier(
        path: Path,
    resource_type: str,
    logical_id: str,
    rows: list[list[str]],
    identifier_outputs: dict[str, set[str]],
 *, findings) -> None:
    expected_properties = sorted(identifier_outputs.get(resource_type, set()))
    for property_name in expected_properties:
        generated_rows = [row for row in rows if row[1] == property_name]
        findings.check(
            len(generated_rows) == 1,
            f"identifier output row must appear exactly once: {findings.relative(path)}: {property_name}",
        )
        if len(generated_rows) != 1:
            continue
        value = unquoted(generated_rows[0][2])
        findings.check(bool(value), f"identifier output value is empty: {findings.relative(path)}: {property_name}")
        findings.check(value != "NOT_DEPLOYED", f"identifier output must use PENDING_DEPLOY after destroy: {findings.relative(path)}: {property_name}")
        findings.check(
            value == "PENDING_DEPLOY" or value != logical_id,
            f"identifier output must use a physical value, not the logical ID: {findings.relative(path)}: {property_name}",
        )
        findings.check(
            re.search(r"\barn:aws[a-z-]*:", value, re.IGNORECASE) is None,
            f"generated ARN is forbidden in design: {findings.relative(path)}: {property_name}",
        )
    if resource_type != "EC2.SecurityGroup" and resource_type not in {"EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}:
        for error in catalog_order_errors(resource_type, rows):
            findings.check(False, f"{findings.relative(path)}: {error}")


def check_required_name_tag(
        path: Path,
    resource_type: str,
    logical_id: str,
    rows: list[list[str]],
    mode: str = "CREATE",
 *, findings, schema_catalog) -> None:
    if resource_type in REQUIRED_NAME_TAG_TYPES:
        try:
            name = resource_display_name(resource_type, rows, mode=mode)
        except ValueError as error:
            findings.check(False, f"{findings.relative(path)}: {error}")
            return
        if name is not None:
            findings.check(logical_id == name, f"resource heading identifier must match Name tag value: {findings.relative(path)}: {resource_type}")
        return
    property_name = REQUIRED_NAME_PROPERTIES.get(resource_type)
    if property_name is None:
        return
    name_rows = [row for row in rows if row[1] == property_name]
    findings.check(
        len(name_rows) == 1 or (mode == "IMPORT" and not name_rows),
        f"required Name property must appear exactly once: {findings.relative(path)}: {property_name}",
    )
    legacy_name_rows = [
        row
        for row in rows
        if resource_property_path(resource_type, row[1])
        in {"Tags[].Key", "HostedZoneTags[].Key"}
        and unquoted(row[2]) == "Name"
    ]
    findings.check(
        not legacy_name_rows,
        f"Name tag must use one-row property {property_name}: {findings.relative(path)}: {resource_type}",
    )
    if len(name_rows) != 1:
        return
    findings.check(rows[0] == name_rows[0], f"design-only Name must be the first row: {findings.relative(path)}: {property_name}")
    value = unquoted(name_rows[0][2]).strip()
    findings.check(bool(value), f"required Name value must not be empty: {findings.relative(path)}: {property_name}")
    if mode == "IMPORT" and schema_catalog is not None:
        for error in schema_catalog.literal_errors(resource_type, "Tags[].Value", unquoted(name_rows[0][2])):
            findings.check(False, f"provider schema violation: {findings.relative(path)}: {property_name}: {error}")
    findings.check(
        mode == "IMPORT" or LOWER_KEBAB_PATTERN.fullmatch(value) is not None,
        f"required Name value must be lower-kebab-case: {findings.relative(path)}: {property_name}: {value}",
    )
    findings.check(
        logical_id == value,
        f"resource heading identifier must match Name value: {findings.relative(path)}: {resource_type}: {logical_id} != {value}",
    )


def check_markdown_iam_policy_artifacts(
    path: Path, logical_id: str, rows: list[list[str]]
, *, design_sources, findings, markdown_iam_policy_artifacts, root) -> None:
    relative = path.relative_to(root / "docs" / "designs")
    if len(relative.parts) < 3:
        return
    target = (relative.parts[0], relative.parts[1])
    from design_layout import resource_identity_metadata
    entry_numbers, _ = resource_identity_metadata(path.read_text(encoding="utf-8").splitlines(), values=design_model_values(path, design_sources=design_sources, root=root)) if path.is_file() else ({}, {})
    legacy = logical_id not in entry_numbers.values()
    properties = [row[1].removeprefix("IAM.Role.") for row in rows]

    for index, row in enumerate(rows):
        property_name = properties[index]
        link = VALUE_LINK_PATTERN.fullmatch(row[2])
        if property_name == "AssumeRolePolicyDocument" and link:
            artifact = (path.parent / link.group(1)).resolve()
            expected = iam_role_policy_artifact_filename(logical_id)
            findings.check(not legacy or artifact.name == expected, f"invalid IAM trust policy artifact name: {findings.relative(path)}: expected {expected}")
            key = (*target, logical_id, "trust")
            findings.check(key not in markdown_iam_policy_artifacts, f"duplicate IAM trust policy artifact: {findings.relative(path)}: {logical_id}")
            markdown_iam_policy_artifacts.setdefault(key, artifact)

        if property_name == "Policies[].PolicyName":
            paired = index + 1 < len(rows) and properties[index + 1] == "Policies[].PolicyDocument"
            findings.check(paired, f"IAM inline PolicyName must immediately precede PolicyDocument: {findings.relative(path)}: {logical_id}")
        if property_name != "Policies[].PolicyDocument":
            continue

        paired = index > 0 and properties[index - 1] == "Policies[].PolicyName"
        findings.check(paired, f"IAM inline PolicyDocument requires a preceding PolicyName: {findings.relative(path)}: {logical_id}")
        if not paired or not link:
            continue
        policy_name = unquoted(rows[index - 1][2])
        findings.check(policy_name not in {"", "UNSET", "PENDING_DEPLOY"}, f"IAM inline PolicyName is required: {findings.relative(path)}: {logical_id}")
        if policy_name in {"", "UNSET", "PENDING_DEPLOY"}:
            continue
        artifact = (path.parent / link.group(1)).resolve()
        expected = iam_role_policy_artifact_filename(logical_id, policy_name)
        findings.check(not legacy or artifact.name == expected, f"invalid IAM inline policy artifact name: {findings.relative(path)}: expected {expected}")
        key = (*target, logical_id, f"inline:{policy_name}")
        findings.check(key not in markdown_iam_policy_artifacts, f"duplicate IAM inline PolicyName: {findings.relative(path)}: {logical_id}: {policy_name}")
        markdown_iam_policy_artifacts.setdefault(key, artifact)


def check_design_tables(
        service_metadata: dict[Path, tuple[str, tuple[str, ...]]],
    catalog_types: set[str],
    catalog_property_owners: dict[str, set[str]],
    identifier_outputs: dict[str, set[str]],
    paths: list[Path] | None = None,
 *, design_sources, findings, markdown_design_artifacts, markdown_iam_policy_artifacts, root, schema_catalog, scope) -> None:
    for path in design_files(root=root, scope=scope) if paths is None else paths:
        lines = resource_heading_lines(path.read_text(encoding="utf-8").splitlines())
        try:
            identities = resource_logical_ids(lines)
            modes = resource_modes(lines, design_model_values(path, design_sources=design_sources, root=root))
            heading_modes = {}
            anchor = ""
            for line in lines:
                if match := ANCHOR_PATTERN.fullmatch(line):
                    anchor = match.group(1)
                elif match := RESOURCE_HEADING_PATTERN.fullmatch(line):
                    heading_modes[match.groups()] = modes.get(anchor, "CREATE")
        except ValueError as error:
            findings.check(False, f"invalid resource identity: {findings.relative(path)}: {error}")
            identities = {}
            heading_modes = {}
        resource_type = ""
        for index, line in enumerate(lines):
            if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                resource_type = heading.group(1)
                findings.check(
                    (resource_type in SECURITY_GROUP_TYPES) == (path.stem == "security-group"),
                    f"Security Group resources must belong only to security-group: {findings.relative(path)}: {resource_type}",
                )
            elif line.startswith("#"):
                resource_type = ""
            if line != TABLE_HEADER or not resource_type:
                continue
            cursor = index + 2
            while cursor < len(lines) and lines[cursor].startswith("|"):
                cells = [cell.strip() for cell in lines[cursor].strip("|").split("|")]
                if len(cells) == 4 and cells[1].startswith(resource_type + "."):
                    findings.check(False, f"resource table Property must omit heading resource type: {findings.relative(path)}:{cursor + 1}: {cells[1]}")
                cursor += 1
        try:
            lines = security_group_table_lines(lines)
            _, children = expanded_design(lines, normalized=True)
            lines = expanded_display_rows(lines)
        except ValueError as error:
            findings.check(False, f"invalid grouped design: {findings.relative(path)}: {error}")
            children = {}
        for child in children.values():
            resource_type = child["resourceType"]
            if schema_catalog is not None:
                present = {
                    resource_property_path(resource_type, prop)
                    for prop in [*(row[1] for row in child["rows"]), child["parentProperty"]]
                }
                for required in schema_catalog.required_properties(resource_type):
                    if resource_type in catalog_property_owners.get(required, set()):
                        findings.check(required in present, f"required grouped property missing: {findings.relative(path)}: {child['logicalId']}: {required}")
            check_generated_identifier(path, resource_type, child["logicalId"], child["rows"], identifier_outputs, findings=findings)
        findings.check(
            len([line for line in lines if re.fullmatch(r"# [^#].+", line)]) == 1,
            f"design must contain exactly one H1 title: {findings.relative(path)}",
        )
        for line in lines:
            findings.check(
                FORBIDDEN_DESIGN_METADATA_PATTERN.match(line) is None,
                f"forbidden design file metadata: {findings.relative(path)}: {line}",
            )
            findings.check(
                FORBIDDEN_DESIGN_SECTION_PATTERN.fullmatch(line) is None,
                f"forbidden design section: {findings.relative(path)}: {line}",
            )
        table_count = 0
        index = 0
        current_resource_type = ""
        current_logical_id = ""
        while index < len(lines):
            heading_match = RESOURCE_HEADING_PATTERN.fullmatch(lines[index])
            if heading_match:
                current_resource_type = heading_match.group(1)
                current_logical_id = heading_match.group(2)
                findings.check(
                    current_resource_type in catalog_types,
                    f"unknown catalog resource type in heading: {findings.relative(path)}: {current_resource_type}",
                )
                if current_resource_type in catalog_types and path in service_metadata:
                    findings.check(
                        current_resource_type in service_metadata[path][1],
                        f"catalog resource type is outside declared service ownership: {findings.relative(path)}: {current_resource_type}",
                    )
                findings.check(
                    current_resource_type not in GROUPED_CHILD_RESOURCE_TYPES,
                    f"grouped resource type must not have an independent heading: {findings.relative(path)}: {current_resource_type}",
                )
            elif lines[index].startswith("#"):
                current_resource_type = ""
                current_logical_id = ""
            if not lines[index].startswith("|"):
                index += 1
                continue
            if not current_resource_type:
                while index < len(lines) and lines[index].startswith("|"):
                    index += 1
                continue
            table_count += 1
            table = []
            while index < len(lines) and lines[index].startswith("|"):
                table.append(lines[index])
                index += 1
            findings.check(len(table) >= 3, f"incomplete table: {findings.relative(path)}")
            if len(table) < 3:
                continue
            findings.check(table[0] == TABLE_HEADER, f"invalid table header: {findings.relative(path)}")
            findings.check(table[1] == TABLE_ALIGNMENT, f"invalid table alignment: {findings.relative(path)}")
            rows: list[list[str]] = []
            for number, row in enumerate(table[2:], 1):
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                findings.check(len(cells) == 4, f"table row must have four cells: {findings.relative(path)}")
                if len(cells) == 4:
                    display_property = cells[1]
                    cells[1] = DISPLAY_PROPERTY_ALIASES.get(display_property, display_property)
                    if cells[1] in DISPLAY_PROPERTY_ALIASES.values():
                        findings.check(
                            display_property in DISPLAY_PROPERTY_ALIASES,
                            f"formal property must use its Markdown display alias: {findings.relative(path)}: {display_property}",
                        )
                    rows.append(cells)
                    check_cidr_value(path, cells[1], cells[2], findings=findings)
                    findings.check(cells[0] == str(number), f"table numbering error: {findings.relative(path)}")
                    findings.check(
                        JAPANESE_TEXT_PATTERN.search(cells[3]) is not None,
                        f"Source / Comment must be Japanese: {findings.relative(path)}: {cells[3]}",
                    )
                    property_owners = catalog_property_owners.get(cells[1], set())
                    allowed_types = {
                        current_resource_type,
                        *GROUPED_RESOURCE_TYPES.get(current_resource_type, set()),
                    }
                    row_types = property_owners & allowed_types
                    if current_resource_type in catalog_types:
                        findings.check(
                            bool(row_types),
                            f"resource table property is not selected by design catalog: {findings.relative(path)}: {current_resource_type}: {cells[1]}",
                        )
                    if property_owners and path in service_metadata:
                        owned_types = set(service_metadata[path][1])
                        findings.check(bool(property_owners & owned_types), f"catalog property is outside declared service ownership: {findings.relative(path)}: {cells[1]}")
                        if current_resource_type:
                            findings.check(bool(row_types), f"catalog property does not belong to resource table: {findings.relative(path)}: {current_resource_type}: {cells[1]}")
                    schema_type = (
                        current_resource_type
                        if current_resource_type in row_types
                        else min(row_types, default="")
                    )
                    if schema_type in GROUPED:
                        findings.check(
                            cells[1].startswith(schema_type + "."),
                            f"grouped property must use its full catalog name: {findings.relative(path)}: {cells[1]}",
                        )
                    if (
                        schema_catalog is not None
                        and schema_type
                        and schema_type not in schema_catalog.api_schemas
                        and cells[1] != REQUIRED_NAME_PROPERTIES.get(schema_type)
                        and cells[1] not in DESIGN_ONLY_PROPERTIES
                        and LINK_PATTERN.fullmatch(cells[2]) is None
                    ):
                        property_path = resource_property_path(schema_type, cells[1])
                        raw_value = unquoted(cells[2])
                        if cells[1] in SUBNET_LIST_PROPERTIES and raw_value.lstrip().startswith("["):
                            property_path = property_path.removesuffix("[]")
                        errors = [] if is_service_role_reference(cells[1], cells[2]) or (
                            cells[1] in identifier_outputs.get(schema_type, set())
                            and raw_value == "PENDING_DEPLOY"
                        ) else schema_catalog.literal_errors(schema_type, property_path, raw_value)
                        for error in errors:
                            findings.check(
                                False,
                                f"provider schema violation: {findings.relative(path)}: {identities.get((current_resource_type, current_logical_id), current_logical_id)}: {schema_type}.{property_path}: {raw_value!r} {error}",
                            )
                    link_match = VALUE_LINK_PATTERN.fullmatch(cells[2])
                    artifact_link = link_match.group(1) if link_match else ""
                    is_json_link = artifact_link.endswith(".json")
                    if is_policy_document_property(cells[1]):
                        findings.check(is_json_link, f"policy property must link to a JSON artifact: {findings.relative(path)}: {cells[1]}")
                    if cells[1] == S3_KMS_MASTER_KEY_ID:
                        findings.check(
                            RESOURCE_LINK_PATTERN.fullmatch(cells[2]) is not None,
                            f"S3 KMSMasterKeyID must link to a KMS.Alias: {findings.relative(path)}: {current_logical_id}",
                        )
                    if cells[1] == "EC2.SecurityGroup.VpcId":
                        findings.check(
                            RESOURCE_LINK_PATTERN.fullmatch(cells[2]) is not None,
                            f"Security Group VpcId must link to its VPC: {findings.relative(path)}: {current_logical_id}",
                        )
                    if is_json_link:
                        artifact = (path.parent / artifact_link).resolve()
                        expected_directory = path.with_suffix("").resolve()
                        findings.check(artifact.parent == expected_directory, f"design JSON artifact must be stored under owning service: {findings.relative(path)}: {artifact_link}")
                        findings.check(LOWER_KEBAB_PATTERN.fullmatch(artifact.stem) is not None, f"invalid design JSON artifact path: {findings.relative(path)}: {artifact_link}")
                        markdown_design_artifacts.add(artifact)
            if current_resource_type in catalog_types:
                if schema_catalog is not None and current_resource_type in schema_catalog.api_schemas:
                    check_api_design_rows(path, current_resource_type, current_logical_id, rows, findings=findings, schema_catalog=schema_catalog)
                if current_resource_type == "Events.Rule":
                    for property_name in ("Events.Rule.Name", "Events.Rule.State"):
                        selected = [row for row in rows if row[1] == property_name]
                        findings.check(
                            len(selected) == 1,
                            f"{property_name} must appear exactly once: {findings.relative(path)}: {current_logical_id}",
                        )
                        if len(selected) == 1:
                            value = unquoted(selected[0][2]).strip()
                            findings.check(
                                value not in {"", "UNSET", "PENDING_DEPLOY"},
                                f"{property_name} must have a confirmed value: {findings.relative(path)}: {current_logical_id}",
                            )
                if current_resource_type == "S3.Bucket":
                    bucket_name_rows = [
                        row for row in rows if row[1] == "S3.Bucket.BucketName"
                    ]
                    findings.check(
                        len(bucket_name_rows) == 1 and rows[0][1] == "S3.Bucket.BucketName",
                        f"S3.Bucket.BucketName must be the first row: {findings.relative(path)}: {current_logical_id}",
                    )
                    if len(bucket_name_rows) == 1:
                        findings.check(
                            current_logical_id == unquoted(bucket_name_rows[0][2]),
                            f"S3.Bucket heading identifier must match BucketName: {findings.relative(path)}: {current_logical_id}",
                        )
                    region_rows = [
                        row for row in rows if row[1] == "S3.Bucket.Region"
                    ]
                    findings.check(
                        len(region_rows) == 1
                        and len(rows) > 1
                        and rows[1][1] == "S3.Bucket.Region",
                        f"S3.Bucket.Region must be the second row: {findings.relative(path)}: {current_logical_id}",
                    )
                    if len(region_rows) == 1:
                        region = unquoted(region_rows[0][2])
                        findings.check(
                            LOWER_KEBAB_PATTERN.fullmatch(region) is not None
                            and region != "UNSET",
                            f"S3.Bucket.Region must be a confirmed AWS region ID: {findings.relative(path)}: {current_logical_id}",
                        )
                if schema_catalog is not None:
                    schema_types = {current_resource_type} | {
                        resource_type
                        for resource_type in GROUPED_RESOURCE_TYPES.get(
                            current_resource_type, set()
                        )
                        if any(
                            resource_type
                            in catalog_property_owners.get(row[1], set())
                            for row in rows
                        )
                    }
                    for resource_type in schema_types:
                        present = property_paths_with_parents({
                            resource_property_path(resource_type, row[1])
                            for row in rows
                            if resource_type
                            in catalog_property_owners.get(row[1], set())
                        })
                        selected_required = schema_catalog.required_design_properties(resource_type)
                        missing = (
                            selected_required
                            - present
                            - IMPLICIT_GROUPED_PROPERTIES.get(resource_type, set())
                        )
                        for property_name in sorted(missing):
                            findings.check(
                                False,
                                f"required provider schema property missing: {findings.relative(path)}: {resource_type}.{property_name}",
                            )
                check_generated_identifier(
                    path, current_resource_type, identities.get((current_resource_type, current_logical_id), current_logical_id), rows, identifier_outputs
                , findings=findings)
                check_required_name_tag(
                    path, current_resource_type, current_logical_id, rows,
                    heading_modes.get((current_resource_type, current_logical_id), "CREATE"),
                 findings=findings, schema_catalog=schema_catalog)
            if current_resource_type == "IAM.Role":
                check_markdown_iam_policy_artifacts(path, identities.get((current_resource_type, current_logical_id), current_logical_id), rows, design_sources=design_sources, findings=findings, markdown_iam_policy_artifacts=markdown_iam_policy_artifacts, root=root)
        findings.check(table_count > 0, f"resource design has no table: {findings.relative(path)}")

        previous = ""
        for line in lines:
            heading_match = RESOURCE_HEADING_PATTERN.fullmatch(line)
            if heading_match:
                anchor_match = ANCHOR_PATTERN.fullmatch(previous)
                findings.check(anchor_match is not None, f"resource heading lacks explicit anchor: {findings.relative(path)}: {line}")
                if path in service_metadata:
                    logical_id = heading_match.group(2)
                    if anchor_match is not None:
                        expected = resource_anchor(service_metadata[path][0], logical_id, heading_match.group(1))
                        findings.check(anchor_match.group(1) == expected, f"resource anchor does not match service ID/logical ID: {findings.relative(path)}: expected {expected}")
            if line.strip():
                previous = line.strip()


def check_api_design_rows(path: Path, resource_type: str, logical_id: str, rows: list[list[str]], *, findings, schema_catalog) -> None:
    catalog = schema_catalog
    schema = catalog.schema(resource_type)
    values = {}
    before = len(findings.errors)
    for row in rows:
        prop = resource_property_path(resource_type, row[1])
        if prop not in schema["properties"]:
            continue  # The common catalog check reports unselected properties.
        findings.check(prop not in values, f"duplicate API design property: {findings.relative(path)}: {prop}")
        raw = unquoted(row[2])
        node = catalog.property_schema(resource_type, prop)
        link = VALUE_LINK_PATTERN.fullmatch(raw)
        try:
            if link and link.group(1).endswith(".json") and node["type"] == "object":
                artifact = (path.parent / link.group(1)).resolve()
                if artifact.parent != path.with_suffix("").resolve():
                    raise ValueError("API JSON artifact must belong to this service")
                value = json.loads(artifact.read_text(encoding="utf-8"))
            else:
                if LINK_PATTERN.fullmatch(raw):
                    raise ValueError("API root property requires a literal or an object JSON artifact")
                value = raw if node["type"] == "string" else json.loads(raw)
            values[prop] = value
            if prop == "jobId" and value == "PENDING_DEPLOY":
                continue
            for error in catalog.api_value_errors(resource_type, node, value, prop):
                findings.check(False, f"API schema violation: {findings.relative(path)}: {error}")
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid API design value: {findings.relative(path)}: {prop}: {error}")
    if len(findings.errors) == before:
        for error in catalog.job_errors(values):
            findings.check(False, f"API design constraint: {findings.relative(path)}: {error}")
    if resource_type == "Macie.ClassificationJob":
        try:
            tables = job_bucket_tables(path)
        except (OSError, ValueError) as error:
            findings.check(False, f"invalid Macie bucket table: {findings.relative(path)}: {error}")
            return
        scope = values.get("s3JobDefinition", {})
        if isinstance(scope, dict) and "bucketDefinitions" in scope:
            findings.check(logical_id in tables, f"Macie bucketDefinitions requires a Markdown mapping table and JSON artifact: {findings.relative(path)}: {logical_id}")
            if logical_id in tables:
                findings.check(scope["bucketDefinitions"] == tables[logical_id][1], f"Macie bucket mapping differs from JSON artifact: {findings.relative(path)}: {logical_id}")
        else:
            findings.check(logical_id not in tables, f"Macie bucket table requires bucketDefinitions, not bucketCriteria: {findings.relative(path)}: {logical_id}")

