#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from support.validator import diagnostics

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.security_group_tables_fixtures import *

@it_case
def main():
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "docs/designs/dev/123456789012/security-group.md"
        path.parent.mkdir(parents=True)
        vpc = path.with_name("vpc.md")
        vpc.write_text(VPC_DESIGN, encoding="utf-8")
        metadata = {vpc: ("vpc", ("EC2.VPC",)), path: ("security-group", ("EC2.SecurityGroup", "EC2.SecurityGroupIngress", "EC2.SecurityGroupEgress"))}

        def errors(text):
            path.write_text(text, encoding="utf-8")
            validator = VALIDATOR.Validator(root)
            validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
            validator.markdown_service_metadata(path, catalog[0])
            validator.check_design_tables(metadata, *catalog)
            validator.check_design_overviews()
            validator.check_design_links(catalog[2])
            validator.check_policy_tables()
            return diagnostics(validator)

        assert not errors(DESIGN), errors(DESIGN)
        original = path.read_bytes()
        generated = """# Synthetic authoritative Model fixture.
desired.service.security-group.serviceId=security-group
desired.service.security-group.ownedCatalogResourceTypes=EC2.SecurityGroup,EC2.SecurityGroupIngress,EC2.SecurityGroupEgress
desired.resource.001.resourceType=EC2.SecurityGroup
desired.resource.001.anchor=security-group-groupone
desired.resource.001.logicalId=GroupOne
desired.row.001-001.property=EC2.SecurityGroup.Id
desired.row.001-001.value=[GroupOne](#security-group-groupone)
desired.row.001-001.comment=一意に識別するID
observed.row.001-001.property=EC2.SecurityGroup.Id
observed.row.001-001.value=`sg-00000001`
observed.row.001-001.comment=一意に識別するID
desired.row.001-002.property=EC2.SecurityGroup.GroupDescription
desired.row.001-002.value=`Application access`
desired.row.001-002.comment=用途の説明
desired.row.001-003.property=EC2.SecurityGroup.GroupName
desired.row.001-003.value=`group-one`
desired.row.001-003.comment=名前
desired.row.001-004.property=EC2.SecurityGroup.VpcId
desired.row.001-004.value=[vpc-app-dev](vpc.md#vpc-vpc-app-dev)
desired.row.001-004.comment=所属するVPCのID
observed.row.001-004.property=EC2.SecurityGroup.VpcId
observed.row.001-004.value=vpc-00000001
observed.row.001-004.comment=所属するVPCのID
desired.row.001-005.property=EC2.SecurityGroup.SecurityGroupIngress[].IpProtocol
desired.row.001-005.value=`icmp`
desired.row.001-005.comment=通信を許可するIP protocol
desired.row.001-006.property=EC2.SecurityGroup.SecurityGroupIngress[].FromPort
desired.row.001-006.value=`8`
desired.row.001-006.comment=許可するport範囲の開始値、またはICMP type
desired.row.001-007.property=EC2.SecurityGroup.SecurityGroupIngress[].ToPort
desired.row.001-007.value=`0`
desired.row.001-007.comment=許可するport範囲の終了値、またはICMP code
desired.row.001-008.property=EC2.SecurityGroup.SecurityGroupIngress[].CidrIp
desired.row.001-008.value=`10.0.0.0/24`
desired.row.001-008.comment=通信を許可するIPv4アドレス範囲
desired.row.001-009.property=EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol
desired.row.001-009.value=`-1`
desired.row.001-009.comment=通信を許可するIP protocol
desired.row.001-010.property=EC2.SecurityGroup.SecurityGroupEgress[].CidrIp
desired.row.001-010.value=`0.0.0.0/0`
desired.row.001-010.comment=通信を許可するIPv4アドレス範囲
desired.row.001-011.property=EC2.SecurityGroup.SecurityGroupEgress[].Description
desired.row.001-011.value=`IPv4 outbound`
desired.row.001-011.comment=用途の説明
desired.row.001-012.property=EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol
desired.row.001-012.value=`-1`
desired.row.001-012.comment=通信を許可するIP protocol
desired.row.001-013.property=EC2.SecurityGroup.SecurityGroupEgress[].CidrIp
desired.row.001-013.value=`10.1.0.0/16`
desired.row.001-013.comment=通信を許可するIPv4アドレス範囲
desired.resource.002.resourceType=EC2.SecurityGroupIngress
desired.resource.002.anchor=security-group-ingressone
desired.resource.002.logicalId=IngressOne
desired.resource.002.parentProperty=EC2.SecurityGroupIngress.GroupId
desired.resource.002.parentReference=[GroupOne](#security-group-groupone)
desired.row.002-001.property=EC2.SecurityGroupIngress.Id
desired.row.002-001.value=[IngressOne](#security-group-ingressone)
desired.row.002-001.comment=一意に識別するID
observed.row.002-001.property=EC2.SecurityGroupIngress.Id
observed.row.002-001.value=`sgr-00000001`
observed.row.002-001.comment=一意に識別するID
desired.row.002-002.property=EC2.SecurityGroupIngress.IpProtocol
desired.row.002-002.value=`tcp`
desired.row.002-002.comment=通信を許可するIP protocol
desired.row.002-003.property=EC2.SecurityGroupIngress.FromPort
desired.row.002-003.value=`443`
desired.row.002-003.comment=許可するport範囲の開始値、またはICMP type
desired.row.002-004.property=EC2.SecurityGroupIngress.ToPort
desired.row.002-004.value=`443`
desired.row.002-004.comment=許可するport範囲の終了値、またはICMP code
desired.row.002-005.property=EC2.SecurityGroupIngress.SourceSecurityGroupId
desired.row.002-005.value=[GroupTwo](#security-group-grouptwo)
desired.row.002-005.comment=通信元として許可するSecurity GroupのID
observed.row.002-005.property=EC2.SecurityGroupIngress.SourceSecurityGroupId
observed.row.002-005.value=PENDING_DEPLOY
observed.row.002-005.comment=通信元として許可するSecurity GroupのID
desired.row.002-006.property=EC2.SecurityGroupIngress.SourceSecurityGroupOwnerId
desired.row.002-006.value=`123456789012`
desired.row.002-006.comment=通信元Security Groupを所有するAWS account ID
desired.row.002-007.property=EC2.SecurityGroupIngress.Description
desired.row.002-007.value=`Application access`
desired.row.002-007.comment=用途の説明
desired.resource.003.resourceType=EC2.SecurityGroupIngress
desired.resource.003.anchor=security-group-ingresstwo
desired.resource.003.logicalId=IngressTwo
desired.resource.003.parentProperty=EC2.SecurityGroupIngress.GroupId
desired.resource.003.parentReference=[GroupOne](#security-group-groupone)
desired.row.003-001.property=EC2.SecurityGroupIngress.Id
desired.row.003-001.value=[IngressTwo](#security-group-ingresstwo)
desired.row.003-001.comment=一意に識別するID
observed.row.003-001.property=EC2.SecurityGroupIngress.Id
observed.row.003-001.value=`PENDING_DEPLOY`
observed.row.003-001.comment=一意に識別するID
desired.row.003-002.property=EC2.SecurityGroupIngress.IpProtocol
desired.row.003-002.value=`icmpv6`
desired.row.003-002.comment=通信を許可するIP protocol
desired.row.003-003.property=EC2.SecurityGroupIngress.FromPort
desired.row.003-003.value=`128`
desired.row.003-003.comment=許可するport範囲の開始値、またはICMP type
desired.row.003-004.property=EC2.SecurityGroupIngress.ToPort
desired.row.003-004.value=`0`
desired.row.003-004.comment=許可するport範囲の終了値、またはICMP code
desired.row.003-005.property=EC2.SecurityGroupIngress.CidrIpv6
desired.row.003-005.value=`2001:db8::/64`
desired.row.003-005.comment=通信を許可するIPv6アドレス範囲
desired.resource.004.resourceType=EC2.SecurityGroupIngress
desired.resource.004.anchor=security-group-ingressthree
desired.resource.004.logicalId=IngressThree
desired.resource.004.parentProperty=EC2.SecurityGroupIngress.GroupId
desired.resource.004.parentReference=[GroupOne](#security-group-groupone)
desired.row.004-001.property=EC2.SecurityGroupIngress.Id
desired.row.004-001.value=[IngressThree](#security-group-ingressthree)
desired.row.004-001.comment=一意に識別するID
observed.row.004-001.property=EC2.SecurityGroupIngress.Id
observed.row.004-001.value=`PENDING_DEPLOY`
observed.row.004-001.comment=一意に識別するID
desired.row.004-002.property=EC2.SecurityGroupIngress.IpProtocol
desired.row.004-002.value=`udp`
desired.row.004-002.comment=通信を許可するIP protocol
desired.row.004-003.property=EC2.SecurityGroupIngress.FromPort
desired.row.004-003.value=`1000`
desired.row.004-003.comment=許可するport範囲の開始値、またはICMP type
desired.row.004-004.property=EC2.SecurityGroupIngress.ToPort
desired.row.004-004.value=`2000`
desired.row.004-004.comment=許可するport範囲の終了値、またはICMP code
desired.row.004-005.property=EC2.SecurityGroupIngress.SourcePrefixListId
desired.row.004-005.value=`pl-00000001`
desired.row.004-005.comment=通信元として許可するPrefix ListのID
desired.row.004-006.property=EC2.SecurityGroupIngress.Description
desired.row.004-006.value=`Prefix Listからの通信`
desired.row.004-006.comment=用途の説明
desired.resource.005.resourceType=EC2.SecurityGroupEgress
desired.resource.005.anchor=security-group-egressone
desired.resource.005.logicalId=EgressOne
desired.resource.005.parentProperty=EC2.SecurityGroupEgress.GroupId
desired.resource.005.parentReference=[GroupOne](#security-group-groupone)
desired.row.005-001.property=EC2.SecurityGroupEgress.Id
desired.row.005-001.value=[EgressOne](#security-group-egressone)
desired.row.005-001.comment=一意に識別するID
observed.row.005-001.property=EC2.SecurityGroupEgress.Id
observed.row.005-001.value=`PENDING_DEPLOY`
observed.row.005-001.comment=一意に識別するID
desired.row.005-002.property=EC2.SecurityGroupEgress.IpProtocol
desired.row.005-002.value=`-1`
desired.row.005-002.comment=通信を許可するIP protocol
desired.row.005-003.property=EC2.SecurityGroupEgress.DestinationSecurityGroupId
desired.row.005-003.value=[GroupOne](#security-group-groupone)
desired.row.005-003.comment=通信先として許可するSecurity GroupのID
observed.row.005-003.property=EC2.SecurityGroupEgress.DestinationSecurityGroupId
observed.row.005-003.value=sg-00000001
observed.row.005-003.comment=通信先として許可するSecurity GroupのID
desired.row.005-004.property=EC2.SecurityGroupEgress.Description
desired.row.005-004.value=`Security Group内の通信`
desired.row.005-004.comment=用途の説明
desired.resource.006.resourceType=EC2.SecurityGroup
desired.resource.006.anchor=security-group-grouptwo
desired.resource.006.logicalId=GroupTwo
desired.row.006-001.property=EC2.SecurityGroup.Id
desired.row.006-001.value=[GroupTwo](#security-group-grouptwo)
desired.row.006-001.comment=一意に識別するID
observed.row.006-001.property=EC2.SecurityGroup.Id
observed.row.006-001.value=`PENDING_DEPLOY`
observed.row.006-001.comment=一意に識別するID
desired.row.006-002.property=EC2.SecurityGroup.GroupDescription
desired.row.006-002.value=`No selected rules`
desired.row.006-002.comment=用途の説明
desired.row.006-003.property=EC2.SecurityGroup.VpcId
desired.row.006-003.value=[vpc-app-dev](vpc.md#vpc-vpc-app-dev)
desired.row.006-003.comment=所属するVPCのID
observed.row.006-003.property=EC2.SecurityGroup.VpcId
observed.row.006-003.value=vpc-00000001
observed.row.006-003.comment=所属するVPCのID
desired.row.006-004.property=EC2.SecurityGroup.Tags[].Key
desired.row.006-004.value="Project"
desired.row.006-004.comment=付与するタグのキー
desired.row.006-005.property=EC2.SecurityGroup.Tags[].Value
desired.row.006-005.value="app"
desired.row.006-005.comment=付与するタグの値
desired.row.006-006.property=EC2.SecurityGroup.Tags[].Key
desired.row.006-006.value="Environment"
desired.row.006-006.comment=付与するタグのキー
desired.row.006-007.property=EC2.SecurityGroup.Tags[].Value
desired.row.006-007.value="dev"
desired.row.006-007.comment=付与するタグの値
"""
        assert path.read_bytes() == original
        validator = VALIDATOR.Validator(root)
        model_path = root / "model/dev/123456789012/security-group.properties"
        model_path.parent.mkdir(parents=True)
        write_model(model_path, generated)
        assert validator.model_service_metadata(model_path, catalog[0]) == metadata[path]
        assert not validator.errors, validator.errors
        short_design = DESIGN.replace("| EC2.SecurityGroup.", "| ")
        assert not errors(short_design), errors(short_design)
        assert expanded_design(short_design.splitlines()) == expanded_design(DESIGN.splitlines())
        assert not errors(DESIGN)
        assert "observed.row.002-001.comment=一意に識別するID\n" in generated
        assert "desired.row.001-004.comment=所属するVPCのID\n" in generated
        assert "desired.row.002-005.comment=通信元として許可するSecurity GroupのID\n" in generated
        assert "comment=通信先として許可するSecurity GroupのID\n" in generated
        assert "comment=Security Group" not in generated
        assert "desired.row.001-002.property=EC2.SecurityGroup.GroupDescription\n" in generated
        assert "desired.row.001-002.value=`Application access`\n" in generated
        assert "desired.row.001-004.property=EC2.SecurityGroup.VpcId\n" in generated
        assert "desired.row.001-004.value=[vpc-app-dev](vpc.md#vpc-vpc-app-dev)\n" in generated
        assert "observed.row.001-004.value=vpc-00000001\n" in generated
        assert generated.count(".property=EC2.SecurityGroup.GroupDescription\n") == 2
        assert 'desired.row.006-004.value="Project"\n' in generated
        assert 'desired.row.006-007.value="dev"\n' in generated
        assert "desired.resource.002.resourceType=EC2.SecurityGroupIngress" in generated
        assert "desired.resource.002.logicalId=IngressOne" in generated
        assert "desired.resource.002.parentProperty=EC2.SecurityGroupIngress.GroupId" in generated
        assert "desired.resource.002.parentReference=[GroupOne](#security-group-groupone)" in generated
        assert "desired.resource.005.parentProperty=EC2.SecurityGroupEgress.GroupId" in generated
        assert "desired.resource.006.logicalId=GroupTwo" in generated
        assert "desired.row.002-001.value=[IngressOne](#security-group-ingressone)" in generated
        assert "observed.row.002-001.value=`sgr-00000001`" in generated
        assert "desired.row.002-005.value=[GroupTwo](#security-group-grouptwo)" in generated
        assert "observed.row.002-005.value=PENDING_DEPLOY" in generated
        assert "SecurityGroupRuleId" not in generated and "<!--" not in generated
        assert "desired.note." not in generated and "=—" not in generated
        assert model_projection.linked_resource(path, "[sgr-00000001](#security-group-ingressone)") == ("EC2.SecurityGroupIngress", "IngressOne")
        assert VALIDATOR.rendered_policy_design(path) == DESIGN

        normalized, children = expanded_design(DESIGN.splitlines())
        assert len(children) == 4
        assert children["security-group-ingressthree"]["logicalId"] == "IngressThree"
        assert [row[2] for row in children["security-group-ingresstwo"]["rows"]] == ["`PENDING_DEPLOY`", "`icmpv6`", "`128`", "`0`", "`2001:db8::/64`"]
        inline = [line.split(" | ")[1:3] for line in normalized if ".SecurityGroupEgress[]." in line]
        assert inline == [
            ["EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol", "`-1`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].CidrIp", "`0.0.0.0/0`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].Description", "`IPv4 outbound`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol", "`-1`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].CidrIp", "`10.1.0.0/16`"],
        ]
        # A single direction and a ruleless group need no rule table.
        inbound_only = "\n".join(line for line in DESIGN.splitlines() if not line.startswith("| Outbound")) + "\n"
        assert not errors(inbound_only), errors(inbound_only)
        assert "### EC2.SecurityGroup: GroupTwo" in DESIGN
        tag_line = next(line for line in DESIGN.splitlines() if line.startswith("<!-- security-group-tags:"))
        no_tags = DESIGN.replace(tag_line + "\n", "")
        assert not errors(no_tags), errors(no_tags)
        assert "EC2.SecurityGroup.Tags[]" not in "\n".join(security_group_table_lines(no_tags.splitlines()))
        inline_peer = DESIGN.replace(
            "| Inbound | `icmp` | `Type=8, Code=0` | `10.0.0.0/24` | — | — | — | — |",
            "| Inbound <!-- security-group-id: [PENDING_DEPLOY](#security-group-grouptwo) --> | `tcp` | `443` | — | — | — | — | — |",
        )
        assert not errors(inline_peer), errors(inline_peer)
        assert any(
            "EC2.SecurityGroup.SecurityGroupIngress[].SourceSecurityGroupId | [PENDING_DEPLOY](#security-group-grouptwo)" in line
            for line in security_group_table_lines(inline_peer.splitlines())
        )
        # No rule tables must still retain both SGs and the ruleless tags.
        rule_lines = [line for line in DESIGN.splitlines() if line.startswith(("| Direction |", "| Inbound", "| Outbound", "| --- | --- | --- | --- | --- | --- | --- | --- |"))]
        no_rules = "\n".join(line for line in DESIGN.splitlines() if line not in rule_lines) + "\n"
        for text in (no_rules, no_rules.replace(tag_line + "\n", "")):
            assert not errors(text), errors(text)
            source = path.read_bytes()
            lines, children = expanded_design(text.splitlines())
            normalized = "\n".join(lines)
            assert path.read_bytes() == source
            assert normalized.count('### EC2.SecurityGroup:') == 2
            assert '<a id="security-group-grouptwo"></a>' in normalized
            assert not children
            assert '### EC2.SecurityGroupIngress:' not in normalized
            assert '### EC2.SecurityGroupEgress:' not in normalized
            assert ('EC2.SecurityGroup.Tags[].Key' in normalized) == (tag_line in text)
        # Moving a standalone row changes its owner, not its logical or current ID.
        rule = next(line for line in DESIGN.splitlines() if 'id="security-group-egressone"' in line)
        moved = DESIGN.replace(rule + "\n", "").rstrip()
        columns = "\n".join(next(line for line in DESIGN.splitlines() if line.startswith(prefix)) for prefix in ("| Direction |", "| --- | --- | --- | --- | --- | --- | --- | --- |"))
        moved += "\n\n" + columns + "\n" + rule + "\n"
        assert not errors(moved), errors(moved)
        _, moved_children = expanded_design(moved.splitlines())
        assert moved_children["security-group-egressone"]["parentLogicalId"] == "GroupTwo"
        assert moved_children["security-group-egressone"]["logicalId"] == "EgressOne"

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
        assert "| SourceSecurityGroupId |" not in DESIGN
        assert "| DestinationSecurityGroupId |" not in DESIGN
        assert ".property=EC2.SecurityGroupIngress.SourceSecurityGroupId\n" in generated
        assert ".property=EC2.SecurityGroupEgress.DestinationSecurityGroupId\n" in generated
        assert "rule-id:" not in generated
        assert "アプリケーションの通信を制御するSG" not in generated
        assert "| Tags |" not in DESIGN
        assert "security-group-tags" not in generated
        bad = [
            (DESIGN.replace(tag_line, tag_line + "\n" + tag_line, 1), "at most one tags metadata line"),
            (DESIGN.replace(tag_line + "\n\n", "", 1).replace("| 3 | VpcId | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | 所属するVPCのID |", "| 3 | VpcId | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | 所属するVPCのID |\n" + tag_line, 1), "tags metadata must follow its detail heading"),
            (DESIGN.replace(tag_line, tag_line[:-3], 1), "invalid Security Group tags metadata"),
            (DESIGN.replace(tag_line, "<!-- security-group-tags: [] -->", 1), "Tags must be a JSON array"),
            (DESIGN.replace(tag_line, "", 1).replace("## リソース一覧", tag_line + "\n\n## リソース一覧", 1), "tags metadata must belong to EC2.SecurityGroup"),
            (DESIGN.replace("| Port |", "| FromPort |", 1), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace("| Port |", "| ToPort |", 1), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace("| SourceSecurityGroupOwnerId |", "| SourceSecurityGroupId |", 1), "omit SourceSecurityGroupId"),
            (DESIGN.replace("| SourceSecurityGroupOwnerId |", "| DestinationSecurityGroupId |", 1), "DestinationSecurityGroupId"),
            (DESIGN.replace("`443`", "`444-443`", 1), "invalid Port range"),
            (DESIGN.replace("`443`", "`65536`", 1), "outside the protocol range"),
            (DESIGN.replace("`443`", "`-1`", 1), "outside the protocol range"),
            (DESIGN.replace("`443`", "`443, 8443`", 1), "invalid Port"),
            (DESIGN.replace("`Type=128, Code=0`", "`128-0`", 1), "invalid Port"),
            (DESIGN.replace("`Type=128, Code=0`", "`Type=256, Code=0`", 1), "outside the protocol range"),
            (DESIGN.replace("`Type=128, Code=0`", "`Type=-1, Code=0`", 1), "invalid Port range"),
            (DESIGN.replace("<!-- rule-id: `sgr-00000001` -->", "", 1), "requires complete anchor/logical-id/rule-id markers"),
            (DESIGN.replace("<!-- security-group-id: [PENDING_DEPLOY](#security-group-grouptwo) -->", "<!-- security-group-id: -->", 1), "invalid Security Group reference metadata"),
            (DESIGN.replace("<!-- security-group-id: [PENDING_DEPLOY](#security-group-grouptwo) -->", "<!-- security-group-id: — -->", 1), "invalid Security Group reference metadata"),
            (DESIGN.replace("| Inbound <", "| inbound <", 1), "requires complete anchor/logical-id/rule-id markers"),
            (DESIGN.replace("rule-id: `sgr-00000001`", "rule-id: `—`", 1), "requires an Id"),
            (DESIGN.replace(" | `tcp` |", " | <!-- rule-id: `sgr-00000001` --> `tcp` |", 1), "identity must be in Direction"),
            (DESIGN.replace('<!-- logical-id: IngressOne -->', ''), "requires complete anchor/logical-id/rule-id markers"),
            (DESIGN.replace('id="security-group-ingressone"', 'id="security-group-wrong"'), "logical ID/anchor"),
            (DESIGN.replace('<!-- logical-id: IngressTwo -->', '<!-- logical-id: IngressOne -->'), "duplicate grouped logical ID"),
            (DESIGN.replace('id="security-group-ingresstwo"', 'id="security-group-ingressone"'), "duplicate resource anchor"),
            (DESIGN.replace('rule-id: `PENDING_DEPLOY` -->', 'rule-id: `sgr-00000001` -->', 1), "duplicate grouped identity value"),
            (DESIGN.replace('| Inbound |', '| inbound |', 1), "Direction must be Inbound or Outbound"),
            (DESIGN.replace('| Inbound <', '| Outbound <', 1), "do not match Direction"),
            (DESIGN.replace('| SourcePrefixListId |', '| DestinationPrefixListId |', 1), "do not match Direction"),
            (DESIGN.replace('| IpProtocol |', '| Type |', 1), "invalid Security Group Direction rule table columns"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '—', 1), "requires Id, GroupDescription and VpcId detail values"),
            (DESIGN.replace('| `Application access` |', '| — |', 1), "requires Id, GroupDescription and VpcId detail values"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '[vpc-wrong](vpc.md#vpc-vpc-app-dev)', 1), "identifier reference does not match"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '`vpc-00000001`', 1), "VpcId must link to its VPC"),
            (DESIGN.replace('[vpc-00000001](vpc.md#vpc-vpc-app-dev)', '[sg-00000001](#security-group-groupone)', 1), "VpcId must link to a VPC in the same target"),
            (DESIGN.replace('[GroupOne](#security-group-groupone)', '[GroupOne](#security-group-grouptwo)', 1), "overview link must match"),
            (DESIGN.replace('[GroupTwo](#security-group-grouptwo)', '[GroupOne](#security-group-grouptwo)', 1), "unique logical ID link"),
            (DESIGN.replace('"Value":"app"', '"Wrong":"app"', 1), "Tags must be a JSON array"),
            (DESIGN.replace(' | `443` |', ' | `invalid` |', 1), "invalid Port"),
            (DESIGN.replace(' | `tcp` |', ' | — |', 1), "requires IpProtocol"),
            (DESIGN.replace(' | `tcp` | `443` | — | — | — | `123456789012` |', ' | `tcp` | `443` | `10.0.0.0/24` | — | — | `123456789012` |', 1), "exactly one address"),
            (DESIGN.replace('[PENDING_DEPLOY](#security-group-grouptwo)', '[sg-wrong](#security-group-grouptwo)', 1), "identifier reference does not match"),
            (DESIGN.replace('### EC2.SecurityGroup: GroupOne', '### EC2.Instance: GroupOne'), "rule table must belong to EC2.SecurityGroup"),
            (DESIGN + '\n<a id="security-group-oldrule"></a>\n### EC2.SecurityGroupIngress: OldRule\n', "must use a horizontal Direction"),
        ]
        for text, message in bad:
            failures = errors(text)
            assert any(message in error for error in failures), (message, failures)
        for text in (DESIGN.replace('| Inbound |', '| invalid |', 1), DESIGN.replace(' | `tcp` |', ' | — |', 1), DESIGN + "\n| Direction | IpProtocol | Port |\n| --- | --- | --- |\n"):
            path.write_text(text, encoding="utf-8")
            try:
                expanded_design(path.read_text().splitlines())
            except ValueError:
                pass
            else:
                raise AssertionError("invalid horizontal rule must not generate a model")
    print("security-group-tables: PASS (detail attributes, Direction/Port rules, inline boundaries, identities, ownership, schema, references)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        main()

