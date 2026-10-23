#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.resource_mode_fixtures import (
    ROOT,
    Path,
    naming_errors,
    resource_mode,
    sync_views,
    sys,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_default_mode():
    assert resource_mode({}) == "CREATE"



def check_import_naming_exemption():
    root = ROOT
    rows = [["1", "CachePolicyConfig.Name", "LEGACY", "名前"]]
    assert naming_errors(root, "CloudFront.CachePolicy", rows)
    assert not naming_errors(root, "CloudFront.CachePolicy", rows, "IMPORT")
    assert naming_errors(root, "IAM.Role", [], "IMPORT")
    assert naming_errors(root, "CodeBuild.Project", [], "IMPORT")



def check_required_name_modes():
    root = ROOT
    path = root / 'docs/designs/dev/123456789012/ec2.md'
    validator_module = sync_views.view_validator(root, root).__class__
    for kind in ("EC2.VPC", "EC2.Subnet", "EC2.RouteTable", "EC2.FlowLog"):
        for mode in ("CREATE", "IMPORT"):
            for rows in ([], [["1", kind + ".Name", "PRIVATE_SUBNET_01", "Nameタグ"]]):
                validator = validator_module(root)
                validator.check_required_name_tag(path, kind, "PRIVATE_SUBNET_01", rows, mode)
                assert bool(validator.errors) == (mode == "CREATE"), (kind, mode, validator.errors)




pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
