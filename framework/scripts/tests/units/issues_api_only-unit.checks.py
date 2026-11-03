#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest import TestCase
from unittest.mock import patch

import pytest
from comparison import Comparison
from design.catalog import main as catalog_main
from issues.aggregate import aggregate, iac_summary
from issues.artifact import summary
from issues.cfn_lint import plan
from issues.reports import iac_report
from model.adapters.observed import mappings
from model.format import serialize
from support.issues_api_only_fixtures import (
    ROOT,
    DesignSchemaCatalog,
    Path,
    sys,
)
from utils.reference_contracts import getatt_attribute

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_api_type_rejection():
    catalog = DesignSchemaCatalog(ROOT)
    for kind, schema in catalog.api_schemas.items():
        if schema.get("cloudFormationType"):
            continue
        try:
            catalog.cloudformation_type(kind)
        except ValueError as error:
            assert (
                "implementation remains incomplete if this resource is in scope"
                in str(error)
            )
        else:
            raise AssertionError("API resource accepted as implemented CFn")


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


def api_comparison(resource, *, load_errors=()):
    comparison = Comparison.__new__(Comparison)
    comparison.root = Path("/synthetic")
    comparison.services, comparison.target = ["s3"], {"iacEngine": "cloudformation"}
    comparison.symbols, comparison.reference_unavailable, comparison.models = {}, {}, {}
    comparison.load_errors, comparison.results = list(load_errors), []
    comparison.resources = {"s3": {"002": resource}}
    comparison.catalog = DesignSchemaCatalog(ROOT)
    comparison.sensitive_values = set()
    comparison.templates = lambda: []
    return comparison


def check_api_record_classification():
    for kind, schema in DesignSchemaCatalog(ROOT).api_schemas.items():
        if schema.get("cloudFormationType"):
            continue
        records = api_comparison({"resourceType": kind}).run()
        (api,) = records
        assert api["category"] == "uncompared"
        assert api["cause"] == {
            "kind": "cloudformation-unsupported",
            "resource_type": kind,
            "implementation_status": "unverified",
        }
        stats = iac_summary(records, "dev", "123456789012", ["s3"])
        assert stats["records"] == dict(
            difference=0, uncompared=1, error=0, matched=0, deferred=0, excluded=0
        )
        assert (
            stats["categories"]["CFn非対応・比較対象外"] == stats["proven_causes"] == 1
        )
        assert (
            stats["categories"]["処理エラー"] == stats["categories"]["原因未確定"] == 0
        )
        artifact = dict(
            version=6,
            ordinary=[],
            judgments=[],
            naming={"names": []},
            naming_context={},
            **aggregate(records, "dev", "123456789012", ["s3"]),
        )
        assert summary(artifact)["iac_status"] == "partial"
        report = iac_report("dev", "123456789012", ["s3"], records)
        assert "今回の判定: partial" in report and "CFn非対応・比較対象外" in report
        assert (
            "CloudFormation非対応" in report
            and "実装scope" not in report
            and "必要な操作" not in report
        )
        assert "complete match" not in report and "## 処理エラー" not in report
    for resource in ({"resourceType": "Macie.Unknown"}, {}, {"resourceType": []}):
        records = api_comparison(resource).run()
        (failure,) = records
        assert (
            failure["category"] == "error"
            and failure.get("cause", {}).get("kind") != "cloudformation-unsupported"
        )
        artifact = dict(version=6, **aggregate(records, "dev", "123456789012", ["s3"]))
        assert summary(artifact)["iac_status"] == "error"


def check_catalog_cli_rejects_api_only_type(capsys):
    kind = "Macie.ClassificationJob"
    with patch.object(
        sys,
        "argv",
        [
            "design_catalog.py",
            "--repository-root",
            str(ROOT),
            "--cloudformation-type",
            kind,
        ],
    ):
        TestCase().assertEqual(catalog_main(), 1)
    TestCase().assertIn("CloudFormation unsupported", capsys.readouterr().out)


@pytest.mark.parametrize("account", ["123456789012", "999999999999"])
def check_group_cloudformation_comparison(project_workspace, account, capsys):
    root = project_workspace
    target = dict(
        environment="dev",
        awsAccountId="123456789012",
        awsRegion="us-east-1",
        iacEngine="cloudformation",
    )
    (root / "project.json").write_text(
        json.dumps(dict(projectName="test", targets=[target]))
    )
    model = root / "model/dev/123456789012"
    model.mkdir(parents=True, exist_ok=True)
    values = {
        "desired.service.quicksight.serviceId": "quicksight",
        "desired.service.identity.lastAllocated": '{"QuickSight.Group":1}',
        "desired.resource.001.resourceType": "QuickSight.Group",
        "desired.resource.001.logicalId": "QuickSight_Group_001",
        "desired.resource.001.anchor": "resource-QuickSight_Group_001",
        "desired.resource.001.cfn-logicalId": "StackA-Group",
    }
    for i, (field, value) in enumerate(
        dict(
            AwsAccountId=account,
            Namespace="default",
            GroupName="readers",
            Description="Readers",
            PrincipalId=json.dumps(
                {
                    "$modelRef": {
                        "logicalId": "QuickSight_Group_001",
                        "attribute": "PrincipalId",
                    }
                }
            ),
        ).items(),
        1,
    ):
        values.update(
            {
                f"desired.row.001-{i:03d}.property": "QuickSight.Group." + field,
                f"desired.row.001-{i:03d}.value": value,
                f"desired.row.001-{i:03d}.comment": "合成テスト",
            }
        )
    (model / "quicksight.properties").write_text(serialize(values), encoding="utf-8")
    unit = dict(
        placementName="StackA",
        name="StackA",
        template="group.yaml",
        parameters="group.json",
        deployOrder="10",
    )
    (model / "cloudformation-stacks.properties").write_text(
        serialize({"desired.stack.001." + k: v for k, v in unit.items()})
    )
    template = root / "infra/cloudformation/templates/group.yaml"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(
        json.dumps(
            {
                "Resources": {
                    "Group": {
                        "Type": "AWS::QuickSight::Group",
                        "Properties": dict(
                            Namespace="default",
                            GroupName="readers",
                            Description="Readers",
                        ),
                    }
                }
            }
        )
    )
    parameters = root / "infra/cloudformation/parameters/dev/123456789012/group.json"
    parameters.parent.mkdir(parents=True, exist_ok=True)
    parameters.write_text("[]")
    document = json.loads(template.read_text())
    document["Outputs"] = {
        "GroupPrincipalId": {"Value": {"Fn::GetAtt": ["Group", "PrincipalId"]}}
    }
    template.write_text(json.dumps(document))
    task = root / "tasks/group.md"
    task.parent.mkdir(exist_ok=True)
    task.write_text(
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n## Modified files\n- `tasks/group.md`\n## Allowed paths\n- `tasks/group.md`\n## Validation scope\n- `dev/123456789012/quicksight`\n"
    )
    assert set(
        mappings(
            root,
            "dev",
            "123456789012",
            {"StackA": (document, {})},
            [unit],
            target=target,
            implementation=True,
        )[1]["StackA"]
    ) == {"Group"}
    comparison = Comparison(root, "dev", "123456789012", ["quicksight"])
    records = comparison.run()
    assert not comparison.load_errors, comparison.load_errors
    assert not [r for r in records if r["category"] in {"error", "uncompared"}], records
    differences = [r for r in records if r["category"] == "difference"]
    assert len(differences) == int(account != "123456789012"), records
    if differences:
        assert differences[0]["property"] == "QuickSight.Group.AwsAccountId"
    jobs, coverage = plan(comparison)
    assert len(jobs) == 1 and not [
        r for r in coverage if r["status"] == "not_applicable"
    ]
    schema = comparison.catalog.schema("QuickSight.Group")
    assert all(
        getatt_attribute("QuickSight.Group", field, schema)
        for field in ("Arn", "PrincipalId")
    )
    with patch.object(
        sys,
        "argv",
        [
            "design_catalog.py",
            "--repository-root",
            str(ROOT),
            "--cloudformation-type",
            "QuickSight.Group",
        ],
    ):
        assert catalog_main() == 0
    assert "AWS::QuickSight::Group" in capsys.readouterr().out


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
