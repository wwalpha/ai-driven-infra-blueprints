"""Expand SG detail properties and horizontal rules into catalog rows in memory."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aws_mapping_display as mapping_display
from model.core import literal
from utils.input_cache import input_scope

from design.common import cells as cells
from design.common import row_table, table
from design.layout_schema import ALIGNMENT, HEADER, RESOURCE
from design.services.definitions.ec2 import COMMENTS as COMMENTS
from design.services.definitions.ec2 import DIRECTIONS as DIRECTIONS
from design.services.definitions.ec2 import GROUP_COMMENTS as GROUP_COMMENTS
from design.services.definitions.ec2 import IDENTITY as IDENTITY
from design.services.definitions.ec2 import SECURITY_GROUP as SECURITY_GROUP
from design.services.definitions.ec2 import (
    SECURITY_GROUP_ID_PREFIX as SECURITY_GROUP_ID_PREFIX,
)
from design.services.definitions.ec2 import TAGS_PREFIX as TAGS_PREFIX

ROOT = Path(__file__).resolve().parents[5]

OVERVIEW_COLUMNS = ["No.", "ResourceName", "Comment"]


def port_properties(value: str, protocol: str) -> dict[str, str]:
    """Decode the single display column without changing protocol or port values."""
    if value == "—":
        return {}
    protocol = protocol.strip("`").lower()
    icmp = protocol in {"icmp", "icmpv6", "1", "58"}
    pattern = r"Type=(-?\d+), Code=(-?\d+)" if icmp else r"(-?\d+)(?:-(-?\d+))?"
    match = re.fullmatch(pattern, value.strip("`"))
    if not match:
        raise ValueError(
            "invalid Port: use a number, start-end, or ICMP Type=n, Code=n"
        )
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) is not None else first
    minimum = 0 if protocol in {"tcp", "udp", "6", "17"} else -1
    maximum = 255 if icmp else 65535
    if not (minimum <= first <= maximum and minimum <= last <= maximum):
        raise ValueError("Port values are outside the protocol range")
    if (not icmp and first > last) or (icmp and first == -1 and last != -1):
        raise ValueError("invalid Port range or ICMP all-types/code pair")
    return {"FromPort": f"`{first}`", "ToPort": f"`{last}`"}


def direction_metadata(value: str) -> tuple[str, str | None]:
    """Separate the rendered Direction from its optional peer SG reference."""
    if SECURITY_GROUP_ID_PREFIX not in value:
        return value, None
    marker = re.fullmatch(r"(.+?) <!-- security-group-id: (.+) -->", value)
    if (
        not marker
        or marker.group(2).strip("`").strip() in {"", "—"}
        or any(token in marker.group(2) for token in ("<!--", "-->"))
    ):
        raise ValueError("invalid Security Group reference metadata")
    return marker.group(1), marker.group(2)


def table_at(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int]:
    headers = cells(lines[start])
    alignment = cells(lines[start + 1]) if start + 1 < len(lines) else []
    expected_alignment = (
        ["---:", *(["---"] * (len(headers) - 1))]
        if headers[:1] == ["No."]
        else ["---"] * len(headers)
    )
    if len(headers) != len(set(headers)) or alignment != expected_alignment:
        raise ValueError("invalid Security Group table columns or alignment")
    cursor = start + 2
    rows = []
    while cursor < len(lines) and lines[cursor].startswith("|"):
        row = cells(lines[cursor])
        if len(row) != len(headers) or any(not value for value in row):
            raise ValueError("invalid Security Group table row")
        rows.append(row)
        cursor += 1
    return headers, rows, cursor


def overview_groups(lines: list[str]) -> dict[str, str]:
    title = "### EC2.SecurityGroup"
    if title not in lines:
        return {}
    if (
        lines.count(title) != 1
        or "## リソース一覧" not in lines
        or "## リソース詳細" not in lines
    ):
        raise ValueError("Security Group requires exactly one overview")
    start = lines.index(title)
    if not lines.index("## リソース一覧") < start < lines.index("## リソース詳細"):
        raise ValueError("Security Group overview must be in リソース一覧")
    start += 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or not lines[start].startswith("|"):
        raise ValueError("missing Security Group overview table")
    headers, rows, end = table_at(lines, start)
    while end < len(lines) and not lines[end].startswith("#"):
        if lines[end].startswith("|"):
            raise ValueError("Security Group requires exactly one overview table")
        end += 1
    if headers != OVERVIEW_COLUMNS or not rows:
        raise ValueError(
            "Security Group overview requires No., ResourceName, Comment only"
        )
    groups = {}
    for number, row in enumerate(rows, 1):
        link = re.fullmatch(r"\[([^\]<>|`]+)\]\(#([A-Za-z0-9_.-]+)\)", row[1])
        if row[0] != str(number) or not link or link.group(1) in groups:
            raise ValueError(
                "Security Group overview requires a unique logical ID link"
            )
        groups[link.group(1)] = link.group(2)
    return groups


@input_scope
def security_group_table_lines(lines: list[str], root=None) -> list[str]:
    """Expand SG detail tables while preserving rule identities and ownership."""
    root = root or mapping_display.ROOT
    groups = overview_groups(lines)
    seen = set()
    result: list[str] = []
    index = 0
    while index < len(lines):
        heading = RESOURCE.fullmatch(lines[index])
        if not heading or heading.group(1) != SECURITY_GROUP:
            if heading and heading.group(1) in {
                "EC2.SecurityGroupIngress",
                "EC2.SecurityGroupEgress",
            }:
                raise ValueError(
                    "Security Group rules must use a horizontal Direction table"
                )
            if TAGS_PREFIX in lines[index]:
                raise ValueError(
                    "Security Group tags metadata must belong to EC2.SecurityGroup"
                )
            if lines[index].startswith("| Direction |"):
                raise ValueError(
                    "Security Group rule table must belong to EC2.SecurityGroup"
                )
            result.append(lines[index])
            index += 1
            continue
        logical_id = heading.group(2)
        if logical_id not in groups or logical_id in seen:
            raise ValueError(
                "Security Group requires exactly one matching overview row and rule block"
            )
        anchor = groups[logical_id]
        previous = next((line for line in reversed(lines[:index]) if line.strip()), "")
        if previous != f'<a id="{anchor}"></a>':
            raise ValueError(
                "Security Group overview link must match its detail block anchor"
            )
        seen.add(logical_id)
        end = index + 1
        while end < len(lines) and not re.match(r"^#{1,3} ", lines[end]):
            end += 1
        block = lines[index:end]
        tag_lines = [line for line in block if TAGS_PREFIX in line]
        if len(tag_lines) > 1:
            raise ValueError("Security Group requires at most one tags metadata line")
        if (
            tag_lines
            and next((line for line in block[1:] if line.strip()), "") != tag_lines[0]
        ):
            raise ValueError(
                "Security Group tags metadata must follow its detail heading"
            )
        tag_rows = []
        if tag_lines:
            marker = re.fullmatch(r"<!-- security-group-tags: (.+) -->", tag_lines[0])
            if not marker or "-->" in marker.group(1) or "<!--" in marker.group(1):
                raise ValueError(
                    "invalid Security Group tags metadata; escape comment delimiters in JSON"
                )
            try:
                tags = json.loads(marker.group(1))
            except ValueError as error:
                raise ValueError(
                    "Security Group Tags must be a JSON array of Key/Value objects"
                ) from error
            if (
                not isinstance(tags, list)
                or not tags
                or any(
                    not isinstance(tag, dict)
                    or set(tag) != {"Key", "Value"}
                    or any(not isinstance(value, str) for value in tag.values())
                    for tag in tags
                )
            ):
                raise ValueError(
                    "Security Group Tags must be a JSON array of Key/Value objects"
                )
            for tag in tags:
                for prop in ("Key", "Value"):
                    tag_rows.append(
                        [
                            f"{SECURITY_GROUP}.Tags[].{prop}",
                            tag[prop],
                            GROUP_COMMENTS[f"Tags[].{prop}"],
                        ]
                    )
            block = [line for line in block if line not in tag_lines]

        start = next(
            (position for position, line in enumerate(block) if line.startswith("|")),
            -1,
        )
        if start == -1:
            raise ValueError("Security Group requires a basic property table")
        basic_headers, basic, basic_end = table_at(block, start)
        if basic_headers != ["No.", "Property", "Value", "Source / Comment"]:
            raise ValueError(
                "Security Group requires a basic property table before rules"
            )
        basic_rows = [row[1:] for row in basic]
        for prop, *_ in basic_rows:
            formal = mapping_display.formal_name(prop, SECURITY_GROUP, root) or (
                prop
                if prop.startswith(SECURITY_GROUP + ".")
                else SECURITY_GROUP + "." + prop
            )
            canonical = formal.removeprefix(SECURITY_GROUP + ".")
            if mapping_display.display_name(
                formal, SECURITY_GROUP, root
            ) != canonical and prop in {formal, canonical}:
                raise ValueError(
                    "Security Group property must use its Mapping display name: "
                    + formal
                )
        basic_rows = [
            [
                mapping_display.formal_name(prop, SECURITY_GROUP, root)
                or (
                    prop
                    if prop.startswith(SECURITY_GROUP + ".")
                    else f"{SECURITY_GROUP}.{prop}"
                ),
                value,
                comment,
            ]
            for prop, value, comment in basic_rows
        ]
        if [row[0] for row in basic] != [
            str(number) for number in range(1, len(basic) + 1)
        ]:
            raise ValueError("Security Group basic property numbering error")
        expected = [
            f"{SECURITY_GROUP}.{prop}"
            for prop in ("Id", "GroupDescription", "GroupName", "VpcId")
        ]
        expected = [prop for prop in expected if mapping_display.show(prop, root)]
        names = [row[0] for row in basic_rows]
        if names not in (
            [prop for prop in expected if prop != SECURITY_GROUP + ".GroupName"],
            expected,
        ) or any(
            row[1].strip("`").strip() in {"", "—"} or not row[2] for row in basic_rows
        ):
            raise ValueError(
                "Security Group requires Id, GroupDescription and VpcId detail values"
            )
        basic_rows.extend(tag_rows)
        rule_start = next(
            (
                position
                for position in range(basic_end, len(block))
                if block[position].startswith("|")
            ),
            -1,
        )
        if rule_start == -1:
            headers, rules, cursor = [], [], basic_end
        else:
            headers, rules, cursor = table_at(block, rule_start)
            allowed = (
                COMMENTS.keys()
                - {
                    "Id",
                    "FromPort",
                    "ToPort",
                    "SourceSecurityGroupId",
                    "DestinationSecurityGroupId",
                }
            ) | {"Port"}
            if (
                headers[:1] != ["Direction"]
                or not {"IpProtocol", "Port"} <= set(headers)
                or set(headers[1:]) - allowed
            ):
                raise ValueError(
                    "invalid Security Group Direction rule table columns; omit SourceSecurityGroupId, "
                    "DestinationSecurityGroupId and the basic property table"
                )
            if not rules:
                raise ValueError("omit empty Security Group rule table")
        properties = [
            prop
            for header in headers[1:]
            for prop in (("FromPort", "ToPort") if header == "Port" else (header,))
        ]
        if any(line.startswith("|") for line in block[cursor:]):
            raise ValueError("Security Group requires at most one Direction rule table")
        inline_rows = {direction: [] for direction in DIRECTIONS.values()}
        child_rows = []
        for row in rules:
            if any("<!--" in value or "<a id=" in value for value in row[1:]):
                raise ValueError("Security Group rule identity must be in Direction")
            direction_cell, security_group_id = direction_metadata(row[0])
            marker = IDENTITY.fullmatch(direction_cell)
            if not marker and ("<!--" in direction_cell or "<a id=" in direction_cell):
                raise ValueError(
                    "Direction requires complete anchor/logical-id/rule-id markers"
                )
            direction_label = marker.group(1) if marker else direction_cell
            if direction_label not in DIRECTIONS:
                raise ValueError("Security Group Direction must be Inbound or Outbound")
            direction = DIRECTIONS[direction_label]
            inline = marker is None
            values = {
                prop: value
                for prop, value in zip(headers[1:], row[1:], strict=False)
                if value != "—"
            }
            if "IpProtocol" not in values:
                raise ValueError("Security Group rule requires IpProtocol")
            values.update(
                port_properties(values.pop("Port", "—"), values["IpProtocol"])
            )
            peer = "Source" if direction == "Ingress" else "Destination"
            peer_property = f"{peer}SecurityGroupId"
            if security_group_id is not None:
                values[peer_property] = security_group_id
            opposite = "Destination" if direction == "Ingress" else "Source"
            if any(prop.startswith(opposite) for prop in values):
                raise ValueError(
                    "Security Group rule properties do not match Direction"
                )
            targets = {
                "CidrIp",
                "CidrIpv6",
                f"{peer}PrefixListId",
                f"{peer}SecurityGroupId",
            }
            if len(targets & values.keys()) != 1:
                raise ValueError(
                    "Security Group rule requires exactly one address, prefix list, or security group"
                )
            if (
                "SourceSecurityGroupOwnerId" in values
                and "SourceSecurityGroupId" not in values
            ):
                raise ValueError(
                    "SourceSecurityGroupOwnerId requires SourceSecurityGroupId"
                )
            prefix = (
                f"{SECURITY_GROUP}.SecurityGroup{direction}[]"
                if inline
                else f"EC2.SecurityGroup{direction}"
            )
            target_rows = inline_rows[direction] if inline else child_rows
            if marker:
                _, rule_anchor, rule_id, identifier = marker.groups()
                if identifier.strip("`") in {"", "—"}:
                    raise ValueError("standalone Security Group rule requires an Id")
                target_rows.append(
                    [
                        f"{prefix}.Id",
                        identifier,
                        f'<a id="{rule_anchor}"></a><!-- logical-id: {rule_id} --> {COMMENTS["Id"]}',
                    ]
                )
            # IpProtocol starts each inline array element, regardless of optional fields.
            row_properties = list(properties)
            if security_group_id is not None:
                position = next(
                    (
                        row_properties.index(prop)
                        for prop in ("SourceSecurityGroupOwnerId", "Description")
                        if prop in row_properties
                    ),
                    len(row_properties),
                )
                row_properties.insert(position, peer_property)
            for prop in [
                "IpProtocol",
                *(prop for prop in row_properties if prop != "IpProtocol"),
            ]:
                if prop in values:
                    target_rows.append(
                        [f"{prefix}.{prop}", values[prop], COMMENTS[prop]]
                    )
        result.extend([*block[:start], HEADER, ALIGNMENT])
        for number, row in enumerate(
            [*basic_rows, *inline_rows["Ingress"], *inline_rows["Egress"], *child_rows],
            1,
        ):
            result.append("| " + " | ".join([str(number), *row]) + " |")
        result.extend(block[cursor:])
        index = end
    if seen != groups.keys():
        raise ValueError("Security Group overview rows must have matching rule blocks")
    return result


@input_scope
def sg_tables(
    rows: list[list[str]],
    children: list[tuple[dict, list[list[str]]]],
    root: Path = ROOT,
    *,
    consumed: list[str] | None = None,
) -> list[str]:
    basic, tags, rules = [], [], []
    current = None
    for row in rows:
        prop = row[1].removeprefix("EC2.SecurityGroup.")
        if match := re.fullmatch(r"SecurityGroup(Ingress|Egress)\[\]\.(.+)", prop):
            direction, field = match.groups()
            if field == "IpProtocol":
                current = {
                    "Direction": "Inbound" if direction == "Ingress" else "Outbound"
                }
                rules.append(current)
            if current is None or current["Direction"] != (
                "Inbound" if direction == "Ingress" else "Outbound"
            ):
                raise ValueError("SG inline rule must start with IpProtocol")
            current[field] = row[2]
        elif prop.startswith("Tags[]."):
            if prop == "Tags[].Key":
                tags.append({"Key": literal(row[2])})
            elif prop == "Tags[].Value" and tags and "Value" not in tags[-1]:
                tags[-1]["Value"] = literal(row[2])
            else:
                raise ValueError("SG tags require contiguous Key/Value pairs")
        else:
            basic.append(
                [
                    row[0],
                    mapping_display.display_name(row[1], "EC2.SecurityGroup", root),
                    *row[2:],
                ]
            )
    output = row_table(basic)
    if tags:
        if any(set(tag) != {"Key", "Value"} for tag in tags):
            raise ValueError("incomplete SG tag")
        # JSON is Markdown metadata, not the Model scalar representation.
        metadata = (
            json.dumps(tags, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )
        output = ["<!-- security-group-tags: " + metadata + " -->", "", *output]
    for child, child_rows in children:
        values = {
            row[1].removeprefix(child["resourceType"] + "."): row[2]
            for row in child_rows
        }
        direction = (
            "Inbound" if child["resourceType"].endswith("Ingress") else "Outbound"
        )
        identifier = values.pop("Id")
        values["Direction"] = (
            f'{direction} <a id="{child["anchor"]}"></a><!-- logical-id: {child["logicalId"]} --><!-- rule-id: {identifier} -->'
        )
        rules.append(values)
    for rule in rules:
        first, last = rule.pop("FromPort", None), rule.pop("ToPort", None)
        if (first is None) != (last is None):
            raise ValueError("SG FromPort and ToPort must be supplied together")
        if first is not None:
            first, last = literal(first), literal(last)
            protocol = literal(rule["IpProtocol"]).lower()
            port = (
                f"Type={first}, Code={last}"
                if protocol in {"icmp", "icmpv6", "1", "58"}
                else first
                if first == last
                else f"{first}-{last}"
            )
            rule["Port"] = f"`{port}`"
        for peer in ("SourceSecurityGroupId", "DestinationSecurityGroupId"):
            if peer in rule:
                rule["Direction"] += f" <!-- security-group-id: {rule.pop(peer)} -->"
    if rules:
        fields = [
            "Direction",
            "IpProtocol",
            "Port",
            "CidrIp",
            "CidrIpv6",
            "SourcePrefixListId",
            "DestinationPrefixListId",
            "SourceSecurityGroupOwnerId",
            "Description",
        ]
        unknown = set().union(*(rule.keys() for rule in rules)) - set(fields)
        if unknown:
            raise ValueError(f"unsupported SG rule fields: {sorted(unknown)}")
        fields = [
            field
            for field in fields
            if field in {"Direction", "Port"} or any(field in rule for rule in rules)
        ]
        output += [
            "",
            *table(
                fields, [[rule.get(field, "—") for field in fields] for rule in rules]
            ),
        ]
    if consumed is not None:
        consumed.extend(row[0] for row in rows)
        consumed.extend(row[0] for _, child_rows in children for row in child_rows)
    return output
