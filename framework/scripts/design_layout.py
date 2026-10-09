"""Shared display relationships and identified children in resource tables."""

from __future__ import annotations

import json
import re
from pathlib import Path
from array_display import restored_rows
from ec2_display import ec2_formal_rows
from service_rows import (codebuild_formal_rows, pipeline_display_rows, restored_glue_argument_rows,
    CODEBUILD_VARIABLE, CODEBUILD_FORMAL_VARIABLE)
from model_core import positive_integer

from design_catalog import design_material_files
from validation_cache import memoized
from security_group_tables import security_group_table_lines


LAYOUT_PATH = Path(__file__).resolve().parents[1] / "rules" / "resource-layout.json"
LAYOUTS = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
RESOURCE_PROPERTY_PREFIXES = tuple(name + "." for name in LAYOUTS)
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
ROTATION_SCHEDULE = "SecretsManager.RotationSchedule"
LAMBDA_PERMISSION = "Lambda.Permission"
PERMISSION_METADATA = re.compile(r'^<!-- lambda-permission: (.+?) -->\s*')
CHILD_NAME = re.compile(r'^([^<>|`\n：]+)：')
HEADER = "| No. | Property | Value | Source / Comment |"
ALIGNMENT = "| ---: | --- | --- | --- |"
CODEBUILD_VPC_PROPERTIES = {"CodeBuild.Project.VpcConfig.Subnets", "CodeBuild.Project.VpcConfig.SecurityGroupIds"}
SUBNET_LIST_PROPERTIES = {
    "ApiGatewayV2.VpcLink.SubnetIds[]",
    "CodeBuild.Project.VpcConfig.Subnets",
    "EC2.TransitGatewayVpcAttachment.SubnetIds",
    "EC2.VPCEndpoint.SubnetIds",
    "ECS.CapacityProvider.ManagedInstancesProvider.InstanceLaunchTemplate.NetworkConfiguration.Subnets[]",
    "ECS.Service.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
    "ElasticLoadBalancingV2.LoadBalancer.Subnets[]",
    "Lambda.Function.VpcConfig.SubnetIds",
    "MWAA.Environment.NetworkConfiguration.SubnetIds",
    "QuickSight.VPCConnection.SubnetIds",
    "RDS.DBProxy.VpcSubnetIds[]",
    "RDS.DBProxyEndpoint.VpcSubnetIds[]",
    "RDS.DBSubnetGroup.SubnetIds[]",
    "SageMaker.Domain.SubnetIds[]",
    "Scheduler.Schedule.Target.EcsParameters.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
    "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds",
}
LINKED_LIST_PROPERTIES = dict.fromkeys(SUBNET_LIST_PROPERTIES, "EC2.Subnet") | {
    "CodeBuild.Project.VpcConfig.SecurityGroupIds": "EC2.SecurityGroup",
}
SUBNET_LIST_SOURCE = re.compile(r'^<!-- subnet-list-source: ("(?:[^"\\]|\\.)*") --> ')
GUARDDUTY_FEATURE = "GuardDuty.Detector.Features."
GUARDDUTY_FORMAL_FEATURE = "GuardDuty.Detector.Features[]."
CLOUDTRAIL_DATA_RESOURCE = re.compile(r"^EventSelectors\.DataResources\[([1-9]\d*)\]\.(S3|Lambda)$")
CLOUDTRAIL_RESOURCE_TYPES = {"S3": "AWS::S3::Object", "Lambda": "AWS::Lambda::Function"}
CLOUDTRAIL_FORMAL_DATA_RESOURCE = "CloudTrail.Trail.EventSelectors[].DataResources[]."
STACK_DESIGN = "cloudformation-stacks.md"
STACK_HEADER = "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |"
SECURITY_GROUP_TYPES = {"EC2.SecurityGroup", "EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}
RESOURCE_REFERENCE_PROPERTIES = {
    "Config.ConfigurationRecorder.RoleARN": ("IAM.Role", "RoleName"),
    "KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN": ("KMS.Key", "KeyId"),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN": ("S3.Bucket", "BucketName"),
    "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN": ("IAM.Role", "RoleName"),
    # DataSource permissions resolve this Group identity link to its transient Arn output.
    "QuickSight.DataSource.Permissions[].Principal": ("QuickSight.Group", "GroupName"),
}
HIDDEN_PROPERTIES = {
    "CodeCommit.Repository.RepositoryId",
    # These Id attributes return ARNs, not persistable observed identifiers.
    "SecretsManager.Secret.Id",
    "SecretsManager.RotationSchedule.Id",
    "QuickSight.Group.Arn",
}
REQUIRED_NAME_TAG_TYPES = {"EC2.VPCEndpoint", "EC2.Instance"}
RESOURCE_MODE = re.compile(r"^<!-- resource-mode: ([a-z0-9_.-]+) (CREATE|IMPORT) -->$")


def is_service_role_reference(prop: str, value: str) -> bool:
    reference = RESOURCE_REFERENCE_PROPERTIES.get(DISPLAY_PROPERTY_ALIASES.get(prop, prop))
    return bool(reference and reference[0] == "IAM.Role" and re.fullmatch(
        r"(`?)AWSService[A-Za-z0-9_+=,.@-]{1,54}\1", value
    ))


def resource_anchor(service_id: str, name: str, resource_type: str = "") -> str:
    """Use the displayed resource name as the navigation identity."""
    kind = {"Config.ConfigurationRecorder": "configuration-recorder",
            "Config.DeliveryChannel": "delivery-channel"}.get(resource_type)
    prefix = f"{service_id}-{kind}" if kind else service_id
    return prefix + "-" + re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-")


def resource_heading_lines(lines: list[str]) -> list[str]:
    """Normalize type-only detail headings; overview type headings stay unchanged."""
    result = []
    details = False
    for line in lines:
        if line.startswith("## "):
            details = line == DETAILS_HEADING
        if details and re.fullmatch(r"### [A-Za-z0-9]+\.[A-Za-z0-9]+", line):
            line += ": " + line[4:]
        result.append(line)
    return result


def resource_logical_ids(lines: list[str]) -> dict[tuple[str, str], str]:
    """Read hidden IDs before anchors without changing displayed headings."""
    identities = {}
    pending = ""
    anchored = False
    for line in resource_heading_lines(lines):
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
    if resource_type == "SSM.Association":
        return ["AssociationName"]  # Name identifies the referenced SSM document.
    kind = resource_type.split(".")[1]
    names = [kind + "Input.Name", kind + "Config.Name", "Name", "name", kind + "Name", kind + "Identifier", kind + "." + kind + "Name"]
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
    from model_files import read_model
    from model_core import properties
    try:
        relative = path.relative_to(root / "docs/designs")
    except ValueError:
        return None
    source = (root / "model" / relative).with_suffix(".properties")
    return properties(read_model(source)) if source.is_file() else None


def resource_modes(lines: list[str], values: dict[str, str] | None = None) -> dict[str, str]:
    """Use model modes for validation; read legacy comments only without a model."""
    if values is not None:
        from model_core import entries
        return {resource["anchor"]: resource_mode(resource)
                for _, resource in entries(values, "desired.resource.") if "resourceMode" in resource}
    modes = {}
    anchors = set(ANCHOR.findall("\n".join(lines)))
    for line in lines:
        if not line.startswith("<!-- resource-mode:"):
            continue
        match = RESOURCE_MODE.fullmatch(line)
        if not match or match[1] in modes or match[1] not in anchors:
            raise ValueError(f"invalid, duplicate or orphan resource mode metadata: {line}")
        modes[match[1]] = match[2]
    return modes


def resource_has_name_property(root: Path, resource_type: str, mode: str = "CREATE") -> bool:
    """Check the catalog, rather than treating an omitted optional name as nameless."""
    if resource_type in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"} | REQUIRED_NAME_TAG_TYPES:
        return mode != "IMPORT"  # Only CREATE requires a Name tag.
    names = set(resource_name_fields(resource_type))
    return any(line.partition("=")[0].removeprefix(resource_type + ".") in names
               and line.partition("=")[2] != "IDENTIFIER_OUTPUT"
               for path in design_material_files(root)
               if path.stem.replace("_", ".", 1) == resource_type
               for line in path.read_text(encoding="utf-8").splitlines())


def resource_display_name(resource_type: str, rows: list[list[str]], selected_label: str | None = None, mode: str = "CREATE") -> str | None:
    """Find a selected root name; never invent an AWS name from an internal ID."""
    if resource_type == "KMS.Key":
        aliases = [row[2].strip("`\"") for row in rows if row[1] == "KMS.Alias.AliasName"]
        if aliases:
            if any(not alias.startswith("alias/") or not alias.removeprefix("alias/").strip() for alias in aliases):
                raise ValueError("KMS Key display requires a confirmed AliasName beginning with alias/")
            names = {alias.removeprefix("alias/") for alias in aliases}
            if len(names) == 1:
                return next(iter(names))
            if selected_label in names:
                return selected_label
            raise ValueError("KMS Key has multiple aliases; select an alias without alias/ in display label")
    fields = {row[1].removeprefix(resource_type + "."): row[2].strip("`\"") for row in rows}
    if resource_type in REQUIRED_NAME_TAG_TYPES:
        if mode == "IMPORT":
            paths = [row[1].removeprefix(resource_type + ".") for row in rows]
            for index, path in enumerate(paths):
                if path == "Tags[].Key" and paths[index + 1:index + 2] != ["Tags[].Value"]:
                    raise ValueError(f"{resource_type} tag requires the corresponding Tags[].Value")
                if path == "Tags[].Value" and (index == 0 or paths[index - 1] != "Tags[].Key"):
                    raise ValueError(f"{resource_type} tag requires the corresponding Tags[].Key")
        keys = [index for index, row in enumerate(rows)
                if row[1].removeprefix(resource_type + ".") == "Tags[].Key"
                and row[2].strip("`\"") == "Name"]
        if mode == "IMPORT" and not keys and "Name" not in fields:
            return None
        if "Name" in fields or len(keys) != 1:
            raise ValueError(f"{resource_type} requires exactly one Tags[].Key=Name; design-only .Name is forbidden")
        index = keys[0] + 1
        if index >= len(rows) or rows[index][1].removeprefix(resource_type + ".") != "Tags[].Value":
            raise ValueError(f"{resource_type} Name tag requires the corresponding Tags[].Value")
        value = rows[index][2].strip("`\"")
        if not value.strip() or value.strip().lower() in {
            "unset", "pending", "pending_deploy", "tbd", "n/a", "none", "not-used", "not used", "unused", "未使用", "未確定",
        } or value.startswith("[") or "{{" in value:
            raise ValueError(f"{resource_type} Name tag value must be confirmed and non-empty")
        return value
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


def stack_deployment_policy(path: Path) -> int:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(lines) < 2 or lines[0] != "# CloudFormation stack 詳細設計":
        raise ValueError("invalid CloudFormation stack design header; explicit DeployOrder migration required")
    match = re.fullmatch(r"<!-- max-concurrent-stacks: (.+) -->", lines[1])
    if not match:
        raise ValueError("invalid CloudFormation deployment policy")
    return positive_integer(match.group(1), "MaxConcurrentStacks")


def stack_design(path: Path) -> list[dict[str, str]]:
    """Read a target's stack detailed design."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line and not line.startswith(("<!-- templateBucket:", "<!-- templateKeyPrefix:"))]
    stack_deployment_policy(path)
    if lines[2:5] != [
        "## Stack一覧", STACK_HEADER,
        "| ---: | ---: | --- | --- | --- | --- |",
    ]:
        raise ValueError("invalid CloudFormation stack design header")
    result = []
    end = next((index for index in range(5, len(lines)) if lines[index].startswith("## ")), len(lines))
    for line in lines[5:end]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not line.startswith("|") or not line.endswith("|") or len(cells) != 6 or not all(cells):
            raise ValueError(f"invalid CloudFormation stack design row: {line}")
        if cells[0] != str(len(result) + 1):
            raise ValueError(f"CloudFormation stack design No. must be sequential: {line}")
        positive_integer(cells[1], "DeployOrder")
        result.append(dict(zip(("deployOrder", "name", "template", "parameters", "comment"), cells[1:])))
    if not result:
        raise ValueError("CloudFormation stack design table must not be empty")
    stack_delivery(path)
    if "## Resource対応" in lines:
        raise ValueError("stack resource mapping table is obsolete; use resource cfn-logicalId")
    return result


def stack_delivery(path: Path) -> dict[str, str]:
    """Read hidden template settings and artifact tables, including old stack views."""
    from model_core import ARTIFACT_FIELDS
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    result = {}
    for line in lines:
        if line.startswith(("<!-- templateBucket:", "<!-- templateKeyPrefix:")):
            match = re.fullmatch(r"<!-- (templateBucket|templateKeyPrefix): (.+) -->", line)
            if not match:
                raise ValueError("invalid S3 delivery setting comment")
            key = "desired.deployment." + match.group(1)
            if key in result:
                raise ValueError("duplicate S3 delivery setting")
            result[key] = match.group(2)
    if "## S3配置" not in lines:
        return result
    lines = lines[lines.index("## S3配置") + 1:]
    lines = lines[:next((index for index, line in enumerate(lines) if line.startswith("## ")), len(lines))]
    if lines[:2] == ["| Property | Value |", "| --- | --- |"]:
        index = 2
    elif lines[:1] == ["### 配置ファイル"]:
        index = 0
    else:
        raise ValueError("invalid S3 delivery settings header")
    while index < len(lines) and lines[index] != "### 配置ファイル":
        cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
        if not lines[index].startswith("|") or not lines[index].endswith("|") or len(cells) != 2 or cells[0] not in {"TemplateBucket", "TemplateKeyPrefix"} or not cells[1]:
            raise ValueError("invalid S3 delivery setting")
        key = "desired.deployment." + cells[0][0].lower() + cells[0][1:]
        if key in result:
            raise ValueError("duplicate S3 delivery setting")
        result[key] = cells[1]
        index += 1
    if index < len(lines):
        if lines[index:index + 3] != ["### 配置ファイル",
                "| No. | StackName | Resource | Property | Source | Bucket | KeyPrefix |",
                "| ---: | --- | --- | --- | --- | --- | --- |"]:
            raise ValueError("invalid S3 artifact table header")
        rows = lines[index + 3:]
        if not rows:
            raise ValueError("empty S3 artifact table")
        for number, line in enumerate(rows, 1):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not line.startswith("|") or not line.endswith("|") or len(cells) != 7 or cells[0] != str(number) or not all(cells):
                raise ValueError("invalid S3 artifact table row")
            result.update({f"desired.artifact.{number:03d}.{field}": value
                           for field, value in zip(ARTIFACT_FIELDS, cells[1:])})
    if not result:
        raise ValueError("empty S3 delivery settings")
    return result


def resource_identity_metadata(lines, *, values=None, import_cfn_ids=False):
    """Use model entry identities; legacy comments remain explicit-import input."""
    if values is not None:
        from model_core import entries
        return ({resource["anchor"]: identity for identity, resource in entries(values, "desired.resource.")
                 if f"desired.resource.{identity}.logicalId" not in values}, {})
    anchors = set(ANCHOR.findall("\n".join(lines)))
    result = {"resource-entry": {}, "cfn-logical-id": {}}
    for line in lines:
        for name, metadata in result.items():
            if name == "cfn-logical-id" and not import_cfn_ids:
                continue
            if not line.startswith("<!-- " + name + ":"):
                continue
            match = re.fullmatch(r"<!-- " + name + r": (\S+) (\S+) -->", line)
            if not match or match[1] not in anchors or match[1] in metadata:
                raise ValueError(f"invalid/duplicate {name} metadata")
            anchor, value = match.groups()
            if name == "resource-entry":
                if not re.fullmatch(r"[0-9]{3}", value) or value in metadata.values():
                    raise ValueError("invalid/duplicate resource entry number")
            else:
                from iac_values import cfn_resource_identity
                cfn_resource_identity(value)
            metadata[anchor] = value
    return result["resource-entry"], result["cfn-logical-id"]


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


@memoized
def catalog_property_order(root: Path, resource_type: str):
    material = next((path for path in design_material_files(root) if path.stem.replace("_", ".", 1) == resource_type), None)
    return None if material is None else {line.partition("=")[0]: number for number, line in enumerate(material.read_text(encoding="utf-8").splitlines())}


def catalog_order_errors(resource_type: str, rows: list[list[str]], root: Path | None = None) -> list[str]:
    """Compare visible rows with the selection-list order, within each resource."""
    root = root or Path(__file__).resolve().parents[2]
    cached_order = catalog_property_order(root, resource_type)
    if cached_order is None:
        return [f"display order catalog is missing: {resource_type}"]
    order = dict(cached_order)
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
    if resource_type == "Lambda.Function" and display.startswith("Permission."):
        return "Lambda." + display
    if display in DISPLAY_PROPERTY_ALIASES or display.startswith(RESOURCE_PROPERTY_PREFIXES):
        return display
    return resource_type + "." + display if resource_type else display


def linked_list_property(display: str, resource_type: str) -> tuple[str, str] | None:
    """Resolve only the final display index; leave enclosing object arrays intact."""
    match = re.fullmatch(r"(.+)\[([^\]]*)\]", display)
    if match:
        base = formal_property(match.group(1), resource_type)
        for prop in LINKED_LIST_PROPERTIES:
            if base == prop.removesuffix("[]"):
                return prop, match.group(2)
    return None


def subnet_list_items(prop: str, value: str) -> list[str]:
    """Split a saved list for display without inferring resource references."""
    raw = value[1:-1] if value.startswith("`") and value.endswith("`") else value
    if prop == "SecretsManager.RotationSchedule.HostedRotationLambda.VpcSubnetIds":
        items = [item.strip() for item in raw.split(",")]
    elif prop.endswith("[]") and not raw.lstrip().startswith(("[", "{")):
        items = [raw]
    else:
        items = json.loads(raw)
    if not isinstance(items, list) or not items or any(
        not isinstance(item, str) or not item.strip() or any(char in item for char in "|\n\r`")
        for item in items
    ):
        raise ValueError(f"{prop}: Subnet list must contain non-empty string elements")
    return [item if re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", item) else f"`{item}`" for item in items]


def permission_rows(rows: list[list[str]]) -> list[list[str]]:
    """Restore hidden permission rows before the shared grouped-child parser."""
    result = []
    index = 0
    order = catalog_property_order(Path(__file__).resolve().parents[2], LAMBDA_PERMISSION)
    while index < len(rows):
        cells = rows[index]
        if not cells[1].startswith(LAMBDA_PERMISSION + "."):
            if "<!-- lambda-permission:" in cells[3]:
                raise ValueError("Lambda Permission metadata must be on Permission.Action")
            result.append(cells)
            index += 1
            continue
        child = CHILD.match(cells[3])
        marker = PERMISSION_METADATA.match(cells[3][child.end():]) if child else None
        if cells[1] != LAMBDA_PERMISSION + ".Action" or not marker:
            raise ValueError("Permission.Action requires complete identity and Lambda Permission metadata")
        try:
            label, hidden = json.loads(marker.group(1))
            if (not isinstance(label, str) or not CHILD_NAME.fullmatch(label + "：") or
                    not isinstance(hidden, list) or len(hidden) != 2 or
                    any(not isinstance(row, list) or len(row) != 3 or
                        any(not isinstance(cell, str) or any(char in cell for char in "|\n\r<>") for cell in row) for row in hidden) or
                    [row[0] for row in hidden] != [LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"]):
                raise ValueError("invalid hidden rows")
        except (ValueError, TypeError) as error:
            raise ValueError("invalid Lambda Permission metadata") from error
        block = [[cells[0], *row] for row in hidden]
        block[0][3] = child.group(0) + label + "：" + block[0][3]
        cells = cells.copy()
        cells[3] = cells[3][child.end() + marker.end():]
        while True:
            if cells[1] not in order or cells[1] in {row[1] for row in block}:
                raise ValueError("invalid or duplicate Lambda Permission property")
            if "<!-- lambda-permission:" in cells[3] or "<!-- logical-id:" in cells[3]:
                raise ValueError("Lambda Permission identity must be on its first Action row")
            block.append(cells)
            index += 1
            if index == len(rows) or not rows[index][1].startswith(LAMBDA_PERMISSION + ".") or CHILD.match(rows[index][3]):
                break
            cells = rows[index]
        visible = block[2:]
        if visible != sorted(visible, key=lambda row: order[row[1]]):
            raise ValueError("Lambda Permission rows must follow catalog file order")
        result += sorted(block, key=lambda row: order[row[1]])
    return result


def expanded_display_rows(lines: list[str]) -> list[str]:
    """Restore compact resource rows to their catalog properties."""
    lines = resource_heading_lines(lines)
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
        linked_list_counts: dict[str, int] = {}
        guardduty_names = set()
        cloudtrail_count = 0
        changed = False
        normalized = False
        kind = ""
        # Generic array markers are removed before service-specific compact rows.
        stop = index
        source_rows = []
        while stop < len(lines) and lines[stop].startswith("|"):
            source_rows.append([cell.strip() for cell in lines[stop].strip("|").split("|")])
            stop += 1
        if any(len(row) != 4 for row in source_rows):
            raise ValueError("resource table row must have four cells")
        restored = restored_glue_argument_rows(restored_rows(source_rows, resource_type), resource_type)
        if restored != source_rows:
            if [row[0] for row in source_rows] != [str(number) for number in range(1, len(source_rows) + 1)]:
                raise ValueError("Array table numbering error")
            lines = [*lines[:index], *("| " + " | ".join([str(number), *row[1:]]) + " |" for number, row in enumerate(restored, 1)), *lines[stop:]]
            changed = True
            kind = "Array"
        while index < len(lines) and lines[index].startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
            if len(cells) != 4:
                raise ValueError("resource table row must have four cells")
            row_numbers.append(cells[0])
            display_property = cells[1]
            if resource_type == "Lambda.Function" and display_property.startswith("Lambda.Permission."):
                raise ValueError("Lambda Permission must use Permission.* display properties")
            if resource_type == "Lambda.Function" and display_property in {"Permission.Id", "Permission.FunctionName"}:
                raise ValueError("Lambda Permission Id and FunctionName must not be displayed")
            prop = formal_property(cells[1], resource_type)
            if "<!-- subnet-list-source:" in cells[3] and not linked_list_property(display_property, resource_type):
                raise ValueError("Subnet list source marker requires an indexed Subnet row")
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
            if prop in LINKED_LIST_PROPERTIES:
                raise ValueError(f"{prop} must use indexed one-resource-per-row display")
            if prop in {GUARDDUTY_FORMAL_FEATURE + "Name", GUARDDUTY_FORMAL_FEATURE + "Status"}:
                raise ValueError("GuardDuty Features Name/Status must use Features.<Name> display rows")
            if resource_type == "CloudTrail.Trail" and prop.startswith(CLOUDTRAIL_FORMAL_DATA_RESOURCE):
                raise ValueError("CloudTrail DataResources Type/Values must use one target per display row")
            if prop.startswith(CODEBUILD_VARIABLE):
                changed = True
                kind = "CodeBuild environment variable"
                rows.extend(codebuild_formal_rows(cells, codebuild_names))
            elif item := linked_list_property(display_property, resource_type):
                list_prop, first_index = item
                expected = linked_list_counts.get(list_prop, 0) + 1
                if not re.fullmatch(r"[1-9][0-9]*", first_index) or int(first_index) != expected:
                    raise ValueError("Subnet/Security Group display indexes must start at 1 and be sequential per property")
                marker = SUBNET_LIST_SOURCE.match(cells[3])
                if "<!-- subnet-list-source:" in cells[3] and not marker:
                    raise ValueError("invalid Subnet list source marker")
                source = json.loads(marker.group(1)) if marker else None
                if source is not None and list_prop in CODEBUILD_VPC_PROPERTIES:
                    raise ValueError("CodeBuild VpcConfig value must be a resource link")
                items = subnet_list_items(list_prop, source) if source is not None else [cells[2]]
                comment = cells[3][marker.end():] if marker else cells[3]
                child = CHILD.match(comment)
                label = CHILD_NAME.match(comment[child.end():]) if child else None
                # Rotation identity metadata occurs only on the first displayed Subnet.
                continuation_comment = comment[child.end() + label.end():] if label and list_prop.startswith(ROTATION_SCHEDULE + ".") else comment
                if source is None and not re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2]):
                    raise ValueError("Subnet/Security Group value must be a resource link")
                for offset, value in enumerate(items):
                    row = cells
                    if offset:
                        row = [cell.strip() for cell in lines[index + offset].strip("|").split("|")] if index + offset < len(lines) else []
                    if len(row) != 4 or linked_list_property(row[1], resource_type) != (list_prop, str(expected + offset)) or row[2] != value or (offset and row[3] != continuation_comment):
                        raise ValueError("Subnet list display differs from its saved source value or comment")
                    if offset:
                        row_numbers.append(row[0])
                linked_list_counts[list_prop] = expected + len(items) - 1
                changed = True
                kind = "Subnet/Security Group list"
                cells[1], cells[2], cells[3] = list_prop, source if source is not None else cells[2], comment
                rows.append(cells)
                index += len(items) - 1
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
        if resource_type == "Lambda.Function" and any(row[1].startswith(LAMBDA_PERMISSION + ".") or "<!-- lambda-permission:" in row[3] for row in rows):
            rows = permission_rows(rows)
            changed = True
            kind = "Lambda Permission"
        if resource_type == "CodePipeline.Pipeline":
            rows = pipeline_display_rows(rows)
            changed = True
            kind = "CodePipeline"
        if resource_type in REQUIRED_NAME_TAG_TYPES:
            rows = ec2_formal_rows(rows, resource_type)
            changed = True
            kind = resource_type
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


def expanded_design(lines: list[str], *, normalized: bool = False,
                    logical_ids: dict[tuple[str, str], str] | None = None) -> tuple[list[str], dict[str, dict]]:
    """Expand identified children for model/link resolution; keep S3's flat model.

    Child anchors and logical IDs live in the first row's comment. Visible tables
    stay grouped; this in-memory expansion never rewrites the source Markdown.
    """
    identities = resource_logical_ids(lines) if logical_ids is None else logical_ids
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
                if prop == f'{resource_type}.{rule["parentProperty"]}' and resource_type not in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                    raise ValueError(f"{prop} must be omitted from its enclosing {parent_type} table")
                identity = rule["identityProperty"]
                if identity:
                    hidden_identity = f"{resource_type}.{identity}" in HIDDEN_PROPERTIES
                    if prop == f"{resource_type}.{identity}" or hidden_identity and marker:
                        if not marker:
                            raise ValueError(f"grouped identity row requires anchor and logical ID: {prop}")
                        anchor, logical_id = marker.groups()
                        name = cells[2].strip("`")
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            label = CHILD_NAME.match(cells[3][marker.end():])
                            if not label or label.group(1).strip() in {"", "UNSET", "PENDING_DEPLOY"}:
                                raise ValueError(f"{resource_type}: {logical_id}: confirmed display name required on {prop}")
                            name = label.group(1)
                        valid_anchors = {f"{service_id}-{logical_id.lower()}", resource_anchor(service_id, name, resource_type)}
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            valid_anchors = {resource_anchor(service_id, name, resource_type)}
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
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            active_child["displayName"] = name
                        children[anchor] = active_child
                        table_children.append(active_child)
                        counts[resource_type] = counts.get(resource_type, 0) + 1
                    elif marker or not active_child or active_child["resourceType"] != resource_type:
                        raise ValueError(f"grouped child rows require anchor and logical ID" if hidden_identity else
                                         f"grouped child rows must start with {resource_type}.{identity}")
                    if marker:
                        cells[3] = cells[3][marker.end():]
                        if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                            cells[3] = cells[3][label.end():]
                    if resource_type in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
                        if any(row[1] == prop for row in active_child["rows"]) and "[]" not in prop:
                            raise ValueError(f"{resource_type}: {active_child['logicalId']}: duplicate property: {prop}")
                        if prop == active_child["parentProperty"]:
                            reference = re.fullmatch(r"\[[^\]]+\]\(#([^)]*)\)", cells[2])
                            if not reference or reference.group(1) != parent_anchor:
                                raise ValueError(f"{resource_type}: {active_child['logicalId']}: {prop} must reference enclosing {parent_type}: {parent_id}")
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
            if child["resourceType"] in {ROTATION_SCHEDULE, LAMBDA_PERMISSION} and not any(row[1] == child["parentProperty"] for row in child["rows"]):
                raise ValueError(f"{child['resourceType']}: {child['logicalId']}: required property missing: {child['parentProperty']}")
            result.extend(("", f'<a id="{child["anchor"]}"></a>',
                           f'### {child["resourceType"]}: {child["logicalId"]}', "", HEADER, ALIGNMENT))
            for number, cells in enumerate(child["rows"], 1):
                result.append("| " + " | ".join([str(number), *cells[1:]]) + " |")
    return result, children
