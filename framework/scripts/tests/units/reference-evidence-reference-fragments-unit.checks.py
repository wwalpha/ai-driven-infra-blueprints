"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
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
    QUEUE_ARN,
    ROOT,
    VPC,
    _reference_decision_data,
    consumer,
    declaration,
    exported,
    fixture,
    fragment_actual,
    fragment_fixture,
    prepared,
    resource,
    setting,
    sqs_policy_fixture,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


def test_existing_named_arn_context_guards():
    comparison = fixture()
    resource(
        comparison,
        "producer",
        "001",
        "CodeBuild.Project",
        "Build",
        [],
        properties={"Name": "fixture-project"},
    )
    reference = comparison.evaluate("producer", {"Fn::GetAtt": ["Build", "Arn"]})
    assert comparison.reference_literal(reference).startswith("arn:aws:")
    comparison.stack_inputs["producer"][2].pop("AWS::Region")
    with pytest.raises(Blocked, match="Region"):
        comparison.reference_literal(reference)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sqs-correspondence-")
)
def test_sqs_arn_correspondence_and_mode_guards(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sqs_correspondence)


def _execute_sqs_correspondence(case):
    data = case["data"]
    comparison, desired, actual = sqs_policy_fixture()
    queue = comparison.stack_inputs["producer"][0]["Resources"]["Queue"]
    model = comparison.resources["sqs"]["001"]
    queue.update(data["queue_fields"])
    model.update(data["model_fields"])
    comparison.stack_inputs["producer"][0].update(data["document_fields"])
    if data["duplicate"]:
        resource(
            comparison,
            "sqs",
            "002",
            "SQS.Queue",
            "Queue",
            [],
            properties={"QueueName": "fixture-dlq"},
        )
    if data["remove_model"]:
        comparison.resources["sqs"].clear()
        comparison.models.pop("sqs")
    records = setting(comparison, "SQS.QueuePolicy", "PolicyDocument", desired, actual)
    TestCase().assertEqual([record["category"] for record in records], ["uncompared"])
    return {"records": projected(records)}


def test_sqs_queue_url_is_not_getatt_arn():
    comparison, _, _ = sqs_policy_fixture()
    ref = comparison.evaluate("producer", {"Ref": "Queue"})
    arn = comparison.evaluate("producer", {"Fn::GetAtt": ["Queue", "Arn"]})
    assert ref["$attribute"] == "QueueUrl" and arn["$attribute"] == "Arn"
    assert (
        comparison.reference_decision(
            QUEUE_ARN, ref, "SQS.QueuePolicy", "PolicyDocument.Statement[].Resource"
        ).equal
        is None
    )
    assert (
        comparison.reference_decision(
            QUEUE_ARN, arn, "SQS.QueuePolicy", "Queues[]"
        ).equal
        is None
    )
    with pytest.raises(Blocked):
        comparison.reference_literal(ref)
    comparison.resources["sqs"]["001"]["resourceMode"] = "IMPORT"
    assert (
        comparison.reference_decision(
            QUEUE_ARN, arn, "SQS.QueuePolicy", "PolicyDocument.Statement[].Resource"
        ).equal
        is None
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sqs-errors-")
)
def test_sqs_reference_processing_errors_propagate(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sqs_errors)


def _execute_sqs_errors(case):
    error = {"OSError": OSError, "ValueError": ValueError, "TypeError": TypeError}[
        case["data"]["error_type"]
    ]
    comparison, desired, actual = sqs_policy_fixture()
    reference = comparison.evaluate("producer", {"Fn::GetAtt": ["Queue", "Arn"]})
    with patch(
        "comparison.inputs.named_arn",
        side_effect=error("synthetic reference evaluation failure"),
    ):
        with pytest.raises(
            error, match="synthetic reference evaluation failure"
        ) as failure:
            comparison.reference_decision(
                QUEUE_ARN,
                reference,
                "SQS.QueuePolicy",
                "PolicyDocument.Statement[].Resource",
            )
        resource(
            comparison,
            "consumer",
            "090",
            "SQS.QueuePolicy",
            "Receiver",
            [("PolicyDocument", json.dumps(desired), None)],
            properties={"PolicyDocument": actual},
        )
        document = comparison.stack_inputs["producer"][0]
        batch = comparison.compare_rows(
            "consumer",
            "090",
            comparison.resources["consumer"]["090"],
            "producer",
            "Receiver",
            ROOT / "synthetic.yaml",
            document["Resources"]["Receiver"],
            document,
        )
        TestCase().assertIsInstance(batch.failure, error)
        TestCase().assertFalse(batch.records)
    return {
        "raised": {"type": type(failure.value).__name__, "message": str(failure.value)},
        "batch_failure": {
            "type": type(batch.failure).__name__,
            "message": str(batch.failure),
        },
        "records": projected(batch.records),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="evidence-error-")
)
def test_recorded_reference_processing_errors_are_not_missing_proof(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_evidence_error)


def _execute_evidence_error(case):
    data = case["data"]
    error = {"OSError": OSError, "ValueError": ValueError, "TypeError": TypeError}[
        data["error_type"]
    ]
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    if data["declared"]:
        declaration(comparison, "desired.row.010-001.value", VPC)
        desired = prepared(comparison, row).require_value()
        actual = VPC
    else:
        desired = VPC
        actual = comparison.evaluate("producer", {"Ref": "Vpc"})
    with patch(
        "comparison.reference_evidence.catalog_outputs",
        side_effect=error("synthetic catalog read failure"),
    ):
        with pytest.raises(error, match="synthetic catalog read failure") as failure:
            comparison.reference_decision(desired, actual, "EC2.Subnet", "VpcId")
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="replacement-proof-")
)
def test_replacement_and_old_observed_cannot_prove_physical_identity(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_replacement_proof)


def _execute_replacement_proof(case):
    operation = case["data"]["operation"]
    decisions = []
    comparison = fixture()
    resource(
        comparison,
        "vpc",
        "001",
        "EC2.VPC",
        "Vpc",
        [("CidrBlock", "10.0.0.0/16", None), ("VpcId", "PENDING_DEPLOY", VPC)],
        properties={"CidrBlock": "10.99.0.0/16"},
    )
    arn = "arn:aws:ec2:ap-northeast-1:123456789012:vpc/" + VPC
    symbol = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "Arn"})
    value = {
        "Arn": symbol,
        "Sub": Expression("Sub", ["${R}", {"R": symbol}]),
        "Join": Expression("Join", ["", [symbol]]),
        "SplitSelect": Expression("Select", [0, Expression("Split", ["|", symbol])]),
    }[operation]
    for left, right in [(value, arn), (arn, value)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        TestCase().assertTrue(decision.equal is None and (not decision.equivalent))
        TestCase().assertTrue(
            decision.diagnostics[0]["evidence_type"] == "recorded_observed"
        )
        TestCase().assertTrue("cannot prove" in decision.diagnostics[0]["reason"])
        decisions.append(_reference_decision_data(decision))
    TestCase().assertTrue(
        comparison.reference_decision(
            value, copy.deepcopy(value), "IAM.Role", "Policies"
        ).equal
        is True
    )
    other = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "VpcId"})
    TestCase().assertTrue(
        comparison.reference_decision(symbol, other, "IAM.Role", "Policies").equal
        is not True
    )
    vpc(comparison, "002", "OtherVpc")
    different = ResourceReference({"$resource": ["vpc", "002"], "$attribute": "Arn"})
    TestCase().assertTrue(
        comparison.reference_decision(symbol, different, "IAM.Role", "Policies").equal
        is False
    )
    return {"decisions": decisions}


@pytest.mark.parametrize(
    ("kind", "path", "service", "producer", "name_property"),
    [
        ("Events.Rule", "Targets[0].Arn", "lambda", "Lambda.Function", "FunctionName"),
        (
            "Events.Rule",
            "Targets[].DeadLetterConfig.Arn",
            "sqs",
            "SQS.Queue",
            "QueueName",
        ),
        (
            "Scheduler.Schedule",
            "Target.Arn",
            "lambda",
            "Lambda.Function",
            "FunctionName",
        ),
    ],
)
def test_eventbridge_target_arn_compares_producer_identity(
    kind, path, service, producer, name_property
):
    comparison = fixture()
    for identity, logical in (("001", "Target"), ("002", "OtherTarget")):
        resource(
            comparison,
            service,
            identity,
            producer,
            logical,
            [],
            properties={name_property: logical.lower()},
        )
    target = comparison.evaluate("producer", {"Fn::GetAtt": ["Target", "Arn"]})
    other = comparison.evaluate("producer", {"Fn::GetAtt": ["OtherTarget", "Arn"]})

    assert comparison.reference_same(target, target, kind, path) is True
    assert comparison.reference_same(target, other, kind, path) is False


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="event-bus-valid-")
)
def test_eventbridge_bus_name_arn_and_proven_reference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_event_bus_valid)


def _execute_event_bus_valid(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "events",
        "001",
        "Events.EventBus",
        "Bus",
        [],
        properties={"Name": "custom"},
    )
    properties = {"Name": "fixture-rule"}
    if data["bus"] is not None:
        properties["EventBusName"] = data["bus"]
    resource(
        comparison, "events", "002", "Events.Rule", "Rule", [], properties=properties
    )
    symbol = comparison.evaluate("producer", {"Fn::GetAtt": ["Rule", "Arn"]})
    arn = (
        "arn:aws:events:ap-northeast-1:123456789012:rule/"
        + data["tail"]
        + "fixture-rule"
    )
    TestCase().assertEqual(comparison.reference_literal(symbol), arn)
    decisions = []
    for left, right in [(arn, symbol), (symbol, arn)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        TestCase().assertIs(decision.equal, True)
        decisions.append(_reference_decision_data(decision))
    return {"arn": arn, "decisions": decisions}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="event-bus-unproven-")
)
def test_eventbridge_unproven_or_conflicting_bus_is_uncompared(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_event_bus_unproven)


def _execute_event_bus_unproven(case):
    comparison = fixture()
    resource(comparison, "events", "001", "Events.EventBus", "Bus", [], properties={})
    resource(
        comparison,
        "events",
        "002",
        "Events.Rule",
        "Rule",
        [],
        properties={"Name": "fixture-rule", "EventBusName": case["data"]["bus"]},
    )
    symbol = comparison.evaluate("producer", {"Fn::GetAtt": ["Rule", "Arn"]})
    arn = "arn:aws:events:ap-northeast-1:123456789012:rule/custom/fixture-rule"
    decisions = []
    for left, right in [(symbol, arn), (arn, symbol)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        TestCase().assertIsNone(decision.equal)
        TestCase().assertFalse(decision.equivalent)
        decisions.append(_reference_decision_data(decision))
    return {"decisions": decisions}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="route53-composite-")
)
def test_route53_composite_export_uses_shared_nested_setting_comparison(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_route53_composite)


def _execute_route53_composite(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "endpoint",
        "001",
        "EC2.VPCEndpoint",
        "Endpoint",
        [],
        stack="consumer",
        properties={"VpcEndpointType": "Interface"},
    )
    comparison.stack_inputs["consumer"][0]["Outputs"]["Dns"] = {
        "Value": data["expression"],
        "Export": {"Name": "EndpointDns"},
    }
    records = setting(
        comparison, "Route53.RecordSet", "AliasTarget", data["desired"], data["actual"]
    )
    TestCase().assertEqual([item["category"] for item in records], ["uncompared"])
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-reproduction-")
)
def test_declared_arn_fragment_reproduction(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_fragment_reproduction)


def _execute_fragment_reproduction(case):
    data = case["data"]
    producer, kind, prop, text = (
        data["producer"],
        data["kind"],
        data["prop"],
        data["text"],
    )
    comparison = fixture()
    resource(
        comparison,
        producer,
        "001",
        kind,
        "Producer",
        [
            (
                prop,
                text if producer == "s3" else "PENDING_DEPLOY",
                text if producer == "kms" else None,
            )
        ],
        properties=data["properties"],
    )
    row = consumer(comparison, data["full"])
    declaration(
        comparison,
        "desired.row.010-001.value",
        text,
        producer=producer,
        logical="Producer",
        kind=kind,
        prop=kind + "." + prop,
        mode="name" if producer == "s3" else "identifier",
    )
    desired = prepared(comparison, row).require_value()
    TestCase().assertIsInstance(desired, Expression)
    TestCase().assertEqual(desired.operation, "Join")
    actual = exported(comparison, data["expression"])
    decision = comparison.reference_decision(desired, actual, "IAM.Role", "Policies")
    TestCase().assertIs(decision.equal, True)
    TestCase().assertTrue(decision.equivalent)
    detail = decision.diagnostics[-1]
    TestCase().assertEqual(detail["evidence_type"], "logical_reference")
    TestCase().assertIs(detail["current_aws_verified"], False)
    TestCase().assertTrue(
        detail["producers"]
        and all(item["producer"] == producer + "/001" for item in detail["producers"])
    )
    TestCase().assertEqual(
        detail["exports"], [{"export_name": "shared", "export_stack": "producer"}]
    )
    return {
        "desired": projected(desired),
        "decision": _reference_decision_data(decision),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-nested-")
)
def test_fragment_nested_sub_import_export_contract_and_unchanged_model(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_fragment_nested)


def _execute_fragment_nested(case):
    decisions = []
    comparison, row = fragment_fixture("S3.Bucket")
    comparison.stack_inputs["consumer"][0]["Parameters"] = {
        "Suffix": {"Type": "String"}
    }
    comparison.stack_inputs["consumer"][1]["Suffix"] = case["data"]["suffix"]
    exported(
        comparison, {"Fn::GetAtt": ["Producer", "Arn"]}, name="QuarantineBucketArnOne"
    )
    actual = comparison.evaluate(
        "consumer",
        {
            "Fn::Sub": [
                "${BucketArn}/*",
                {
                    "BucketArn": {
                        "Fn::ImportValue": {"Fn::Sub": "QuarantineBucketArn${Suffix}"}
                    }
                },
            ]
        },
    )
    before = {
        service: copy.deepcopy(snapshot.authoritative)
        for service, snapshot in comparison.models.items()
    }
    desired = prepared(comparison, row).require_value()
    reference = desired.operands[1][1]
    TestCase().assertTrue(reference.saved_literal == "fixture-bucket")
    TestCase().assertTrue(reference.saved_property == "S3.Bucket.BucketName")
    for left, right in [(desired, actual), (actual, desired)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        TestCase().assertTrue(decision.equal is True and decision.equivalent)
        detail = decision.diagnostics[0]
        TestCase().assertTrue(detail["evidence_type"] == "logical_reference")
        TestCase().assertTrue(
            detail["declarations"]
            == [{"producer": "s3/001", "property": "S3.Bucket.BucketName"}]
        )
        TestCase().assertTrue(
            detail["exports"]
            == [{"export_name": "QuarantineBucketArnOne", "export_stack": "producer"}]
        )
        TestCase().assertTrue(detail["current_aws_verified"] is False)
        decisions.append(_reference_decision_data(decision))
    TestCase().assertTrue(
        before
        == {
            service: snapshot.authoritative
            for service, snapshot in comparison.models.items()
        }
    )
    return {"decisions": decisions}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-affix-")
)
def test_fragment_arn_fixed_parts_are_differences(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_fragment_affix)


def _execute_fragment_affix(case):
    data = case["data"]
    comparison, row = fragment_fixture(data["kind"], data["value"])
    desired = prepared(comparison, row).require_value()
    actual = fragment_actual(comparison, data["kind"])
    decisions = []
    for left, right in [(desired, actual), (actual, desired)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        TestCase().assertIs(decision.equal, False)
        TestCase().assertFalse(decision.equivalent)
        TestCase().assertIs(decision.diagnostics[0]["current_aws_verified"], False)
        decisions.append(_reference_decision_data(decision))
    return {"decisions": decisions}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-scalar-")
)
def test_fragment_scalar_backtick_coordinates(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_fragment_scalar)


def _execute_fragment_scalar(case):
    data = case["data"]
    comparison, row = fragment_fixture("S3.Bucket", data["value"])
    authority = comparison.models["consumer"].authoritative
    authority["desired.reference.ref.text"] = data["text"]
    authority["desired.reference.ref.occurrence"] = data["occurrence"]
    desired = prepared(comparison, row).require_value()
    parts = desired.operands[1] if isinstance(desired, Expression) else [desired]
    actual_parts = [
        comparison.evaluate("producer", {"Ref": "Producer"})
        if isinstance(part, ResourceReference)
        else part
        for part in parts
    ]
    decision = comparison.reference_decision(
        desired, Expression("Join", ["", actual_parts]), "IAM.Role", "Policies"
    )
    TestCase().assertIs(decision.equal, True)
    return {
        "parts": [
            part.saved_literal if isinstance(part, ResourceReference) else part
            for part in parts
        ],
        "decision": _reference_decision_data(decision),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="fragment-pointers-")
)
def test_fragment_json_pointer_and_multiple_nonoverlapping_declarations(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_fragment_pointers)


def _execute_fragment_pointers(case):
    comparison, row = fragment_fixture("S3.Bucket")
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    body = case["data"]["body"]
    row[1]["document"] = json.dumps(body)
    authority = comparison.models["consumer"].authoritative
    authority["desired.row.010-001.document"] = row[1]["document"]
    authority["desired.reference.ref.consumerKey"] = "desired.row.010-001.document"
    authority["desired.reference.ref.pointer"] = "/a~1b~0c/0/Resource"
    declaration(
        comparison,
        "desired.row.010-001.document",
        KEY_ID,
        pointer="/a~1b~0c/0/Resource",
        producer="kms",
        logical="Key",
        kind="KMS.Key",
        prop="KMS.Key.KeyId",
        name="key",
    )
    desired = prepared(comparison, row).require_value()
    leaf = desired["a/b~c"][0]["Resource"]
    TestCase().assertTrue(
        [
            part.saved_literal
            for part in leaf.operands[1]
            if isinstance(part, ResourceReference)
        ]
        == ["fixture-bucket", KEY_ID]
    )
    TestCase().assertTrue(desired["sibling"] == KEY_ID)
    actual = comparison.evaluate(
        "producer",
        {
            "Fn::Join": [
                "",
                [
                    {"Fn::GetAtt": ["Producer", "Arn"]},
                    "/*|",
                    {"Fn::GetAtt": ["Key", "Arn"]},
                ],
            ]
        },
    )
    decision = comparison.reference_decision(leaf, actual, "IAM.Role", "Policies")
    TestCase().assertTrue(decision.equal is True and decision.equivalent)
    TestCase().assertTrue(
        {item["producer"] for item in decision.diagnostics[0]["declarations"]}
        == {"s3/001", "kms/002"}
    )
    comparison.models["kms"].authoritative["observed.row.002-001.value"] = (
        "`PENDING_DEPLOY`"
    )
    decision = comparison.reference_decision(leaf, actual, "IAM.Role", "Policies")
    TestCase().assertTrue(decision.equal is None and (not decision.equivalent))
    TestCase().assertTrue("identifier_unobserved" in decision.diagnostics[0]["reason"])
    return {"decision": _reference_decision_data(decision)}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
