#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aws_mapping_display import selected_rows
from comparison.values import desired_value
from design.catalog import DesignSchemaCatalog
from design.services.ec2.security_groups import cells, sg_tables
from model.core import literal, properties
from model.sources import runtime_values
from support.fixture_cases import load_case, load_suite
from support.security_group_tables_fixtures import (
    COMMENTS,
    DESIGN,
    DIRECTIONS,
    GENERATED_MODEL,
    LAYOUTS,
    REPOSITORY,
    VALIDATOR,
    VPC_DESIGN,
    Path,
    expanded_design,
    layout_errors,
    model_projection,
    port_properties,
    security_group_table_lines,
    sys,
    tempfile,
)
from support.validator import diagnostics
from utils.iac_values import same

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_rule_catalog():
    assert not layout_errors(REPOSITORY)
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    # Every supported horizontal field resolves to both standalone and inline catalogs.
    for direction in DIRECTIONS.values():
        resource_type = f"EC2.SecurityGroup{direction}"
        assert LAYOUTS[resource_type]["display"] == "rule-table"
        selected = {
            prop.rsplit(".", 1)[1]
            for prop, owners in catalog[1].items()
            if resource_type in owners and prop.startswith(resource_type + ".")
        }
        assert selected - {"GroupId"} <= COMMENTS.keys()
        for prop in selected - {"GroupId", "Id"}:
            assert (
                "EC2.SecurityGroup"
                in catalog[1][f"EC2.SecurityGroup.SecurityGroup{direction}[].{prop}"]
            )


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


def check_tag_scalars():
    fixture = load_suite("security_group_tables")
    prefix, _ = DESIGN.split("### EC2.SecurityGroup: GroupTwo", 1)
    for name in sorted(fixture["cases"].keys() - {"invalid-metadata"}):
        case = load_case("security_group_tables", name)
        rows = [
            [f"006-{number:03}", "EC2.SecurityGroup." + prop, value, comment]
            for number, (prop, value, comment) in enumerate(case["data"]["basic"], 1)
        ]
        expected = [
            dict(zip(("Key", "Value"), case["expected"], strict=False)),
            {"Key": "Environment", "Value": "dev"},
        ]
        for pair in (case["data"]["scalars"], list(expected[1].values())):
            for prop, value in zip(("Key", "Value"), pair, strict=False):
                rows.append(
                    [
                        f"006-{len(rows) + 1:03}",
                        "EC2.SecurityGroup.Tags[]." + prop,
                        value,
                        "タグ",
                    ]
                )
        consumed = []
        block = sg_tables(selected_rows(rows), [], consumed=consumed)
        assert consumed == [row[0] for row in rows]
        metadata = (
            block[0].removeprefix("<!-- security-group-tags: ").removesuffix(" -->")
        )
        assert json.loads(metadata) == expected, name
        assert "<!--" not in metadata and "-->" not in metadata
        text = prefix + "### EC2.SecurityGroup: GroupTwo\n\n" + "\n".join(block)
        restored = security_group_table_lines(text.splitlines())
        owners = {}
        for line in restored:
            if line.startswith("### EC2.SecurityGroup:"):
                owner = line
                owners[owner] = []
            elif line.startswith("|") and "EC2.SecurityGroup.Tags[]." in line:
                owners[owner].append(cells(line)[1:3])
        assert owners["### EC2.SecurityGroup: GroupOne"] == []
        assert owners["### EC2.SecurityGroup: GroupTwo"] == [
            ["EC2.SecurityGroup.Tags[]." + prop, tag[prop]]
            for tag in expected
            for prop in ("Key", "Value")
        ]
        assert "| 3 | GroupName | group-two |" in text
        # The existing comparison must keep these schema-typed scalars as strings.
        context = SimpleNamespace(
            catalog=DesignSchemaCatalog(REPOSITORY), local_comparison=True
        )
        for row in rows[4:]:
            value = desired_value(
                "security-group",
                {"property": row[1], "value": row[2]},
                "EC2.SecurityGroup",
                local_comparison=True,
                property_schema=context.catalog.property_schema,
                desired_reference=None,
                evaluate=None,
                model_path=None,
            ).require_value()
            assert same(value, literal(row[2])) is True
        with patch(
            "aws_mapping_display.show",
            side_effect=lambda prop, root: not prop.endswith("Tags[].Value"),
        ):
            hidden = sg_tables(selected_rows(rows), [])
        assert not any("security-group-tags:" in line for line in hidden)


def check_invalid_tag_metadata():
    marker = next(
        line
        for line in DESIGN.splitlines()
        if line.startswith("<!-- security-group-tags:")
    )
    for metadata in load_case("security_group_tables", "invalid-metadata")["data"][
        "metadata"
    ]:
        with pytest.raises(ValueError, match="Security Group (Tags|tags)"):
            security_group_table_lines(
                DESIGN.replace(
                    marker, "<!-- security-group-tags: " + metadata + " -->"
                ).splitlines()
            )


def check_service_filenames(tmp_path):
    root = tmp_path
    path = root / "security-group.md"
    for filename, service, kinds in (
        ("ec2.md", "ec2", ("EC2.SecurityGroup",)),
        ("ec2.properties", "ec2", ("EC2.SecurityGroupIngress",)),
        ("security-group.md", "security-group", ("EC2.Instance",)),
        ("security-group.md", "security-group", ("EC2.SecurityGroup", "EC2.VPC")),
        ("security_group.md", "security_group", ("EC2.SecurityGroup",)),
        ("security_group.properties", "security_group", ("EC2.SecurityGroup",)),
        ("other_service.md", "other_service", ("S3.Bucket",)),
    ):
        invalid = VALIDATOR.Validator(root)
        invalid.check_service_file(path.with_name(filename), service, kinds)
        assert invalid.errors, (filename, service, kinds)


def _callback_main_errors(catalog, metadata, path, root, /, text, *, saved=True):
    path.write_text(text, encoding="utf-8")
    validator = VALIDATOR.Validator(root)
    values = {
        key: raw
        for key, raw in properties(GENERATED_MODEL).items()
        if not (key.startswith("observed.") and key.endswith((".property", ".comment")))
    }
    if saved:
        validator.design_sources = {path: runtime_values(values)}
    validator.schema_catalog = VALIDATOR.DesignSchemaCatalog(REPOSITORY)
    validator.markdown_service_metadata(path, catalog[0])
    validator.check_design_tables(metadata, *catalog)
    validator.check_design_overviews()
    validator.check_design_links(catalog[2])
    validator.check_policy_tables()
    return diagnostics(validator)


def check_table_conditions():
    catalog = VALIDATOR.Validator(REPOSITORY).catalog_design_properties()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (root / "project.json").write_text(
            __import__("json").dumps(
                {
                    "targets": [
                        {
                            "environment": "dev",
                            "awsAccountId": "123456789012",
                            "awsRegion": "ap-northeast-1",
                            "iacEngine": "cloudformation",
                        }
                    ]
                }
            )
            + "\n"
        )
        path = root / "docs/designs/dev/123456789012/security-group.md"
        path.parent.mkdir(parents=True)
        vpc = path.with_name("vpc.md")
        vpc.write_text(VPC_DESIGN, encoding="utf-8")
        metadata = {
            vpc: ("vpc", ("EC2.VPC",)),
            path: (
                "security-group",
                (
                    "EC2.SecurityGroup",
                    "EC2.SecurityGroupIngress",
                    "EC2.SecurityGroupEgress",
                ),
            ),
        }

        errors = _bind_framework_callback(
            _callback_main_errors, catalog, metadata, path, root
        )

        assert not errors(
            DESIGN.replace(
                "resource-EC2_SecurityGroup_001", "security-group-groupone"
            ).replace("resource-EC2_SecurityGroup_002", "security-group-grouptwo"),
            saved=False,
        ), errors(path.read_text(), saved=False)
        short_design = DESIGN.replace("| EC2.SecurityGroup.", "| ")
        assert not errors(short_design), errors(short_design)
        assert expanded_design(short_design.splitlines()) == expanded_design(
            DESIGN.splitlines()
        )
        assert not errors(DESIGN)
        assert model_projection.linked_resource(
            path, "[sgr-00000001](#resource-EC2_SecurityGroupIngress_001)"
        ) == ("EC2.SecurityGroupIngress", "EC2_SecurityGroupIngress_001")
        assert VALIDATOR.rendered_policy_design(path) == DESIGN

        normalized, children = expanded_design(DESIGN.splitlines())
        assert len(children) == 4
        assert (
            children["resource-EC2_SecurityGroupIngress_003"]["logicalId"]
            == "EC2_SecurityGroupIngress_003"
        )
        assert [
            row[2] for row in children["resource-EC2_SecurityGroupIngress_002"]["rows"]
        ] == ["`PENDING_DEPLOY`", "`icmpv6`", "`128`", "`0`", "`2001:db8::/64`"]
        inline = [
            line.split(" | ")[1:3]
            for line in normalized
            if ".SecurityGroupEgress[]." in line
        ]
        assert inline == [
            ["EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol", "`-1`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].CidrIp", "`0.0.0.0/0`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].Description", "`IPv4 outbound`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol", "`-1`"],
            ["EC2.SecurityGroup.SecurityGroupEgress[].CidrIp", "`10.1.0.0/16`"],
        ]
        # A single direction and a ruleless group need no rule table.
        inbound_only = (
            "\n".join(
                line
                for line in DESIGN.splitlines()
                if not line.startswith("| Outbound")
            )
            + "\n"
        )
        assert not errors(inbound_only), errors(inbound_only)
        assert "### EC2.SecurityGroup: GroupTwo" in DESIGN
        tag_line = next(
            line
            for line in DESIGN.splitlines()
            if line.startswith("<!-- security-group-tags:")
        )
        no_tags = DESIGN.replace(tag_line + "\n", "")
        assert not errors(no_tags), errors(no_tags)
        assert "EC2.SecurityGroup.Tags[]" not in "\n".join(
            security_group_table_lines(no_tags.splitlines())
        )
        inline_peer = DESIGN.replace(
            "| Inbound | `icmp` | `Type=8, Code=0` | `10.0.0.0/24` | — | — | — | — |",
            "| Inbound <!-- security-group-id: [PENDING_DEPLOY](#resource-EC2_SecurityGroup_002) --> | `tcp` | `443` | — | — | — | — | — |",
        )
        assert not errors(inline_peer), errors(inline_peer)
        assert any(
            "EC2.SecurityGroup.SecurityGroupIngress[].SourceSecurityGroupId | [PENDING_DEPLOY](#resource-EC2_SecurityGroup_002)"
            in line
            for line in security_group_table_lines(inline_peer.splitlines())
        )
        # No rule tables must still retain both SGs and the ruleless tags.
        rule_lines = [
            line
            for line in DESIGN.splitlines()
            if line.startswith(
                (
                    "| Direction |",
                    "| Inbound",
                    "| Outbound",
                    "| --- | --- | --- | --- | --- | --- | --- | --- |",
                )
            )
        ]
        no_rules = (
            "\n".join(line for line in DESIGN.splitlines() if line not in rule_lines)
            + "\n"
        )
        for text in (no_rules, no_rules.replace(tag_line + "\n", "")):
            assert not errors(text), errors(text)
            source = path.read_bytes()
            lines, children = expanded_design(text.splitlines())
            normalized = "\n".join(lines)
            assert path.read_bytes() == source
            assert normalized.count("### EC2.SecurityGroup:") == 2
            assert '<a id="resource-EC2_SecurityGroup_002"></a>' in normalized
            assert not children
            assert "### EC2.SecurityGroupIngress:" not in normalized
            assert "### EC2.SecurityGroupEgress:" not in normalized
            assert ("EC2.SecurityGroup.Tags[].Key" in normalized) == (tag_line in text)
        # Moving a standalone row changes its owner, not its logical or current ID.
        rule = next(
            line
            for line in DESIGN.splitlines()
            if 'id="resource-EC2_SecurityGroupEgress_001"' in line
        )
        moved = DESIGN.replace(rule + "\n", "").rstrip()
        columns = "\n".join(
            next(line for line in DESIGN.splitlines() if line.startswith(prefix))
            for prefix in (
                "| Direction |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            )
        )
        moved += "\n\n" + columns + "\n" + rule + "\n"
        assert not errors(moved), errors(moved)
        _, moved_children = expanded_design(moved.splitlines())
        assert (
            moved_children["resource-EC2_SecurityGroupEgress_001"]["parentLogicalId"]
            == "EC2_SecurityGroup_002"
        )
        assert (
            moved_children["resource-EC2_SecurityGroupEgress_001"]["logicalId"]
            == "EC2_SecurityGroupEgress_001"
        )

        assert "| FromPort |" not in DESIGN and "| ToPort |" not in DESIGN
        for protocol, display, first, last in (
            ("tcp", "443", 443, 443),
            ("udp", "1000-2000", 1000, 2000),
            ("6", "0-65535", 0, 65535),
            ("17", "53", 53, 53),
            ("icmp", "Type=8, Code=0", 8, 0),
            ("58", "Type=128, Code=0", 128, 0),
            ("1", "Type=-1, Code=-1", -1, -1),
            ("icmpv6", "Type=128, Code=-1", 128, -1),
        ):
            assert port_properties(display, protocol) == {
                "FromPort": f"`{first}`",
                "ToPort": f"`{last}`",
            }
        assert port_properties("—", "-1") == {}
        assert port_properties("—", "icmpv6") == {}
        assert "SecurityGroupRuleId" not in DESIGN
        assert "| SourceSecurityGroupId |" not in DESIGN
        assert "| DestinationSecurityGroupId |" not in DESIGN
        assert "| Tags |" not in DESIGN
        bad = [
            (
                DESIGN.replace(tag_line, tag_line + "\n" + tag_line, 1),
                "at most one tags metadata line",
            ),
            (
                DESIGN.replace(tag_line + "\n\n", "", 1).replace(
                    "| 3 | VpcId | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | 所属するVPCのID |",
                    "| 3 | VpcId | [vpc-00000001](vpc.md#vpc-vpc-app-dev) | 所属するVPCのID |\n"
                    + tag_line,
                    1,
                ),
                "tags metadata must follow its detail heading",
            ),
            (
                DESIGN.replace(tag_line, tag_line[:-3], 1),
                "invalid Security Group tags metadata",
            ),
            (
                DESIGN.replace(tag_line, "<!-- security-group-tags: [] -->", 1),
                "Tags must be a JSON array",
            ),
            (
                DESIGN.replace(tag_line, "", 1).replace(
                    "## リソース一覧", tag_line + "\n\n## リソース一覧", 1
                ),
                "tags metadata must belong to EC2.SecurityGroup",
            ),
            (
                DESIGN.replace("| Port |", "| FromPort |", 1),
                "invalid Security Group Direction rule table columns",
            ),
            (
                DESIGN.replace("| Port |", "| ToPort |", 1),
                "invalid Security Group Direction rule table columns",
            ),
            (
                DESIGN.replace(
                    "| SourceSecurityGroupOwnerId |", "| SourceSecurityGroupId |", 1
                ),
                "omit SourceSecurityGroupId",
            ),
            (
                DESIGN.replace(
                    "| SourceSecurityGroupOwnerId |",
                    "| DestinationSecurityGroupId |",
                    1,
                ),
                "DestinationSecurityGroupId",
            ),
            (DESIGN.replace("`443`", "`444-443`", 1), "invalid Port range"),
            (DESIGN.replace("`443`", "`65536`", 1), "outside the protocol range"),
            (DESIGN.replace("`443`", "`-1`", 1), "outside the protocol range"),
            (DESIGN.replace("`443`", "`443, 8443`", 1), "invalid Port"),
            (DESIGN.replace("`Type=128, Code=0`", "`128-0`", 1), "invalid Port"),
            (
                DESIGN.replace("`Type=128, Code=0`", "`Type=256, Code=0`", 1),
                "outside the protocol range",
            ),
            (
                DESIGN.replace("`Type=128, Code=0`", "`Type=-1, Code=0`", 1),
                "invalid Port range",
            ),
            (
                DESIGN.replace("<!-- rule-id: `sgr-00000001` -->", "", 1),
                "requires complete anchor/logical-id/rule-id markers",
            ),
            (
                DESIGN.replace(
                    "<!-- security-group-id: [PENDING_DEPLOY](#resource-EC2_SecurityGroup_002) -->",
                    "<!-- security-group-id: -->",
                    1,
                ),
                "invalid Security Group reference metadata",
            ),
            (
                DESIGN.replace(
                    "<!-- security-group-id: [PENDING_DEPLOY](#resource-EC2_SecurityGroup_002) -->",
                    "<!-- security-group-id: — -->",
                    1,
                ),
                "invalid Security Group reference metadata",
            ),
            (
                DESIGN.replace("| Inbound <", "| inbound <", 1),
                "requires complete anchor/logical-id/rule-id markers",
            ),
            (
                DESIGN.replace("rule-id: `sgr-00000001`", "rule-id: `—`", 1),
                "requires an Id",
            ),
            (
                DESIGN.replace(
                    " | `tcp` |", " | <!-- rule-id: `sgr-00000001` --> `tcp` |", 1
                ),
                "identity must be in Direction",
            ),
            (
                DESIGN.replace("<!-- logical-id: EC2_SecurityGroupIngress_001 -->", ""),
                "requires complete anchor/logical-id/rule-id markers",
            ),
            (
                DESIGN.replace(
                    'id="resource-EC2_SecurityGroupIngress_001"',
                    'id="security-group-wrong"',
                ),
                "logical ID/anchor",
            ),
            (
                DESIGN.replace(
                    "<!-- logical-id: EC2_SecurityGroupIngress_002 -->",
                    "<!-- logical-id: EC2_SecurityGroupIngress_001 -->",
                ),
                "duplicate grouped logical ID",
            ),
            (
                DESIGN.replace(
                    'id="resource-EC2_SecurityGroupIngress_002"',
                    'id="resource-EC2_SecurityGroupIngress_001"',
                ),
                "duplicate resource anchor",
            ),
            (
                DESIGN.replace(
                    "rule-id: `PENDING_DEPLOY` -->", "rule-id: `sgr-00000001` -->", 1
                ),
                "duplicate grouped identity value",
            ),
            (
                DESIGN.replace("| Inbound |", "| inbound |", 1),
                "Direction must be Inbound or Outbound",
            ),
            (
                DESIGN.replace("| Inbound <", "| Outbound <", 1),
                "do not match Direction",
            ),
            (
                DESIGN.replace(
                    "| SourcePrefixListId |", "| DestinationPrefixListId |", 1
                ),
                "do not match Direction",
            ),
            (
                DESIGN.replace("| IpProtocol |", "| Type |", 1),
                "invalid Security Group Direction rule table columns",
            ),
            (
                DESIGN.replace("[vpc-00000001](vpc.md#vpc-vpc-app-dev)", "—", 1),
                "requires Id, GroupDescription and VpcId detail values",
            ),
            (
                DESIGN.replace("| `Application access` |", "| — |", 1),
                "requires Id, GroupDescription and VpcId detail values",
            ),
            (
                DESIGN.replace(
                    "[vpc-00000001](vpc.md#vpc-vpc-app-dev)",
                    "[vpc-wrong](vpc.md#vpc-vpc-app-dev)",
                    1,
                ),
                "identifier reference does not match",
            ),
            (
                DESIGN.replace(
                    "[vpc-00000001](vpc.md#vpc-vpc-app-dev)", "`vpc-00000001`", 1
                ),
                "VpcId must link to its VPC",
            ),
            (
                DESIGN.replace(
                    "[vpc-00000001](vpc.md#vpc-vpc-app-dev)",
                    "[sg-00000001](#resource-EC2_SecurityGroup_001)",
                    1,
                ),
                "VpcId must link to a VPC in the same target",
            ),
            (
                DESIGN.replace(
                    "[GroupOne](#resource-EC2_SecurityGroup_001)",
                    "[GroupOne](#resource-EC2_SecurityGroup_002)",
                    1,
                ),
                "overview link must match",
            ),
            (
                DESIGN.replace(
                    "[GroupTwo](#resource-EC2_SecurityGroup_002)",
                    "[GroupOne](#resource-EC2_SecurityGroup_002)",
                    1,
                ),
                "unique logical ID link",
            ),
            (
                DESIGN.replace('"Value":"app"', '"Wrong":"app"', 1),
                "Tags must be a JSON array",
            ),
            (DESIGN.replace(" | `443` |", " | `invalid` |", 1), "invalid Port"),
            (DESIGN.replace(" | `tcp` |", " | — |", 1), "requires IpProtocol"),
            (
                DESIGN.replace(
                    " | `tcp` | `443` | — | — | — | `123456789012` |",
                    " | `tcp` | `443` | `10.0.0.0/24` | — | — | `123456789012` |",
                    1,
                ),
                "exactly one address",
            ),
            (
                DESIGN.replace(
                    "[PENDING_DEPLOY](#resource-EC2_SecurityGroup_002)",
                    "[sg-wrong](#resource-EC2_SecurityGroup_002)",
                    1,
                ),
                "identifier reference does not match",
            ),
            (
                DESIGN.replace(
                    "### EC2.SecurityGroup: GroupOne", "### EC2.Instance: GroupOne"
                ),
                "rule table must belong to EC2.SecurityGroup",
            ),
            (
                DESIGN
                + '\n<a id="security-group-oldrule"></a>\n### EC2.SecurityGroupIngress: OldRule\n',
                "must use a horizontal Direction",
            ),
        ]
        for text, message in bad:
            failures = errors(text)
            assert any(message in error for error in failures), (message, failures)
        for text in (
            DESIGN.replace("| Inbound |", "| invalid |", 1),
            DESIGN.replace(" | `tcp` |", " | — |", 1),
            DESIGN + "\n| Direction | IpProtocol | Port |\n| --- | --- | --- |\n",
        ):
            path.write_text(text, encoding="utf-8")
            try:
                expanded_design(path.read_text().splitlines())
            except ValueError:
                pass
            else:
                raise AssertionError(
                    "invalid horizontal rule must not generate a model"
                )
    print(
        "security-group-tables: PASS (detail attributes, Direction/Port rules, inline boundaries, identities, ownership, schema, references)"
    )


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
