"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from support.comparison_cases import projected
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    ResourceReference,
    same,
    unordered_same,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    QUEUE_ARN,
    ROOT,
    RULE_ARN,
    VPC,
    _execute_sqs_context,
    _portable_synthetic_root,
    _reference_decision_data,
    exported,
    fixture,
    reference_for,
    resource,
    setting,
    sqs_policy_fixture,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="export-scope-")
)
def test_cached_exports_are_bound_to_the_consumer_scope(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_export_scope)


def _execute_export_scope(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison)
    original = exported(comparison, {"Ref": "Vpc"})
    TestCase().assertIsNone(
        comparison.reference_same(VPC, original, "EC2.Subnet", "VpcId")
    )
    document, parameters, pseudo = comparison.stack_inputs["consumer"]
    comparison.stack_inputs["consumer"] = (
        document,
        parameters,
        dict(pseudo, **{data["field"]: data["replacement"]}),
    )
    with pytest.raises(Blocked, match="handoff matches=0|confirmed") as failure:
        comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="shared-arn-")
)
def test_shared_recorded_arn_proof(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_shared_recorded_arn)


def _execute_shared_recorded_arn(case):
    data = case["data"]
    kind, attribute, arn = data["kind"], data["attribute"], data["arn"]
    comparison = fixture()
    resource(
        comparison,
        "producer",
        "001",
        kind,
        "Resource",
        [(attribute, "PENDING_DEPLOY", data["identifier"])],
        properties=dict(data["properties"], **{attribute: "forged-template-id"}),
    )
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    if not data["observed_present"]:
        comparison.models["producer"].authoritative.pop("observed.row.001-001.value")
    comparison.resources["producer"]["001"]["resourceMode"] = data["resource_mode"]
    if data["inactive"]:
        comparison.stack_inputs["producer"][0]["Conditions"] = {"Off": False}
        comparison.stack_inputs["producer"][0]["Resources"]["Resource"]["Condition"] = (
            "Off"
        )
    decisions = []
    for left, right in [(symbol, arn), (arn, symbol)]:
        decision = comparison.reference_decision(
            left, right, "IAM.Role", "Policies[].PolicyDocument.Statement[].Resource"
        )
        TestCase().assertIsNone(decision.equal)
        TestCase().assertFalse(decision.equivalent)
        if data["check_evidence"]:
            TestCase().assertEqual(
                decision.diagnostics[0]["evidence_type"], "recorded_observed"
            )
            TestCase().assertIs(decision.diagnostics[0]["current_aws_verified"], False)
        decisions.append(_reference_decision_data(decision))
    different_results = []
    if data["check_evidence"]:
        for different in (
            arn + "-other",
            arn.replace("arn:aws:", "arn:aws-cn:"),
            arn.replace("123456789012", "999999999999"),
        ):
            if different != arn:
                result = comparison.reference_same(symbol, different, "IAM.Role", "")
                TestCase().assertIsNone(result)
                different_results.append(result)
    return {"decisions": decisions, "different_results": different_results}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-errors-")
)
def test_iac_partial_errors_preserve_known_fields(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_errors)


def _execute_partial_errors(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    actual = data["actual"]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        data["rows"],
        properties={"Environment": actual},
    )
    comparison.template_locations[id(actual["EnvironmentVariables"][0])] = {"Value": 23}
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    categories = [item["category"] for item in batch.records]
    check = TestCase()
    check.assertEqual(categories.count("difference"), int(data["known_difference"]))
    check.assertEqual(categories.count("error"), 1)
    check.assertEqual(categories.count("uncompared"), int(data["model_unresolved"]))
    check.assertNotIn("matched", categories)
    check.assertIsNone(batch.failure)
    error = next(item for item in batch.records if item["category"] == "error")
    check.assertEqual(
        error["property"], "CodeBuild.Project.Environment#/EnvironmentVariables/0/Value"
    )
    check.assertEqual(
        error["iac"],
        {
            "path": "synthetic.yaml",
            "line": 23,
            "pointer": "/EnvironmentVariables/0/Value",
        },
    )
    if data["known_difference"]:
        check.assertEqual(
            {item["path"] for item in next(iter(batch.display_differences.values()))},
            {"Image", "EnvironmentVariables[0].Type"},
        )
    if data["model_unresolved"]:
        unresolved = next(
            item for item in batch.records if item["category"] == "uncompared"
        )
        check.assertIn("PLAINTEXTではResource linkは禁止", unresolved["reason"])
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-extra-")
)
def test_iac_partial_selective_extra_fields(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_extra)


def _execute_partial_extra(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        data["rows"],
        properties={"Environment": data["actual"]},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    differences = [item for item in batch.records if item["category"] == "difference"]
    TestCase().assertEqual(len(differences), int(data["different"]))
    TestCase().assertFalse(any(item["category"] == "error" for item in batch.records))
    if not data["exact"]:
        TestCase().assertEqual(
            [item["category"] for item in batch.records],
            ["difference" if data["different"] else "matched"],
        )
    if data["different"]:
        TestCase().assertIn(
            "Image",
            {item["path"] for item in next(iter(batch.display_differences.values()))},
        )
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-presence-")
)
def test_iac_partial_array_presence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_presence)


def _execute_partial_presence(case):
    data = case["data"]
    comparison = fixture()
    comparison.stack_inputs["producer"][2]["AWS::NoValue"] = {"$noValue": True}
    comparison.stack_inputs["producer"][0].update(data["document_fields"])
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [(data["key"], json.dumps(data["desired"]), None)],
        properties=data["properties"],
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    TestCase().assertEqual(
        sum(item["category"] == "difference" for item in batch.records), 1
    )
    fields = next(iter(batch.display_differences.values()))
    TestCase().assertEqual(len(fields), 1)
    TestCase().assertTrue(
        fields[0]["path"].endswith(".Value" if data["key"] == "Tags" else ".Type")
    )
    TestCase().assertNotEqual(fields[0]["iac"], "欠落")
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-keyed-")
)
def test_iac_partial_keyed_and_conditional_membership(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_keyed)


def _execute_partial_keyed(case):
    data = case["data"]
    comparison = fixture()
    comparison.stack_inputs["producer"][2]["AWS::NoValue"] = {"$noValue": True}
    comparison.stack_inputs["producer"][0].update(data["document_fields"])
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        data["rows"],
        properties={"Tags": data["actual"]},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-cardinality-")
)
def test_iac_partial_array_cardinality(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_cardinality)


def _execute_partial_cardinality(case):
    data = case["data"]
    comparison = fixture()
    actual = [
        Expression("Unverified", []) if item == "unknown" else item
        for item in data["actual"]
    ]
    callback = partial(reference_for, comparison, "IAM.Role")
    result = (
        unordered_same(data["desired"], actual, reference=callback)
        if data["unordered"]
        else same(data["desired"], actual, reference=callback)
    )
    if result is not None:
        TestCase().assertIs(type(result), bool)
    return {"equal": result}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-diagnostic-")
)
def test_iac_partial_error_keeps_reference_diagnostics(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_diagnostic)


def _execute_partial_diagnostic(case):
    comparison = fixture()
    vpc(comparison, observed=None)
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        case["data"]["rows"],
        properties=case["data"]["properties"],
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    TestCase().assertEqual(
        sorted(item["category"] for item in batch.records), ["error", "uncompared"]
    )
    unresolved = next(
        item for item in batch.records if item["category"] == "uncompared"
    )
    TestCase().assertTrue(unresolved["reference_diagnostics"])
    TestCase().assertFalse(batch.display_differences)
    return {"records": projected(batch.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="partial-condition-")
)
def test_iac_partial_error_and_unknown_condition(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_partial_condition)


def _execute_partial_condition(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        data["rows"],
        properties={"Environment": data["actual"]},
    )
    _portable_synthetic_root(comparison)
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        comparison.root / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    check = TestCase()
    check.assertIsNone(batch.failure)
    check.assertEqual(
        sorted(item["category"] for item in batch.records),
        sorted(["error", "uncompared"] + (["difference"] if data["different"] else [])),
    )
    check.assertTrue(any("Condition" in item["message"] for item in batch.warnings))
    if data["different"]:
        check.assertEqual(
            [item["path"] for item in next(iter(batch.display_differences.values()))],
            ["Image"],
        )
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "warnings": projected(batch.warnings),
    }


def test_sqs_policy_named_arn_match():
    comparison, desired, actual = sqs_policy_fixture()
    before = copy.deepcopy(comparison.models["sqs"].authoritative)
    records = setting(comparison, "SQS.QueuePolicy", "PolicyDocument", desired, actual)
    assert [record["category"] for record in records] == ["matched"], records
    assert comparison.models["sqs"].authoritative == before


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sqs-policy-difference-")
)
def test_sqs_policy_proven_difference_is_sqs_specific(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sqs_policy_difference)


def _execute_sqs_policy_difference(case):
    data = case["data"]
    comparison, desired, actual = sqs_policy_fixture()
    statement = desired["Statement"][0]
    comparison.stack_inputs["producer"][0]["Resources"]["Queue"]["Properties"][
        "QueueName"
    ] = data["queue_name"]
    statement["Resource"] = data["queue_arn"]
    statement["Condition"]["ArnEquals"]["aws:SourceArn"] = data["source_arn"]
    records = setting(comparison, "SQS.QueuePolicy", "PolicyDocument", desired, actual)
    check = TestCase()
    check.assertEqual([record["category"] for record in records], ["difference"])
    diagnostics = records[0]["reference_diagnostics"]
    queue = next(item for item in diagnostics if item["path"].endswith(".Resource"))
    rule = next(item for item in diagnostics if item["path"].endswith("aws:SourceArn"))
    check.assertEqual(queue["producers"], [{"producer": "sqs/001", "attribute": "Arn"}])
    source_diff = data["source_arn"] != RULE_ARN
    check.assertEqual(
        queue["local_comparison"], "matched" if source_diff else "difference"
    )
    check.assertEqual(
        rule["local_comparison"], "difference" if source_diff else "matched"
    )
    check.assertEqual(queue["identity"], "unproven")
    check.assertEqual(queue["format"]["model"], "unproven")
    check.assertEqual(queue["evidence_type"], "local_evaluation")
    check.assertIs(queue["current_aws_verified"], False)
    check.assertEqual(records[0]["desired"], desired)
    check.assertIn(statement["Resource"], json.dumps(records))
    check.assertIn(
        statement["Condition"]["ArnEquals"]["aws:SourceArn"], json.dumps(records)
    )
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sqs-unproven-")
)
def test_sqs_unproven_names(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sqs_unproven)


def _execute_sqs_unproven(case):
    comparison, desired, actual = sqs_policy_fixture()
    properties = comparison.stack_inputs["producer"][0]["Resources"]["Queue"][
        "Properties"
    ]
    properties.clear()
    properties.update(case["data"]["properties"])
    records = setting(comparison, "SQS.QueuePolicy", "PolicyDocument", desired, actual)
    TestCase().assertEqual([record["category"] for record in records], ["uncompared"])
    queue = next(
        item
        for item in records[0]["reference_diagnostics"]
        if item["path"].endswith(".Resource")
    )
    TestCase().assertEqual(queue["local_comparison"], "uncompared")
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sqs-name-boundary-")
)
def test_sqs_explicit_name_boundaries(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sqs_name_boundary)


def _execute_sqs_name_boundary(case):
    name = case["data"]["name"]
    comparison, desired, actual = sqs_policy_fixture()
    comparison.stack_inputs["producer"][0]["Resources"]["Queue"]["Properties"][
        "QueueName"
    ] = name
    desired["Statement"][0]["Resource"] = QUEUE_ARN.rsplit(":", 1)[0] + ":" + name
    records = setting(comparison, "SQS.QueuePolicy", "PolicyDocument", desired, actual)
    TestCase().assertEqual([item["category"] for item in records], ["matched"])
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sqs-context-")
)
def test_sqs_arn_context_requires_proof(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sqs_context)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
