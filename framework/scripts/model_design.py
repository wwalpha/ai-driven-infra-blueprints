"""Render detailed designs from authoritative service properties."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
import iac_values
from array_display import indexed_rows
from model_references import bound_resource_anchors, deployment_bucket, catalog_outputs, resource_rows, design_target, resource_display_rows
from model_display import display_rows, catalog_display_rows, row_table, sg_tables
from aws_mapping_display import selected_rows
from model_templates import service_source
from model_core import properties, entries, stack_model, deployment_settings, LINK, ARTIFACT_FIELDS

from design_layout import (
    GROUPED,
    HIDDEN_PROPERTIES,
    resource_display_name,
    resource_name_fields,
    resource_anchor,
    resource_has_name_property,
    resource_mode,
    is_import_pending_reference,
    GROUPED_RESOURCE_TYPES,
    IMPLICIT_GROUPED_PROPERTIES,
    ROTATION_SCHEDULE,
    LAMBDA_PERMISSION,
    SUBNET_LIST_SOURCE,
)
from policy_tables import literal, table, unique_object, invalid_constant
from design_catalog import DesignSchemaCatalog, property_paths_with_parents, selected_properties
from validation_cache import input_scope, memoized


NAMING_EXEMPT_PROPERTIES = {
    "Config.ConfigurationRecorder.Name",
    "Config.DeliveryChannel.Name",
    "Glue.Connection.ConnectionInput.Name",
    "Glue.Database.DatabaseInput.Name",
    "Glue.Table.TableInput.Name",
    "GuardDuty.Detector.Name",
    "IAM.ManagedPolicy.ManagedPolicyName",
    "IAM.User.UserName",
    "IAM.InstanceProfile.InstanceProfileName",
    "Route53.HostedZone.Name",
    "Route53.RecordSet.Name",
}


@memoized
def naming_rule_files(root: Path, namespace: str | None = None) -> tuple[Path, ...]:
    """Read the common entry and only explicitly indexed service rules."""
    path = root / "framework/rules/aws-resource-naming.md"
    files = [path]
    for name, reference in re.findall(
        r"^\| `([A-Za-z0-9]+)` \| \[[^\]]+\]\((aws-resource-naming/[A-Za-z0-9]+\.md)\) \|$",
        path.read_text(encoding="utf-8"), re.MULTILINE,
    ):
        if namespace is None or name == namespace:
            files.append(path.parent / reference)
    return tuple(files)


def naming_target_matches(prop: str, targets: set[str], kind: str | None = None) -> bool:
    """Match a Naming Target at its declared root or exact nested property path."""
    normalized = {target.removeprefix(kind + ".") if kind else target for target in targets}
    return prop in normalized


@memoized
def naming_targets(root: Path, namespace: str | None = None) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    for path in naming_rule_files(root, namespace):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) in {5, 6} and cells[2].startswith("`") and re.fullmatch(r"`[^`]+`", cells[4]):
                for kind in re.findall(r"`([^`]+)`", cells[2]):
                    targets.setdefault(kind, set()).add(cells[3].strip("`"))
    return targets


def naming_coverage_errors(root: Path, kind: str, selected: set[str], name_tag: bool = False,
                           mode: str = "CREATE") -> list[str]:
    """Check rule existence without requiring any design values."""
    if mode not in {"CREATE", "IMPORT"}:
        raise ValueError(f"resourceMode must be CREATE or IMPORT: {mode!r}")
    if mode == "IMPORT":
        return []
    targets = naming_targets(root, kind.partition(".")[0])
    expected = selected & set(resource_name_fields(kind))
    expected.update(field for field in selected if naming_target_matches(field, targets.get(kind, set()), kind))
    if name_tag:
        expected.add("Name tag")
    return [f"naming rule missing: {kind}: {field}" for field in sorted(expected)
            if kind + "." + field not in NAMING_EXEMPT_PROPERTIES
            and not naming_target_matches(field, targets.get(kind, set()), kind)]


def design_naming_errors(root: Path, kind: str, mode: str = "CREATE", name_tag: bool = False) -> list[str]:
    """Preflight a selected resource type before asking for design values."""
    # Deployment StackName is a model input, not a catalog resource property.
    selected = {"StackName"} if kind == "CloudFormation.Stack" else set(selected_properties(root, kind))
    if not selected:
        raise ValueError(f"catalog resource type missing: {kind}")
    selected -= {field.removeprefix(kind + ".") for field in catalog_outputs(root, kind)}
    if name_tag and not selected.intersection({"Tags", "Tags[].Key", "HostedZoneTags", "HostedZoneTags[].Key"}):
        raise ValueError(f"Name tag is not selectable: {kind}")
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        selected.add("Name")
    if kind in {"EC2.VPCEndpoint", "EC2.Instance"}:
        name_tag = True
    return naming_coverage_errors(root, kind, selected, name_tag, mode)


def naming_errors(root: Path, kind: str, rows: list[list[str]], mode: str = "CREATE") -> list[str]:
    if kind in {"CodeBuild.Project", "IAM.Role"}:
        field = "RoleName" if kind == "IAM.Role" else "Name"
        names = [row[2].strip("`\"") for row in rows if row[1].removeprefix(kind + ".") == field]
        if len(names) != 1:
            return [f"{kind}.{field} must appear exactly once"]
        value = names[0]
        if not value.strip() or value.strip().lower() in {"unset", "pending", "pending_deploy", "tbd", "n/a", "none", "未確定"} or value.startswith("[") or "{{" in value:
            return [f"{kind}.{field} must be confirmed and non-empty"]
    if mode == "IMPORT":
        return []  # Confirmed actual names above and provider/schema checks remain mandatory.
    outputs = catalog_outputs(root, kind)
    selected = {row[1].removeprefix(kind + ".") for row in rows if kind + "." + row[1].removeprefix(kind + ".") not in outputs}
    tag_rows = [row for row in rows if row[1].removeprefix(kind + ".").startswith(("Tags", "HostedZoneTags"))]
    return naming_coverage_errors(root, kind, selected, resource_display_name(kind, tag_rows) is not None, mode)


def validate_required_properties(values: dict[str, str], root: Path) -> None:
    """Reject missing required model inputs before producing any view or artifact."""
    if entries(values, "desired.stack."):
        stack_model(values)
        return
    catalog = DesignSchemaCatalog(root)
    errors = []
    for identity, resource in entries(values, "desired.resource."):
        resource_mode(resource)
        kind = resource["resourceType"]
        rows = resource_rows(values, identity, kind, root)
        properties = {row[1] for row in rows
                      if (resource_mode(resource) == "IMPORT" and is_import_pending_reference(row[1], row[2]))
                      or literal(row[2]).strip().strip('"').strip().lower()
                      not in {"", "unset", "pending", "pending_deploy", "tbd", "未確定"}}
        if "parentProperty" in resource:
            properties.add(resource["parentProperty"])
        kinds = {kind} | {
            child for child in GROUPED_RESOURCE_TYPES.get(kind, set())
            if any(row[1].startswith(child + ".") for row in rows)
        }
        for schema_kind in sorted(kinds):
            present = property_paths_with_parents({prop.removeprefix(schema_kind + ".") for prop in properties
                                                  if prop.startswith(schema_kind + ".")})
            missing = catalog.required_design_properties(schema_kind) - present - IMPLICIT_GROUPED_PROPERTIES.get(schema_kind, set())
            errors.extend(f"{resource['logicalId']}: required provider schema property missing: {schema_kind}.{prop}"
                          for prop in sorted(missing))
    if errors:
        raise ValueError("\n- ".join(errors))


def validate_kms_policy_accounts(values: dict[str, str], target: dict) -> None:
    """Check local KMS account principals without rewriting explicit external grants."""
    if not target:
        return
    execution = target.get("awsExecutionAccountId", target["awsAccountId"])
    keys = {identity for identity, resource in entries(values, "desired.resource.")
            if resource["resourceType"] == "KMS.Key" and resource_mode(resource) == "CREATE"}
    for identity, row in entries(values, "desired.row."):
        if not any(identity.startswith(key + "-") for key in keys) or row.get("property") != "KMS.Key.KeyPolicy" or "document" not in row:
            continue
        external = set(re.findall(r"\bcross-account:(arn:[A-Za-z0-9_+=,.@:/-]+)(?=$|[\s`])", row.get("comment", "")))
        document = json.loads(row["document"], object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(document, dict):
            raise ValueError(f"KMS.Key.KeyPolicy {identity}: document must be an object")
        statements = document.get("Statement", [])
        for number, statement in enumerate(statements if isinstance(statements, list) else [statements], 1):
            if not isinstance(statement, dict):
                raise ValueError(f"KMS.Key.KeyPolicy {identity} Statement[{number}]: must be an object")
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal", {})
            principals = principal.get("AWS", []) if isinstance(principal, dict) else []
            for arn in principals if isinstance(principals, list) else [principals]:
                match = re.fullmatch(r"arn:[^:]+:iam::([0-9]{12}):(root|role/aws-service-role/macie(?:\.[a-z0-9-]+)?\.amazonaws\.com/AWSServiceRoleForAmazonMacie)", str(arn))
                if match and match[1] != execution and arn not in external:
                    raise ValueError(f"KMS.Key.KeyPolicy {identity} Statement[{number}] Principal.AWS: {arn}: "
                                     f"must use AWS execution account {execution}; explicit cross-account grant requires "
                                     f"cross-account:{arn} in the policy row comment")


def stack_markdown(path, values, root):
    limit, stacks = stack_model(values)
    for _, stack in stacks:
        if errors := naming_errors(root, "CloudFormation.Stack", [["1", "StackName", stack["name"], "名前"]]):
            raise ValueError("; ".join(errors))
    settings, artifacts = deployment_settings(values)
    delivery = []
    if artifacts:
        delivery = ["", "## S3配置", "", "### 配置ファイル", "",
            "| No. | StackName | Resource | Property | Source | Bucket | KeyPrefix |",
            "| ---: | --- | --- | --- | --- | --- | --- |"]
        delivery += ["| " + " | ".join([str(number)] + [artifact[field] for field in ARTIFACT_FIELDS]) + " |"
                     for number, (_, artifact) in enumerate(artifacts, 1)]
    if settings:
        deployment_bucket(settings["templateBucket"], path, root)
    for _, artifact in artifacts:
        deployment_bucket(artifact["bucket"], path, root)
    return "\n".join(["# CloudFormation stack 詳細設計", "",
        f"<!-- max-concurrent-stacks: {limit} -->", "",
        *[f"<!-- {field}: {value} -->" for field, value in settings.items()],
        "## Stack一覧", "", "| No. | Deploy<br>Order | StackName | Template | Parameters | Comment |",
        "| ---: | ---: | --- | --- | --- | --- |", *[
            "| " + " | ".join([str(number), stack["deployOrder"], stack["name"], stack["template"],
                stack["parameters"], values[f"display.stack.{identity}.comment"]]) + " |"
            for number, (identity, stack) in enumerate(stacks, 1)], *delivery]) + "\n"


def validate_resource_identities(path, values, root, resources):
    relative = path.parent.relative_to(root / "docs/designs") if path.is_relative_to(root / "docs/designs") else None
    target = design_target(path, root)
    validate_kms_policy_accounts(values, target)
    stack_source = root / "model" / relative / "cloudformation-stacks.properties" if relative is not None else None
    stack_names = None
    identity_catalog = DesignSchemaCatalog(root)
    for identity, resource in resources:
        if "cfn-logicalId" not in resource:
            if target.get("iacEngine") == "cloudformation" and resource_mode(resource) == "CREATE" and f"desired.resource.{identity}.logicalId" not in values:
                try:
                    cfn_type = identity_catalog.cloudformation_type(resource["resourceType"])
                except ValueError:
                    cfn_type = None  # API-only design resources have no CFn identity.
                if cfn_type:
                    raise ValueError(f"{identity}: cfn-logicalId required for CloudFormation CREATE resource")
            continue
        if target.get("iacEngine") == "terraform":
            raise ValueError(f"{identity}: cfn-logicalId is forbidden for Terraform")
        if resource_mode(resource) != "CREATE":
            raise ValueError(f"{identity}: cfn-logicalId requires CREATE with a formal CFn type")
        identity_catalog.cloudformation_type(resource["resourceType"])
        from import_scope import selected as import_selection, placement_names
        if import_selection(root) is not None and stack_source is not None:
            if stack_names is None:
                stack_names = placement_names(stack_source, {iac_values.cfn_resource_identity(spec['cfn-logicalId'])[0]
                    for _, spec in resources if spec.get('cfn-logicalId')})[0]
            if iac_values.cfn_resource_identity(resource['cfn-logicalId'])[0] not in stack_names:
                raise ValueError(f"{identity}: cfn-logicalId references an undeclared stack")
            continue
        if target.get("iacEngine") == "cloudformation" and (stack_source is None or service_source(stack_source) is None):
            raise ValueError(f"{identity}: cfn-logicalId requires authoritative cloudformation-stacks.properties")
        if stack_source is not None and service_source(stack_source) is not None:
            if stack_names is None:
                from model_files import read_model
                _, stacks = stack_model(properties(read_model(stack_source)))
                from model_references import bound_stack_names
                stack_names = set(bound_stack_names(stack_source)) or {stack["name"] for _, stack in stacks}
            if iac_values.cfn_resource_identity(resource["cfn-logicalId"])[0] not in stack_names:
                raise ValueError(f"{identity}: cfn-logicalId references an undeclared stack")


def resource_presentation(values, identity, resource, root):
    kind = resource['resourceType']
    rows = catalog_display_rows(resource_rows(values, identity, kind, root), kind, root)
    rule_table = GROUPED.get(kind, {}).get('display') == 'rule-table'
    configured = None if rule_table else resource_display_name(
        kind, resource_display_rows(values, identity, resource, root), values.get(f'display.resource.{identity}.label'), resource_mode(resource))
    name = (values.get(f'display.resource.{identity}.label') or resource['logicalId']) if rule_table else configured or values.get(f'display.resource.{identity}.label')
    return name, configured, rows


def resource_details(values, root, service, owned, resources, bound_anchors):
    counts = Counter(resource["resourceType"] for _, resource in resources)
    by_anchor = {}
    names = set()
    details = []
    for identity, resource in resources:
        kind = resource["resourceType"]
        mode = resource_mode(resource)
        if kind not in owned:
            raise ValueError(f"resource is outside service ownership: {kind}")
        name, configured_name, rows = resource_presentation(values, identity, resource, root)
        rule_table = GROUPED.get(kind, {}).get('display') == 'rule-table'
        type_display = not rule_table and configured_name is None and (name is None or name == kind)
        if type_display:
            if kind in GROUPED or counts[kind] != 1 or resource_has_name_property(root, kind, mode):
                raise ValueError(f"resource type display requires a single nameless independent resource: {kind}")
            name = kind
        if not name or name in {"UNSET", "PENDING_DEPLOY"}:
            raise ValueError(f"confirmed resource display label is missing: {kind}: {identity}")
        anchor = resource["anchor"]
        derived = resource_anchor(service, name, kind)
        expected = bound_anchors.get((kind, resource["logicalId"]), derived)
        if anchor != expected or anchor in by_anchor or derived in names:
            raise ValueError(f"resource anchor must be unique and match its name: {kind}: {anchor}")
        errors = naming_errors(root, kind, rows, mode)
        if errors:
            raise ValueError("; ".join(errors))
        names.add(derived)
        item = (identity, resource, name, rows)
        by_anchor[anchor] = item
        details.append(item)
    return details, by_anchor


def grouped_resources(values, details, by_anchor):
    grouped: dict[str, list] = {}
    for item in details:
        identity, resource, name, rows = item
        if resource["resourceType"] not in GROUPED:
            continue
        kind = resource["resourceType"]
        rule = GROUPED[kind]
        for field in ("parentReference", "parentProperty"):
            if not resource.get(field):
                raise ValueError(f"{kind}: {resource['logicalId']}: required metadata missing: desired.resource.{identity}.{field} ({kind}.{rule['parentProperty']})")
        link = LINK.fullmatch(resource["parentReference"])
        parent = by_anchor.get(link.group(3)) if link and not link.group(2) else None
        if not parent or parent[1]["resourceType"] != rule["parent"] or link.group(1) != parent[1]["logicalId"] or resource["parentProperty"] != kind + "." + rule["parentProperty"]:
            raise ValueError(f"{kind}: {resource['logicalId']}: invalid grouped parent: parentReference / parentProperty ({kind}.{rule['parentProperty']})")
        if kind in {ROTATION_SCHEDULE, LAMBDA_PERMISSION}:
            parent_rows = [row for row_id, row in entries(values, "desired.row.")
                           if row_id.startswith(identity + "-") and row.get("property") == resource["parentProperty"]]
            if len(parent_rows) != 1 or parent_rows[0].get("value") != resource["parentReference"]:
                raise ValueError(f"{kind}: {resource['logicalId']}: {resource['parentProperty']} requires exactly one formal row matching parentReference")
            if kind + ".Id" not in HIDDEN_PROPERTIES and (not rows or rows[0][1] != kind + ".Id"):
                raise ValueError(f"{kind}: {resource['logicalId']}: required first property: {kind}.Id")
        grouped.setdefault(parent[0], []).append(item)
        maximum = rule["maxCount"]
        if maximum is not None and sum(child[1]["resourceType"] == kind for child in grouped[parent[0]]) > maximum:
            raise ValueError(f"{kind}: {resource['logicalId']}: too many grouped children for {parent[1]['logicalId']}: {resource['parentProperty']}")
    return grouped


def resource_table_lines(resource, name, rows, children, root):
    output = []
    kind = resource["resourceType"]
    if kind == "EC2.SecurityGroup":
        rules = [(child, selected_rows(child_rows, root)) for _, child, _, child_rows in children]
        output += sg_tables(selected_rows(rows, root), [(child, rows) for child, rows in rules if rows], root)
    else:
        display = display_rows(kind, rows, root)
        for _, child, child_name, child_rows in children:
            child_rows = selected_rows(child_rows, root)
            if not child_rows:
                continue
            if child["resourceType"] == ROTATION_SCHEDULE:
                child_rows = [[rid, prop, f'[{name}](#{resource["anchor"]})' if prop == child["parentProperty"] else value, comment]
                              for rid, prop, value, comment in child_rows]
            child_display = display_rows(kind if child["resourceType"] == ROTATION_SCHEDULE else child["resourceType"], child_rows, root)
            if child["resourceType"] != ROTATION_SCHEDULE:
                for row in child_display:
                    row[1] = child["resourceType"] + "." + row[1]
            if child["resourceType"] == LAMBDA_PERMISSION:
                hidden = [row[1:] for row in child_rows if row[1] in {LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"}]
                child_display = [row for row in child_display if row[1] not in {LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"}]
                metadata = json.dumps([child_name, hidden], ensure_ascii=False, separators=(",", ":"))
                for char in "<>|()":
                    metadata = metadata.replace(char, "\\u%04x" % ord(char))
                for row in child_display:
                    row[1] = row[1].removeprefix("Lambda.")
                child_display[0][3] = f"<!-- lambda-permission: {metadata} --> " + child_display[0][3]
            prefix = f'<a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --> '
            if child["resourceType"] == ROTATION_SCHEDULE:
                prefix += child_name + "："
            comment = child_display[0][3]
            source = SUBNET_LIST_SOURCE.match(comment)
            child_display[0][3] = (source.group(0) if source else "") + prefix + (comment[source.end():] if source else comment)
            display += child_display
        display = indexed_rows(display, kind, root)
        output += row_table(display)
    return output


@input_scope
def markdown_for(path: Path, values: dict[str, str], root: Path) -> str:
    """Validated generation used by ordinary design and explicit validation."""
    from aws_mapping_display import validate_mappings
    validate_mappings(values, root)
    validate_required_properties(values, root)
    return render_validated_model(path, values, root)


def render_validated_model(path: Path, values: dict[str, str], root: Path) -> str:
    """Internal renderer after mapping/required-property preflight, before artifacts."""
    if path.stem == "cloudformation-stacks":
        return stack_markdown(path, values, root)
    service = path.stem
    if values.get(f"desired.service.{service}.serviceId") != service:
        raise ValueError(f"service ID must equal file stem: {path.name}")
    owned = values[f"desired.service.{service}.ownedCatalogResourceTypes"].split(",")
    resources = entries(values, "desired.resource.")
    if not resources:
        raise ValueError(f"service model has no resources: {path.name}")
    validate_resource_identities(path, values, root, resources)
    details, by_anchor = resource_details(values, root, service, owned, resources, bound_resource_anchors(path))
    return render_markdown(path, values, root, owned, details, grouped_resources(values, details, by_anchor))


@input_scope
def generate_markdown(path: Path, values: dict[str, str], root: Path) -> str:
    """Render the selected service without deciding whether its design is correct."""
    service = path.stem
    owned = values.get(f"desired.service.{service}.ownedCatalogResourceTypes", "").split(",")
    details = []
    for identity, resource in entries(values, "desired.resource."):
        kind = resource["resourceType"]
        name, _, rows = resource_presentation(values, identity, resource, root)
        name = name or kind
        details.append((identity, resource, name, rows))
    by_anchor = {item[1]["anchor"]: item for item in details}
    grouped = {}
    for item in details:
        link = LINK.fullmatch(item[1].get('parentReference', ''))
        parent = by_anchor.get(link[3]) if link and not link[2] else None
        if item[1]['resourceType'] in GROUPED and parent:
            grouped.setdefault(parent[0], []).append(item)
    return render_markdown(path, values, root, owned, details, grouped, model_policy_views(values))


def render_markdown(path, values, root, owned, details, grouped, policy_views=None):
    service = path.stem
    children = {item[0] for items in grouped.values() for item in items}
    independent = [item for item in details if item[0] not in children]
    output = [values["display.service.title"], "", f"- Design service ID: `{service}`",
              "- Owned catalog resource types: " + ", ".join(f"`{kind}`" for kind in owned)]
    output += ["", "## リソース一覧"]
    for kind in dict.fromkeys(item[1]["resourceType"] for item in independent):
        items = [item for item in independent if item[1]["resourceType"] == kind]
        output += ["", "### " + kind, "", *table(["No.", "ResourceName", "Comment"], [
            [str(number), f'[{name}](#{resource["anchor"]})', values[f"display.resource.{identity}.comment"]]
            for number, (identity, resource, name, _) in enumerate(items, 1)], numbered=True)]
    output += ["", "## リソース詳細"]
    for identity, resource, name, rows in independent:
        kind = resource["resourceType"]
        heading = f"### {kind}" if name == kind and resource_display_name(kind, rows, mode=resource_mode(resource)) is None else f"### {kind}: {name}"
        output += ["", f'<!-- resource-logical-id: {resource["logicalId"]} -->', f'<a id="{resource["anchor"]}"></a>', "", heading, ""]
        children = grouped.get(identity, [])
        output += resource_table_lines(resource, name, rows, children, root)
        output += (policy_views or {}).get(identity, [])
        if kind == "Macie.ClassificationJob":
            definitions = [row for row in rows if row[1] == kind + ".s3JobDefinition"]
            if definitions:
                match = re.fullmatch(r"\[[^\]]+\]\(([^)#]+\.json)\)", definitions[0][2])
                raw = (path.parent / match.group(1)).read_text(encoding="utf-8") if match else literal(definitions[0][2])
                document = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                if "bucketDefinitions" in document:
                    mappings = [[f'[{name}](#{resource["anchor"]})', f'`{group["accountId"]}`', f"`{bucket}`"] for group in document["bucketDefinitions"] for bucket in group["buckets"]]
                    output += ["", "#### 対象S3 bucket", "", *table(["Job", "AWS account ID", "Bucket"], mappings)]
    for _, note in entries(values, "desired.note."):
        output += ["", note["text"]]
    return "\n".join(output) + "\n"


def model_policy_views(values):
    from policy_tables import (Policy, POLICY_FORMATS, INLINE_POLICY_DOCUMENTS, JSON_LINK,
                               artifact_id, policy_document_lines, START, END, IAM_START, IAM_END)
    from model_files import resource_row_index
    result = {}
    rows_by_resource = resource_row_index(values)
    for identity, resource in entries(values, 'desired.resource.'):
        policies = []
        rows = rows_by_resource[identity]
        for position, (_, row) in enumerate(rows):
            prop = row['property']
            link = JSON_LINK.fullmatch(row.get('value', ''))
            if prop not in POLICY_FORMATS or not link or 'document' not in row:
                continue
            label, target = link.groups()
            trust = prop == 'IAM.Role.AssumeRolePolicyDocument'
            inline = prop in INLINE_POLICY_DOCUMENTS
            if inline and position and rows[position - 1][1]['property'] == prop.removesuffix('PolicyDocument') + 'PolicyName':
                label = literal(rows[position - 1][1]['value'])
            suffix = 'trust' if trust else 'inline-' + artifact_id(label) if inline else 'policy-' + artifact_id(Path(target).stem)
            kind = '信頼ポリシー' if trust else 'インラインポリシー' if inline else 'ポリシー設定' if POLICY_FORMATS[prop] == 'settings' else 'ポリシー'
            policy = Policy(label, target, resource['anchor'] + '-' + suffix, kind, prop)
            policies.extend(['', *policy_document_lines(json.loads(row['document']), policy)])
        if policies:
            start, end = (IAM_START, IAM_END) if resource['resourceType'] == 'IAM.Role' else (START, END)
            result[identity] = ['', start, *policies, '', end]
    return result
