"""security-group: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import MISSING, AcquisitionError, Unresolved, one, select

APIS = {("ec2", "describe_security_groups"), ("ec2", "describe_security_group_rules")}


def sensitive(prop):
    return False


def _fetch_permissions(items, egress):
    result = []
    for item in items:
        base = {k: item[k] for k in ("IpProtocol", "FromPort", "ToPort") if k in item}
        for entry in item.get("IpRanges", []):
            result.append(dict(base, **entry))
        for entry in item.get("UserIdGroupPairs", []):
            result.append(
                dict(
                    base,
                    **{
                        "DestinationSecurityGroupId"
                        if egress
                        else "SourceSecurityGroupId": entry["GroupId"]
                    },
                    **{"Description": entry["Description"]}
                    if "Description" in entry
                    else {},
                )
            )
    return result


def rule_candidates(records, group, egress, expected):
    """Match only complete, independently specified rule identities."""
    sources = (
        "CidrIp",
        "CidrIpv6",
        "SourcePrefixListId",
        "DestinationPrefixListId",
        "SourceSecurityGroupId",
        "DestinationSecurityGroupId",
    )
    selected = [key for key in sources if expected.get(key)]
    protocol = str(expected.get("IpProtocol", "")).lower()
    if not group or not protocol or len(selected) != 1:
        raise Unresolved("security group rule identity is incomplete")
    if protocol in {"tcp", "udp", "icmp", "icmpv6", "6", "17", "1", "58"} and any(
        key not in expected for key in ("FromPort", "ToPort")
    ):
        raise Unresolved("security group rule ports are incomplete")
    aliases = {"6": "tcp", "17": "udp", "1": "icmp", "58": "icmpv6"}
    rename = {
        "CidrIp": "CidrIpv4",
        "SourcePrefixListId": "PrefixListId",
        "DestinationPrefixListId": "PrefixListId",
        "SourceSecurityGroupId": "ReferencedGroupInfo.GroupId",
        "DestinationSecurityGroupId": "ReferencedGroupInfo.GroupId",
    }
    fields = [selected[0], *[key for key in ("FromPort", "ToPort") if key in expected]]
    return [
        record
        for record in records
        if record.get("GroupId") == group
        and record.get("IsEgress") is egress
        and aliases.get(
            str(record.get("IpProtocol", "")).lower(),
            str(record.get("IpProtocol", "")).lower(),
        )
        == aliases.get(protocol, protocol)
        and all(select(record, rename.get(key, key)) == expected[key] for key in fields)
    ]


def fetch(ctx, r, getter):
    if getter == "group":
        current = r.current("Id")
        inputs = (
            {"GroupIds": [current]}
            if current
            else {
                "Filters": [
                    {"Name": "group-name", "Values": [r.value("GroupName")]},
                    {"Name": "vpc-id", "Values": [r.value("VpcId", "id")]},
                ]
            }
        )
        record = dict(
            one(
                ctx.pages("ec2", "describe_security_groups", **inputs).get(
                    "SecurityGroups", []
                ),
                "ec2.describe_security_groups",
            )
        )
        permissions = _fetch_permissions
        record["SecurityGroupIngress"] = permissions(
            record.get("IpPermissions", []), False
        )
        record["SecurityGroupEgress"] = permissions(
            record.get("IpPermissionsEgress", []), True
        )
        return record
    parent = r.parent()
    group = parent.identity()
    current = r.current("Id")
    inputs = (
        {"SecurityGroupRuleIds": [current]}
        if current
        else {"Filters": [{"Name": "group-id", "Values": [group]}]}
    )
    try:
        records = ctx.pages("ec2", "describe_security_group_rules", **inputs).get(
            "SecurityGroupRules", []
        )
    except AcquisitionError as error:
        if not current or error.code != "InvalidSecurityGroupRuleId.NotFound":
            raise
        current = None
        records = ctx.pages(
            "ec2",
            "describe_security_group_rules",
            Filters=[{"Name": "group-id", "Values": [group]}],
        ).get("SecurityGroupRules", [])
    if any(v["GroupId"] != group for v in records):
        raise Unresolved("security group rule parent mismatch")
    egress = r.kind.endswith("Egress")
    candidates = [
        v for v in records if v["GroupId"] == group and v["IsEgress"] == egress
    ]
    if not current:
        expected = {
            row["property"].removeprefix(r.kind + "."): r.parse(
                row, "id" if row["property"].endswith("SecurityGroupId") else "typed"
            )
            for _, row in r.rows
            if not row["property"].endswith(".Id")
        }
        rename = {
            "CidrIp": "CidrIpv4",
            "SourceSecurityGroupId": "ReferencedGroupInfo.GroupId",
            "DestinationSecurityGroupId": "ReferencedGroupInfo.GroupId",
            "SourceSecurityGroupOwnerId": "ReferencedGroupInfo.UserId",
        }
        fields = (
            "IpProtocol",
            "FromPort",
            "ToPort",
            "CidrIpv4",
            "CidrIpv6",
            "PrefixListId",
            "ReferencedGroupInfo.GroupId",
            "Description",
        )
        rename["DestinationPrefixListId"] = "PrefixListId"
        rename["SourcePrefixListId"] = "PrefixListId"
        expected_paths = {rename.get(k, k) for k in expected}
        candidates = rule_candidates(candidates, group, egress, expected)
        candidates = [
            v
            for v in candidates
            if all(
                select(v, field) in (MISSING, None) or field in expected_paths
                for field in fields
            )
            and all(
                select(v, rename.get(k, k)) == value for k, value in expected.items()
            )
        ]
    return one(candidates, "ec2.describe_security_group_rules")
