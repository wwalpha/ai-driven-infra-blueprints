"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.methods import ORDERED, UNORDERED, CompareOutcome, compare_values, keyed
from comparison.references import ReferenceDecision
from comparison.result import identifier, setting_result
from comparison.runner import Settings
from issues.aggregate import aggregate, iac_dataset, iac_summary
from issues.artifact import detail_payload
from support.comparison_cases import projected
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    ResourceReference,
    safe_value,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    KEY_ID,
    ROOT,
    declaration,
    fixture,
    kms_key,
    resource,
    unproven_reference,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="lambda-env-")
)
def test_lambda_environment_iac_reference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_lambda_environment)


def _execute_lambda_environment(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "s3",
        "001",
        "S3.Bucket",
        "Bucket",
        [("BucketName", "fixture-bucket", None)],
        properties={"BucketName": "fixture-bucket"},
    )
    desired = {"Variables": {"BUCKET": data["literal"]}}
    actual = {"Variables": {"BUCKET": data["reference"]}}
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    outcome = comparison.compare_setting(
        "lambda",
        "002",
        "Lambda.Function",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    (record,) = outcome.records
    if record["category"] != "uncompared":
        (evidence,) = record["reference_diagnostics"]
        TestCase().assertEqual(evidence["evidence_type"], "local_evaluation")
        TestCase().assertEqual(evidence["local_comparison"], record["category"])
        TestCase().assertIs(evidence["current_aws_verified"], False)
    return {"records": projected(outcome.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-kms-form-")
)
def test_codebuild_material_key_id_reference_formats(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_kms_form)


def _execute_codebuild_kms_form(case):
    data = case["data"]
    comparison = fixture()
    kms_key(comparison)
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/material", None)],
        properties={"AliasName": "alias/material", "TargetKeyId": {"Ref": "Key"}},
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "MATERIAL_KEY_ID", "Type": "PLAINTEXT", "Value": data["literal"]}
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][0]["Value"] = data["reference"]
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    outcome = comparison.compare_setting(
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    (record,) = outcome.records
    (evidence,) = record["reference_diagnostics"]
    TestCase().assertEqual(evidence["local_comparison"], record["category"])
    TestCase().assertIs(evidence["current_aws_verified"], False)
    TestCase().assertTrue(evidence["reason"])
    return {"records": projected(outcome.records)}


@pytest.mark.parametrize(
    ("observed", "export_value", "category", "reason"),
    [
        (KEY_ID, {"Ref": "Key"}, "matched", "logical_reference"),
        (
            "87654321-1234-1234-1234-123456789012",
            {"Ref": "Key"},
            "uncompared",
            "recorded_identifier_mismatch",
        ),
        (KEY_ID, {"Ref": "OtherKey"}, "difference", "different producer Resources"),
    ],
)
def test_codebuild_declared_plaintext_key_id(observed, export_value, category, reason):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", observed)],
    )
    resource(comparison, "kms", "002", "KMS.Key", "OtherKey", [])
    comparison.stack_inputs["producer"][0]["Outputs"]["SharedKey"] = {
        "Value": export_value,
        "Export": {"Name": "SharedKey"},
    }
    path = "Environment.EnvironmentVariables[].Value"
    ((row_id, row),) = resource(
        comparison,
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Project",
        [(path, KEY_ID, None)],
        stack="consumer",
    )
    declaration(
        comparison,
        f"desired.row.{row_id}.value",
        KEY_ID,
        service="codebuild",
        producer="kms",
        logical="Key",
        kind="KMS.Key",
        prop="KMS.Key.KeyId",
    )
    context = {"Name": "MATERIAL_KEY_ID", "Type": "PLAINTEXT"}
    value = comparison.prepare_value(
        "codebuild",
        row,
        "CodeBuild.Project",
        row_id=row_id,
        stack="consumer",
        context=context,
    ).require_value()
    desired = {"EnvironmentVariables": [dict(context, Value=value)]}
    actual = {
        "EnvironmentVariables": [dict(context, Value={"Fn::ImportValue": "SharedKey"})]
    }
    (record,) = comparison.compare_setting(
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        Settings(desired={"Environment": desired}, sources={"Environment": [{}]}),
        "consumer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    ).records
    assert record["category"] == category
    (diagnostic,) = record["reference_diagnostics"]
    assert diagnostic["reason"].startswith(reason)
    assert diagnostic.get("current_aws_verified") in (None, False)


def test_codebuild_observed_only_and_difference_are_preserved():
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "KEY", "Type": "PLAINTEXT", "Value": KEY_ID},
            {"Name": "SETTING", "Type": "PLAINTEXT", "Value": "before"},
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][0]["Value"] = {"Fn::GetAtt": ["Key", "KeyId"]}
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    args = (
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    outcome = comparison.compare_setting(*args)
    (record,) = outcome.records
    TestCase().assertEqual(record["category"], "uncompared")
    TestCase().assertTrue(record["reference_diagnostics"][0]["reason"])
    actual["EnvironmentVariables"][1]["Value"] = "after"
    outcome = comparison.compare_setting(*args)
    (record,) = outcome.records
    TestCase().assertEqual(record["category"], "difference")
    TestCase().assertTrue(record["reference_diagnostics"][0]["reason"])


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-display-")
)
def test_codebuild_uncompared_reference_display_real_path(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_display)


def _execute_codebuild_display(case):
    observed = case["data"]["observed"]
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", observed)],
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "FIRST", "Type": "PLAINTEXT", "Value": "same"},
            {"Name": "SECOND", "Type": "PLAINTEXT", "Value": "same"},
            {
                "Name": "KEY",
                "Type": "PLAINTEXT",
                "Value": "alias/venusinf-stg-material",
            },
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][2]["Value"] = {"Fn::GetAtt": ["Key", "KeyId"]}
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    args = (
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    with patch.object(comparison, "display_reference", None):
        before = comparison.compare_setting(*args)
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        after = comparison.compare_setting(*args)
    TestCase().assertTrue(before.records == after.records)
    (record,) = after.records
    TestCase().assertTrue(record["category"] == "uncompared")
    (diagnostic,) = record["reference_diagnostics"]
    TestCase().assertEqual(diagnostic["local_comparison"], "uncompared")
    TestCase().assertTrue(diagnostic["reason"])
    TestCase().assertFalse(diagnostic["current_aws_verified"])
    (field,) = after.display_differences[identifier(record)]
    TestCase().assertTrue("EnvironmentVariables[2].Value" in field["path"])
    TestCase().assertTrue(field["model"] == "alias/venusinf-stg-material")
    TestCase().assertTrue("kms/007.KeyId" in field["iac"])
    if observed:
        TestCase().assertTrue(observed in field["iac"] and "Observed" in field["iac"])
    else:
        TestCase().assertTrue("未解決" in field["iac"] and "理由" in field["iac"])
    args = ("fixture", "team", ["codebuild"])
    old = iac_dataset(before.records, *args, before.display_differences)
    new = iac_dataset(after.records, *args, after.display_differences)
    TestCase().assertTrue(old[:2] == new[:2])
    summary = iac_summary(after.records, *args, dataset=new)
    TestCase().assertTrue(summary["groups"][0]["examples"][0]["fields"] == [field])
    artifact = dict(
        version=6, **aggregate(after.records, *args, after.display_differences)
    )
    TestCase().assertTrue(
        detail_payload(artifact, "iac")["items"][0]["value_differences"] == [field]
    )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "detail": detail_payload(artifact, "iac"),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="uncompared-redaction-")
)
def test_uncompared_reference_display_preserves_redaction(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_uncompared_redaction)


def _execute_uncompared_redaction(case):
    shape = case["data"]["shape"]
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    actual = {"Items": [ref]}
    prop = "Setting"
    if shape == "expression":
        actual = Expression("Join", ["/", ["prefix", ref]])
    elif shape == "secret":
        actual = {"Name": "SECRET_TOKEN", "Value": ref}
    elif shape == "sensitive":
        comparison.sensitive_values.add(KEY_ID)
    batch = setting_result(
        "codebuild",
        "002",
        prop,
        "unknown",
        actual,
        CompareOutcome(None),
        "producer",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=comparison.display_reference,
    )
    rendered = json.dumps(batch.display_differences, ensure_ascii=False)
    if shape == "secret":
        TestCase().assertTrue(KEY_ID not in rendered and "kms/007" not in rendered)
    else:
        TestCase().assertTrue("kms/007.KeyId" in rendered)
        TestCase().assertTrue((KEY_ID not in rendered) == (shape == "sensitive"))
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


def unordered_reference(refs, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    if right == refs[0]:
        equal = True if left == "confirmed" else False
    else:
        equal = None if left == "pending" else False
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": left,
                "iac": right,
                "local_comparison": "matched"
                if equal is True
                else "uncompared"
                if equal is None
                else "difference",
                "reason": "fixture",
                "identity": "unproven",
                "allowed_forms": None,
                "format": {},
            },
        ),
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="model-correspondence-")
)
def test_uncompared_shows_only_proven_model_correspondence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_model_correspondence)


def _execute_model_correspondence(case):
    mode = case["data"]["mode"]
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    if mode == "scalar":
        desired, actual, rule = ("model-value", ref, ORDERED)
    elif mode == "ordered":
        desired, actual, rule = ([{"Value": "model-value"}], [{"Value": ref}], ORDERED)
    else:
        desired = [
            {"Name": "A", "Value": "model-value"},
            {"Name": "B", "Value": "other"},
        ]
        actual = [{"Name": "B", "Value": "other"}, {"Name": "A", "Value": ref}]
        rule = keyed("Name") if mode == "keyed" else UNORDERED
        if mode == "ambiguous":
            desired = [{"Value": "model-value"}, {"Value": "other"}]
            actual = [{"Value": ref}, {"Value": ref}]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": rule},
        reference=unproven_reference,
    )
    TestCase().assertTrue(decision.equal is None)
    batch = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=lambda v, *args: v,
        display_reference=lambda ref: ("resolved", "fixture"),
    )
    if mode == "ambiguous":
        fields = next(iter(batch.display_differences.values()))
        TestCase().assertTrue(
            [field["model"] for field in fields] == ["対応未確定"] * 2
        )
    else:
        fields = next(iter(batch.display_differences.values()))
        TestCase().assertTrue([field["model"] for field in fields] == ["model-value"])
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sensitive-correspondence-")
)
def test_uncompared_model_correspondence_respects_sensitive_redaction(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_sensitive_correspondence)


def _execute_sensitive_correspondence(case):
    comparison = fixture()
    comparison.sensitive_values.add(case["data"]["secret"])
    desired = {"Value": case["data"]["secret"]}
    actual = {
        "Value": ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    }
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=lambda left, right, path: ReferenceDecision(
            None,
            (
                comparison.redacted(
                    {
                        "path": path,
                        "model": left,
                        "iac": right,
                        "local_comparison": "uncompared",
                        "reason": "unproven",
                    }
                ),
            ),
        )
        if isinstance(right, ResourceReference)
        else ReferenceDecision(NotImplemented),
    )
    batch = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=lambda ref: ("resolved", "fixture"),
    )
    field = next(iter(batch.display_differences.values()))[0]
    TestCase().assertTrue(case["data"]["secret"] not in json.dumps(field))
    TestCase().assertTrue("masked" in field["model"])
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "warnings": projected(batch.warnings),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="display-error-")
)
def test_display_failure_does_not_change_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_display_error)


def _execute_display_error(case):
    equal = case["data"]["equal"]
    actual_error = Blocked("original error") if case["data"]["actual_error"] else None
    ref = ResourceReference({"$resource": ["s3", "001"], "$attribute": "BucketName"})
    decision = CompareOutcome(equal, diagnostics=({"reason": "original evidence"},))
    if equal is False:
        decision = compare_values("other", ref, "Setting", rules={"Setting": ORDERED})
    args = ("s3", "001", "Setting", "other", ref, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=actual_error, redact=safe_value)
    resolver = Mock(side_effect=ValueError("display bug"))
    after = setting_result(
        *args, actual_error=actual_error, redact=safe_value, display_reference=resolver
    )
    TestCase().assertTrue(after.records == before.records)
    if actual_error is not None:
        resolver.assert_not_called()
        TestCase().assertTrue(not after.warnings)
    else:
        TestCase().assertTrue("ValueError: display bug" in after.warnings[0]["message"])
        if equal is False:
            field = next(iter(after.display_differences.values()))[0]
            TestCase().assertTrue(
                "未解決" in field["iac"] and "s3/001.BucketName" in field["iac"]
            )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "warnings": projected(after.warnings),
        "resolve_count": resolver.call_count,
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="unordered-diagnosed-")
)
def test_unordered_uncompared_displays_only_diagnosed_reference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_unordered_diagnosed)


def _execute_unordered_diagnosed(case):
    nested = case["data"]["nested"]
    refs = [
        ResourceReference({"$resource": ["kms", f"00{i}"], "$attribute": "KeyId"})
        for i in (1, 2)
    ]
    desired = ["confirmed", "pending"]
    actual = refs
    ruleset = {"Setting": UNORDERED}
    if nested:
        desired = [{"Value": value} for value in desired]
        actual = [{"Value": value} for value in refs]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules=ruleset,
        reference=partial(unordered_reference, refs),
    )
    TestCase().assertTrue(decision.equal is None)
    resolver = Mock(side_effect=[("resolved", "fixture")])
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    TestCase().assertTrue(after.records == before.records and (not after.warnings))
    fields = after.display_differences[identifier(after.records[0])]
    TestCase().assertTrue(len(fields) == 1)
    TestCase().assertTrue(fields[0]["model"] == "pending")
    TestCase().assertTrue("kms/002.KeyId" in fields[0]["iac"])
    resolver.assert_called_once_with(refs[1])
    old = iac_dataset(
        before.records, "fixture", "team", ["test"], before.display_differences
    )
    new = iac_dataset(
        after.records, "fixture", "team", ["test"], after.display_differences
    )
    TestCase().assertTrue(old[:2] == new[:2])
    artifact = dict(
        version=6,
        **aggregate(
            after.records, "fixture", "team", ["test"], after.display_differences
        ),
    )
    TestCase().assertTrue(
        detail_payload(artifact, "iac")["items"][0]["value_differences"] == fields
    )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "detail": detail_payload(artifact, "iac"),
    }


def many_reference(left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    number = int(right["$resource"][1])
    equal = (None if number == 30 else True) if left == str(number) else False
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": left,
                "iac": right,
                "local_comparison": "uncompared"
                if equal is None
                else "matched"
                if equal
                else "difference",
            },
        ),
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="many-unordered-")
)
def test_many_unordered_references_resolve_only_pending(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_many_unordered)


def _execute_many_unordered(case):
    refs = [
        ResourceReference({"$resource": ["kms", f"{i:03}"], "$attribute": "KeyId"})
        for i in range(1, case["data"]["stop"])
    ]
    desired = [str(i) for i in range(1, case["data"]["stop"])]
    decision = compare_values(
        desired, refs, "Setting", rules={"Setting": UNORDERED}, reference=many_reference
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        refs,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    TestCase().assertTrue(decision.equal is None and (not result.warnings))
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue(len(fields) == 1 and "kms/030.KeyId" in fields[0]["iac"])
    resolver.assert_called_once_with(refs[-1])
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
        "warnings": projected(result.warnings),
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
