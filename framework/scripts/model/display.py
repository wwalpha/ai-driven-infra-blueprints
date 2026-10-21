"""Catalog ordering and common display tables, separate from document assembly."""

import json
import re
from collections import Counter
from pathlib import Path
from model.core import LINK, literal, ReferenceResolutionError
from ec2_display import ec2_display_rows
from service_rows import codebuild_display_row, pipeline_rows, glue_argument_rows, CODEBUILD_FORMAL_VARIABLE, packed_compact_rows
from design_layout import (HEADER, ALIGNMENT, GROUPED, REQUIRED_NAME_TAG_TYPES,
    GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE, CLOUDTRAIL_RESOURCE_TYPES,
    LINKED_LIST_PROPERTIES, CODEBUILD_VPC_PROPERTIES, subnet_list_items, catalog_property_order)
from policy_tables import table
from aws_mapping_display import ROOT, rule, selected_rows, compact_group, display_name
from validation_cache import input_scope


def catalog_display_rows(rows: list[list[str]], kind: str, root: Path) -> list[list[str]]:
    """Sort property blocks without separating contiguous array elements."""
    if kind == "EC2.SecurityGroup" or GROUPED.get(kind, {}).get("display") == "rule-table":
        return rows  # Horizontal rule tables have their own generation and restoration.
    order = dict(catalog_property_order(root, kind) or {})
    if kind == "CodeBuild.Project":
        subnets, groups = kind + ".VpcConfig.Subnets", kind + ".VpcConfig.SecurityGroupIds"
        order[subnets], order[groups] = order[groups], order[subnets]
    if kind in {"EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"}:
        order[kind + ".Name"] = -1
    if kind == "S3.Bucket":
        order[kind + ".Region"] = order[kind + ".BucketName"] + 0.5
    blocks = []
    previous_array = ""
    array_order = {}
    for prop, rank in order.items():
        if "[]" in prop:
            array = prop.split("[]", 1)[0] + "[]"
            array_order.setdefault(array, rank)
    for row in rows:
        array = row[1].split("[]", 1)[0] + "[]" if "[]" in row[1] else ""
        if array and array == previous_array:
            blocks[-1].append(row)
        else:
            blocks.append([row])
        previous_array = array
    return [row for block in sorted(blocks, key=lambda block: array_order.get(
        block[0][1].split("[]", 1)[0] + "[]", order.get(block[0][1], len(order)))) for row in block]


@input_scope
def display_rows(kind: str, rows: list[list[str]], root: Path = ROOT, *, mode="CREATE", _counts=None, consumed: list[str] | None = None) -> list[list[str]]:
    """Apply the existing service displays without changing formal model values."""
    rows = selected_rows(rows, root)
    processed = []
    formal_properties = {row[1] for row in rows}
    result = []
    index = 0
    counts = {} if _counts is None else _counts
    while index < len(rows):
        start = index
        identity, prop, value, comment = rows[index]
        packed = packed_compact_rows(rows, index) if mode == 'IMPORT' else None
        if packed is not None:
            block, expanded = packed
            rendered = display_rows(kind, expanded, root, mode=mode, _counts=counts)
            source = json.dumps([[row[1:] for row in block], len(rendered)], ensure_ascii=True)
            for char in '|<>':
                source = source.replace(char, f'\\u{ord(char):04x}')
            rendered[0][3] = '<!-- compact-source: ' + source + ' --> ' + rendered[0][3]
            result.extend(rendered)
            processed.extend(row[0] for row in block)
            index += len(block)
            continue
        if prop == CODEBUILD_FORMAL_VARIABLE + "Name":
            _, prop, value, comment = codebuild_display_row(rows, index, comment, mode=mode)
            index += 2
        elif prop in LINKED_LIST_PROPERTIES:
            linked = LINK.fullmatch(value)
            if prop in CODEBUILD_VPC_PROPERTIES and not linked and mode != "IMPORT":
                if literal(value).lstrip().startswith(('[', '{')):
                    subnet_list_items(prop, value)
                raise ReferenceResolutionError("CodeBuild VpcConfig value must be a resource link", property=prop, reference=value)
            items = [value] if linked else subnet_list_items(prop, value)
            source = ""
            if not linked:
                encoded = json.dumps(value, ensure_ascii=True)
                for char in "|<>[]":
                    encoded = encoded.replace(char, f"\\u{ord(char):04x}")
                source = "<!-- subnet-list-source: " + encoded + " --> "
            field = prop.removesuffix("[]").removeprefix(kind + ".")
            for offset, item in enumerate(items):
                counts[prop] = counts.get(prop, 0) + 1
                result.append([identity, f"{field}[{counts[prop]}]", item, (source if offset == 0 else "") + comment])
            processed.extend(row[0] for row in rows[start:index + 1])
            index += 1
            continue
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
            if literal(value) == '["arn:aws:s3"]' or mode == 'IMPORT' and literal(value) == 'arn:aws:s3':
                value = "`All current and future S3 buckets`"
            index += 1
        elif prop.startswith((CODEBUILD_FORMAL_VARIABLE, GUARDDUTY_FORMAL_FEATURE, CLOUDTRAIL_FORMAL_DATA_RESOURCE)) and not prop.startswith(GUARDDUTY_FORMAL_FEATURE + "AdditionalConfiguration"):
            raise ValueError(f"incomplete compact display group: {prop}")
        # Compact producers own their dynamic names; ordinary rows use Mapping names.
        item = rule(prop, root) if not compact_group(prop) and prop in formal_properties else None
        from design_layout import is_import_role_arn
        prop = "RoleARN" if is_import_role_arn(prop, value, mode) else display_name(prop, kind, root) if item else prop.removeprefix(kind + ".")
        result.append([identity, prop, value, comment])
        processed.extend(row[0] for row in rows[start:index + 1])
        index += 1
    if Counter(processed) != Counter(row[0] for row in rows):
        raise ValueError("selected display rows were omitted or consumed more than once")
    if kind == "CodePipeline.Pipeline":
        result = pipeline_rows(result)
    elif kind in REQUIRED_NAME_TAG_TYPES:
        result = ec2_display_rows(result)
    elif kind == "Glue.Job":
        result = glue_argument_rows(result, kind)
    if consumed is not None:
        consumed.extend(processed)
    return result


def row_table(rows: list[list[str]]) -> list[str]:
    return [HEADER, ALIGNMENT, *("| " + " | ".join([str(number), *row[1:]]) + " |" for number, row in enumerate(rows, 1))]


@input_scope
def sg_tables(rows: list[list[str]], children: list[tuple[dict, list[list[str]]]], root: Path = ROOT, *, consumed: list[str] | None = None) -> list[str]:
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
            basic.append([row[0], display_name(row[1], "EC2.SecurityGroup", root), *row[2:]])
    output = row_table(basic)
    if tags:
        if any(set(tag) != {"Key", "Value"} for tag in tags):
            raise ValueError("incomplete SG tag")
        output = ["<!-- security-group-tags: " + json.dumps(tags, ensure_ascii=False, separators=(",", ":")) + " -->", "", *output]
    for child, child_rows in children:
        values = {row[1].removeprefix(child["resourceType"] + "."): row[2] for row in child_rows}
        direction = "Inbound" if child["resourceType"].endswith("Ingress") else "Outbound"
        identifier = values.pop("Id")
        values["Direction"] = f'{direction} <a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --><!-- rule-id: {identifier} -->'
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
    if consumed is not None:
        consumed.extend(row[0] for row in rows)
        consumed.extend(row[0] for _, child_rows in children for row in child_rows)
    return output


