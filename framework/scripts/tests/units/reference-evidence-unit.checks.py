"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.methods import compare_values
from comparison.registry import rules
from comparison.rows import validated_rows
from model.references import declarations
from support.comparison_cases import outcome_data, projected
from support.fixture_cases import load_case
from support.regression_cases import case_ids, expected_path
from utils.comparison_rows import put_row
from utils.iac_values import (
    ResourceReference,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    ROOT,
    VPC,
    _execute_negative,
    _reference_decision_data,
    consumer,
    declaration,
    exported,
    fixture,
    policy_reference,
    prepared,
    resource,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="terminal-"))
def test_terminal_string_array_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_terminal)


def _execute_terminal(case):
    stored, shape, actual = (
        case["data"]["stored"],
        case["data"]["shape"],
        case["data"]["actual"],
    )
    comparison = fixture()
    kind = "GuardDuty.MalwareProtectionPlan"
    field = "ProtectedResource.S3Bucket.ObjectPrefixes[]"
    rows = resource(
        comparison,
        "guardduty",
        "001",
        kind,
        "Plan",
        [(field, value, None) for value in stored],
        properties={"ProtectedResource": {"S3Bucket": {"ObjectPrefixes": actual}}},
    )
    for rid, row in rows:
        row["valueShape"] = shape
        comparison.models["guardduty"].authoritative[
            f"desired.row.{rid}.valueShape"
        ] = shape
    if case["data"]["prepare"]:
        desired = {}
        for rid, row in rows:
            value = comparison.prepare_value("guardduty", row, kind, row_id=rid)
            put_row(desired, field, value.require_value())
        assert desired == {
            "ProtectedResource": {"S3Bucket": {"ObjectPrefixes": actual}}
        }
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "guardduty",
        "001",
        comparison.resources["guardduty"]["001"],
        "producer",
        "Plan",
        ROOT / "synthetic.yaml",
        document["Resources"]["Plan"],
        document,
    )
    assert batch.failure is None, batch.failure
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "warnings": projected(batch.warnings),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="array-member-literal-")
)
def test_array_member_string_remains_literal(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_array_member_literal)


def _execute_array_member_literal(case):
    data = case["data"]
    comparison = fixture()
    kind = "GuardDuty.MalwareProtectionPlan"
    values = {}
    for field in data["fields"]:
        value = comparison.prepare_value(
            "guardduty",
            {"property": kind + "." + field, "value": "`" + data["text"] + "`"},
            kind,
        )
        values[field] = value.require_value()
        TestCase().assertEqual(values[field], data["text"])
    return {"values": values}


def test_terminal_string_array_is_not_service_specific():
    comparison = fixture()
    value = comparison.prepare_value(
        "codebuild",
        {
            "property": "CodeBuild.Project.VpcConfig.Subnets[]",
            "value": '`["subnet-first","subnet-second"]`',
            "valueShape": "projection",
        },
        "CodeBuild.Project",
    )
    assert value.require_value() == ["subnet-first", "subnet-second"]


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="sibling-"))
def test_projection_sibling_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sibling)


def _execute_sibling(case):
    conflicting, selected = case["data"]["conflicting"], case["data"]["selected"]
    comparison = fixture()
    kind = "CodeBuild.Project"
    values = [
        ("VpcConfig.VpcId", "vpc-123", None),
        ("VpcConfig.Subnets[]", '["subnet-2","subnet-1"]', None),
    ]
    if conflicting:
        values.append(("VpcConfig.Subnets[]", "subnet-3", None))
    rows = resource(
        comparison,
        "codebuild",
        "001",
        kind,
        "Build",
        values,
        properties={
            "VpcConfig": {"VpcId": "vpc-123", "Subnets": ["subnet-2", "subnet-1"]}
        },
    )
    rows[1][1]["valueShape"] = "projection"
    comparison.models["codebuild"].authoritative["desired.row.001-002.valueShape"] = (
        "projection"
    )
    valid, unresolved = validated_rows(kind, rows)
    assert valid == (rows[:1] if conflicting else rows)
    assert set(unresolved) == ({"VpcConfig.Subnets[]"} if conflicting else set())
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
        properties=selected,
    )
    assert batch.failure is None, batch.failure
    uncompared = [item for item in batch.records if item["category"] == "uncompared"]
    assert bool(uncompared) == (conflicting and selected != ["VpcConfig.VpcId"]), (
        batch.records
    )
    if uncompared:
        assert all(
            item["property"] == kind + ".VpcConfig.Subnets[]" for item in uncompared
        )
    else:
        assert batch.records and all(
            item["category"] == "matched" for item in batch.records
        ), batch.records
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "warnings": projected(batch.warnings),
        "valid": projected(valid),
        "unresolved": projected(unresolved),
    }


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="indexed-"))
def test_indexed_projection_iac_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_indexed)


def _execute_indexed(case):
    actual = case["data"]["actual"]
    comparison = fixture()
    kind = "QuickSight.DataSource"
    rows = resource(
        comparison,
        "quicksight",
        "001",
        kind,
        "Projected",
        [
            ("Permissions[1].Principal", "principal", None),
            ("Permissions[1].Actions[]", '["ActionA"]', None),
        ],
        properties={"Permissions": [{"Principal": "principal", "Actions": actual}]},
    )
    rows[1][1]["valueShape"] = "projection"
    comparison.models["quicksight"].authoritative["desired.row.001-002.valueShape"] = (
        "projection"
    )
    valid, unresolved = validated_rows(kind, rows)
    assert valid == rows and not unresolved
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "quicksight",
        "001",
        comparison.resources["quicksight"]["001"],
        "producer",
        "Projected",
        ROOT / "synthetic.yaml",
        document["Resources"]["Projected"],
        document,
    )
    assert batch.failure is None, batch.failure
    assert not any(
        item["category"] in {"error", "uncompared"} for item in batch.records
    ), batch.records
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "warnings": projected(batch.warnings),
    }


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="parent-"))
def test_parent_projection_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_parent)


def _execute_parent(case):
    service, kind, field, encoded, actual = (
        case["data"]["service"],
        case["data"]["kind"],
        case["data"]["field"],
        case["data"]["encoded"],
        case["data"]["actual"],
    )
    comparison = fixture()
    rows = resource(
        comparison,
        service,
        "001",
        kind,
        "Projected",
        [(field, encoded, None)],
        properties=actual,
    )
    rows[0][1]["valueShape"] = "projection"
    comparison.models[service].authoritative["desired.row.001-001.valueShape"] = (
        "projection"
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        service,
        "001",
        comparison.resources[service]["001"],
        "producer",
        "Projected",
        ROOT / "synthetic.yaml",
        document["Resources"]["Projected"],
        document,
    )
    assert batch.failure is None, batch.failure
    assert batch.records and all(
        item["category"] == "matched" for item in batch.records
    ), batch.records
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
        "warnings": projected(batch.warnings),
    }


@pytest.mark.parametrize(
    "case_id,fault",
    [
        ("terminal-invalid", "promote"),
        ("terminal-reordered", "order"),
        ("observation-missing", "diagnostic"),
        ("json-pointers", "sibling"),
        ("json-pointers", "position"),
        ("negative-type", "unblocked"),
    ],
)
def test_reference_case_faults(data_regression, tmp_path, case_id, fault):
    execute = {
        "terminal": _execute_terminal,
        "observation": _execute_observation,
        "json": _execute_json_pointers,
        "negative": _execute_negative,
    }[case_id.split("-")[0]]
    result = execute(load_case("reference_evidence", case_id))
    if fault == "promote":
        result["records"][0]["category"] = "matched"
    elif fault == "order":
        result["records"][0]["desired"]["S3Bucket"]["ObjectPrefixes"].reverse()
    elif fault == "diagnostic":
        result["declared"]["diagnostics"] = []
    elif fault == "sibling":
        del result["desired"]["unrelated"]
    elif fault == "position":
        result["desired"]["a/b~c"].reverse()
    else:
        result = {"decision": {"equal": True}}
    target = tmp_path / "expected.yml"
    target.write_bytes(expected_path("reference_evidence", case_id).read_bytes())
    with pytest.raises(AssertionError, match="FILES DIFFER"):
        data_regression.check(result, fullpath=target)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="recorded-ref-")
)
def test_recorded_ref_export_import(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_recorded_ref)


def _execute_recorded_ref(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "network",
        "001",
        data["kind"],
        "Network",
        [(data["output"], "PENDING_DEPLOY", data["fixed"])],
        properties=data["properties"],
    )
    actual = exported(comparison, {"Ref": "Network"})
    before = copy.deepcopy(comparison.models["network"].authoritative)
    decision = comparison.reference_decision(
        data["fixed"], actual, data["receiving"], data["path"]
    )
    check = TestCase()
    check.assertEqual(actual["$attribute"], data["attribute"])
    check.assertIsNone(decision.equal)
    check.assertFalse(decision.equivalent)
    detail = decision.diagnostics[0]
    check.assertEqual(detail["evidence_type"], "recorded_observed")
    check.assertIs(detail["current_aws_verified"], False)
    check.assertEqual(
        detail["exports"], [{"export_name": "shared", "export_stack": "producer"}]
    )
    check.assertEqual(
        detail["producers"],
        [{"producer": "network/001", "attribute": data["attribute"]}],
    )
    check.assertEqual(comparison.models["network"].authoritative, before)
    return {"actual": projected(actual), "decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="concrete-name-")
)
def test_concrete_name_and_getatt_arn(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_concrete_name)


def _execute_concrete_name(case):
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
    actual = exported(comparison, data["expression"])
    decision = comparison.reference_decision(
        data["fixed"],
        actual,
        "IAM.Role",
        "Policies[].PolicyDocument.Statement[].Resource",
    )
    check = TestCase()
    check.assertIs(decision.equal, True)
    check.assertEqual(decision.diagnostics[0]["evidence_type"], "local_evaluation")
    different = comparison.reference_decision(
        data["fixed"] + "-different", actual, "IAM.Role", ""
    )
    check.assertIs(different.equal, False)
    return {
        "actual": projected(actual),
        "decision": _reference_decision_data(decision),
        "different": _reference_decision_data(different),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="declared-cache-")
)
def test_declared_scalar_and_no_reparsing_or_snapshot_reload(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_declared_cache)


def _execute_declared_cache(case):
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", case["data"]["vpc"])
    with patch("comparison.model_reference.declarations", wraps=declarations) as parse:
        first = prepared(comparison, row).require_value()
        second = prepared(comparison, row).require_value()
        TestCase().assertTrue(parse.call_count == 1)
    TestCase().assertTrue(isinstance(first, ResourceReference) and first == second)
    actual = exported(comparison, {"Ref": "Vpc"})
    TestCase().assertTrue(
        comparison.reference_decision(first, actual, "EC2.Subnet", "VpcId").equal
        is True
    )
    TestCase().assertTrue(
        comparison.reference_decision(
            first, case["data"]["vpc"], "EC2.Subnet", "VpcId"
        ).equal
        is None
    )
    TestCase().assertTrue(
        comparison.reference_decision(
            first, "vpc-different", "EC2.Subnet", "VpcId"
        ).equal
        is None
    )
    return {
        "first": projected(first),
        "actual": projected(actual),
        "decision": _reference_decision_data(
            comparison.reference_decision(first, actual, "EC2.Subnet", "VpcId")
        ),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="declared-name-")
)
def test_declared_name_checks_producer_model_and_return_attribute_mapping(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_declared_name)


def _execute_declared_name(case):
    comparison = fixture()
    resource(
        comparison,
        "repository",
        "001",
        "CodeCommit.Repository",
        "Repository",
        [("RepositoryName", case["data"]["name"], None)],
        properties={"RepositoryName": case["data"]["name"]},
    )
    row = consumer(comparison, case["data"]["name"])
    declaration(
        comparison,
        "desired.row.010-001.value",
        case["data"]["name"],
        producer="repository",
        logical="Repository",
        kind="CodeCommit.Repository",
        prop="CodeCommit.Repository.RepositoryName",
        mode="name",
    )
    desired = prepared(comparison, row).require_value()
    TestCase().assertTrue(desired["$attribute"] == "Name")
    actual = exported(comparison, {"Fn::GetAtt": ["Repository", "Name"]})
    TestCase().assertTrue(
        comparison.reference_decision(desired, actual, "IAM.Role", "").equal is True
    )
    comparison.rows["repository"]["001"][0][1]["value"] = "`different-model-name`"
    TestCase().assertTrue(
        comparison.reference_decision(desired, actual, "IAM.Role", "").equal is None
    )
    TestCase().assertTrue(
        comparison.reference_decision(
            desired, case["data"]["name"], "IAM.Role", ""
        ).equal
        is None
    )
    return {
        "desired": projected(desired),
        "changed": _reference_decision_data(
            comparison.reference_decision(desired, actual, "IAM.Role", "")
        ),
    }


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="json-"))
def test_json_pointer_multiple_references_preserves_siblings_and_order(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_json_pointers)


def _execute_json_pointers(case):
    comparison = fixture()
    vpc(comparison)
    other = case["data"]["other"]
    vpc(comparison, "002", "OtherVpc", other)
    row = resource(
        comparison,
        "consumer",
        "010",
        "IAM.Role",
        "Consumer",
        [("AssumeRolePolicyDocument", "unused", None)],
        stack="consumer",
    )[0]
    body = copy.deepcopy(case["data"]["body"])
    row[1]["document"] = json.dumps(body)
    comparison.models["consumer"].authoritative["desired.row.010-001.document"] = row[
        1
    ]["document"]
    for index, text in enumerate((VPC, other)):
        declaration(
            comparison,
            "desired.row.010-001.document",
            text,
            pointer="/a~1b~0c/" + str(index),
            logical="Vpc" if index == 0 else "OtherVpc",
            name="ref" + str(index),
        )
    desired = prepared(comparison, row).require_value()
    assert desired["unrelated"] == VPC
    assert [item["$resource"][1] for item in desired["a/b~c"]] == ["001", "002"]
    actual = {
        "a/b~c": [
            exported(comparison, {"Ref": "Vpc"}),
            comparison.evaluate("producer", {"Ref": "OtherVpc"}),
        ],
        "unrelated": VPC,
    }
    callback = partial(policy_reference, comparison)
    before = copy.deepcopy(comparison.models["consumer"].authoritative)
    for value in desired["a/b~c"]:
        TestCase().assertIs(type(value), ResourceReference)
    first = compare_values(
        desired,
        actual,
        "AssumeRolePolicyDocument",
        whole=True,
        rules=rules("IAM.Role"),
        reference=callback,
    )
    actual["a/b~c"].reverse()
    reversed_result = compare_values(
        desired,
        actual,
        "AssumeRolePolicyDocument",
        whole=True,
        rules=rules("IAM.Role"),
        reference=callback,
    )
    TestCase().assertEqual(comparison.models["consumer"].authoritative, before)
    TestCase().assertEqual(body, case["data"]["body"])
    return {
        "desired": projected(desired),
        "matched": outcome_data(first),
        "reversed": outcome_data(reversed_result),
    }


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="arn-affix-"))
def test_composite_arn_requires_all_literal_affixes(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_arn_affix)


def _execute_arn_affix(case):
    comparison = fixture()
    vpc(comparison)
    actual = exported(comparison, case["data"]["expression"])
    fixed = case["data"]["fixed"]
    first = comparison.reference_decision(fixed, actual, "IAM.Role", "")
    wrong = comparison.reference_decision(
        fixed.replace("123456789012", "999999999999"), actual, "IAM.Role", ""
    )
    comparison.models["vpc"].authoritative["observed.row.001-001.value"] = (
        "`PENDING_DEPLOY`"
    )
    pending = comparison.reference_decision(fixed, actual, "IAM.Role", "")
    for decision in (first, wrong, pending):
        TestCase().assertIsNone(decision.equal)
    return {
        "first": _reference_decision_data(first),
        "wrong": _reference_decision_data(wrong),
        "pending": _reference_decision_data(pending),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="observation-")
)
def test_missing_pending_and_conflicting_observations(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_observation)


def _execute_observation(case):
    observed = case["data"]["observed"]
    comparison = fixture()
    vpc(comparison, observed=observed)
    actual = exported(comparison, {"Ref": "Vpc"})
    decision = comparison.reference_decision(VPC, actual, "EC2.Subnet", "VpcId")
    first = _reference_decision_data(decision)
    row = consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", VPC)
    desired = prepared(comparison, row).require_value()
    decision = comparison.reference_decision(desired, actual, "EC2.Subnet", "VpcId")
    return {"literal": first, "declared": _reference_decision_data(decision)}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
