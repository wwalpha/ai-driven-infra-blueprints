"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison import Comparison
from comparison.reference_evidence import compare_expression
from comparison.registry import rules
from comparison.resource import inactive_evidence
from comparison.result import identifier
from comparison.rules.kms import FormOutcome
from issues.materials import naming_materials
from issues.publication import save_scan
from issues.review import review_snapshot
from support.comparison_cases import projected
from support.issues_scan_fixtures import (
    review_for,
    snapshot_artifact,
    stamp_naming_scan,
    task,
)
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    ATHENA_KMS,
    KEY_ARN,
    ROOT,
    VPC,
    _reference_decision_data,
    consumer,
    declaration,
    exported,
    fixture,
    kms_key,
    prepared,
    resource,
    setting,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="naming-provider-")
)
def test_naming_import_provider_constraint_from_materials(
    tmp_path, case_runner, case_id
):
    case_runner.run(
        "reference_evidence", case_id, partial(_execute_naming_provider, tmp_path)
    )


def _execute_naming_provider(tmp_path, case):
    comparison = fixture()
    comparison.services = ["kms"]
    rows = resource(
        comparison,
        "kms",
        "001",
        "KMS.Alias",
        "Alias",
        [("AliasName", case["data"]["value"], None)],
    )
    for _, row in rows:
        row["comment"] = ""
    comparison.resources["kms"]["001"]["resourceMode"] = "IMPORT"
    material, judgments = naming_materials(comparison)
    data = snapshot_artifact(tmp_path, services=["kms"])
    data["naming_context"] = {
        key: val for key, val in material.items() if key != "names"
    }
    data["naming"]["names"] = material["names"]
    stamp_naming_scan(data)
    data["judgments"] = judgments
    item = next(
        (item for item in data["naming"]["names"] if item["property"] == "AliasName")
    )
    TestCase().assertTrue(item["provider_errors"])
    review = review_for(data)
    review["issues"] = [
        dict(
            service="kms",
            resource="001",
            property="AliasName",
            rule="review.naming",
            naming_item_id=item["id"],
            applied_rule=item["provider_errors"][0],
            violation="provider_constraint",
            evidence="Provider schema",
            message="Invalid provider name",
        )
    ]
    with task(tmp_path, ["kms"]):
        _, snapshot, _ = save_scan(tmp_path, data, review)
    TestCase().assertTrue(len(json.loads(snapshot.data)["ordinary"]) == 1)
    review["issues"][0].update(
        violation="format",
        applied_rule="alias/{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]",
    )
    with pytest.raises(ValueError, match="IMPORT"):
        save_scan(tmp_path, data, review)
    return {"ordinary": json.loads(snapshot.data)["ordinary"]}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="naming-missing-")
)
def test_naming_missing_rule_from_materials(tmp_path, case_runner, case_id):
    case_runner.run(
        "reference_evidence", case_id, partial(_execute_naming_missing, tmp_path)
    )


def _execute_naming_missing(tmp_path, case):
    comparison = fixture()
    comparison.services = ["cdn"]
    rows = resource(
        comparison,
        "cdn",
        "001",
        "CloudFront.CachePolicy",
        "Policy",
        [("CachePolicyConfig.Name", case["data"]["value"], None)],
    )
    for _, row in rows:
        row["comment"] = ""
    material, judgments = naming_materials(comparison)
    data = snapshot_artifact(tmp_path, services=["cdn"])
    data["naming_context"] = {
        key: val for key, val in material.items() if key != "names"
    }
    data["naming"]["names"] = material["names"]
    stamp_naming_scan(data)
    data["judgments"] = judgments
    item = next(
        (
            item
            for item in data["naming"]["names"]
            if item["property"] == "CachePolicyConfig.Name"
        )
    )
    review = review_for(data)
    review["issues"] = [
        dict(
            service="cdn",
            resource="001",
            property=item["property"],
            rule="review.naming",
            naming_item_id=item["id"],
            applied_rule=data["naming_context"]["rules"]["common"][0]["path"],
            violation="rule_missing",
            evidence="No registered target",
            message="Missing naming rule",
        )
    ]
    with task(tmp_path, ["cdn"]):
        _, snapshot, _ = save_scan(tmp_path, data, review)
    TestCase().assertTrue(len(json.loads(snapshot.data)["ordinary"]) == 1)
    return {"ordinary": json.loads(snapshot.data)["ordinary"]}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="naming-unavailable-")
)
def test_naming_input_unavailable_from_materials(tmp_path, case_runner, case_id):
    case_runner.run(
        "reference_evidence", case_id, partial(_execute_naming_unavailable, tmp_path)
    )


def _execute_naming_unavailable(tmp_path, case):
    comparison = fixture()
    comparison.services = ["vpc"]
    comparison.reference_unavailable["vpc"] = case["data"]["reason"]
    material, judgments = naming_materials(comparison)
    data = snapshot_artifact(tmp_path, services=["vpc"])
    data["naming_context"] = {
        key: val for key, val in material.items() if key != "names"
    }
    data["naming_context_id"] = identifier(data["naming_context"])
    data["judgments"] = judgments
    review = review_for(data)
    review["unverified"] = [
        dict(
            service="vpc",
            check="naming",
            reason="Model unavailable",
            failure_kind="input_unavailable",
        )
    ]
    TestCase().assertTrue(
        json.loads(review_snapshot(data, review).data)["unverified"]
        == review["unverified"]
    )
    return {"unverified": json.loads(review_snapshot(data, review).data)["unverified"]}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="stack-region-")
)
def test_stack_partition_and_noecho(case_runner, tmp_path, case_id):
    case_runner.run(
        "reference_evidence", case_id, partial(_execute_stack_region, tmp_path)
    )


def _execute_stack_region(tmp_path, case):
    data = case["data"]
    comparison = fixture()
    comparison.root = tmp_path
    comparison.target["awsRegion"] = data["region"]
    comparison.stack_inputs = {}
    comparison.documents = {}
    comparison.metrics = dict(template_decodes=0, stack_evaluations=0)
    comparison.track = Mock()
    template = tmp_path / "infra/cloudformation/templates/one.yaml"
    parameters = tmp_path / "infra/cloudformation/parameters/fixture/team/one.json"
    template.parent.mkdir(parents=True)
    parameters.parent.mkdir(parents=True)
    template.write_text(json.dumps(data["template"]), encoding="utf-8")
    parameters.write_text("[]", encoding="utf-8")
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        Comparison.stack_input(
            comparison,
            dict(name="producer", template="one.yaml", parameters="one.json"),
        )
    document, _, pseudo = comparison.stack_inputs["producer"]
    check = TestCase()
    for name, expected in [
        ("AWS::Region", data["region"]),
        ("AWS::AccountId", "123456789012"),
        ("AWS::StackName", "producer"),
        ("AWS::NoValue", {"$noValue": True}),
    ]:
        check.assertEqual(comparison.evaluate("producer", {"Ref": name}), expected)
    redacted = comparison.redacted("prefix-private")
    check.assertEqual(redacted, "<masked sensitive parameter>")
    missing = []
    for name in ("AWS::Partition", "AWS::URLSuffix"):
        if name not in pseudo:
            for value in ({"Ref": name}, {"Fn::Sub": "${" + name + "}"}):
                with pytest.raises(
                    Blocked, match="unresolved pseudo parameter"
                ) as failure:
                    comparison.evaluate("producer", value)
                missing.append(
                    {
                        "type": type(failure.value).__name__,
                        "message": str(failure.value),
                    }
                )
        else:
            check.assertEqual(
                comparison.evaluate("producer", {"Ref": name}), pseudo[name]
            )
    suffix = pseudo.get("AWS::URLSuffix")
    expression = {"Fn::Sub": "secretsmanager.${AWS::Region}.${AWS::URLSuffix}"}
    suffix_input = None
    if suffix is not None:
        check.assertEqual(
            comparison.evaluate("producer", expression),
            f"secretsmanager.{data['region']}.{suffix}",
        )
        document["Conditions"] = {"Off": {"Fn::Equals": [expression, "other"]}}
        _, evidence = inactive_evidence(
            "producer",
            "Role",
            {"Condition": "Off"},
            document,
            {},
            pseudo,
            path="one.yaml",
            parameter_path="one.json",
            supplied=set(),
            stack_id="001",
            target=comparison.target,
            environment="fixture",
            directory="team",
            marks={},
            source_lookup=Mock(),
            redact=comparison.redacted,
        )
        suffix_input = next(
            item for item in evidence["inputs"] if item["name"] == "AWS::URLSuffix"
        )
        check.assertEqual(
            suffix_input,
            {
                "name": "AWS::URLSuffix",
                "value": suffix,
                "source": {
                    "kind": "botocore-endpoints",
                    "region": data["region"],
                    "key": "AWS::URLSuffix",
                },
            },
        )
    comparison.root = ROOT
    categories = []
    for different in (False, True):
        policy = [
            {
                "PolicyName": "KmsPolicy",
                "PolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "kms:Decrypt",
                            "Resource": "*",
                            "Condition": {
                                "StringEquals": {
                                    "kms:ViaService": f"secretsmanager.{data['region']}.{suffix}"
                                }
                            },
                        }
                    ],
                },
            }
        ]
        actual = copy.deepcopy(policy)
        actual[0]["PolicyDocument"]["Statement"][0]["Condition"]["StringEquals"][
            "kms:ViaService"
        ] = expression
        if different:
            policy[0]["PolicyDocument"]["Statement"][0]["Condition"]["StringEquals"][
                "kms:ViaService"
            ] = "different"
        records = setting(comparison, "IAM.Role", "Policies", policy, actual)
        categories.append([item["category"] for item in records])
    return {
        "partition": pseudo.get("AWS::Partition"),
        "suffix": suffix,
        "redacted": redacted,
        "missing": missing,
        "suffix_input": projected(suffix_input),
        "policy_categories": categories,
    }


def test_inactive_inline_policy_provenance():
    comparison = fixture()
    resource(
        comparison,
        "s3",
        "001",
        "S3.Bucket",
        "Bucket",
        [("BucketName", "fixture", None)],
        properties={"BucketName": "fixture"},
    )
    comparison.rows["s3"]["001"].append(
        ("001-002", dict(property="S3.BucketPolicy.PolicyDocument", value="{}"))
    )
    document = comparison.stack_inputs["producer"][0]
    document["Conditions"] = {"Off": {"Fn::Equals": [1, 2]}}
    document["Resources"]["Policy"] = dict(
        Type="AWS::S3::BucketPolicy",
        Condition="Off",
        Properties={"Bucket": {"Ref": "Bucket"}, "PolicyDocument": {}},
    )
    comparison.parameter_keys = Mock(return_value=(ROOT / "parameters.json", set()))
    result = comparison.compare_rows(
        "s3",
        "001",
        comparison.resources["s3"]["001"],
        "producer",
        "Bucket",
        ROOT / "synthetic.yaml",
        document["Resources"]["Bucket"],
        document,
    ).records
    child = next(
        item
        for item in result
        if item.get("cause", {}).get("kind") == "condition-disabled"
    )
    assert (
        child["property"] == "S3.BucketPolicy" and child["cause"]["logical"] == "Policy"
    )
    assert child["iac"]["key"] == "Resources.Policy.Condition"


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="inline-document-")
)
def test_inline_policy_document(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_inline_document)


def _execute_inline_document(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "s3", "001", "S3.Bucket", "Bucket", [])
    comparison.rows["s3"]["001"].append(
        (
            "001-001",
            dict(
                property="S3.BucketPolicy.PolicyDocument",
                value="policy.json",
                document=data["document"],
            ),
        )
    )
    document = comparison.stack_inputs["producer"][0]
    document["Resources"]["Policy"] = dict(
        Type="AWS::S3::BucketPolicy",
        Properties={"Bucket": {"Ref": "Bucket"}, "PolicyDocument": data["actual"]},
    )
    result = comparison.compare_rows(
        "s3",
        "001",
        comparison.resources["s3"]["001"],
        "producer",
        "Bucket",
        ROOT / "synthetic.yaml",
        document["Resources"]["Bucket"],
        document,
    )
    return {"records": projected(result.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="grouped-parent-")
)
def test_grouped_parent_reference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_grouped_parent)


def _execute_grouped_parent(case):
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Key", "Key", [])
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Alias",
        "Alias",
        [("AliasName", case["data"]["value"], None)],
        properties={"AliasName": case["data"]["value"], "TargetKeyId": {"Ref": "Key"}},
    )
    alias = comparison.resources["kms"]["002"]
    alias.update(
        parentReference=json.dumps(model_ref("KMS_Key_001", "KeyId")),
        parentProperty="KMS.Alias.TargetKeyId",
    )
    document = comparison.stack_inputs["producer"][0]
    result = comparison.compare_rows(
        "kms",
        "002",
        alias,
        "producer",
        "Alias",
        ROOT / "synthetic.yaml",
        document["Resources"]["Alias"],
        document,
    ).records
    TestCase().assertTrue(
        any(
            (
                item["property"] == "KMS.Alias.TargetKeyId"
                and item["category"] == "matched"
                for item in result
            )
        ),
        result,
    )
    return {"records": projected(result)}


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="run-mode-"))
def test_run_mode_classification(case_runner, tmp_path, case_id):
    case_runner.run("reference_evidence", case_id, partial(_execute_run_mode, tmp_path))


def _execute_run_mode(tmp_path, case):
    data = case["data"]
    comparison = fixture()
    comparison.root = tmp_path
    comparison.services = ["s3"]
    resource(comparison, "s3", "001", "S3.Bucket", "Bucket", [])
    comparison.resources["s3"]["001"].update(data["metadata"])
    comparison.target.update(data["target"])
    records = comparison.run()
    TestCase().assertEqual(len(records), 1)
    record = records[0]
    return {
        "category": record["category"],
        "reason": record.get("reason"),
        "cause": projected(record.get("cause")),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="import-failure-cause-")
)
def test_import_failure_cause_requires_unique_path(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_import_failure_cause)


def _execute_import_failure_cause(case):
    data = case["data"]
    comparison = fixture()
    failures = [Blocked("stack input missing"), Blocked("another input missing")]
    failures[0].iac_cause = data["first"]
    if data["second"] is not None:
        failures[1].iac_cause = data["second"]
    comparison.stack = Mock(side_effect=failures)
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("consumer", {"Fn::ImportValue": "missing"})
    return {"cause": projected(failure.value.iac_cause)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="nested-evidence-")
)
def test_recorded_evidence_survives_nested_expression_and_reversal(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_nested_evidence)


def _execute_nested_evidence(case):
    data = case["data"]
    comparison = fixture()
    kms_key(comparison)
    actual = exported(comparison, data["expression"])
    results = []
    for left, right in [(KEY_ARN + "/suffix", actual), (actual, KEY_ARN + "/suffix")]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        TestCase().assertIsNone(decision.equal)
        TestCase().assertFalse(decision.equivalent)
        detail = decision.diagnostics[0]
        TestCase().assertIs(detail["current_aws_verified"], False)
        TestCase().assertEqual(detail["evidence_type"], "recorded_observed")
        TestCase().assertEqual(detail["producers"][0]["producer"], "kms/001")
        results.append(_reference_decision_data(decision))
    other = comparison.reference_decision(
        KEY_ARN + "/other", actual, "IAM.Role", "Policies"
    )
    TestCase().assertIsNone(other.equal)
    return {"decisions": results, "other": _reference_decision_data(other)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="saved-evidence-")
)
def test_saved_literal_evidence_is_checked_in_both_directions(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_saved_evidence)


def _execute_saved_evidence(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", VPC)
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {"Ref": "Vpc"})
    authority = comparison.models["vpc"].authoritative
    if not data["observed_present"]:
        authority.pop("observed.row.001-001.value")
    elif data["observed"] is not None:
        authority["observed.row.001-001.value"] = data["observed"]
    compound = Expression("Join", ["", ["pre/", desired]])
    evaluated = Expression("Sub", ["pre/${R}", {"R": actual}])
    format_result = None
    if data["check_format"]:
        rule = replace(
            rules("Athena.WorkGroup")[ATHENA_KMS],
            form_compare=Mock(
                return_value=FormOutcome(
                    False, "kms.format_mismatch", "形式が一致しません"
                )
            ),
        )
        with patch(
            "comparison.reference_evidence.registry.property_rule", return_value=rule
        ):
            decision = compare_expression(
                comparison, compound, evaluated, "Athena.WorkGroup", ATHENA_KMS
            )
        TestCase().assertIs(decision.equal, False)
        TestCase().assertEqual(decision.diagnostics[0]["code"], "kms.format_mismatch")
        TestCase().assertEqual(decision.diagnostics[0]["reason"], "形式が一致しません")
        format_result = _reference_decision_data(decision)
    results = []
    for left, right in [
        (desired, actual),
        (actual, desired),
        (desired, VPC),
        (VPC, desired),
        (compound, evaluated),
        (evaluated, compound),
    ]:
        decision = comparison.reference_decision(left, right, "EC2.Subnet", "VpcId")
        expected = (
            True
            if data["check_format"]
            and not isinstance(left, str)
            and not isinstance(right, str)
            else None
        )
        TestCase().assertIs(decision.equal, expected)
        results.append(_reference_decision_data(decision))
    return {"format": format_result, "decisions": results}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
