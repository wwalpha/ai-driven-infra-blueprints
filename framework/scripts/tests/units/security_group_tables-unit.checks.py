#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.security_group_tables_fixtures import *

def check_rule_catalog():
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



import pytest
import json
from types import SimpleNamespace
from unittest.mock import patch
from support.fixture_cases import load_case, load_suite
from model.display import sg_tables
from model.core import literal
from aws_mapping_display import selected_rows
from design_catalog import DesignSchemaCatalog
from issues.comparison import Comparison
from iac_values import same
from security_group_tables import cells
pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

def check_tag_scalars():
    fixture = load_suite("security_group_tables")
    prefix, _ = DESIGN.split("### EC2.SecurityGroup: GroupTwo", 1)
    for name in sorted(fixture["cases"].keys() - {"invalid-metadata"}):
        case = load_case("security_group_tables", name)
        rows = [[f"006-{number:03}", "EC2.SecurityGroup." + prop, value, comment]
                for number, (prop, value, comment) in enumerate(case["data"]["basic"], 1)]
        expected = [dict(zip(("Key", "Value"), case["expected"])), {"Key": "Environment", "Value": "dev"}]
        for pair in (case["data"]["scalars"], list(expected[1].values())):
            for prop, value in zip(("Key", "Value"), pair):
                rows.append([f"006-{len(rows) + 1:03}", "EC2.SecurityGroup.Tags[]." + prop, value, "タグ"])
        consumed = []
        block = sg_tables(selected_rows(rows), [], consumed=consumed)
        assert consumed == [row[0] for row in rows]
        metadata = block[0].removeprefix("<!-- security-group-tags: ").removesuffix(" -->")
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
            ["EC2.SecurityGroup.Tags[]." + prop, tag[prop]] for tag in expected for prop in ("Key", "Value")]
        assert "| 3 | GroupName | group-two |" in text
        # The existing comparison must keep these schema-typed scalars as strings.
        context = SimpleNamespace(catalog=DesignSchemaCatalog(REPOSITORY), local_comparison=True)
        for row in rows[4:]:
            value = Comparison.desired_value(context, "security-group", {"property": row[1], "value": row[2]}, "EC2.SecurityGroup")
            assert same(value, literal(row[2])) is True
        with patch("aws_mapping_display.show", side_effect=lambda prop, root: not prop.endswith("Tags[].Value")):
            hidden = sg_tables(selected_rows(rows), [])
        assert not any("security-group-tags:" in line for line in hidden)


def check_invalid_tag_metadata():
    marker = next(line for line in DESIGN.splitlines() if line.startswith("<!-- security-group-tags:"))
    for metadata in load_case("security_group_tables", "invalid-metadata")["data"]["metadata"]:
        with pytest.raises(ValueError, match="Security Group (Tags|tags)"):
            security_group_table_lines(DESIGN.replace(marker, "<!-- security-group-tags: " + metadata + " -->").splitlines())

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


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
