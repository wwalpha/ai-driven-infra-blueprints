"""Offline reference proof through the shared evaluator and comparison pipeline."""

import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.deferral import failure_category
from issues.aggregate import aggregate, comparison_status
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
    KEY_ARN,
    KEY_ID,
    ROOT,
    _reference_decision_data,
    declaration,
    exported,
    fixture,
    fragment_actual,
    fragment_fixture,
    prepared,
    resource,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-invalid-")
)
def test_fragment_invalid_declarations_fail_closed(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_fragment_invalid)


def _execute_fragment_invalid(case):
    data = case["data"]
    comparison, row = fragment_fixture("S3.Bucket")
    authority = comparison.models["consumer"].authoritative
    authority.update(
        {"desired.reference.ref." + key: value for key, value in data["fields"].items()}
    )
    if data["second_text"] is not None:
        declaration(
            comparison,
            "desired.row.010-001.value",
            data["second_text"],
            producer="s3",
            logical="Producer",
            kind="S3.Bucket",
            prop="S3.Bucket.BucketName",
            mode="name",
            name="other",
        )
    if data["duplicate_producer"]:
        resource(
            comparison,
            "s3",
            "002",
            "S3.Bucket",
            "Other",
            [("BucketName", "fixture-bucket", None)],
            properties={"BucketName": "fixture-bucket"},
        )
        authority2 = comparison.models["s3"].authoritative
        authority2["desired.resource.002.logicalId"] = authority2[
            "desired.resource.001.logicalId"
        ]
    error = prepared(comparison, row).error
    TestCase().assertIsInstance(error, Blocked)
    return {"error": {"type": type(error).__name__, "message": str(error)}}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-producer-")
)
def test_fragment_producer_and_attribute_evidence_cannot_be_replaced_by_values(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_fragment_producer)


def _execute_fragment_producer(case):
    data = case["data"]
    kind = data["kind"]
    comparison, row = fragment_fixture(kind)
    desired = prepared(comparison, row).require_value()
    service = "kms" if kind == "KMS.Key" else "s3"
    if data["other_producer"]:
        prop, text = (
            ("KeyId", KEY_ID) if service == "kms" else ("BucketName", "fixture-bucket")
        )
        resource(
            comparison,
            service,
            "002",
            kind,
            "Other",
            [
                (
                    prop,
                    "PENDING_DEPLOY" if service == "kms" else text,
                    text if service == "kms" else None,
                )
            ],
            properties={} if service == "kms" else {prop: text},
        )
    if data["actual_literal"] is not None:
        actual = data["actual_literal"]
    elif data["unknown_attribute"]:
        actual = Expression(
            "Join",
            [
                "",
                [
                    "pre/",
                    ResourceReference(
                        {"$resource": [service, "001"], "$attribute": "Unknown"}
                    ),
                ],
            ],
        )
    else:
        actual = fragment_actual(
            comparison, kind, "Other" if data["other_producer"] else "Producer"
        )
        if data["remove_resource"]:
            comparison.stack_inputs["producer"][0]["Resources"].pop("Producer")
            comparison.symbols.clear()
        if data["wrong_type"]:
            comparison.stack_inputs["producer"][0]["Resources"]["Producer"]["Type"] = (
                "AWS::EC2::VPC"
            )
            comparison.symbols.clear()
        if data["import_mode"]:
            comparison.resources[service]["001"]["resourceMode"] = "IMPORT"
    if data["clear_arn_contract"]:
        with patch.dict("comparison.reference_evidence.ARN_SHAPES", clear=True):
            decision = comparison.reference_decision(
                desired, actual, "IAM.Role", "Policies"
            )
    else:
        decision = comparison.reference_decision(
            desired, actual, "IAM.Role", "Policies"
        )
    TestCase().assertIs(decision.equal, False if data["other_producer"] else None)
    TestCase().assertFalse(decision.equivalent)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-observed-")
)
def test_fragment_all_observed_uncertainties_remain_uncompared(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_fragment_observed)


def _execute_fragment_observed(case):
    observed = case["data"]["observed"]
    comparison, row = fragment_fixture()
    authority = comparison.models["kms"].authoritative
    if observed is None:
        authority.pop("observed.row.001-001.value")
    else:
        authority["observed.row.001-001.value"] = "`" + observed + "`"
    desired = prepared(comparison, row).require_value()
    decision = comparison.reference_decision(
        desired, fragment_actual(comparison), "IAM.Role", "Policies"
    )
    TestCase().assertIsNone(decision.equal)
    TestCase().assertFalse(decision.equivalent)
    TestCase().assertIs(decision.diagnostics[0]["current_aws_verified"], False)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-origin-")
)
def test_fragment_import_export_requires_proven_origin(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_fragment_origin)


def _execute_fragment_origin(case):
    data = case["data"]
    comparison, row = fragment_fixture()
    desired = prepared(comparison, row).require_value()
    if data["literal"]:
        actual = exported(comparison, KEY_ARN)
        decision = comparison.reference_decision(
            desired, actual, "IAM.Role", "Policies"
        )
        TestCase().assertIsNone(decision.equal)
        return {"decision": _reference_decision_data(decision)}
    exported(comparison, {"Fn::GetAtt": ["Producer", "Arn"]})
    comparison.exports = None
    comparison.stack_inputs["producer"][0]["Outputs"] = data["producer_outputs"]
    comparison.stack_inputs["consumer"][0]["Outputs"].update(data["consumer_outputs"])
    document, parameters, pseudo = comparison.stack_inputs["producer"]
    comparison.stack_inputs["producer"] = (
        document,
        parameters,
        dict(pseudo, **data["pseudo_fields"]),
    )
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


def test_fragment_wrong_declared_name_and_missing_second_proof_do_not_match():
    comparison, row = fragment_fixture("S3.Bucket")
    desired = prepared(comparison, row).require_value()
    comparison.rows["s3"]["001"][0][1]["value"] = "`other-name`"
    actual = fragment_actual(comparison, "S3.Bucket")
    decision = comparison.reference_decision(desired, actual, "IAM.Role", "Policies")
    assert (
        decision.equal is None
        and "recorded_identifier_mismatch" in decision.diagnostics[0]["reason"]
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-undeclared-")
)
def test_fragment_undeclared_identifier_and_replacement_stay_uncompared(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_fragment_undeclared)


def _execute_fragment_undeclared(case):
    comparison, row = fragment_fixture()
    comparison.stack_inputs["producer"][0]["Resources"]["Producer"]["Properties"][
        "Description"
    ] = case["data"]["description"]
    desired = prepared(comparison, row).require_value()
    actual = fragment_actual(comparison)
    decision = comparison.reference_decision(desired, actual, "IAM.Role", "Policies")
    TestCase().assertTrue(
        decision.equal is True
        and decision.diagnostics[0]["current_aws_verified"] is False
    )
    TestCase().assertTrue(
        comparison.reference_decision(KEY_ARN, actual, "IAM.Role", "Policies").equal
        is None
    )
    undeclared = Expression(
        "Join", ["", ["arn:aws:kms:ap-northeast-1:123456789012:key/", KEY_ID]]
    )
    TestCase().assertTrue(
        comparison.reference_decision(undeclared, actual, "IAM.Role", "Policies").equal
        is None
    )
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="import-wait-")
)
def test_import_wait_propagates_without_parent_issue(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_import_wait)


def _execute_import_wait(case):
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
        "consumer",
        "001",
        data["kind"],
        "Receiver",
        [(data["prop"], data["desired"], None)],
        properties={data["prop"]: data["actual"]},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "consumer",
        "001",
        comparison.resources["consumer"]["001"],
        "producer",
        "Receiver",
        ROOT / "synthetic.yaml",
        document["Resources"]["Receiver"],
        document,
    )
    check = TestCase()
    check.assertIsNone(batch.failure)
    check.assertEqual(len(batch.records), 1)
    item = batch.records[0]
    expected_phase = (
        "unobserved"
        if data["observed"] is None
        else "pending_deploy"
        if data["observed"] == "PENDING_DEPLOY"
        else "awaiting_handoff"
    )
    check.assertEqual(
        item["category"],
        "excluded" if expected_phase == "pending_deploy" else "deferred",
    )
    check.assertEqual(item["cause"]["phase"], expected_phase)
    check.assertEqual(
        item["cause"]["producer"],
        dict(service="vpc", resource="001", resourceType="EC2.VPC", attribute="VpcId"),
    )
    result = aggregate(batch.records, "fixture", "team", ["consumer"])
    check.assertEqual(result["overview"]["issue_count"], 0)
    check.assertIsNone(result["record_meta"][0]["issue_id"])
    check.assertEqual(
        comparison_status(result["overview"]["records"]),
        "no compared records" if expected_phase == "pending_deploy" else "partial",
    )
    check.assertEqual(
        result["overview"]["pending_deploy_excluded"],
        int(expected_phase == "pending_deploy"),
    )
    return {
        "records": projected(batch.records),
        "overview": projected(result["overview"]),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="import-invalid-")
)
def test_import_invalid_contract_or_identifier_stays_an_issue(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_import_invalid)


def _execute_import_invalid(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison, observed=data["observed"])
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    if data["ambiguous"]:
        resource(comparison, "duplicate", "001", "EC2.VPC", "Duplicate", [])
    comparison.root = Path("synthetic-project")
    comparison.models = {
        name: replace(model, scope=replace(model.scope, root=comparison.root))
        for name, model in comparison.models.items()
    }
    link = ResourceReference(data["link"]) if data["typed_link"] else data["link"]
    prop = data["prop"]
    kind, path = ".".join(prop.split(".")[:2]), ".".join(prop.split(".")[2:])
    with pytest.raises((Blocked, KeyError)) as failure:
        comparison.desired_reference("consumer", link, kind, path)
    category = failure_category(failure.value)
    TestCase().assertEqual(category, "uncompared")
    item = comparison.make_record(category, "consumer", "001", prop, str(failure.value))
    count = aggregate([item], "fixture", "team", ["consumer"])["overview"][
        "issue_count"
    ]
    TestCase().assertEqual(count, 1)
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)},
        "issue_count": count,
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="import-difference-")
)
def test_import_wait_preserves_known_json_difference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_import_wait_difference)


def _execute_import_wait_difference(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison, observed=data["observed"])
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    comparison.models["vpc"].authoritative["desired.resource.001.resourceMode"] = (
        "IMPORT"
    )
    comparison.models["vpc"].values["desired.resource.001.resourceMode"] = "IMPORT"
    if data["subnet"]:
        resource(
            comparison,
            "vpc",
            "002",
            "EC2.Subnet",
            "Subnet",
            [("SubnetId", "PENDING_DEPLOY", data["observed"])],
        )
        comparison.resources["vpc"]["002"]["resourceMode"] = "IMPORT"
        comparison.models["vpc"].authoritative["desired.resource.002.resourceMode"] = (
            "IMPORT"
        )
        comparison.models["vpc"].values["desired.resource.002.resourceMode"] = "IMPORT"
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("VpcConfig", json.dumps(data["desired"]), None)],
        properties={"VpcConfig": data["actual"]},
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
    category = "excluded" if data["observed"] == "PENDING_DEPLOY" else "deferred"
    TestCase().assertEqual(
        sorted(item["category"] for item in batch.records),
        sorted([category, "difference"]),
    )
    parent = next(item for item in batch.records if item["category"] == "difference")
    TestCase().assertFalse(parent.get("deferred_children"))
    TestCase().assertIn("subnet-first", json.dumps(batch.display_differences))
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="route53-pending-")
)
def test_route53_direct_pending_deploy_classification(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_route53_pending)


def _execute_route53_pending(case):
    data = case["data"]
    comparison = fixture()
    comparison.environment, comparison.directory = data["environment"], "cde"
    resource(
        comparison,
        "route53",
        "003",
        "Route53.RecordSet",
        "Alias",
        [("AliasTarget.DNSName", data["desired"], None)],
        properties={"AliasTarget": {"DNSName": "actual.example"}},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "route53",
        "003",
        comparison.resources["route53"]["003"],
        "producer",
        "Alias",
        ROOT / "synthetic.yaml",
        document["Resources"]["Alias"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    result = aggregate(batch.records, data["environment"], "cde", ["route53"])
    if data["desired"] == "PENDING_DEPLOY":
        TestCase().assertEqual(len(batch.records), 1)
        TestCase().assertEqual(
            batch.records[0]["cause"],
            dict(
                kind="desired-value-excluded",
                phase="pending_deploy",
                consumer_property="Route53.RecordSet.AliasTarget.DNSName",
            ),
        )
        TestCase().assertEqual(result["overview"]["issue_count"], 0)
        TestCase().assertEqual(result["overview"]["pending_deploy_excluded"], 1)
        TestCase().assertFalse(result["overview"]["comparison_incomplete"])
    else:
        TestCase().assertGreater(result["overview"]["issue_count"], 0)
        TestCase().assertEqual(result["overview"]["pending_deploy_excluded"], 0)
    return {
        "records": projected(batch.records),
        "overview": projected(result["overview"]),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="pending-sibling-")
)
def test_direct_pending_deploy_preserves_sibling_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_pending_sibling)


def _execute_pending_sibling(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "route53",
        "003",
        "Route53.RecordSet",
        "Alias",
        [
            ("AliasTarget.DNSName", "PENDING_DEPLOY", None),
            (data["sibling"], data["desired"], None),
        ],
        properties={
            "Name": "fixed",
            "AliasTarget": {"DNSName": "actual.example", "HostedZoneId": "fixed"},
        },
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "route53",
        "003",
        comparison.resources["route53"]["003"],
        "producer",
        "Alias",
        ROOT / "synthetic.yaml",
        document["Resources"]["Alias"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    result = aggregate(batch.records, "dev", "cde", ["route53"])
    TestCase().assertTrue(
        all(
            "DNSName" not in item["property"]
            for item in batch.records
            if item["category"] != "excluded"
        )
    )
    return {
        "records": projected(batch.records),
        "overview": projected(result["overview"]),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="pending-actual-")
)
def test_direct_pending_deploy_retains_actual_sibling_failures(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_pending_actual)


def _execute_pending_actual(case):
    comparison = fixture()
    resource(
        comparison,
        "route53",
        "003",
        "Route53.RecordSet",
        "Alias",
        [
            ("AliasTarget.DNSName", "PENDING_DEPLOY", None),
            ("AliasTarget.HostedZoneId", "fixed", None),
        ],
        properties={"AliasTarget": case["data"]["actual"]},
    )
    document = comparison.stack_inputs["producer"][0]
    batch = comparison.compare_rows(
        "route53",
        "003",
        comparison.resources["route53"]["003"],
        "producer",
        "Alias",
        ROOT / "synthetic.yaml",
        document["Resources"]["Alias"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    overview = aggregate(batch.records, "dev", "cde", ["route53"])["overview"]
    TestCase().assertEqual(overview["pending_deploy_excluded"], 1)
    return {"records": projected(batch.records), "overview": projected(overview)}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
