#!/usr/bin/env python3
"""Check horizontal SG rules, catalog validation, model ownership and references."""

import importlib.util
import tempfile
from pathlib import Path

from design_layout import LAYOUTS, expanded_design, layout_errors
from security_group_tables import COMMENTS, DIRECTIONS, port_properties, security_group_table_lines


REPOSITORY = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load("validate-blueprint")
MODEL = load("sync-model")
DESIGN = """# Security Group 詳細設計

- Design service ID: `ec2`
- Owned catalog resource types: `EC2.SecurityGroup`, `EC2.SecurityGroupIngress`, `EC2.SecurityGroupEgress`

## リソース一覧

### EC2.SecurityGroup

| SecurityGroup | GroupName | Id | VpcId | Description | Tags |
| --- | --- | --- | --- | --- | --- |
| [GroupOne](#ec2-groupone) | `group-one` | `sg-00000001` | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | `Application access` | `[{"Key":"Project","Value":"app"},{"Key":"Environment","Value":"dev"}]` |
| [GroupTwo](#ec2-grouptwo) | — | `PENDING_DEPLOY` | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | `No selected rules` | — |

## リソース詳細

<a id="ec2-groupone"></a>

### EC2.SecurityGroup: GroupOne

| Direction | IpProtocol | Port | CidrIp | CidrIpv6 | SourcePrefixListId | SourceSecurityGroupId | SourceSecurityGroupOwnerId | DestinationSecurityGroupId | Description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Inbound <a id="ec2-ingressone"></a><!-- logical-id: IngressOne --><!-- rule-id: `sgr-00000001` --> | `tcp` | `443` | — | — | — | [PENDING_DEPLOY](#ec2-grouptwo) | `123456789012` | — | `Application access` |
| Inbound <a id="ec2-ingresstwo"></a><!-- logical-id: IngressTwo --><!-- rule-id: `PENDING_DEPLOY` --> | `icmpv6` | `Type=128, Code=0` | — | `2001:db8::/64` | — | — | — | — | — |
| Inbound <a id="ec2-ingressthree"></a><!-- logical-id: IngressThree --><!-- rule-id: `PENDING_DEPLOY` --> | `udp` | `1000-2000` | — | — | `pl-00000001` | — | — | — | `Prefix Listからの通信` |
| Inbound | `icmp` | `Type=8, Code=0` | `10.0.0.0/24` | — | — | — | — | — | — |
| Outbound <a id="ec2-egressone"></a><!-- logical-id: EgressOne --><!-- rule-id: `PENDING_DEPLOY` --> | `-1` | — | — | — | — | — | — | [sg-00000001](#ec2-groupone) | `Security Group内の通信` |
| Outbound | `-1` | — | `0.0.0.0/0` | — | — | — | — | — | `IPv4 outbound` |
| Outbound | `-1` | — | `10.1.0.0/16` | — | — | — | — | — | — |

<a id="ec2-grouptwo"></a>

### EC2.SecurityGroup: GroupTwo

| Direction | IpProtocol | Port |
| --- | --- | --- |
"""
VPC_DESIGN = """# Amazon VPC 詳細設計

- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`

## リソース一覧

### EC2.VPC

| VPC | CidrBlock |
| --- | --- |
| [vpc-app-dev](#vpc-vpc-app-dev) | `10.0.0.0/16` |

## リソース詳細

<a id="vpc-vpc-app-dev"></a>

### EC2.VPC: vpc-app-dev

| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
| 1 | EC2.VPC.VpcId | `vpc-00000001` | VPCを一意に識別するID |
| 2 | EC2.VPC.Name | vpc-app-dev | VPCを識別する名前 |
| 3 | EC2.VPC.CidrBlock | `10.0.0.0/16` | VPCで使用するIPv4アドレス範囲 |
"""


def main():
    assert not layout_errors(REPOSITORY)
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    # Every supported horizontal field resolves to both standalone and inline catalogs.
    for direction in DIRECTIONS.values():
        resource_type = f"EC2.SecurityGroup{direction}"
        assert LAYOUTS[resource_type]["display"] == "rule-table"
        selected = {prop.rsplit(".", 1)[1] for prop, owners in catalog[1].items() if resource_type in owners and prop.startswith(resource_type + ".")}
        assert selected - {"GroupId"} <= COMMENTS.keys()
        for prop in selected - {"GroupId", "Id"}:
            assert "EC2.SecurityGroup" in catalog[1][f"EC2.SecurityGroup.SecurityGroup{direction}[].{prop}"]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/ec2.md"
        path.parent.mkdir(parents=True)
        vpc = path.with_name("vpc.md")
        vpc.write_text(VPC_DESIGN, encoding="utf-8")
        metadata = {vpc: ("vpc", ("EC2.VPC",)), path: ("ec2", ("EC2.SecurityGroup", "EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"))}

        def errors(text):
            path.write_text(text, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.check_design_tables(metadata, *catalog)
            validator.check_design_overviews()
            validator.check_design_links(catalog[2])
            validator.check_policy_tables()
            return validator.errors

        assert not errors(DESIGN), errors(DESIGN)
        original = path.read_bytes()
        generated = MODEL.model_for(path, REPOSITORY)
        assert path.read_bytes() == original
        assert "desired.row.001-002.property=EC2.SecurityGroup.GroupDescription\n" in generated
        assert "desired.row.001-002.value=`Application access`\n" in generated
        assert "desired.row.001-004.property=EC2.SecurityGroup.VpcId\n" in generated
        assert "desired.row.001-004.value=[vpc-app-dev](vpc.md#vpc-vpc-app-dev)\n" in generated
        assert "observed.row.001-004.value=vpc-00000001\n" in generated
        assert generated.count(".property=EC2.SecurityGroup.GroupDescription\n") == 2
        assert 'desired.row.001-005.value="Project"\n' in generated
        assert 'desired.row.001-008.value="dev"\n' in generated
        assert "desired.resource.002.resourceType=EC2.SecurityGroupIngress" in generated
        assert "desired.resource.002.logicalId=IngressOne" in generated
        assert "desired.resource.002.parentProperty=EC2.SecurityGroupIngress.GroupId" in generated
        assert "desired.resource.002.parentReference=[GroupOne](#ec2-groupone)" in generated
        assert "desired.resource.005.parentProperty=EC2.SecurityGroupEgress.GroupId" in generated
        assert "desired.resource.006.logicalId=GroupTwo" in generated
        assert "desired.row.002-001.value=[IngressOne](#ec2-ingressone)" in generated
        assert "observed.row.002-001.value=`sgr-00000001`" in generated
        assert "desired.row.002-005.value=[GroupTwo](#ec2-grouptwo)" in generated
        assert "observed.row.002-005.value=PENDING_DEPLOY" in generated
        assert "SecurityGroupRuleId" not in generated and "<!--" not in generated
        assert "desired.note." not in generated and "=—" not in generated
        assert MODEL.linked_resource(path, "[sgr-00000001](#ec2-ingressone)") == ("EC2.SecurityGroupIngress", "IngressOne")
        assert VALIDATOR.rendered_policy_design(path) == DESIGN

        normalized, children = expanded_design(DESIGN.splitlines())
        assert len(children) == 4
        assert children["ec2-ingressthree"]["logicalId"] == "IngressThree"
        assert [row[2] for row in children["ec2-ingresstwo"]["rows"]] == ["`PENDING_DEPLOY`", "`icmpv6`", "`128`", "`0`", "`2001:db8::/64`"]
        inline = [line.split(" | ")[1:3] for line in normalized if ".SecurityGroupEgress[]." in line]
        assert inline == [
            ["EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol", "`-1`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].CidrIp", "`0.0.0.0/0`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].Description", "`IPv4 outbound`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol", "`-1`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].CidrIp", "`10.1.0.0/16`"],
        ]
        # A single direction and an overview without optional Tags need no extra table.
        inbound_only = "\n".join(line for line in DESIGN.splitlines() if not line.startswith("| Outbound")) + "\n"
        assert not errors(inbound_only), errors(inbound_only)
        no_tags = "\n".join(
            line.rsplit("|", 2)[0].rstrip() + " |" if line.startswith(("| SecurityGroup |", "| [Group", "| --- | --- | --- | --- | --- | --- |")) and len(line.split("|")) == 8 else line
            for line in DESIGN.splitlines()
        ) + "\n"
        assert not errors(no_tags), errors(no_tags)
        assert "EC2.SecurityGroup.Tags[]" not in "\n".join(security_group_table_lines(no_tags.splitlines()))
        # Moving a standalone row changes its owner, not its logical or current ID.
        rule = next(line for line in DESIGN.splitlines() if 'id="ec2-egressone"' in line)
        moved = DESIGN.replace(rule + "\n", "").rstrip()
        empty = "| Direction | IpProtocol | Port |\n| --- | --- | --- |"
        columns = "\n".join(next(line for line in DESIGN.splitlines() if line.startswith(prefix)) for prefix in ("| Direction |", "| --- | --- | --- | --- | --- | --- | --- |"))
        position = moved.rfind(empty)
        moved = moved[:position] + columns + "\n" + rule + "\n"
        assert not errors(moved), errors(moved)
        _, moved_children = expanded_design(moved.splitlines())
        assert moved_children["ec2-egressone"]["parentLogicalId"] == "GroupTwo"
        assert moved_children["ec2-egressone"]["logicalId"] == "EgressOne"

        assert "| FromPort |" not in DESIGN and "| ToPort |" not in DESIGN
        assert ".property=Port\n" not in generated
        for protocol, display, first, last in (
            ("tcp", "443", 443, 443), ("udp", "1000-2000", 1000, 2000),
            ("6", "0-65535", 0, 65535), ("17", "53", 53, 53),
            ("icmp", "Type=8, Code=0", 8, 0), ("58", "Type=128, Code=0", 128, 0),
            ("1", "Type=-1, Code=-1", -1, -1), ("icmpv6", "Type=128, Code=-1", 128, -1),
        ):
            assert port_properties(display, protocol) == {"FromPort": f"`{first}`", "ToPort": f"`{last}`"}
        assert port_properties("—", "-1") == {}
        assert port_properties("—", "icmpv6") == {}
        assert "SecurityGroupRuleId" not in DESIGN
        assert "rule-id:" not in generated
        bad = [
            (DESIGN.replace("| Port |", "| FromPort |", 1), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace("| Port |", "| ToPort |", 1), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace("`443`", "`444-443`", 1), "invalid Port range"),
            (DESIGN.replace("`443`", "`65536`", 1), "outside the protocol range"),
            (DESIGN.replace("`443`", "`-1`", 1), "outside the protocol range"),
            (DESIGN.replace("`443`", "`443, 8443`", 1), "invalid Port"),
            (DESIGN.replace("`Type=128, Code=0`", "`128-0`", 1), "invalid Port"),
            (DESIGN.replace("`Type=128, Code=0`", "`Type=256, Code=0`", 1), "outside the protocol range"),
            (DESIGN.replace("`Type=128, Code=0`", "`Type=-1, Code=0`", 1), "invalid Port range"),
            (DESIGN.replace("| Direction | IpProtocol | Port |\n| --- | --- | --- |", "| Direction | SecurityGroupRuleId | IpProtocol | Port |\n| --- | --- | --- | --- |"), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace("<!-- rule-id: `sgr-00000001` -->", "", 1), "requires complete anchor/logical-id/rule-id markers"),
            (DESIGN.replace("| Inbound <", "| inbound <", 1), "requires complete anchor/logical-id/rule-id markers"),
            (DESIGN.replace("rule-id: `sgr-00000001`", "rule-id: `—`", 1), "requires an Id"),
            (DESIGN.replace(" | `tcp` |", " | <!-- rule-id: `sgr-00000001` --> `tcp` |", 1), "identity must be in Direction"),
            (DESIGN.replace('<!-- logical-id: IngressOne -->', ''), "requires complete anchor/logical-id/rule-id markers"),
            (DESIGN.replace('id="ec2-ingressone"', 'id="ec2-wrong"'), "logical ID/anchor"),
            (DESIGN.replace('<!-- logical-id: IngressTwo -->', '<!-- logical-id: IngressOne -->'), "duplicate grouped logical ID"),
            (DESIGN.replace('id="ec2-ingresstwo"', 'id="ec2-ingressone"'), "duplicate resource anchor"),
            (DESIGN.replace('rule-id: `PENDING_DEPLOY` -->', 'rule-id: `sgr-00000001` -->', 1), "duplicate grouped identity value"),
            (DESIGN.replace('| Inbound |', '| inbound |', 1), "Direction must be Inbound or Outbound"),
            (DESIGN.replace('| Inbound <', '| Outbound <', 1), "do not match Direction"),
            (DESIGN.replace('| SourcePrefixListId |', '| DestinationPrefixListId |', 1), "do not match Direction"),
            (DESIGN.replace('| IpProtocol |', '| Type |', 1), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace('| VpcId |', '| Region |', 1), "overview requires SecurityGroup"),
            (DESIGN.replace('| Description | Tags |', '| GroupDescription | Tags |', 1), "overview requires SecurityGroup"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '—', 1), "requires Id, VpcId and Description values"),
            (DESIGN.replace('`Application access` | `[{', '— | `[{', 1), "requires Id, VpcId and Description values"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '[vpc-wrong](vpc.md#vpc-vpc-app-dev)', 1), "identifier reference does not match"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '`vpc-00000001`', 1), "VpcId must link to its VPC"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '[sg-00000001](#ec2-groupone)', 1), "VpcId must link to a VPC in the same target"),
            (DESIGN.replace('[GroupOne](#ec2-groupone)', '[GroupOne](#ec2-grouptwo)', 1), "overview link must match"),
            (DESIGN.replace('[GroupTwo](#ec2-grouptwo)', '[GroupOne](#ec2-grouptwo)', 1), "unique logical ID link"),
            (DESIGN.replace('"Value":"app"', '"Wrong":"app"', 1), "Tags must be a JSON array"),
            (DESIGN + "\n| Direction | IpProtocol | Port |\n| --- | --- | --- |\n", "requires one Direction rule table"),
            (DESIGN.replace(' | `443` |', ' | `invalid` |', 1), "invalid Port"),
            (DESIGN.replace(' | `tcp` |', ' | — |', 1), "requires IpProtocol"),
            (DESIGN.replace(' | — | — | — | [PENDING_DEPLOY]', ' | `10.0.0.0/24` | — | — | [PENDING_DEPLOY]', 1), "exactly one address"),
            (DESIGN.replace('[PENDING_DEPLOY](#ec2-grouptwo)', '[sg-wrong](#ec2-grouptwo)', 1), "identifier reference does not match"),
            (DESIGN.replace('### EC2.SecurityGroup: GroupOne', '### EC2.Instance: GroupOne'), "must belong to EC2.SecurityGroup"),
            (DESIGN.replace("| Direction | IpProtocol | Port |\n| --- | --- | --- |", "| No. | Property | Value | Source / Comment |\n| --- | --- | --- | --- |"), "omit the basic property table"),
            (DESIGN + '\n<a id="ec2-oldrule"></a>\n### EC2.SecurityGroupIngress: OldRule\n', "must use a horizontal Direction"),
        ]
        for text, message in bad:
            failures = errors(text)
            assert any(message in error for error in failures), (message, failures)
        for text in (DESIGN.replace('| Inbound |', '| invalid |', 1), DESIGN.replace(' | `tcp` |', ' | — |', 1)):
            path.write_text(text, encoding="utf-8")
            try:
                MODEL.model_for(path, REPOSITORY)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid horizontal rule must not generate a model")
    print("security-group-tables: PASS (overview attributes, Direction/Port rules, inline boundaries, identities, ownership, schema, references)")


if __name__ == "__main__":
    main()
