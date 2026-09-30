"""Shared display relationships and identified children in resource tables."""

from __future__ import annotations

import json
import re
from pathlib import Path

from design_catalog import design_material_files
from security_group_tables import security_group_table_lines


LAYOUT_PATH = Path(__file__).resolve().parents[1] / "rules" / "resource-layout.json"
LAYOUTS = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
GROUPED = {name: rule for name, rule in LAYOUTS.items() if isinstance(rule, dict)}
GROUPED_RESOURCE_TYPES = {
    rule["parent"]: {name for name, child in GROUPED.items() if child["parent"] == rule["parent"]}
    for rule in GROUPED.values()
}
IMPLICIT_GROUPED_PROPERTIES = {
    name: {rule["parentProperty"]} for name, rule in GROUPED.items()
}
DISPLAY_ALIAS_PATH = Path(__file__).resolve().parents[1] / "rules" / "display-property-aliases.json"
DISPLAY_PROPERTY_ALIASES = json.loads(DISPLAY_ALIAS_PATH.read_text(encoding="utf-8"))
DETAILS_HEADING = "## リソース詳細"
RESOURCE = re.compile(r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+): ([^<>|`\s](?:[^<>|`]*[^<>|`\s])?)$")
ANCHOR = re.compile(r'<a\s+id="([^"]+)"\s*></a>')
RESOURCE_ID = re.compile(r"^<!-- resource-logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->$")
CHILD = re.compile(
    r'^<a id="([a-z0-9_.-]+)"></a><!-- logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) -->\s*'
)
HEADER = "| No. | Property | Value | Source / Comment |"
ALIGNMENT = "| ---: | --- | --- | --- |"
CODEBUILD_VARIABLE = "CodeBuild.Project.Environment.Variables."
CODEBUILD_FORMAL_VARIABLE = "CodeBuild.Project.Environment.EnvironmentVariables[]."
CODEBUILD_VARIABLE_TYPE = re.compile(r"^<!-- codebuild-variable-type: (PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER) -->\s*")
CODEBUILD_VPC_ITEM = re.compile(r"^VpcConfig\.(Subnets|SecurityGroupIds)\[([1-9][0-9]*)\]$")
CODEBUILD_VPC_PROPERTIES = {"CodeBuild.Project.VpcConfig.Subnets", "CodeBuild.Project.VpcConfig.SecurityGroupIds"}
GUARDDUTY_FEATURE = "GuardDuty.Detector.Features."
GUARDDUTY_FORMAL_FEATURE = "GuardDuty.Detector.Features[]."
CLOUDTRAIL_DATA_RESOURCE = re.compile(r"^EventSelectors\.DataResources\[([1-9]\d*)\]\.(S3|Lambda)$")
CLOUDTRAIL_RESOURCE_TYPES = {"S3": "AWS::S3::Object", "Lambda": "AWS::Lambda::Function"}
CLOUDTRAIL_FORMAL_DATA_RESOURCE = "CloudTrail.Trail.EventSelectors[].DataResources[]."
STACK_DESIGN = "cloudformation-stacks.md"
STACK_HEADER = "| No. | StackName | Template | Parameters | Comment |"
SECURITY_GROUP_TYPES = {"EC2.SecurityGroup", "EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}
RESOURCE_REFERENCE_PROPERTIES = {
    "Config.ConfigurationRecorder.RoleARN": ("IAM.Role", "RoleName"),
    "KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN": ("KMS.Key", "KeyId"),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN": ("S3.Bucket", "BucketName"),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN": ("IAM.Role", "RoleName"),
}
HIDDEN_PROPERTIES = {"CodeCommit.Repository.RepositoryId"}
CODEPIPELINE_STAGE = re.compile(r"^Stages\[([1-9]\d*)\]\.(?:Actions(?:\[([1-9]\d*)\])?\.)?(.+)$")
CODEPIPELINE_CONFIGURATION = "CodePipeline.Pipeline.Stages[].Actions[].Configuration"


def is_service_role_reference(prop: str, value: str) -> bool:
    reference = RESOURCE_REFERENCE_PROPERTIES.get(DISPLAY_PROPERTY_ALIASES.get(prop, prop))
    return bool(reference and reference[0] == "IAM.Role" and re.fullmatch(
        r"(`?)AWSService[A-Za-z0-9_+=,.@-]{1,54}\1", value
    ))


def resource_anchor(service_id: str, name: str) -> str:
    """Use the displayed resource name as the navigation identity."""
    return service_id + "-" + re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-")


def resource_logical_ids(lines: list[str]) -> dict[tuple[str, str], str]:
    """Read hidden IDs before anchors without changing displayed headings."""
    identities = {}
    pending = ""
    anchored = False
    for line in lines:
        if not line.strip():
            continue
        if marker := RESOURCE_ID.fullmatch(line):
            if pending:
                raise ValueError("duplicate resource logical ID metadata")
            pending, anchored = marker.group(1), False
        elif pending and ANCHOR.fullmatch(line) and not anchored:
            anchored = True
        elif pending and (heading := RESOURCE.fullmatch(line)) and anchored:
            if heading.groups() in identities or pending in identities.values():
                raise ValueError("duplicate resource logical ID metadata")
            identities[heading.groups()] = pending
            pending, anchored = "", False
        elif pending or line.startswith("<!-- resource-logical-id:"):
            raise ValueError("resource logical ID metadata must precede its anchor and heading")
    if pending:
        raise ValueError("resource logical ID metadata lacks its anchor and heading")
    return identities


def resource_name_fields(resource_type: str) -> list[str]:
    """Candidate resource names, excluding names of referenced resources."""
    kind = resource_type.split(".")[1]
    names = [kind + "Input.Name", kind + "Config.Name", "Name", "name", kind + "Name", kind + "Identifier", kind + "." + kind + "Name"]
    if kind.endswith("Name"):
        names.append(kind)
    if resource_type == "EC2.SecurityGroup":
        names.append("GroupName")
    if resource_type == "IAM.ManagedPolicy":
        names.append("PolicyName")
    return names


def resource_display_name(resource_type: str, rows: list[list[str]]) -> str | None:
    """Find a selected root name; never invent an AWS name from an internal ID."""
    fields = {row[1].removeprefix(resource_type + "."): row[2].strip("`\"") for row in rows}
    names = resource_name_fields(resource_type)
    for field in names:
        if field in fields and not fields[field].startswith("["):
            return fields[field]
    for tags in ("Tags", "HostedZoneTags"):
        for index, row in enumerate(rows[:-1]):
            if row[1].removeprefix(resource_type + ".") == tags + "[].Key" and row[2].strip("`\"") == "Name":
                value = rows[index + 1]
                if value[1].removeprefix(resource_type + ".") == tags + "[].Value":
                    return value[2].strip("`\"")
        if tags in fields:
            try:
                values = json.loads(fields[tags])
            except ValueError:
                continue  # The schema validator reports malformed JSON.
            if isinstance(values, dict) and isinstance(values.get("Name"), str):
                return values["Name"]
    return None


def stack_design(path: Path) -> list[dict[str, str]]:
    """Read a target's stack detailed design."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if lines[:4] != [
        "# CloudFormation stack 詳細設計", "## Stack一覧", STACK_HEADER,
        "| ---: | --- | --- | --- | --- |",
    ]:
        raise ValueError("invalid CloudFormation stack design header")
    result = []
    for line in lines[4:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not line.startswith("|") or not line.endswith("|") or len(cells) != 5 or not all(cells):
            raise ValueError(f"invalid CloudFormation stack design row: {line}")
        if cells[0] != str(len(result) + 1):
            raise ValueError(f"CloudFormation stack design No. must be sequential: {line}")
        result.append(dict(zip(("name", "template", "parameters", "comment"), cells[1:])))
    if not result:
        raise ValueError("CloudFormation stack design table must not be empty")
    return result


def layout_errors(root: Path) -> list[str]:
    """Require an explicit display decision for every catalog resource."""
    errors = []
    try:
        layouts = json.loads((root / "framework" / "rules" / "resource-layout.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"cannot read resource layout decisions: {error}"]
    if not isinstance(layouts, dict):
        return ["resource layout decisions must be an object"]
    catalog = {
        path.stem.replace("_", ".", 1): {
            line.partition("=")[0] for line in path.read_text(encoding="utf-8").splitlines()
        }
        for path in design_material_files(root)
    }
    try:
        aliases = json.loads((root / "framework" / "rules" / "display-property-aliases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        errors.append(f"cannot read display property aliases: {error}")
        aliases = {}
    selected = set().union(*catalog.values())
    if not isinstance(aliases, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in aliases.items()) or len(set(aliases.values())) != len(aliases):
        errors.append("display property aliases must be a one-to-one object")
    else:
        for display, formal in aliases.items():
            if not isinstance(display, str) or not isinstance(formal, str) or display in selected or formal not in selected or display.split(".")[0] != formal.split(".")[0]:
                errors.append(f"invalid display property alias: {display}: {formal}")
    if set(layouts) != set(catalog):
        errors.append(
            f"resource layout coverage mismatch: unclassified={sorted(set(catalog) - set(layouts))}, "
            f"stale={sorted(set(layouts) - set(catalog))}"
        )
    for name, rule in layouts.items():
        if rule == "independent":
            continue
        required = {"parent", "parentProperty", "maxCount", "identityProperty"}
        if not isinstance(rule, dict) or set(rule) not in (required, required | {"display"}):
            errors.append(f"invalid resource layout decision: {name}")
            continue
        if "display" in rule and (
            rule["display"] != "rule-table"
            or name not in {"EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}
            or rule != {"parent": "EC2.SecurityGroup", "parentProperty": "GroupId", "maxCount": None, "identityProperty": "Id", "display": "rule-table"}
        ):
            errors.append(f"invalid Security Group rule table layout: {name}")
        parent = rule["parent"]
        if not isinstance(parent, str) or parent not in catalog or layouts.get(parent) != "independent":
            errors.append(f"grouped parent must be an independent catalog resource: {name}: {parent}")
        if f'{name}.{rule["parentProperty"]}' not in catalog.get(name, set()):
            errors.append(f"grouped parent property is absent from catalog: {name}")
        identity = rule["identityProperty"]
        if identity is not None and f"{name}.{identity}" not in catalog.get(name, set()):
            errors.append(f"grouped identity property is absent from catalog: {name}")
        if rule["maxCount"] != 1 and not (rule["maxCount"] is None and identity):
            errors.append(f"multiple grouped children require an identity property: {name}")
    return errors


def catalog_order_errors(resource_type: str, rows: list[list[str]], root: Path | None = None) -> list[str]:
    """Compare visible rows with the selection-list order, within each resource."""
    root = root or Path(__file__).resolve().parents[2]
    material = next((path for path in design_material_files(root) if path.stem.replace("_", ".", 1) == resource_type), None)
    if material is None:
        return [f"display order catalog is missing: {resource_type}"]
    order = {line.partition("=")[0]: number for number, line in enumerate(material.read_text(encoding="utf-8").splitlines())}
    if resource_type == "CodeBuild.Project":
        subnets, groups = "CodeBuild.Project.VpcConfig.Subnets", "CodeBuild.Project.VpcConfig.SecurityGroupIds"
        order[subnets], order[groups] = order[groups], order[subnets]
    previous = -1
    seen: set[str] = set()
    previous_property = ""
    for row in rows:
        prop = row[1] if row[1].startswith(resource_type + ".") else resource_type + "." + row[1]
        if prop not in order:
            continue  # Design-only fields and other grouped resources are separate.
        rank = order[prop]
        if rank < previous:
            array = prop.split("[]", 1)[0] + "[]" if "[]" in prop else ""
            if not array or prop not in seen or not previous_property.startswith(array + "."):
                return [f"resource rows must follow catalog file order: {resource_type}: {prop}"]
            # A repeated field starts the next array element, not a global sort.
            seen = {item for item in seen if not item.startswith(array + ".")}
        seen.add(prop)
        previous = rank
        previous_property = prop
    return []


def formal_property(display: str, resource_type: str) -> str:
    """Restore the resource type omitted from a detail table's Property column."""
    if display in DISPLAY_PROPERTY_ALIASES or any(
        display.startswith(name + ".") for name in LAYOUTS
    ):
        return display
    return resource_type + "." + display if resource_type else display


def pipeline_display_rows(rows: list[list[str]]) -> list[list[str]]:
    """Restore indexed stages/actions and key rows to the selected catalog fields."""
    stages: dict[int, dict[int, bool]] = {}
    configurations: dict[tuple[int, int], dict[str, str]] = {}
    configuration_rows: dict[tuple[int, int], list[str]] = {}
    fields: set[tuple[int, int, str]] = set()
    result = []
    previous_stage = previous_action = 0
    previous_configuration = None
    for row in rows:
        display = row[1].removeprefix("CodePipeline.Pipeline.")
        if not display.startswith("Stages"):
            result.append(row)
            previous_configuration = None
            continue
        match = CODEPIPELINE_STAGE.fullmatch(display)
        if not match:
            raise ValueError("CodePipeline stages must use Stages[N], starting at 1")
        stage = int(match.group(1))
        if stage != previous_stage:
            if stage != len(stages) + 1:
                raise ValueError("CodePipeline stage indexes must be sequential and contiguous")
            stages[stage] = {}
            previous_stage, previous_action = stage, 0
        is_action = display.startswith(f"Stages[{stage}].Actions")
        action = int(match.group(2) or 1) if is_action else 0
        field = match.group(3)
        if is_action and field.startswith("Actions"):
            raise ValueError("CodePipeline actions must use Actions or Actions[N], without []")
        identity_field = stage, action, field
        if "[]" not in field and identity_field in fields:
            raise ValueError(f"duplicate CodePipeline stage/action field: {display}")
        fields.add(identity_field)
        if is_action and action != previous_action:
            if action != len(stages[stage]) + 1:
                raise ValueError("CodePipeline action indexes must be sequential and contiguous per stage")
            stages[stage][action] = bool(match.group(2))
            previous_action = action
        elif is_action and stages[stage][action] != bool(match.group(2)):
            raise ValueError("CodePipeline action index spelling must be consistent")
        row = row.copy()
        row[1] = "CodePipeline.Pipeline.Stages[]." + ("Actions[]." if is_action else "") + field
        if not is_action or not field.startswith("Configuration"):
            result.append(row)
            previous_configuration = None
            continue
        key = field.removeprefix("Configuration.")
        if not field.startswith("Configuration.") or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError("CodePipeline Configuration must use Configuration.<Key> display rows")
        identity = stage, action
        if identity in configurations and previous_configuration != identity:
            raise ValueError("CodePipeline Configuration key rows must be contiguous per action")
        values = configurations.setdefault(identity, {})
        if key in values:
            raise ValueError(f"duplicate CodePipeline Configuration key: {key}")
        value = row[2]
        linked = re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", value)
        if not linked:
            if len(value) >= 2 and value[0] == value[-1] == "`":
                value = value[1:-1]
            if value.startswith(("{", "[", "!")) or "Fn::" in value or "](" in value or "\n" in value:
                raise ValueError("CodePipeline Configuration value must be a literal or a resource link, without CFN intrinsics")
        values[key] = value
        if identity not in configuration_rows:
            row[1] = CODEPIPELINE_CONFIGURATION
            configuration_rows[identity] = row
            result.append(row)
            row[3] = f"{key}: {row[3]}"
        else:
            configuration_rows[identity][3] += f" / {key}: {row[3]}"
        configuration_rows[identity][2] = "`" + json.dumps(values, ensure_ascii=False, separators=(",", ":")) + "`"
        previous_configuration = identity
    for actions in stages.values():
        if len(actions) > 1 and not all(actions.values()):
            raise ValueError("CodePipeline multiple actions must use Actions[N]")
        if len(actions) == 1 and any(actions.values()):
            raise ValueError("CodePipeline single action must use Actions without an index")
    return result


def expanded_display_rows(lines: list[str]) -> list[str]:
    """Restore compact resource rows to their catalog properties."""
    result = []
    index = 0
    resource_type = ""
    while index < len(lines):
        if lines[index] != HEADER or index + 1 >= len(lines) or lines[index + 1] != ALIGNMENT:
            if heading := RESOURCE.fullmatch(lines[index]):
                resource_type = heading.group(1)
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
        codebuild_vpc_counts = {"Subnets": 0, "SecurityGroupIds": 0}
        guardduty_names = set()
        cloudtrail_count = 0
        changed = False
        normalized = False
        kind = ""
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError("resource table row must have four cells")
            row_numbers.append(cells[0])
            display_property = cells[1]
            prop = formal_property(cells[1], resource_type)
            if prop == "Config.ConfigurationRecorder.RoleARN":
                raise ValueError("ConfigurationRecorder RoleARN must use RoleName display")
            if DISPLAY_PROPERTY_ALIASES.get(prop, prop) in RESOURCE_REFERENCE_PROPERTIES:
                if not is_service_role_reference(prop, cells[2]) and not re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2]):
                    raise ValueError(f"{prop} must be a resource link")
            if prop in HIDDEN_PROPERTIES:
                raise ValueError(f"property must not be displayed: {prop}")
            if prop != cells[1]:
                normalized = True
                cells[1] = prop
            if prop.startswith(CODEBUILD_FORMAL_VARIABLE):
                raise ValueError("CodeBuild environment variables must use Variables.<Name> display rows")
            if resource_type == "CodeBuild.Project" and prop in CODEBUILD_VPC_PROPERTIES:
                raise ValueError("CodeBuild VpcConfig Subnets/SecurityGroupIds must use one linked resource per display row")
            if prop in {GUARDDUTY_FORMAL_FEATURE + "Name", GUARDDUTY_FORMAL_FEATURE + "Status"}:
                raise ValueError("GuardDuty Features Name/Status must use Features.<Name> display rows")
            if resource_type == "CloudTrail.Trail" and prop.startswith(CLOUDTRAIL_FORMAL_DATA_RESOURCE):
                raise ValueError("CloudTrail DataResources Type/Values must use one target per display row")
            if prop.startswith(CODEBUILD_VARIABLE):
                changed = True
                kind = "CodeBuild environment variable"
                name = prop.removeprefix(CODEBUILD_VARIABLE)
                if not re.fullmatch(r"[^.\s|]+", name) or name in codebuild_names:
                    raise ValueError(f"invalid or duplicate CodeBuild environment variable name: {name}")
                codebuild_names.add(name)
                raw = cells[2]
                if len(raw) >= 2 and raw[0] == raw[-1] == "`":
                    raw = raw[1:-1]
                marker = CODEBUILD_VARIABLE_TYPE.match(cells[3])
                linked = re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2])
                if cells[2].startswith("[") and "](" in cells[2] and not linked:
                    raise ValueError(f"CodeBuild resource variable must use a single resource anchor link: {name}")
                if "<!-- codebuild-variable-type:" in cells[3] and not marker:
                    raise ValueError(f"invalid CodeBuild environment variable Type marker: {name}")
                if bool(marker) != bool(linked):
                    raise ValueError(f"CodeBuild resource variable requires a link and Type marker: {name}")
                if re.match(r"^(PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER):", raw):
                    raise ValueError(f"CodeBuild environment variable must omit the Type prefix: {name}")
                variable_type = marker.group(1) if marker else "PLAINTEXT"
                comment = cells[3][marker.end():] if marker else cells[3]
                value = cells[2] if linked else f"`{raw}`"
                for field, field_value in (("Name", f"`{name}`"), ("Type", f"`{variable_type}`"), ("Value", value)):
                    rows.append([cells[0], CODEBUILD_FORMAL_VARIABLE + field, field_value, comment])
            elif resource_type == "CodeBuild.Project" and display_property.startswith(("VpcConfig.Subnets[", "VpcConfig.SecurityGroupIds[")):
                match = CODEBUILD_VPC_ITEM.fullmatch(display_property)
                if not match or int(match.group(2)) != codebuild_vpc_counts[match.group(1)] + 1:
                    raise ValueError("CodeBuild VpcConfig display indexes must start at 1 and be sequential per property")
                if not re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2]):
                    raise ValueError("CodeBuild VpcConfig value must be a resource link")
                codebuild_vpc_counts[match.group(1)] += 1
                changed = True
                kind = "CodeBuild VpcConfig"
                cells[1] = "CodeBuild.Project.VpcConfig." + match.group(1)
                rows.append(cells)
            elif prop.startswith(GUARDDUTY_FEATURE):
                changed = True
                kind = "GuardDuty Feature"
                name = prop.removeprefix(GUARDDUTY_FEATURE)
                if not re.fullmatch(r"[^.\s|]+", name) or name in guardduty_names:
                    raise ValueError(f"invalid or duplicate GuardDuty Feature name: {name}")
                guardduty_names.add(name)
                status = cells[2]
                if len(status) >= 2 and status[0] == status[-1] == "`":
                    status = status[1:-1]
                for field, field_value in (("Name", name), ("Status", status)):
                    rows.append([cells[0], GUARDDUTY_FORMAL_FEATURE + field, f"`{field_value}`", cells[3]])
            elif resource_type == "CloudTrail.Trail" and display_property.startswith("EventSelectors.DataResources["):
                match = CLOUDTRAIL_DATA_RESOURCE.fullmatch(display_property)
                if not match or int(match.group(1)) != cloudtrail_count + 1:
                    raise ValueError("CloudTrail DataResources display indexes must start at 1 and be sequential")
                resource_value = cells[2]
                if match.group(2) == "S3" and resource_value == "`All current and future S3 buckets`":
                    resource_value = '`["arn:aws:s3"]`'
                elif not re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", resource_value):
                    raise ValueError("CloudTrail DataResources value must be a resource link or, for S3, `All current and future S3 buckets`")
                cloudtrail_count += 1
                changed = True
                kind = "CloudTrail DataResources"
                for field, value in (("Type", f"`{CLOUDTRAIL_RESOURCE_TYPES[match.group(2)]}`"), ("Values", resource_value)):
                    rows.append([cells[0], CLOUDTRAIL_FORMAL_DATA_RESOURCE + field, value, cells[3]])
            else:
                rows.append(cells)
            index += 1
        if resource_type == "CodePipeline.Pipeline":
            rows = pipeline_display_rows(rows)
            changed = True
            kind = "CodePipeline"
        if changed:
            if row_numbers != [str(number) for number in range(1, len(row_numbers) + 1)]:
                raise ValueError(f"{kind} table numbering error")
            result.extend((HEADER, ALIGNMENT))
            result.extend("| " + " | ".join([str(number), *cells[1:]]) + " |" for number, cells in enumerate(rows, 1))
        elif normalized:
            result.extend((HEADER, ALIGNMENT))
            result.extend("| " + " | ".join(cells) + " |" for cells in rows)
        else:
            result.extend(lines[start:index])
    return result


def expanded_design(lines: list[str], *, normalized: bool = False) -> tuple[list[str], dict[str, dict]]:
    """Expand identified children for model/link resolution; keep S3's flat model.

    Child anchors and logical IDs live in the first row's comment. Visible tables
    stay grouped; this in-memory expansion never rewrites the source Markdown.
    """
    identities = resource_logical_ids(lines)
    lines = [line for line in lines if not RESOURCE_ID.fullmatch(line)]
    if not normalized:
        lines = security_group_table_lines(lines)
    lines = expanded_display_rows(lines)
    result: list[str] = []
    children: dict[str, dict] = {}
    parent_type = parent_id = parent_anchor = pending_anchor = service_id = ""
    child_names: set[tuple[str, str]] = set()
    logical_ids: set[str] = set()
    grouped_tables: set[str] = set()
    anchors = ANCHOR.findall("\n".join(lines))
    if len(anchors) != len(set(anchors)):
        raise ValueError("duplicate resource anchor")
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("- Design service ID: "):
            service_id = line.split("`")[1]
        if anchor := ANCHOR.fullmatch(line):
            pending_anchor = anchor.group(1)
        if heading := RESOURCE.fullmatch(line):
            parent_type, parent_id = heading.groups()
            parent_id = identities.get(heading.groups(), parent_id)
            parent_anchor = pending_anchor
            pending_anchor = ""
            if parent_id in logical_ids:
                raise ValueError(f"duplicate resource logical ID: {parent_id}")
            logical_ids.add(parent_id)
        elif line.startswith("#"):
            parent_type = ""
        if line != HEADER:
            if "<!-- logical-id:" in line:
                raise ValueError("child identity marker must be in a resource table row")
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
            cells[1] = prop = DISPLAY_PROPERTY_ALIASES.get(cells[1], cells[1])
            resource_type = ".".join(prop.split(".")[:2])
            rule = GROUPED.get(resource_type)
            marker = CHILD.match(cells[3])
            if rule and resource_type != parent_type:
                if parent_type != rule["parent"]:
                    raise ValueError(f"grouped resource has wrong parent: {resource_type}: {parent_type}")
                grouped_started = True
                if prop == f'{resource_type}.{rule["parentProperty"]}':
                    raise ValueError(f"{prop} must be omitted from its enclosing {parent_type} table")
                identity = rule["identityProperty"]
                if identity:
                    if prop == f"{resource_type}.{identity}":
                        if not marker:
                            raise ValueError(f"grouped identity row requires anchor and logical ID: {prop}")
                        anchor, logical_id = marker.groups()
                        name = cells[2].strip("`")
                        valid_anchors = {f"{service_id}-{logical_id.lower()}", resource_anchor(service_id, name)}
                        if anchor not in valid_anchors or logical_id in logical_ids:
                            raise ValueError(f"invalid or duplicate grouped logical ID/anchor: {logical_id}")
                        logical_ids.add(logical_id)
                        pending_rule = rule.get("display") == "rule-table" and name == "PENDING_DEPLOY"
                        if not pending_rule and (resource_type, name) in child_names:
                            raise ValueError(f"duplicate grouped identity value: {resource_type}: {name}")
                        if not pending_rule:
                            child_names.add((resource_type, name))
                        active_child = {
                            "resourceType": resource_type, "logicalId": logical_id, "anchor": anchor,
                            "parentLogicalId": parent_id, "parentAnchor": parent_anchor,
                            "parentProperty": f'{resource_type}.{rule["parentProperty"]}', "rows": [],
                        }
                        children[anchor] = active_child
                        table_children.append(active_child)
                        counts[resource_type] = counts.get(resource_type, 0) + 1
                    elif marker or not active_child or active_child["resourceType"] != resource_type:
                        raise ValueError(f"grouped child rows must start with {resource_type}.{identity}")
                    if marker:
                        cells[3] = cells[3][marker.end():]
                    active_child["rows"].append(cells)
                else:
                    if marker or "<!-- logical-id:" in cells[3]:
                        raise ValueError("unidentified grouped child must not have an identity marker")
                    if prop in single_properties:
                        raise ValueError(f"duplicate property in single grouped child: {prop}")
                    single_properties.add(prop)
                    counts[resource_type] = 1
                    parent_rows.append(cells)
            else:
                if marker or "<!-- logical-id:" in cells[3]:
                    raise ValueError("child identity marker is only allowed on a grouped identity row")
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
            result.extend(("", f'<a id="{child["anchor"]}"></a>',
                           f'### {child["resourceType"]}: {child["logicalId"]}', "", HEADER, ALIGNMENT))
            for number, cells in enumerate(child["rows"], 1):
                result.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
    return result, children
