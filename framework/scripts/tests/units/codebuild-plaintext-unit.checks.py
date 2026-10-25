"""PLAINTEXT reference policy and ordinary Issue publication; synthetic inputs only."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from design.services.codebuild import codebuild_display_row, codebuild_formal_rows
from issue_gate import issue_errors, unresolved_services
from issues.publication import save_scan
from issues.runner import scan
from model.core import entries
from model.display import display_rows
from model.render import markdown_for
from model.validation import (
    check_model_inputs as _check_model_inputs,
)
from model.validation import (
    codebuild_reference_errors,
)
from support.issues_scan_fixtures import fixture, task, write
from support.model_sources import write_model
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias
from utils.reference_contracts import reference_error

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

FRAMEWORK = Path(__file__).resolve().parents[4]
PREFIX = "CodeBuild.Project.Environment.EnvironmentVariables"
REASON = "PLAINTEXTではResource linkは禁止"
NODE = {"$modelRef": {"logicalId": "S3_Bucket_001", "attribute": "Arn"}}


def values_for(variables, mode="CREATE", indexed=False):
    values = {
        "display.service.title": "# CodeBuild 詳細設計",
        "desired.service.codebuild.serviceId": "codebuild",
        "desired.service.codebuild.ownedCatalogResourceTypes": "CodeBuild.Project",
        "desired.service.identity.lastAllocated": '{"CodeBuild.Project":1}',
        "desired.resource.001.resourceType": "CodeBuild.Project",
        "desired.resource.001.resourceMode": mode,
        "desired.resource.001.logicalId": "CodeBuild_Project_001",
        "desired.resource.001.anchor": "project",
        "display.resource.001.comment": "合成 Project",
        "display.resource.001.label": "project",
    }
    rows = [
        ("Name", "`project`"),
        ("Artifacts.Type", "`NO_ARTIFACTS`"),
        ("Environment.Type", "`LINUX_CONTAINER`"),
        ("Environment.ComputeType", "`BUILD_GENERAL1_SMALL`"),
        ("Environment.Image", "`image`"),
        ("ServiceRole", "[role](iam.md#role)"),
        ("Source.Type", "`NO_SOURCE`"),
    ]
    for number, (name, variable_type, value) in enumerate(variables, 1):
        prefix = f"Environment.EnvironmentVariables[{number if indexed else ''}]."
        rows.extend(
            (prefix + field, raw)
            for field, raw in (
                ("Name", f"`{name}`"),
                ("Type", f"`{variable_type}`"),
                ("Value", value),
            )
        )
    for number, (prop, value) in enumerate(rows, 1):
        prefix = f"desired.row.001-{number:03d}."
        values.update(
            {
                prefix + "property": "CodeBuild.Project." + prop,
                prefix + "value": value,
                prefix + "comment": "合成設定",
            }
        )
    return values


@pytest.fixture
def models(tmp_path):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "projectName": "fixture",
                "targets": [
                    {
                        "environment": "dev",
                        "alias": "team",
                        "awsAccountId": "123456789012",
                        "awsRegion": "ap-northeast-1",
                        "iacEngine": "terraform",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with mapping_alias(FRAMEWORK, tmp_path):
        yield tmp_path


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
@pytest.mark.parametrize(
    "value,forbidden",
    [
        ("`hello:world`", False),
        ("`arn:aws:s3:::fixture`", False),
        ("`https://example.com/path#fragment`", False),
        ("[bucket](s3.md#bucket)", True),
        ("[secret](secretsmanager.md#secret)", True),
        ("[key](kms.md#key)", True),
        ("[other](vpc.md#vpc)", True),
        ("[missing](missing.md#missing)", True),
        ("`" + json.dumps(NODE) + "`", True),
    ],
)
def test_model_policy(models, mode, value, forbidden):
    path = models / "model/dev/team/codebuild.properties"
    values = values_for([("VALUE", "PLAINTEXT", value)], mode)
    write_model(path, values)
    findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    errors = [error for error in findings.errors if REASON in error]
    assert len(errors) == int(forbidden), findings.errors
    if forbidden:
        assert all(
            text in errors[0]
            for text in [
                str(path),
                "CodeBuild_Project_001",
                "Name=VALUE",
                "Type=PLAINTEXT",
                "Property=" + PREFIX,
            ]
        )
        assert not any(REASON in str(w) for w in findings.warnings)
    else:
        assert not findings.errors, findings.errors


@pytest.mark.parametrize("indexed", [False, True])
def test_exact_sibling_type_and_continuation(models, indexed):
    path = models / "model/dev/team/codebuild.properties"
    values = values_for(
        [
            ("SECRET", "SECRETS_MANAGER", "[secret](secretsmanager.md#secret)"),
            ("BAD", "PLAINTEXT", "[missing](missing.md#missing)"),
            ("TEXT", "PLAINTEXT", "`literal`"),
            ("PARAMETER", "PARAMETER_STORE", "[parameter](ssm.md#parameter)"),
            ("OTHER_BAD", "PLAINTEXT", "`" + json.dumps(NODE) + "`"),
        ],
        indexed=indexed,
    )
    values.update(
        {
            "desired.row.001-999.property": "CodeBuild.Project.TimeoutInMinutes",
            "desired.row.001-999.value": "`invalid`",
            "desired.row.001-999.comment": "不正",
        }
    )
    write_model(path, values)
    with patch(
        "model.render.resource_details", side_effect=ValueError("render unavailable")
    ):
        findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    errors = [error for error in findings.errors if REASON in error]
    assert len(errors) == 2, findings.errors
    assert "Name=BAD," in errors[0] and "Name=OTHER_BAD," in errors[1]
    assert any("provider schema violation" in e for e in findings.errors)


@pytest.mark.parametrize("document", [False, True])
def test_container_references_use_exact_context(models, document):
    values = values_for([])
    variables = [
        {"Name": "SECRET", "Type": "SECRETS_MANAGER", "Value": NODE},
        {"Name": "BAD", "Type": "PLAINTEXT", "Value": NODE},
        {
            "Name": "BAD_LINK",
            "Type": "PLAINTEXT",
            "Value": "[missing](missing.md#missing)",
        },
    ]
    values.update(
        {
            "desired.row.001-008.property": "CodeBuild.Project.Environment",
            "desired.row.001-008.value": "`"
            + json.dumps({"EnvironmentVariables": variables})
            + "`",
            "desired.row.001-008.comment": "合成",
        }
    )
    if document:
        values["desired.row.001-008.document"] = values[
            "desired.row.001-008.value"
        ].strip("`")
        values["desired.row.001-008.value"] = (
            "[Environment](codebuild/environment.json)"
        )
    errors = codebuild_reference_errors(
        models / "model/dev/team/codebuild.properties", values
    )
    assert len(errors) == 2
    assert (
        "Name=BAD,"
        in errors[
            "001-008",
            "document" if document else "value",
            "/EnvironmentVariables/1/Value",
        ]
    )
    assert (
        "Name=BAD_LINK,"
        in errors[
            "001-008",
            "document" if document else "value",
            "/EnvironmentVariables/2/Value",
        ]
    )


@pytest.mark.parametrize("marker", ["", "<!-- codebuild-variable-type: PLAINTEXT -->"])
@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_markdown_rejects_plaintext_link(marker, mode):
    cells = [
        "1",
        "CodeBuild.Project.Environment.Variables.VALUE",
        "[missing](missing.md#missing)",
        marker,
    ]
    with pytest.raises(ValueError, match=REASON):
        codebuild_formal_rows(cells, set(), mode=mode)
    rows = [
        ["1", PREFIX + "[]." + field, value, "合成"]
        for field, value in (
            ("Name", "`VALUE`"),
            ("Type", "`PLAINTEXT`"),
            ("Value", cells[2]),
        )
    ]
    with pytest.raises(ValueError, match=REASON):
        codebuild_display_row(rows, 0, "合成", mode=mode)


@pytest.mark.parametrize("kind", ["PARAMETER_STORE", "SECRETS_MANAGER"])
def test_non_plaintext_round_trip(kind):
    cells = [
        "1",
        "CodeBuild.Project.Environment.Variables.VALUE",
        "[reference](service.md#resource)",
        f"<!-- codebuild-variable-type: {kind} --> 合成",
    ]
    rows = codebuild_formal_rows(cells, set())
    assert codebuild_display_row(rows, 0, "合成") == cells
    assert reference_error(PREFIX + "[].Value", {"Type": kind}) is None


@pytest.mark.parametrize("unreadable_view", [False, True])
def test_scan_save_owns_codebuild_and_deduplicates(tmp_path, unreadable_view):
    with mapping_alias(FRAMEWORK, tmp_path):
        _, template = fixture(tmp_path, services=("s3",))
        path = tmp_path / "model/dev/123456789012/codebuild.properties"
        view = tmp_path / "docs/designs/dev/123456789012/codebuild.md"
        values = values_for([("BUCKET", "PLAINTEXT", "`bucket-app-dev-data1`")])
        values["desired.resource.001.cfn-logicalId"] = "cfn-stack-app-dev-data1-Build"
        write_model(path, values)
        write(view, markdown_for(view, values, tmp_path))
        variables = {rid: row for rid, row in entries(values, "desired.row.")}
        rid = next(
            rid
            for rid, row in variables.items()
            if row["property"].endswith("EnvironmentVariables[].Value")
        )
        values[f"desired.row.{rid}.value"] = (
            "[bucket-app-dev-data1](s3.md#s3-bucket-app-dev-data1)"
        )
        write_model(path, values)
        # The same symbolic bucket is also the IaC value; equality cannot waive policy.
        template["Resources"]["Build"] = {
            "Type": "AWS::CodeBuild::Project",
            "Properties": {
                "Name": "project",
                "Artifacts": {"Type": "NO_ARTIFACTS"},
                "Environment": {
                    "Type": "LINUX_CONTAINER",
                    "ComputeType": "BUILD_GENERAL1_SMALL",
                    "Image": "image",
                    "EnvironmentVariables": [
                        {
                            "Name": "BUCKET",
                            "Type": "PLAINTEXT",
                            "Value": {"Ref": "Bucket"},
                        }
                    ],
                },
                "ServiceRole": "role",
                "Source": {"Type": "NO_SOURCE"},
            },
        }
        write(
            tmp_path / "infra/cloudformation/templates/shared.yaml",
            json.dumps(template),
        )
        if unreadable_view:
            view.write_bytes(b"\xff")
        services = ["s3", "codebuild"]
        for _iteration in range(2):
            artifact = scan(tmp_path, "dev", "123456789012", services, jobs=1)
            errors = [
                item for item in artifact["ordinary"] if REASON in item["message"]
            ]
            assert len(errors) == 1, artifact["ordinary"]
            assert errors[0]["service"] == "codebuild"
            assert not any(
                REASON in str(item)
                for channel in ("warnings", "unverified")
                for item in artifact[channel]
            )
            assert not any(
                REASON in str(item)
                for item in artifact["judgments"]
                if item.get("kind") != "existing-issue-correspondence"
            )
            review = dict(
                scan_id=artifact["scan_id"],
                reviewed_naming_context_id=artifact["naming_context_id"],
                reviewed_names=[item["id"] for item in artifact["naming"]["names"]],
                reviewed_judgments=[item["id"] for item in artifact["judgments"]],
                diagnostic_assignments={},
                issues=[],
                resolved=[],
            )
            review["existing_issue_judgments"] = [
                dict(
                    id=item["materials"]["id"],
                    service="codebuild",
                    status="continuing",
                    reason="同じ禁止違反を今回のModel検証でも検出",
                    verification="local",
                    diagnostic_id=errors[0]["id"],
                    evidence=[
                        dict(kind="scan", section="ordinary", id=errors[0]["id"])
                    ],
                )
                for item in artifact["judgments"]
                if item.get("kind") == "existing-issue-correspondence"
            ]
            with task(tmp_path, services):
                paths = save_scan(tmp_path, artifact, review)
            report = paths[0].read_text(encoding="utf-8")
            assert REASON in report
            assert (
                sum(
                    "codebuild" in owners
                    for _, owners in unresolved_services(tmp_path, paths[0])
                )
                == 1
            ), report
            assert "### codebuild" in report
            assert issue_errors(tmp_path, {("dev", "123456789012", "codebuild")})


@pytest.mark.parametrize("mode", ["CREATE", "IMPORT"])
def test_structured_reference_display_is_rejected(mode):
    rows = [
        ["001-" + str(n), PREFIX + "[]." + field, raw, "合成"]
        for n, (field, raw) in enumerate(
            [
                ("Name", "`VALUE`"),
                ("Type", "`PLAINTEXT`"),
                ("Value", "`" + json.dumps(NODE) + "`"),
            ],
            1,
        )
    ]
    with pytest.raises(ValueError, match=REASON):
        display_rows("CodeBuild.Project", rows, FRAMEWORK, mode=mode)


@pytest.mark.parametrize(
    "variable_type,service,kind",
    [
        ("SECRETS_MANAGER", "secretsmanager", "SecretsManager.Secret"),
        ("PARAMETER_STORE", "ssm", "SSM.Parameter"),
    ],
)
def test_non_plaintext_model_links_pass(models, variable_type, service, kind):
    producer = {
        "desired.service." + service + ".serviceId": service,
        "desired.service." + service + ".ownedCatalogResourceTypes": kind,
        "desired.service.identity.lastAllocated": json.dumps({kind: 1}),
        "desired.resource.001.resourceType": kind,
        "desired.resource.001.resourceMode": "IMPORT",
        "desired.resource.001.logicalId": kind.replace(".", "_") + "_001",
        "desired.resource.001.anchor": "reference",
        "desired.row.001-001.property": kind + ".Name",
        "desired.row.001-001.value": "`fixture-name`",
        "desired.row.001-001.comment": "合成",
    }
    write_model(models / f"model/dev/team/{service}.properties", producer)
    path = models / "model/dev/team/codebuild.properties"
    values = values_for(
        [("VALUE", variable_type, f"[fixture-name]({service}.md#reference)")]
    )
    write_model(path, values)
    findings = _check_model_inputs(path, values, models, definitions_root=FRAMEWORK)
    assert not findings.errors, findings.errors


if __name__ == "__main__":
    raise SystemExit(run(__file__, message="CodeBuild PLAINTEXT unit checks passed"))
