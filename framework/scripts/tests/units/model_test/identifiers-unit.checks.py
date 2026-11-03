import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime, timezone
from functools import partial
from unittest.mock import Mock, patch

import pytest
from support.fixture_cases import load_case
from support.model_test_cases import (
    identifier_case,
    identifier_state,
)
from support.pytest_cli import run
from support.regression_cases import case_ids

from model import audit_runtime as audit

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def identifier():
    return identifier_state()


@pytest.mark.parametrize(
    "case_id", case_ids("model_test_identifiers", prefix="identifier-")
)
def test_identifier_cases(case_runner, identifier, case_id):
    case_runner.run(
        "model_test_identifiers", case_id, partial(identifier_case, identifier)
    )


def test_acquisition_and_normal_attributes_unchanged(identifier):
    for status in ("acquisition_failed", "unimplemented"):
        item = {**identifier.item, "status": status}
        result = audit.identifier_result(
            identifier.m, identifier.ctx, identifier.resource, item
        )
        TestCase().assertEqual(result["status"], status)
        TestCase().assertEqual(result["designValue"], "vpc-123")
    item = {**identifier.item, "status": "match", "propertiesKey": "EC2.VPC.CidrBlock"}
    TestCase().assertIs(
        audit.identifier_result(
            identifier.m, identifier.ctx, identifier.resource, item
        ),
        item,
    )


def test_report_uses_design_for_every_result(identifier, subtests):
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "vpc",
        "modelHash": "hash",
        "names": {},
    }
    for status, reason in (
        ("match", ""),
        ("difference", "value differs"),
        ("design_unresolved", "Design reference unresolved"),
        ("resource_missing", "ResourceNotFound"),
        ("acquisition_failed", "AccessDenied"),
    ):
        with subtests.test(status=status):
            item = {
                **identifier.item,
                "resource": "id",
                "status": status,
                "reason": reason,
                "designValue": "vpc-123",
            }
            text, _ = audit.report(
                snapshot, None, "account", [item], datetime.now(timezone.utc)
            )
            TestCase().assertIn('  Design: "vpc-123"', text)
            TestCase().assertIn('  AWS:    "vpc-123"', text)
            TestCase().assertNotIn("  Model:", text)
            TestCase().assertIn("Design SHA256: hash", text)
            TestCase().assertNotIn("Model SHA256", text)
            if reason:
                TestCase().assertIn(reason, text)


def test_excluded_reporting_and_failure_codes(identifier):
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "kms",
        "modelHash": "hash",
        "names": {},
    }
    excluded = {
        "resource": "key",
        "propertiesKey": "KMS.Key.PendingWindowInDays",
        "status": "excluded",
        "designValue": 30,
        "reason": "write-only",
    }
    ok = {**excluded, "propertiesKey": "KMS.Key.Enabled", "status": "match"}
    for records, code in [
        ([excluded, ok], 0),
        ([excluded], 2),
        ([excluded, {**ok, "status": "difference"}], 1),
        ([excluded, {**ok, "status": "sdk_unavailable"}], 2),
        ([excluded, {**ok, "status": "acquisition_failed"}], 2),
        ([excluded, {**ok, "status": "design_unresolved"}], 2),
    ]:
        text, actual = audit.report(
            snapshot, None, "account", records, datetime.now(timezone.utc)
        )
        TestCase().assertEqual(actual, code)
        TestCase().assertIn("[INFO]", text)
        TestCase().assertIn("Verification: NOT_VERIFIABLE", text)
        TestCase().assertIn("INFO: 1", text)


def test_lakeformation_request_input_requires_resource_confirmation(identifier):
    prop = "LakeFormation.Resource.UseServiceLinkedRole"
    item = {
        "propertiesKey": prop,
        "status": "sdk_unavailable",
        "reason": "request input",
    }
    for desired in (True, False):
        identifier.resource.rows_for.return_value = [
            ("001-001", {"value": str(desired)})
        ]
        identifier.resource.parse = lambda row, desired=desired: desired
        result = audit.classify_exclusion(
            identifier.m, {}, identifier.resource, item, resource_confirmed=True
        )
        TestCase().assertEqual(result["status"], "excluded")
        TestCase().assertIs(result["designValue"], desired)
        TestCase().assertIs(
            audit.classify_exclusion(identifier.m, {}, identifier.resource, item), item
        )
    identifier.resource.parse = Mock(side_effect=ValueError("invalid"))
    TestCase().assertEqual(
        audit.classify_exclusion(
            identifier.m, {}, identifier.resource, item, resource_confirmed=True
        )["status"],
        "design_unresolved",
    )


def test_missing_resource_report_is_not_a_property_diff(identifier):
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "glue",
        "modelHash": "hash",
        "names": {"job": "fixture-job"},
    }
    item = {
        "resource": "job",
        "resourceType": "Glue.Job",
        "propertiesKey": "Glue.Job.Timeout",
        "status": "resource_missing",
        "designValue": ["`30`"],
        "awsValue": None,
        "reason": "EntityNotFoundException",
    }
    text, code = audit.report(
        snapshot,
        None,
        "account",
        [item, {**item, "propertiesKey": "Glue.Job.Name"}],
        datetime.now(timezone.utc),
    )
    TestCase().assertEqual(code, 1)
    TestCase().assertIn(
        "[NG] Glue.Job | fixture-job | Timeout (resource missing)", text
    )
    TestCase().assertIn("[NG] Glue.Job | fixture-job | Name (resource missing)", text)
    TestCase().assertEqual(text.count("[NG] Glue.Job"), 2)
    TestCase().assertIn('  Design: ["`30`"]', text)
    TestCase().assertIn("  AWS:    null", text)
    TestCase().assertIn("  Reason: EntityNotFoundException", text)
    TestCase().assertNotIn("Diff paths:", text)
    TestCase().assertNotIn("[ERROR]", text)
    text, code = audit.report(
        snapshot,
        None,
        "account",
        [item, {**item, "status": "acquisition_failed", "reason": "AccessDenied"}],
        datetime.now(timezone.utc),
    )
    TestCase().assertEqual(code, 2)
    TestCase().assertIn("[ERROR]", text)


def test_report_translates_fixed_producer_diagnostic_only(identifier):
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "vpc",
        "modelHash": "hash",
        "names": {},
    }
    item = {
        **identifier.item,
        "resource": "ModelResource",
        "status": "design_unresolved",
        "reason": "producer Model is absent",
        "designValue": "ModelValue",
    }
    text, _ = audit.report(
        snapshot, None, "account", [item], datetime.now(timezone.utc)
    )
    TestCase().assertIn("producer Design is absent", text)
    TestCase().assertIn("ModelValue", text)
    TestCase().assertNotIn("producer Model is absent", text)


def test_report_does_not_include_internal_id_or_api(identifier):
    snapshot = {
        "target": {"environment": "dev", "directory": "cde", "awsRegion": "region"},
        "service": "vpc",
        "modelHash": "hash",
        "names": {"EC2_VPC_001": "vpc-name"},
    }
    item = {
        **identifier.item,
        "resource": "EC2_VPC_001",
        "resourceType": "EC2.VPC",
        "status": "match",
        "designValue": "vpc-123",
        "apis": [{"api": "ec2.describe_vpcs"}],
    }
    text, code = audit.report(
        snapshot, None, "account", [item], datetime.now(timezone.utc)
    )
    TestCase().assertEqual(code, 0)
    TestCase().assertIn("[OK] EC2.VPC | vpc-name | VpcId", text)
    TestCase().assertNotIn("EC2_VPC_001", text)
    TestCase().assertNotIn("API:", text)
    item["resource"] = "EC2_VPC_002"
    TestCase().assertIn(
        "（名前未設定）",
        audit.report(snapshot, None, "account", [item], datetime.now(timezone.utc))[0],
    )


def test_identifier_secret_failure_before_snapshot(identifier):
    case = load_case("model_test_identifiers", "identifier-sensitive")
    with (
        patch.object(
            audit, "identifier_result", return_value={"designValue": 42, "awsValue": 42}
        ),
        pytest.raises(pytest.fail.Exception, match="secret exposed"),
    ):
        identifier_case(identifier, case)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
