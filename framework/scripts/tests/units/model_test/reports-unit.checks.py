import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from unittest.mock import patch

import pytest
from model.projection import resource_display_rows
from model.render import display_name
from support.fixture_cases import load_case
from support.model_test_cases import display_case, guardduty_report_case
from support.pytest_cli import run
from support.regression_cases import case_ids

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "case_id",
    case_ids("model_test_display", prefix="duplicate-")
    + case_ids("model_test_display", prefix="partial-")
    + case_ids("model_test_display", prefix="composite-"),
)
def test_display_names(case_runner, case_id):
    case_runner.run("model_test_display", case_id, display_case)


@pytest.mark.parametrize("case_id", ["guardduty-json"])
def test_guardduty_json_type_and_masking(case_runner, case_id):
    case_runner.run("model_test_display", case_id, guardduty_report_case)


def test_formal_names(subtests):
    root = Path(__file__).resolve().parents[5]
    for kind, fields, expected in [
        ("EC2.VPC", [("Name", "vpc-name")], "vpc-name"),
        ("EC2.Subnet", [("Name", "subnet-name")], "subnet-name"),
        (
            "EC2.SecurityGroup",
            [("Tags[].Key", "Name"), ("Tags[].Value", "sg-name")],
            "sg-name",
        ),
        ("IAM.Role", [("RoleName", "role-name")], "role-name"),
        ("Lambda.Function", [("FunctionName", "function-name")], "function-name"),
        ("CodeBuild.Project", [("Name", "project-name")], "project-name"),
    ]:
        with subtests.test(kind=kind):
            resource = {
                "resourceType": kind,
                "logicalId": "Internal_001",
                "anchor": "resource",
            }
            values = {
                "desired.resource.001." + key: value for key, value in resource.items()
            }
            for index, (field, value) in enumerate(fields, 1):
                prefix = f"desired.row.001-{index:03d}."
                values.update(
                    {
                        prefix + "property": kind + "." + field,
                        prefix + "value": "`" + value + "`",
                        prefix + "comment": "fixture",
                    }
                )
            rows = resource_display_rows(values, "001", resource, root)
            name, _ = display_name(values, "001", resource, rows, root, projection=True)
            TestCase().assertEqual(name, expected)


def test_kms_grouped_alias():
    root = Path(__file__).resolve().parents[5]
    resource = {
        "resourceType": "KMS.Key",
        "logicalId": "Internal_001",
        "anchor": "key",
    }
    values = {"desired.resource.001." + key: value for key, value in resource.items()}
    values.update(
        {
            "desired.resource.002.resourceType": "KMS.Alias",
            "desired.resource.002.logicalId": "Internal_002",
            "desired.resource.002.anchor": "alias",
            "desired.resource.002.parentReference": json.dumps(
                {"$modelRef": {"logicalId": "Internal_001", "attribute": "KeyId"}}
            ),
            "desired.row.002-001.property": "KMS.Alias.AliasName",
            "desired.row.002-001.value": "`alias/app`",
            "desired.row.002-001.comment": "fixture",
        }
    )
    rows = resource_display_rows(values, "001", resource, root)
    name, _ = display_name(values, "001", resource, rows, root, projection=True)
    TestCase().assertEqual(name, "app")


def test_guardduty_secret_failure_before_snapshot():
    case = load_case("model_test_display", "guardduty-json")
    with (
        patch.object(
            audit, "masked", side_effect=[case["data"]["value"], case["data"]["secret"]]
        ),
        pytest.raises(pytest.fail.Exception, match="secret exposed") as caught,
    ):
        guardduty_report_case(case)
    TestCase().assertNotIn("hidden", str(caught.value))


def test_summary_precedes_details_and_profile_is_omitted():
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "vpc",
        "modelHash": "hash",
        "names": {},
    }
    record = {"resource": "vpc", "propertiesKey": "EC2.VPC.Id", "status": "match"}
    text, code = audit.report(
        snapshot, "profile", "account", [record], datetime.now(timezone.utc)
    )
    assert code == 0
    assert text.index("Total: 1") < text.index("[OK]")
    assert "OK: 1\nNG: 0\nERROR: 0\nINFO: 0\nResult: PASS" in text
    assert "Profile:" not in text


def test_pending_deploy_report_classification():
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "security-group",
        "modelHash": "hash",
        "names": {},
    }
    for status, pending, reason, expected in (
        ("design_unresolved", True, "REFERENCE_PENDING_DEPLOY", "NG"),
        (
            "design_unresolved",
            True,
            "REFERENCE_PENDING_DEPLOY; REFERENCE_UNRESOLVED",
            "ERROR",
        ),
        ("acquisition_failed", True, "AccessDenied", "ERROR"),
        ("design_unresolved", False, "ambiguous", "ERROR"),
        ("pending_identifier", False, "PENDING_DEPLOY", "NG"),
    ):
        item = {
            "resource": "sg",
            "propertiesKey": "EC2.SecurityGroup.Id",
            "status": status,
            "pendingDeploy": pending,
            "reason": reason,
            "designValue": None,
            "awsValue": None,
        }
        text, code = audit.report(
            snapshot, None, "account", [item], datetime.now(timezone.utc)
        )
        assert f"[{expected}]" in text
        design = '"PENDING_DEPLOY"' if expected == "NG" else "null"
        assert "  Design: " + design in text
        assert code == (1 if expected == "NG" else 2)


@pytest.mark.parametrize("attribute", ["Type", "Description", "SecretString"])
def test_secrets_manager_report_masks_only_sensitive_attributes(attribute):
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "secrets-manager",
        "modelHash": "hash",
        "names": {},
    }
    item = {
        "resource": "secret",
        "resourceType": "SecretsManager.Secret",
        "propertiesKey": "SecretsManager.Secret." + attribute,
        "status": "difference",
        "designValue": "design-value",
        "awsValue": "aws-value",
    }
    text, code = audit.report(
        snapshot, None, "account", [item], datetime.now(timezone.utc)
    )
    assert code == 1
    if attribute == "SecretString":
        assert "design-value" not in text and "aws-value" not in text
        assert '"[REDACTED]"' in text
    else:
        assert 'Design: "design-value"' in text
        assert 'AWS:    "aws-value"' in text
        assert "Diff paths: $" in text


if __name__ == "__main__":
    raise SystemExit(run(__file__))
