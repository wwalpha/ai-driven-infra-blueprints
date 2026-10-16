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
pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

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
