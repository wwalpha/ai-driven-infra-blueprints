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
from comparison.deferral import ImportReferenceDeferred
from comparison.evaluation import project_actual
from comparison.methods import ORDERED, compare_values
from comparison.registry import rules
from comparison.result import identifier, setting_result, value_differences
from comparison.runner import Settings
from issues.aggregate import aggregate, iac_dataset, iac_summary
from issues.artifact import detail_payload
from support.comparison_cases import projected
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    ResourceReference,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    KEY_ID,
    ROOT,
    codebuild_batch,
    fixture,
    resource,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


def evaluate_actual_wait(original, error, stack, value, *args):
    if value == {"Ref": "External"}:
        raise error
    return original(stack, value, *args)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="actual-wait-")
)
def test_actual_wait_retains_pointer_and_known_siblings(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_actual_wait)


def _execute_actual_wait(case):
    data = case["data"]
    error = ImportReferenceDeferred(
        data["phase"],
        "vpc",
        "004",
        "EC2.Subnet",
        "SubnetId",
        "CodeBuild.Project.VpcConfig.Subnets[]",
    )
    comparison = fixture()
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("VpcConfig", json.dumps(data["desired"]), None)],
        properties={"VpcConfig": data["actual"]},
    )
    evaluate = partial(evaluate_actual_wait, comparison.evaluate, error)
    comparison.evaluate = evaluate
    projection = project_actual(
        data["projection"],
        evaluate=partial(evaluate, "producer"),
        property_name="CodeBuild.Project.VpcConfig",
        model_path=ROOT / "synthetic.yaml",
    )
    TestCase().assertEqual(len(projection.failures), 1)
    TestCase().assertEqual(projection.failures[0][1], "/Subnets/0")
    TestCase().assertIs(projection.failures[0][2], error)
    TestCase().assertFalse(projection.warnings)
    document = comparison.stack_inputs["producer"][0]
    batch = codebuild_batch(comparison, document)
    return {
        "failure_pointer": projection.failures[0][1],
        "records": projected(batch.records),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="resource-failure-")
)
def test_resource_failure_uses_shared_classification(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_resource_failure)


def _execute_resource_failure(case):
    data = case["data"]
    comparison = fixture()
    comparison.services = ["codebuild"]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("Name", "build", None)],
    )
    if data["phase"] is not None:
        failure = ImportReferenceDeferred(
            data["phase"],
            "vpc",
            "004",
            "EC2.Subnet",
            "SubnetId",
            "CodeBuild.Project.VpcConfig.Subnets[]",
        )
    else:
        failure = {"Blocked": Blocked, "ValueError": ValueError}[data["error_type"]](
            data["message"]
        )
    comparison.compare_rows = Mock(side_effect=failure)
    with patch.object(Path, "is_file", return_value=True):
        (item,) = comparison.run()
    if data["phase"] is not None:
        TestCase().assertEqual(item["cause"], failure.iac_cause)
    return {"record": projected(item)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="deferred-operand-")
)
def test_deferred_intrinsic_does_not_hide_other_operand_failures(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_deferred_operand)


def _execute_deferred_operand(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison, observed=data["observed"])
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    comparison.models["vpc"].authoritative["desired.resource.001.resourceMode"] = (
        "IMPORT"
    )
    comparison.models["vpc"].values["desired.resource.001.resourceMode"] = "IMPORT"
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("VpcConfig", json.dumps({"VpcId": data["expression"]}), None)],
        properties={"VpcConfig": {"VpcId": "external"}},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = codebuild_batch(comparison, document)
    TestCase().assertTrue(
        any(item["category"] in {"uncompared", "error"} for item in batch.records)
    )
    TestCase().assertFalse(
        any(item["category"] in {"matched", "difference"} for item in batch.records)
    )
    return {"records": projected(batch.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="display-pipeline-")
)
def test_iac_reference_display_pipeline_preserves_comparison_and_issues(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_display_pipeline)


def _execute_display_pipeline(case):
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
    resource(
        comparison,
        "kms",
        "008",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/fixture", None)],
        properties={"AliasName": "alias/fixture", "TargetKeyId": {"Ref": "Key"}},
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "FIRST", "Type": "PLAINTEXT", "Value": "same"},
            {"Name": "SECOND", "Type": "PLAINTEXT", "Value": "same"},
            {"Name": "KEY_ID", "Type": "PLAINTEXT", "Value": "alias/fixture"},
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][2]["Value"] = {"Fn::GetAtt": ["Key", "KeyId"]}
    actual = comparison.evaluate("producer", actual)
    decision = compare_values(
        desired, actual, "Environment", rules=rules("CodeBuild.Project")
    )
    args = (
        "codebuild",
        "002",
        "CodeBuild.Project.Environment",
        desired,
        actual,
        decision,
        "producer",
        [{}],
        {},
    )
    before = setting_result(*args, actual_error=None, redact=comparison.redacted)
    authority = copy.deepcopy(comparison.models["kms"].authoritative)
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        after = setting_result(
            *args,
            actual_error=None,
            redact=comparison.redacted,
            display_reference=comparison.display_reference,
        )
    TestCase().assertTrue(after.failure is None, after.failure)
    TestCase().assertTrue(
        before.records == after.records and before.warnings == after.warnings
    )
    TestCase().assertTrue(authority == comparison.models["kms"].authoritative)
    (record,) = after.records
    TestCase().assertTrue(record["category"] == "difference", record)
    (field,) = after.display_differences[identifier(record)]
    TestCase().assertTrue(field["path"] == "EnvironmentVariables[2].Value")
    TestCase().assertTrue(field["model"] == "alias/fixture")
    TestCase().assertTrue("参照: kms/007.KeyId" in field["iac"])
    TestCase().assertTrue("alias/fixture" not in field["iac"])
    if observed == KEY_ID:
        TestCase().assertTrue(
            field["iac"].startswith(json.dumps(KEY_ID) + " (参照:"), field
        )
        TestCase().assertTrue("Observed（記録値・現在AWS未確認）" in field["iac"])
    else:
        TestCase().assertTrue(field["iac"].startswith("未解決"))
        TestCase().assertTrue("理由: identifier_unobserved" in field["iac"])
    args = ("fixture", "team", ["codebuild"])
    old_dataset = iac_dataset(before.records, *args, before.display_differences)
    dataset = iac_dataset(after.records, *args, after.display_differences)
    TestCase().assertTrue(old_dataset[:2] == dataset[:2])
    TestCase().assertTrue(dataset[2] == after.display_differences)
    old_summary = iac_summary(before.records, *args, dataset=old_dataset)
    summary = iac_summary(after.records, *args, dataset=dataset)
    TestCase().assertTrue(summary["groups"][0]["examples"][0]["fields"][0]["iac"])
    for report in (old_summary, summary):
        for group in report["groups"]:
            for example in group["examples"]:
                example["fields"] = []
    TestCase().assertTrue(old_summary == summary)
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
    "case_id", case_ids("reference_evidence", prefix="display-cache-")
)
def test_iac_reference_display_local_expression_and_cache(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_display_cache)


def _execute_display_cache(case):
    shape = case["data"]["shape"]
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
    ref = ResourceReference({"$resource": ["s3", "001"], "$attribute": "BucketName"})
    actual = {
        "direct": ref,
        "nested": {"Items": [ref, ref]},
        "join": Expression("Join", ["/", [ref, ref]]),
        "sub": Expression("Sub", ["prefix/${bucket}", {"bucket": ref}]),
        "select": Expression(
            "Select",
            [0, Expression("Split", ["/", Expression("Join", ["/", [ref, "tail"]])])],
        ),
    }[shape]
    decision = compare_values(
        "different", actual, "Setting", rules={"Setting": ORDERED}
    )
    original = copy.deepcopy(actual)
    with patch.object(
        comparison, "reference_literal", wraps=comparison.reference_literal
    ) as resolve:
        fields = value_differences(
            decision,
            "different",
            actual,
            "Setting",
            redact=comparison.redacted,
            display_reference=comparison.display_reference,
        )
        TestCase().assertEqual(resolve.call_count, 1)
    TestCase().assertEqual(actual, original)
    shown = fields[0]["iac"]
    for text in ("fixture-bucket", "s3/001.BucketName", "IaC（ローカル評価）"):
        TestCase().assertIn(text, shown)
    for text in ("Observed", "$resource", "$expression"):
        TestCase().assertNotIn(text, shown)
    if shape == "join":
        TestCase().assertTrue(shown.startswith("fixture-bucket/fixture-bucket"))
    if shape == "sub":
        TestCase().assertTrue(shown.startswith("prefix/fixture-bucket"))
    return {"fields": fields, "resolve_count": resolve.call_count}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="display-mask-")
)
def test_iac_reference_display_retains_masks(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_display_mask)


def _execute_display_mask(case):
    mask = case["data"]["mask"]
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
    prop, actual = "Setting", ref
    if mask == "property":
        prop = "SecretString"
    elif mask == "environment":
        actual = {"Name": "SECRET_TOKEN", "Value": ref}
    elif mask == "sensitive":
        comparison.sensitive_values.add(KEY_ID)
    elif mask == "producer":
        ref["$attribute"] = "SecretString"
    elif mask == "expression":
        actual = Expression(
            "Sub", ["${Password}/${key}", {"Password": "never-expose", "key": ref}]
        )
    decision = compare_values("different", actual, prop, rules={prop: ORDERED})
    with patch.object(comparison, "reference_literal", return_value=KEY_ID) as resolve:
        fields = value_differences(
            decision,
            "different",
            actual,
            prop,
            redact=comparison.redacted,
            display_reference=comparison.display_reference,
        )
    text = json.dumps(fields, ensure_ascii=False)
    TestCase().assertNotIn("never-expose", text)
    if mask != "expression":
        TestCase().assertNotIn(KEY_ID, text)
        TestCase().assertIn("masked", text)
    if mask in {"property", "environment"}:
        resolve.assert_not_called()
    batch = setting_result(
        "codebuild",
        "002",
        prop,
        "different",
        actual,
        decision,
        "producer",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=comparison.display_reference,
    )
    artifact = dict(
        version=6,
        **aggregate(
            batch.records,
            "fixture",
            "team",
            ["codebuild"],
            batch.display_differences,
            redact=comparison.redacted,
        ),
    )
    text = json.dumps(detail_payload(artifact, "iac"), ensure_ascii=False)
    TestCase().assertNotIn("never-expose", text)
    if mask != "expression":
        TestCase().assertNotIn(KEY_ID, text)
    return {"fields": fields, "detail": detail_payload(artifact, "iac")}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="display-failure-")
)
def test_iac_reference_display_expected_failures_only(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_display_failure)


def _execute_display_failure(case):
    failure = case["data"]["failure"]
    comparison = fixture()
    vpc(comparison)
    ref = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "VpcId"})
    if failure == "absent":
        ref["$resource"][1] = "999"
    if failure == "context":
        comparison.reference_models_loaded = False
    decision = compare_values("different", ref, "Setting", rules={"Setting": ORDERED})
    error = (
        ValueError("implementation bug")
        if failure == "bug"
        else Blocked("identifier_unobserved")
    )
    with patch.object(comparison, "reference_literal", side_effect=error) as resolve:
        if failure == "bug":
            with pytest.raises(ValueError, match="implementation bug") as raised:
                value_differences(
                    decision,
                    "different",
                    ref,
                    display_reference=comparison.display_reference,
                )
            return {
                "error": {
                    "type": type(raised.value).__name__,
                    "message": str(raised.value),
                },
                "resolve_count": resolve.call_count,
            }
        results = []
        for _ in range(2):
            fields = value_differences(
                decision,
                "different",
                ref,
                display_reference=comparison.display_reference,
            )
            TestCase().assertIn("未解決", fields[0]["iac"])
            TestCase().assertIn("理由:", fields[0]["iac"])
            TestCase().assertIn("vpc/", fields[0]["iac"])
            results.append(fields)
        TestCase().assertEqual(resolve.call_count, 1 if failure == "blocked" else 0)
    return {"results": results, "resolve_count": resolve.call_count}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="display-nonreference-")
)
def test_iac_reference_display_preserves_nonreferences_and_missing(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_display_nonreference)


def _execute_display_nonreference(case):
    data = case["data"]
    actual = Expression("Join", data["actual"]) if data["join"] else data["actual"]
    decision = compare_values({"a": 1}, actual, "Setting", rules={"Setting": ORDERED})
    expected = value_differences(decision, {"a": 1}, actual)
    resolver = Mock(side_effect=AssertionError("non-reference must not resolve"))
    fields = value_differences(decision, {"a": 1}, actual, display_reference=resolver)
    TestCase().assertEqual(fields, expected)
    resolver.assert_not_called()
    return {"fields": fields}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="display-runner-")
)
def test_iac_reference_display_runner_decisions_unchanged(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_display_runner)


def _execute_display_runner(case):
    desired, expected = case["data"]["desired"], case["data"]["category"]
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
    vpc(comparison)
    actual = {"Ref": "Vpc" if expected == "uncompared" else "Bucket"}
    settings = Settings(desired={"Description": desired}, sources={"Description": [{}]})
    args = (
        "iam",
        "002",
        "IAM.Role",
        "Description",
        desired,
        settings,
        "producer",
        {"Properties": {"Description": actual}},
        ROOT / "synthetic.yaml",
    )
    with patch.object(comparison, "display_reference", None):
        before = comparison.compare_setting(*args)
    with patch.object(
        comparison, "display_reference", wraps=comparison.display_reference
    ) as resolve:
        after = comparison.compare_setting(*args)
    TestCase().assertEqual(before.records, after.records)
    TestCase().assertEqual([item["category"] for item in after.records], [expected])
    TestCase().assertEqual(resolve.call_count, 0 if expected == "matched" else 1)
    if expected == "difference":
        TestCase().assertIn(
            "参照: s3/001.BucketName",
            next(iter(after.display_differences.values()))[0]["iac"],
        )
    return {
        "records": projected(after.records),
        "display": projected(after.display_differences),
        "resolve_count": resolve.call_count,
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-env-")
)
def test_codebuild_plaintext_iac_reference_environment(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_environment)


def _execute_codebuild_environment(case):
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
        stack="producer",
    )
    if data["export"]:
        comparison.stack_inputs["producer"][0]["Outputs"]["Shared"] = {
            "Value": {"Ref": "Bucket"},
            "Export": {"Name": "shared"},
        }
    desired = {
        "EnvironmentVariables": [
            {"Name": data["name"], "Type": data["selector"], "Value": data["literal"]}
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
        data["stack"],
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    if data["check_evidence"]:
        (record,) = outcome.records
        (evidence,) = record["reference_diagnostics"]
        TestCase().assertEqual(evidence["evidence_type"], "local_evaluation")
        TestCase().assertEqual(evidence["local_comparison"], record["category"])
        TestCase().assertIs(evidence["current_aws_verified"], False)
    return {"records": projected(outcome.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-producer-")
)
def test_codebuild_wrong_producer_expression(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_environment)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-bucket-arn-")
)
def test_codebuild_plaintext_getatt_bucket_arn(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_environment)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
