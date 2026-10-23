#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.design_catalog_fixtures import (
    MACIE_JOB,
    QUICKSIGHT_GROUP,
    ROOT,
    CloudFormationSchemaCatalog,
    DesignSchemaCatalog,
    Path,
    api_snapshot_errors,
    sys,
)

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def check_api_schema():
    assert not api_snapshot_errors(ROOT)
    catalog = DesignSchemaCatalog(ROOT)
    assert catalog.cloudformation_type("Macie.Session") == "AWS::Macie::Session"
    group = catalog.schema(QUICKSIGHT_GROUP)
    assert group["identityProperties"] == ["AwsAccountId", "Namespace", "GroupName"]
    assert group["identifierOutputs"] == ["Arn", "PrincipalId"]
    assert group["source"]["readOperations"] == ["ListGroups", "DescribeGroup"]
    assert group["source"]["updateOperation"] == "UpdateGroup"
    assert group["source"]["deleteOperation"] == "DeleteGroup"
    assert catalog.required_design_properties(QUICKSIGHT_GROUP) == {"AwsAccountId", "Namespace", "GroupName"}
    for resource_type in (MACIE_JOB, QUICKSIGHT_GROUP, "Macie.Unknown"):
        try:
            catalog.cloudformation_type(resource_type)
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError(f"unsupported CFn type accepted: {resource_type}")
    try:
        CloudFormationSchemaCatalog(ROOT).schema(MACIE_JOB)
    except KeyError:
        pass
    else:
        raise AssertionError("API design leaked into the CFn catalog")




pytestmark = pytest.mark.usefixtures("catalog_display_fixture")

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
