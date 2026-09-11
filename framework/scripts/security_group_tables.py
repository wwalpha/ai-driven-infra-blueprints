"""Expand SG overview attributes and horizontal rules into catalog rows in memory."""

from __future__ import annotations

import json
import re


SECURITY_GROUP = "EC2.SecurityGroup"
DIRECTIONS = {"Inbound": "Ingress", "Outbound": "Egress"}
TAGS_PREFIX = "<!-- security-group-tags:"
OVERVIEW_COLUMNS = ["SecurityGroup", "GroupName", "Id", "VpcId", "Description"]
RESOURCE = re.compile(r"^### ([A-Za-z0-9]+\.[A-Za-z0-9]+): ([A-Za-z0-9][A-Za-z0-9_.-]*)$")
IDENTITY = re.compile(r'^(Inbound|Outbound) <a id="([a-z0-9_.-]+)"></a><!-- logical-id: ([A-Za-z0-9][A-Za-z0-9_.-]*) --><!-- rule-id: ([^<>]+) -->$')
HEADER = "| No. | Property | Value | Source / Comment |"
ALIGNMENT = "| ---: | --- | --- | --- |"
COMMENTS = {
    "Id": "Security Groupルールを一意に識別するID",
    "IpProtocol": "通信を許可するIP protocol",
    "FromPort": "許可するport範囲の開始値、またはICMP type",
    "ToPort": "許可するport範囲の終了値、またはICMP code",
    "CidrIp": "通信を許可するIPv4アドレス範囲",
    "CidrIpv6": "通信を許可するIPv6アドレス範囲",
    "SourcePrefixListId": "通信元として許可するPrefix ListのID",
    "SourceSecurityGroupId": "通信元として許可するSecurity GroupのID",
    "SourceSecurityGroupOwnerId": "通信元Security Groupを所有するAWS account ID",
    "DestinationPrefixListId": "通信先として許可するPrefix ListのID",
    "DestinationSecurityGroupId": "通信先として許可するSecurity GroupのID",
    "Description": "Security Groupルールの用途を説明する値",
}
GROUP_COMMENTS = {
    "Id": "Security Groupを一意に識別するID",
    "GroupDescription": "Security Groupの用途を説明する値",
    "GroupName": "Security Groupの名前",
    "VpcId": "Security Groupが所属するVPCのID",
    "Tags[].Key": "Security Groupへ付与するタグのキー",
    "Tags[].Value": "Security Groupへ付与するタグの値",
}


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def port_properties(value: str, protocol: str) -> dict[str, str]:
    """Decode the single display column without changing protocol or port values."""
    if value == "—":
        return {}
    protocol = protocol.strip("`").lower()
    icmp = protocol in {"icmp", "icmpv6", "1", "58"}
    pattern = r"Type=(-?\d+), Code=(-?\d+)" if icmp else r"(-?\d+)(?:-(-?\d+))?"
    match = re.fullmatch(pattern, value.strip("`"))
    if not match:
        raise ValueError("invalid Port: use a number, start-end, or ICMP Type=n, Code=n")
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) is not None else first
    minimum = 0 if protocol in {"tcp", "udp", "6", "17"} else -1
    maximum = 255 if icmp else 65535
    if not (minimum <= first <= maximum and minimum <= last <= maximum):
        raise ValueError("Port values are outside the protocol range")
    if (not icmp and first > last) or (icmp and first == -1 and last != -1):
        raise ValueError("invalid Port range or ICMP all-types/code pair")
    return {"FromPort": f"`{first}`", "ToPort": f"`{last}`"}


def table_at(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int]:
    headers = cells(lines[start])
    alignment = cells(lines[start + 1]) if start + 1 < len(lines) else []
    if len(headers) != len(set(headers)) or alignment != ["---"] * len(headers):
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


def overview_groups(lines: list[str]) -> dict[str, tuple[str, list[list[str]]]]:
    title = "### EC2.SecurityGroup"
    if title not in lines:
        return {}
    if lines.count(title) != 1 or "## リソース一覧" not in lines or "## リソース詳細" not in lines:
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
        raise ValueError("Security Group overview requires SecurityGroup, GroupName, Id, VpcId, Description only; omit Tags column")
    groups = {}
    for row in rows:
        link = re.fullmatch(r"\[([A-Za-z0-9][A-Za-z0-9_.-]*)\]\(#([a-z0-9_.-]+)\)", row[0])
        if not link or link.group(1) in groups:
            raise ValueError("Security Group overview requires a unique logical ID link")
        values = dict(zip(headers, row))
        if any(values[prop].strip("`").strip() in {"", "—"} for prop in ("Id", "VpcId", "Description")):
            raise ValueError("Security Group overview requires Id, VpcId and Description values")
        basic = []
        for prop in ("Id", "GroupDescription", "GroupName", "VpcId"):
            value = values["Description" if prop == "GroupDescription" else prop]
            if value != "—":
                basic.append([f"{SECURITY_GROUP}.{prop}", value, GROUP_COMMENTS[prop]])
        groups[link.group(1)] = (link.group(2), basic)
    return groups


def security_group_table_lines(lines: list[str]) -> list[str]:
    """Keep one source for SG attributes and preserve rule identities/ownership."""
    groups = overview_groups(lines)
    seen = set()
    result: list[str] = []
    index = 0
    while index < len(lines):
        heading = RESOURCE.fullmatch(lines[index])
        if not heading or heading.group(1) != SECURITY_GROUP:
            if heading and heading.group(1) in {"EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"}:
                raise ValueError("Security Group rules must use a horizontal Direction table")
            if TAGS_PREFIX in lines[index]:
                raise ValueError("Security Group tags metadata must belong to EC2.SecurityGroup")
            if lines[index].startswith("| Direction |"):
                raise ValueError("Security Group rule table must belong to EC2.SecurityGroup")
            result.append(lines[index])
            index += 1
            continue
        logical_id = heading.group(2)
        if logical_id not in groups or logical_id in seen:
            raise ValueError("Security Group requires exactly one matching overview row and rule block")
        anchor, basic_rows = groups[logical_id]
        previous = next((line for line in reversed(lines[:index]) if line.strip()), "")
        if previous != f'<a id="{anchor}"></a>':
            raise ValueError("Security Group overview link must match its rule block anchor")
        seen.add(logical_id)
        end = index + 1
        while end < len(lines) and not re.match(r"^#{1,3} ", lines[end]):
            end += 1
        block = lines[index:end]
        tag_lines = [line for line in block if TAGS_PREFIX in line]
        if len(tag_lines) > 1:
            raise ValueError("Security Group requires at most one tags metadata line")
        if tag_lines:
            marker = re.fullmatch(r"<!-- security-group-tags: (.+) -->", tag_lines[0])
            if not marker or "-->" in marker.group(1) or "<!--" in marker.group(1):
                raise ValueError("invalid Security Group tags metadata; escape comment delimiters in JSON")
            try:
                tags = json.loads(marker.group(1))
            except ValueError as error:
                raise ValueError("Security Group Tags must be a JSON array of Key/Value objects") from error
            if not isinstance(tags, list) or not tags or any(
                not isinstance(tag, dict) or set(tag) != {"Key", "Value"}
                or any(not isinstance(value, str) for value in tag.values()) for tag in tags
            ):
                raise ValueError("Security Group Tags must be a JSON array of Key/Value objects")
            for tag in tags:
                for prop in ("Key", "Value"):
                    value = json.dumps(tag[prop], ensure_ascii=False)
                    basic_rows.append([f"{SECURITY_GROUP}.Tags[].{prop}", value, GROUP_COMMENTS[f"Tags[].{prop}"]])
            block = [line for line in block if line not in tag_lines]

        start = next((position for position, line in enumerate(block) if line.startswith("|")), -1)
        if start == -1:
            # Insert the model-only property table before the next resource anchor.
            start = cursor = 1
            headers, rules = [], []
        else:
            headers, rules, cursor = table_at(block, start)
            allowed = (COMMENTS.keys() - {"Id", "FromPort", "ToPort"}) | {"Port"}
            if headers[:1] != ["Direction"] or not {"IpProtocol", "Port"} <= set(headers) or set(headers[1:]) - allowed:
                raise ValueError("invalid Security Group Direction rule table columns; omit the basic property table")
            if not rules:
                raise ValueError("omit empty Security Group rule table")
        properties = [prop for header in headers[1:] for prop in (("FromPort", "ToPort") if header == "Port" else (header,))]
        if any(line.startswith("|") for line in block[cursor:]):
            raise ValueError("Security Group requires one Direction rule table and no basic property table")
        inline_rows = {direction: [] for direction in DIRECTIONS.values()}
        child_rows = []
        for row in rules:
            if any("<!--" in value or '<a id=' in value for value in row[1:]):
                raise ValueError("Security Group rule identity must be in Direction")
            marker = IDENTITY.fullmatch(row[0])
            if not marker and ("<!--" in row[0] or '<a id=' in row[0]):
                raise ValueError("Direction requires complete anchor/logical-id/rule-id markers")
            direction_label = marker.group(1) if marker else row[0]
            if direction_label not in DIRECTIONS:
                raise ValueError("Security Group Direction must be Inbound or Outbound")
            direction = DIRECTIONS[direction_label]
            inline = marker is None
            values = {prop: value for prop, value in zip(headers[1:], row[1:]) if value != "—"}
            if "IpProtocol" not in values:
                raise ValueError("Security Group rule requires IpProtocol")
            values.update(port_properties(values.pop("Port", "—"), values["IpProtocol"]))
            opposite = "Destination" if direction == "Ingress" else "Source"
            if any(prop.startswith(opposite) for prop in values):
                raise ValueError("Security Group rule properties do not match Direction")
            peer = "Source" if direction == "Ingress" else "Destination"
            targets = {"CidrIp", "CidrIpv6", f"{peer}PrefixListId", f"{peer}SecurityGroupId"}
            if len(targets & values.keys()) != 1:
                raise ValueError("Security Group rule requires exactly one address, prefix list, or security group")
            if "SourceSecurityGroupOwnerId" in values and "SourceSecurityGroupId" not in values:
                raise ValueError("SourceSecurityGroupOwnerId requires SourceSecurityGroupId")
            prefix = f"{SECURITY_GROUP}.SecurityGroup{direction}[]" if inline else f"EC2.SecurityGroup{direction}"
            target_rows = inline_rows[direction] if inline else child_rows
            if marker:
                _, rule_anchor, rule_id, identifier = marker.groups()
                if identifier.strip("`") in {"", "—"}:
                    raise ValueError("standalone Security Group rule requires an Id")
                target_rows.append([f"{prefix}.Id", identifier, f'<a id="{rule_anchor}"></a><!-- logical-id: {rule_id} --> {COMMENTS["Id"]}'])
            # IpProtocol starts each inline array element, regardless of optional fields.
            for prop in ["IpProtocol", *(prop for prop in properties if prop != "IpProtocol")]:
                if prop in values:
                    target_rows.append([f"{prefix}.{prop}", values[prop], COMMENTS[prop]])
        result.extend([*block[:start], HEADER, ALIGNMENT])
        for number, row in enumerate([*basic_rows, *inline_rows["Ingress"], *inline_rows["Egress"], *child_rows], 1):
            result.append("| " + " | ".join([str(number), *row]) + " |")
        result.extend(block[cursor:])
        index = end
    if seen != groups.keys():
        raise ValueError("Security Group overview rows must have matching rule blocks")
    return result
