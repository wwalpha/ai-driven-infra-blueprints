#!/usr/bin/env python3
"""Limited Model expression syntax, links and unchanged literal constraints."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import sys
from pathlib import Path

import pytest
from model.projection import is_import_expression
from model.render import markdown_for
from model.validations.full_inputs import check_model_inputs as _check_model_inputs
from support.import_model_fixtures import resource_values
from support.model_design_fixtures import ROOT, model
from support.model_sources import write_model
from support.validator import schema_validator
from utils.cloudformation.schema import CloudFormationSchemaCatalog

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_limited_import_expression(tmp_path):
    prop = "Route53.RecordSet.AliasTarget.HostedZoneId"
    expression = (
        "Fn::ImportValue: QuickSightWebsiteInterfaceEndpointHostedZoneId${Suffix}"
    )
    design = tmp_path / "route53.md"
    (tmp_path / "vpc-endpoint.md").write_text("# 接続先\n", encoding="utf-8")
    link = f"[{expression}](vpc-endpoint.md)"
    for value in (expression, "`" + expression + "`", link):
        assert is_import_expression(prop, value, design)
    for value in ("Z123", "Z" * 45, "[Z123](vpc-endpoint.md#endpoint)"):
        assert not is_import_expression(prop, value, design)
    for value in (
        expression.replace("ImportValue", "Unknown"),
        expression.replace("QuickSightWebsiteInterfaceEndpointHostedZoneId", ""),
        expression.replace("QuickSightWebsite", "Quick SightWebsite"),
        expression.replace("QuickSight", "quickSight"),
        expression.replace("${Suffix}", ""),
        expression + "${Suffix}",
        expression + "Extra",
        "prefix " + expression,
        " " + expression,
        expression.replace("${Suffix}", "${Other}"),
        expression[:-1],
        "Fn::ImportValue: Fn::Sub: Export${Suffix}",
        "Ref: Export",
        "!ImportValue Export",
        link[:-1],
        link + "extra",
        "`" + link + "`",
        "[Z123](vpc-endpoint.md)",
        f"[{expression}](vpc-endpoint.md#endpoint)",
        f"[{expression}](missing.md)",
        f"[{expression}](../vpc-endpoint.md)",
        f"[{expression}](/vpc-endpoint.md)",
        f"[{expression}](https://example.com/vpc-endpoint.md)",
        f"[{expression}](vpc-endpoint.md?query)",
    ):
        with pytest.raises(ValueError):
            is_import_expression(prop, value, design)
    for other in (
        "Route53.RecordSet.HostedZoneId",
        "Route53.RecordSet.AliasTarget.DNSName",
    ):
        for value in (expression, link):
            with pytest.raises(ValueError):
                is_import_expression(other, value, design)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.md").write_text("# 外部\n", encoding="utf-8")
    (tmp_path / "escape.md").symlink_to(outside / "target.md")
    with pytest.raises(ValueError):
        is_import_expression(prop, f"[{expression}](escape.md)", design)

    catalog = CloudFormationSchemaCatalog(Path(__file__).resolve().parents[4])
    assert not catalog.literal_errors(
        "Route53.RecordSet", "AliasTarget.HostedZoneId", "Z" * 44
    )
    assert catalog.literal_errors(
        "Route53.RecordSet", "AliasTarget.HostedZoneId", "Z" * 45
    )
    assert not catalog.literal_errors(
        "Route53.RecordSet", "AliasTarget.EvaluateTargetHealth", "true"
    )
    assert catalog.literal_errors(
        "Route53.RecordSet", "AliasTarget.EvaluateTargetHealth", "yes"
    )
    assert catalog.literal_errors("Route53.RecordSet", "Weight", "not-a-number")


@pytest.mark.usefixtures("catalog_display_fixture")
def check_route53_import_expression_validation(tmp_path):
    path = tmp_path / "docs/designs/dev/123456789012/route53.md"
    path.parent.mkdir(parents=True)
    (path.parent / "vpc-endpoint.md").write_text("# 接続先\n", encoding="utf-8")
    source = tmp_path / "model/dev/123456789012/route53.properties"
    expression = (
        "Fn::ImportValue: QuickSightWebsiteInterfaceEndpointHostedZoneId${Suffix}"
    )
    values = model(
        "route53",
        "Route53.RecordSet",
        "test.example.com",
        [
            ("Name", "`test.example.com`", "レコード名"),
            ("Type", "`A`", "種別"),
            ("AliasTarget.DNSName", "`test.example.com`", "接続先"),
            ("AliasTarget.HostedZoneId", "Z123", "ゾーンID"),
            ("AliasTarget.EvaluateTargetHealth", "true", "ヘルス評価"),
        ],
    )
    (tmp_path / "project.json").write_text(
        json.dumps(
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
    )
    values.update(
        resource_values(
            "002",
            "Route53.HostedZone",
            "endpoint",
            "IMPORT",
            [
                ("Name", "`example.com`"),
                (
                    "Id",
                    '`{"$modelRef":{"logicalId":"Route53_HostedZone_002","attribute":"Id"}}`',
                ),
            ],
        )
    )
    values["desired.service.identity.lastAllocated"] = (
        '{"Route53.RecordSet":1,"Route53.HostedZone":2}'
    )
    values["desired.service.route53.ownedCatalogResourceTypes"] = (
        "Route53.RecordSet,Route53.HostedZone"
    )
    values["observed.row.002-002.value"] = "`Z123`"
    write_model(source, values)
    document = markdown_for(path, values, tmp_path, definitions_root=ROOT)
    validator = schema_validator(tmp_path)
    catalog = validator.catalog_design_properties()
    for field, value, valid in (
        ("AliasTarget.HostedZoneId", "Z" * 44, True),
        ("AliasTarget.HostedZoneId", "Z" * 45, False),
        ("AliasTarget.HostedZoneId", expression, True),
        ("AliasTarget.HostedZoneId", "`" + expression + "`", True),
        ("AliasTarget.HostedZoneId", f"[{expression}](vpc-endpoint.md)", True),
        (
            "AliasTarget.HostedZoneId",
            '`{"$modelRef":{"logicalId":"Route53_HostedZone_002","attribute":"Id"}}`',
            True,
        ),
        ("AliasTarget.HostedZoneId", f"[{expression}](missing.md)", False),
        ("AliasTarget.HostedZoneId", f"[{expression}](../vpc-endpoint.md)", False),
        ("AliasTarget.HostedZoneId", "[Z123](vpc-endpoint.md)", False),
        (
            "AliasTarget.HostedZoneId",
            expression.replace("ImportValue", "Unknown"),
            False,
        ),
        (
            "AliasTarget.HostedZoneId",
            expression.replace("${Suffix}", "${Other}"),
            False,
        ),
        ("AliasTarget.HostedZoneId", expression + "extra", False),
        ("AliasTarget.DNSName", expression, False),
        ("AliasTarget.DNSName", f"[{expression}](vpc-endpoint.md)", False),
        ("AliasTarget.EvaluateTargetHealth", "yes", False),
    ):
        selected = dict(values)
        row = {
            "AliasTarget.HostedZoneId": "004",
            "AliasTarget.DNSName": "003",
            "AliasTarget.EvaluateTargetHealth": "005",
            "Type": "002",
        }[field]
        key = f"desired.row.001-{row}.value"
        selected[key] = value
        write_model(source, selected)
        inputs = _check_model_inputs(source, selected, tmp_path, definitions_root=ROOT)
        errors = [
            error
            for error in inputs.errors
            if "provider schema violation" in error or "ImportValue" in error
        ]
        assert bool(errors) != valid, (field, value, inputs.errors)
        # Render accepted values; inject rejected values into an otherwise valid View.
        shown = (
            markdown_for(path, selected, tmp_path, definitions_root=ROOT)
            if valid
            else document.replace(
                "| " + field + " | " + values[key] + " |",
                "| " + field + " | " + value + " |",
            )
        )
        path.write_text(shown, encoding="utf-8")
        validator = schema_validator(tmp_path)
        validator.design_sources = {path: selected}
        validator.check_design_tables({}, *catalog, paths=[path])
        errors = [
            error
            for error in validator.findings.errors
            if "provider schema violation" in error
            or "invalid Model expression" in error
        ]
        assert bool(errors) != valid, (field, value, validator.findings.errors)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
