"""Render detailed designs from authoritative service properties."""

from __future__ import annotations

import json
import re
from pathlib import Path

from design_layout import (
    ALIGNMENT, HEADER, DISPLAY_PROPERTY_ALIASES, GROUPED, HIDDEN_PROPERTIES,
    CODEBUILD_FORMAL_VARIABLE, GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE,
    CLOUDTRAIL_RESOURCE_TYPES, resource_display_name,
    resource_name_fields, resource_anchor,
)
from policy_tables import literal, table, unique_object, invalid_constant
from design_catalog import design_material_files


LINK = re.compile(r"^\[([^\]]+)\]\(([^)]*?)#([^)]+)\)$")


def properties(text: str) -> dict[str, str]:
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in result or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            raise ValueError(f"invalid or duplicate model property at line {number}: {key}")
        result[key] = value
    return result


def entries(values: dict[str, str], prefix: str) -> list[tuple[str, dict[str, str]]]:
    groups: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        if key.startswith(prefix):
            identity, separator, field = key[len(prefix):].partition(".")
            if not separator:
                raise ValueError(f"invalid model entry: {key}")
            groups.setdefault(identity, {})[field] = value
    return sorted(groups.items())


def naming_targets(root: Path) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    path = root / "framework/rules/aws-resource-naming.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[2].startswith("`") and cells[4].startswith("`"):
            for kind in re.findall(r"`([^`]+)`", cells[2]):
                targets.setdefault(kind, set()).add(cells[3].strip("`"))
    return targets


def naming_errors(root: Path, kind: str, rows: list[list[str]]) -> list[str]:
    if kind == "CodeBuild.Project":
        names = [row[2].strip("`\"") for row in rows if row[1].removeprefix(kind + ".") == "Name"]
        if len(names) != 1:
            return ["CodeBuild.Project.Name must appear exactly once"]
        value = names[0]
        if not value.strip() or value.strip().lower() in {"unset", "pending", "pending_deploy", "tbd", "n/a", "none", "未確定"} or value.startswith("[") or "{{" in value:
            return ["CodeBuild.Project.Name must be confirmed and non-empty"]
    targets = naming_targets(root)
    outputs = catalog_outputs(root, kind)
    selected = {row[1].removeprefix(kind + ".") for row in rows if kind + "." + row[1].removeprefix(kind + ".") not in outputs}
    expected = selected & set(resource_name_fields(kind))
    # Registered nested names (e.g. BackupPlan) are also naming targets.
    expected.update(selected & targets.get(kind, set()))
    tag_rows = [row for row in rows if row[1].removeprefix(kind + ".").startswith(("Tags", "HostedZoneTags"))]
    if resource_display_name(kind, tag_rows) is not None:
        expected.add("Name tag")
    return [f"naming rule missing: {kind}: {field}" for field in sorted(expected)
            if field not in targets.get(kind, set()) and kind + "." + field not in targets.get(kind, set())
            and field.rsplit(".", 1)[-1] not in targets.get(kind, set())]


def catalog_outputs(root: Path, kind: str) -> set[str]:
    return {line.partition("=")[0] for path in design_material_files(root)
            if path.stem.replace("_", ".", 1) == kind
            for line in path.read_text(encoding="utf-8").splitlines() if line.endswith("=IDENTIFIER_OUTPUT")}


def resource_rows(values: dict[str, str], identity: str, kind: str, root: Path) -> list[list[str]]:
    outputs = catalog_outputs(root, kind)
    rows = []
    for row_id, row in entries(values, "desired.row."):
        if not row_id.startswith(identity + "-"):
            continue
        if set(row) - {"property", "value", "comment", "artifactSha256", "document"} or not {"property", "value", "comment"} <= row.keys():
            raise ValueError(f"invalid resource row: {row_id}")
        observed = values.get(f"observed.row.{row_id}.value")
        value = row["value"]
        if observed is not None:
            if link := LINK.fullmatch(value):
                value = observed if row["property"] in outputs else f"[{literal(observed)}]({link.group(2)}#{link.group(3)})"
            else:
                raise ValueError(f"observed value requires a desired logical reference: {row_id}")
        rows.append([row_id, row["property"], value, row["comment"]])
    return rows


def display_rows(kind: str, rows: list[list[str]]) -> list[list[str]]:
    """Apply the existing service displays without changing formal model values."""
    aliases = {formal: display for display, formal in DISPLAY_PROPERTY_ALIASES.items()}
    result = []
    index = 0
    counts: dict[str, int] = {}
    while index < len(rows):
        identity, prop, value, comment = rows[index]
        if prop in HIDDEN_PROPERTIES:
            raise ValueError(f"hidden property must not be a display row: {prop}")
        if prop == CODEBUILD_FORMAL_VARIABLE + "Name":
            block = rows[index:index + 3]
            if [row[1] for row in block] != [CODEBUILD_FORMAL_VARIABLE + field for field in ("Name", "Type", "Value")]:
                raise ValueError("CodeBuild variables require contiguous Name/Type/Value rows")
            name, variable_type, value = [literal(row[2]) for row in block]
            prop = "CodeBuild.Project.Environment.Variables." + name
            if LINK.fullmatch(block[2][2]):
                value = block[2][2]
                comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
            elif variable_type == "PLAINTEXT":
                value = block[2][2]
            else:
                raise ValueError("CodeBuild non-PLAINTEXT variables require a resource link")
            index += 2
        elif prop in {"CodeBuild.Project.VpcConfig.Subnets", "CodeBuild.Project.VpcConfig.SecurityGroupIds"}:
            counts[prop] = counts.get(prop, 0) + 1
            prop += f"[{counts[prop]}]"
        elif prop == GUARDDUTY_FORMAL_FEATURE + "Name":
            if index + 1 >= len(rows) or rows[index + 1][1] != GUARDDUTY_FORMAL_FEATURE + "Status":
                raise ValueError("GuardDuty features require contiguous Name/Status rows")
            prop = "GuardDuty.Detector.Features." + literal(value)
            value = rows[index + 1][2]
            index += 1
        elif prop == CLOUDTRAIL_FORMAL_DATA_RESOURCE + "Type":
            if index + 1 >= len(rows) or rows[index + 1][1] != CLOUDTRAIL_FORMAL_DATA_RESOURCE + "Values":
                raise ValueError("CloudTrail data resources require contiguous Type/Values rows")
            types = {value: key for key, value in CLOUDTRAIL_RESOURCE_TYPES.items()}
            if literal(value) not in types:
                raise ValueError("unsupported CloudTrail data resource type")
            counts["data"] = counts.get("data", 0) + 1
            prop = f"CloudTrail.Trail.EventSelectors.DataResources[{counts['data']}].{types[literal(value)]}"
            value = rows[index + 1][2]
            if literal(value) == '["arn:aws:s3"]':
                value = "`All current and future S3 buckets`"
            index += 1
        elif prop.startswith((CODEBUILD_FORMAL_VARIABLE, GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE)) and not prop.startswith(GUARDDUTY_FORMAL_FEATURE + "AdditionalConfiguration"):
            raise ValueError(f"incomplete compact display group: {prop}")
        prop = aliases.get(prop, prop).removeprefix(kind + ".")
        result.append([identity, prop, value, comment])
        index += 1
    if kind == "CodePipeline.Pipeline":
        return pipeline_rows(result)
    return result


def pipeline_rows(rows: list[list[str]]) -> list[list[str]]:
    stages: list[list[list[list[str]]]] = []
    stage_rows = []
    action_rows = []
    seen_stage: set[str] = set()
    seen_action: set[str] = set()
    result = []
    trailing = []
    for row in rows:
        field = row[1]
        if not field.startswith("Stages[]."):
            (trailing if stages else result).append(row)
            continue
        if trailing:
            raise ValueError("CodePipeline stage rows must be contiguous")
        field = field.removeprefix("Stages[].")
        action = field.startswith("Actions[].")
        field = field.removeprefix("Actions[].")
        if not stages or (not action and field in seen_stage):
            stage_rows, action_rows, seen_stage, seen_action = [], [], set(), set()
            stages.append([stage_rows])
        if action:
            if not action_rows or field in seen_action:
                action_rows, seen_action = [], set()
                stages[-1].append(action_rows)
            seen_action.add(field)
            action_rows.append([row[0], field, *row[2:]])
        else:
            seen_stage.add(field)
            stage_rows.append([row[0], field, *row[2:]])
    for stage, blocks in enumerate(stages, 1):
        for action, block in enumerate(blocks):
            prefix = f"Stages[{stage}]."
            if action:
                prefix += "Actions." if len(blocks) == 2 else f"Actions[{action}]."
            for identity, field, value, comment in block:
                if field != "Configuration":
                    result.append([identity, prefix + field, value, comment])
                    continue
                config = json.loads(literal(value), object_pairs_hook=unique_object, parse_constant=invalid_constant)
                if not isinstance(config, dict) or not config or any(not isinstance(item, str) for item in config.values()):
                    raise ValueError("CodePipeline Configuration must be a non-empty string object")
                comments = dict(part.split(": ", 1) for part in comment.split(" / ") if ": " in part)
                if set(comments) != set(config):
                    raise ValueError("CodePipeline Configuration requires a comment for each key")
                for key, item in config.items():
                    result.append([identity, prefix + "Configuration." + key, item if LINK.fullmatch(item) else f"`{item}`", comments[key]])
    return result + trailing


def row_table(rows: list[list[str]]) -> list[str]:
    return [HEADER, ALIGNMENT, *("| " + " | ".join([str(number), *row[1:]]) + " |" for number, row in enumerate(rows, 1))]


def sg_tables(rows: list[list[str]], children: list[tuple[dict, list[list[str]]]]) -> list[str]:
    basic, tags, rules = [], [], []
    current = None
    for row in rows:
        prop = row[1].removeprefix("EC2.SecurityGroup.")
        if match := re.fullmatch(r"SecurityGroup(Ingress|Egress)\[\]\.(.+)", prop):
            direction, field = match.groups()
            if field == "IpProtocol":
                current = {"Direction": "Inbound" if direction == "Ingress" else "Outbound"}
                rules.append(current)
            if current is None or current["Direction"] != ("Inbound" if direction == "Ingress" else "Outbound"):
                raise ValueError("SG inline rule must start with IpProtocol")
            current[field] = row[2]
        elif prop.startswith("Tags[]."):
            if prop == "Tags[].Key":
                tags.append({"Key": json.loads(row[2])})
            elif prop == "Tags[].Value" and tags and "Value" not in tags[-1]:
                tags[-1]["Value"] = json.loads(row[2])
            else:
                raise ValueError("SG tags require contiguous Key/Value pairs")
        else:
            basic.append([row[0], prop, *row[2:]])
    output = row_table(basic)
    if tags:
        if any(set(tag) != {"Key", "Value"} for tag in tags):
            raise ValueError("incomplete SG tag")
        output = ["<!-- security-group-tags: " + json.dumps(tags, ensure_ascii=False, separators=(",", ":")) + " -->", "", *output]
    for child, child_rows in children:
        values = {row[1].removeprefix(child["resourceType"] + "."): row[2] for row in child_rows}
        direction = "Inbound" if child["resourceType"].endswith("Ingress") else "Outbound"
        identifier = values.pop("Id")
        values["Direction"] = f'{direction} <a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --><!-- rule-id: {literal(identifier)} -->'
        rules.append(values)
    for rule in rules:
        first, last = rule.pop("FromPort", None), rule.pop("ToPort", None)
        if (first is None) != (last is None):
            raise ValueError("SG FromPort and ToPort must be supplied together")
        if first is not None:
            first, last = literal(first), literal(last)
            protocol = literal(rule["IpProtocol"]).lower()
            port = f"Type={first}, Code={last}" if protocol in {"icmp", "icmpv6", "1", "58"} else first if first == last else f"{first}-{last}"
            rule["Port"] = f"`{port}`"
        for peer in ("SourceSecurityGroupId", "DestinationSecurityGroupId"):
            if peer in rule:
                rule["Direction"] += f" <!-- security-group-id: {rule.pop(peer)} -->"
    if rules:
        fields = ["Direction", "IpProtocol", "Port", "CidrIp", "CidrIpv6", "SourcePrefixListId", "DestinationPrefixListId", "SourceSecurityGroupOwnerId", "Description"]
        unknown = set().union(*(rule.keys() for rule in rules)) - set(fields)
        if unknown:
            raise ValueError(f"unsupported SG rule fields: {sorted(unknown)}")
        fields = [field for field in fields if field in {"Direction", "Port"} or any(field in rule for rule in rules)]
        output += ["", *table(fields, [[rule.get(field, "—") for field in fields] for rule in rules])]
    return output


def markdown_for(path: Path, values: dict[str, str], root: Path) -> str:
    """Produce the complete base view; policy tables are rendered afterwards."""
    if path.stem == "cloudformation-stacks":
        stacks = entries(values, "desired.stack.")
        if not stacks:
            raise ValueError("stack model is empty")
        for _, stack in stacks:
            if errors := naming_errors(root, "CloudFormation.Stack", [["1", "StackName", stack["name"], "名前"]]):
                raise ValueError("; ".join(errors))
        return "\n".join(["# CloudFormation stack 詳細設計", "", "## Stack一覧", *table(
            ["No.", "StackName", "Template", "Parameters", "Comment"],
            [[str(number), stack["name"], stack["template"], stack["parameters"], values[f"display.stack.{identity}.comment"]]
             for number, (identity, stack) in enumerate(stacks, 1)], numbered=True)]) + "\n"
    service = path.stem
    if values.get(f"desired.service.{service}.serviceId") != service:
        raise ValueError(f"service ID must equal file stem: {path.name}")
    owned = values[f"desired.service.{service}.ownedCatalogResourceTypes"].split(",")
    resources = entries(values, "desired.resource.")
    if not resources:
        raise ValueError(f"service model has no resources: {path.name}")
    by_anchor = {}
    details = []
    for identity, resource in resources:
        kind = resource["resourceType"]
        if kind not in owned:
            raise ValueError(f"resource is outside service ownership: {kind}")
        rows = resource_rows(values, identity, kind, root)
        rule_table = GROUPED.get(kind, {}).get("display") == "rule-table"
        name = resource["logicalId"] if rule_table else resource_display_name(kind, rows) or values.get(f"display.resource.{identity}.label")
        if not name or name in {"UNSET", "PENDING_DEPLOY"}:
            raise ValueError(f"confirmed resource display label is missing: {kind}: {identity}")
        anchor = resource["anchor"]
        if anchor != resource_anchor(service, name) or anchor in by_anchor:
            raise ValueError(f"resource anchor must be unique and match its name: {kind}: {anchor}")
        errors = naming_errors(root, kind, rows)
        if errors:
            raise ValueError("; ".join(errors))
        item = (identity, resource, name, rows)
        by_anchor[anchor] = item
        details.append(item)
    independent = [item for item in details if item[1]["resourceType"] not in GROUPED]
    grouped: dict[str, list] = {}
    for item in details:
        identity, resource, name, rows = item
        if resource["resourceType"] not in GROUPED:
            continue
        link = LINK.fullmatch(resource["parentReference"])
        rule = GROUPED[resource["resourceType"]]
        parent = by_anchor.get(link.group(3)) if link and not link.group(2) else None
        if not parent or parent[1]["resourceType"] != rule["parent"] or resource["parentProperty"] != resource["resourceType"] + "." + rule["parentProperty"]:
            raise ValueError(f"invalid grouped parent: {identity}")
        grouped.setdefault(parent[0], []).append(item)
    output = [values["display.service.title"], "", f"- Design service ID: `{service}`",
              "- Owned catalog resource types: " + ", ".join(f"`{kind}`" for kind in owned), "", "## リソース一覧"]
    for kind in dict.fromkeys(item[1]["resourceType"] for item in independent):
        items = [item for item in independent if item[1]["resourceType"] == kind]
        output += ["", "### " + kind, "", *table(["No.", "ResourceName", "Comment"], [
            [str(number), f'[{name}](#{resource["anchor"]})', values[f"display.resource.{identity}.comment"]]
            for number, (identity, resource, name, _) in enumerate(items, 1)], numbered=True)]
    output += ["", "## リソース詳細"]
    for identity, resource, name, rows in independent:
        kind = resource["resourceType"]
        output += ["", f'<!-- resource-logical-id: {resource["logicalId"]} -->', f'<a id="{resource["anchor"]}"></a>', "", f"### {kind}: {name}", ""]
        children = grouped.get(identity, [])
        if kind == "EC2.SecurityGroup":
            output += sg_tables(rows, [(child, child_rows) for _, child, _, child_rows in children])
        else:
            display = display_rows(kind, rows)
            for _, child, _, child_rows in children:
                child_display = display_rows(child["resourceType"], child_rows)
                for row in child_display:
                    row[1] = child["resourceType"] + "." + row[1]
                child_display[0][3] = f'<a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --> ' + child_display[0][3]
                display += child_display
            output += row_table(display)
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
