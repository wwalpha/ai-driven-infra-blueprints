"""Offline reference proof through the shared evaluator and comparison pipeline."""

import sys
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.methods import ORDERED, compare_values
from comparison.references import ReferenceDecision
from comparison.result import identifier, setting_result
from support.comparison_cases import projected
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    ResourceReference,
)
from utils.reference_contracts import (
    IMPORT_PROPERTIES,
    REFERENCE_PROPERTIES,
    reference_attribute,
)
from utils.reference_contracts import (
    contract as receiving_contract,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    VPC,
    _reference_decision_data,
    consumer,
    declaration,
    fixture,
    prepared,
    resource,
    setting,
    typed_duplicate_reference,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="typed-position-")
)
def test_typed_position_evidence_rejects_unrelated_diagnostics(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_typed_position)


def _execute_typed_position(case):
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    diagnostic = {"path": case["data"]["wrong_path"], "local_comparison": "matched"}
    decision = compare_values(
        ["same", "pending"],
        [ref, ref],
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(unrelated_position_reference, diagnostic),
        diagnostic_kind="KMS.Key",
    )
    TestCase().assertIsNone(decision.equal)
    TestCase().assertFalse(decision.reference_positions)
    return {
        "equal": decision.equal,
        "positions": projected(decision.reference_positions),
    }


def unrelated_position_reference(diagnostic, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    return ReferenceDecision(True if left == "same" else None, (diagnostic,))


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="typed-mixed-")
)
def test_typed_same_reference_mixed_statuses(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_typed_mixed)


def _execute_typed_mixed(case):
    comparison = fixture()
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    desired, actual = (case["data"]["desired"], [ref, ref])
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(typed_duplicate_reference, comparison, iter((True, None))),
        diagnostic_kind="KMS.Key",
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
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
        display_reference=resolver,
    )
    TestCase().assertTrue(
        decision.reference_positions
        == (((0,), (0,), "matched"), ((1,), (1,), "uncompared"))
    )
    fields = result.display_differences[identifier(result.records[0])]
    TestCase().assertTrue(
        len(fields) == 1 and fields[0]["path"] == "IaC:[1]（比較未確定）"
    )
    resolver.assert_called_once_with(ref)
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
        "warnings": projected(result.warnings),
    }


def test_security_group_ref_does_not_resolve_external_vpc():
    comparison = fixture()
    external = {"Fn::ImportValue": "ExternalVpcId"}
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": external},
    )
    assert comparison.evaluate("producer", {"Ref": "Group"})["$attribute"] == "GroupId"
    with pytest.raises(Blocked) as error:
        comparison.evaluate("producer", external)
    assert error.value.iac_cause["kind"] == "import-unresolved"


def test_security_group_sub_value_is_independently_unresolved():
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Suffix": {"Type": "String"}}
    parameters["Suffix"] = "PENDING_DEPLOY"
    value = {"Fn::Sub": "vpc-${Suffix}"}
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": value},
    )
    assert comparison.evaluate("producer", {"Ref": "Group"})["$attribute"] == "GroupId"
    assert comparison.evaluate("producer", value) == "vpc-PENDING_DEPLOY"
    assert parameters["Suffix"] == "PENDING_DEPLOY"


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-external-")
)
def test_security_group_receiver_rows_with_external_vpc(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_external)


def _execute_sg_external(case):
    data = case["data"]
    service, producer, attribute, kind, path = data["receiver"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Suffix": {"Type": "String"}, "Stage": {"Type": "String"}}
    parameters.update(Suffix="PENDING_DEPLOY", Stage="VpcId")
    for identity, logical, vpc_value in (
        ("001", "Producer", data["expression"]),
        ("002", "OtherProducer", data["expression"]),
        ("003", "UnknownVpc", None),
    ):
        resource(
            comparison,
            service,
            identity,
            producer,
            logical,
            [],
            properties={"VpcId": vpc_value},
        )
    records = setting(
        comparison,
        kind,
        path,
        model_ref("EC2_SecurityGroup_001", "GroupId"),
        {"Ref": data["target"]},
    )
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("producer", {"Fn::ImportValue": "ExternalVpcId"})
    return {
        "records": projected(records),
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)},
    }


def test_security_group_vpc_comparison_retains_external_uncertainty():
    comparison = fixture()
    records = setting(
        comparison,
        "EC2.SecurityGroup",
        "VpcId",
        VPC,
        {"Fn::ImportValue": "ExternalVpcId"},
    )
    assert [record["category"] for record in records] == ["uncompared"], records
    document, parameters, _ = comparison.stack_inputs["consumer"]
    document["Parameters"] = {"VpcId": {"Type": "String"}}
    parameters["VpcId"] = "PENDING_DEPLOY"
    records = setting(comparison, "EC2.SecurityGroup", "VpcId", VPC, {"Ref": "VpcId"})
    assert [record["category"] for record in records] == ["uncompared"], records


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-identity-")
)
def test_security_group_vpc_expression_identity_rows(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_identity)


def _execute_sg_identity(case):
    data = case["data"]
    service, producer, attribute, kind, path = data["receiver"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {
        name: {"Type": "String"} for name in ("VpcId", "Suffix", "Mode")
    }
    document["Conditions"] = {"Active": {"Fn::Equals": [{"Ref": "Mode"}, "yes"]}}
    parameters.update(
        VpcId="PENDING_DEPLOY", Suffix="PENDING_DEPLOY", Mode=data["active"]
    )
    resource(comparison, "iam", "001", "IAM.Role", "Role", [])
    comparison.stack_inputs["consumer"][0]["Outputs"]["Bad"] = {
        "Value": "invalid",
        "Export": {"Name": "bad-export"},
    }
    for identity, logical in (("001", "Producer"), ("002", "OtherProducer")):
        resource(
            comparison,
            service,
            identity,
            producer,
            logical,
            [],
            properties={"VpcId": data["expression"]},
        )
    try:
        evaluated = comparison.evaluate("producer", {"Ref": data["target"]})
    except Blocked as failure:
        evaluation = {"error": type(failure).__name__}
    else:
        TestCase().assertEqual(evaluated["$attribute"], "GroupId")
        evaluation = {"attribute": evaluated["$attribute"]}
    records = setting(
        comparison,
        kind,
        path,
        model_ref("EC2_SecurityGroup_001", "GroupId"),
        {"Ref": data["target"]},
    )
    return {"evaluation": evaluation, "records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-invalid-expr-")
)
def test_security_group_invalid_expression_receiver_rows(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_invalid_expression)


def _execute_sg_invalid_expression(case):
    data = case["data"]
    service, producer, attribute, kind, path = data["receiver"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"VpcId": {"Type": "String"}}
    parameters["VpcId"] = data["vpc_value"]
    resource(
        comparison,
        service,
        "001",
        producer,
        "Producer",
        [],
        properties={"VpcId": data["expression"]},
    )
    records = setting(
        comparison,
        kind,
        path,
        model_ref("EC2_SecurityGroup_001", "GroupId"),
        {"Ref": "Producer"},
    )
    TestCase().assertIn(
        [record["category"] for record in records], (["uncompared"], ["error"])
    )
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="import-receiver-")
)
def test_import_only_receiving_contract_prepares_link(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_import_receiver)


def _execute_import_receiver(case):
    kind, path, producer, attribute = (
        case["data"][key] for key in ("kind", "path", "producer", "attribute")
    )
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    symbol = comparison.desired_reference(
        "producer",
        model_ref(producer.replace(".", "_") + "_001", attribute),
        kind,
        path,
    )
    TestCase().assertEqual(
        symbol,
        ResourceReference({"$resource": ["producer", "001"], "$attribute": attribute}),
    )
    return {"resource": symbol["$resource"], "attribute": symbol["$attribute"]}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="wrong-producer-")
)
def test_same_wrong_producer_cannot_match(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_wrong_producer)


def _execute_wrong_producer(case):
    kind, path = (case["data"][key] for key in ("kind", "path"))
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    decision = comparison.reference_decision(symbol, symbol, kind, path)
    TestCase().assertIsNot(decision.equal, True)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="new-receiver-")
)
def test_new_receiving_contracts(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_new_receiver)


def _execute_new_receiver(case):
    data = case["data"]
    kind, path, producer, attribute = (
        data[k] for k in ("kind", "path", "producer", "attribute")
    )
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    wrong_kind = "IAM.Role" if producer == "EC2.Subnet" else "EC2.Subnet"
    resource(comparison, "wrong", "001", wrong_kind, "Wrong", [])
    valid = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": attribute}
    )
    wrong = ResourceReference({"$resource": ["wrong", "001"], "$attribute": "SubnetId"})
    TestCase().assertEqual(
        comparison.desired_reference("producer", valid, kind, path), valid
    )
    expected = None if kind == "Route53.HostedZone" else True
    valid_equal = comparison.reference_decision(valid, valid, kind, path).equal
    wrong_equal = comparison.reference_decision(wrong, wrong, kind, path).equal
    TestCase().assertIs(valid_equal, expected)
    TestCase().assertIsNot(wrong_equal, True)
    with pytest.raises(Blocked):
        comparison.desired_reference("wrong", wrong, kind, path)
    invalid = ResourceReference(dict(valid, **{"$attribute": "Invalid"}))
    invalid_equal = comparison.reference_decision(invalid, invalid, kind, path).equal
    TestCase().assertIsNot(invalid_equal, True)
    with pytest.raises(Blocked):
        comparison.desired_reference("producer", invalid, kind, path)
    return {"valid": valid_equal, "wrong": wrong_equal, "invalid": invalid_equal}


def test_wrong_producer_in_identical_expression_cannot_match():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    expression = Expression("Join", ["", [symbol]])
    assert (
        comparison.reference_decision(
            expression, expression, "ECS.TaskDefinition", "TaskRoleArn"
        ).equal
        is not True
    )


@pytest.mark.parametrize(
    "prop", sorted(set(IMPORT_PROPERTIES) - set(REFERENCE_PROPERTIES))
)
def test_import_only_contracts_prepare_explicit_references(prop):
    kind, path = prop.split(".", 2)[:2], prop.split(".", 2)[2]
    kind = ".".join(kind)
    declared = receiving_contract(prop)
    assert declared
    for producer, forms in declared.items():
        for form in forms:
            comparison = fixture()
            resource(comparison, "producer", "001", producer, "Producer", [])
            symbol = ResourceReference(
                {
                    "$resource": ["producer", "001"],
                    "$attribute": reference_attribute(producer, form),
                }
            )
            assert comparison.desired_reference("producer", symbol, kind, path)


def test_wrong_producer_in_identical_expression_with_prefix_cannot_match():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    expression = Expression("Join", ["", ["prefix", symbol]])
    assert (
        comparison.reference_decision(
            expression, expression, "ECS.TaskDefinition", "TaskRoleArn"
        ).equal
        is not True
    )


def test_wrong_attribute_in_identical_expression_with_prefix_cannot_match():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    expression = Expression("Join", ["", ["prefix", symbol]])
    assert (
        comparison.reference_decision(
            expression, expression, "S3.Bucket", "ReplicationConfiguration.Role"
        ).equal
        is not True
    )


def test_replication_role_rejects_role_name():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    assert (
        comparison.reference_decision(
            symbol, symbol, "S3.Bucket", "ReplicationConfiguration.Role"
        ).equal
        is not True
    )
    with pytest.raises(Blocked):
        comparison.desired_reference(
            "producer", symbol, "S3.Bucket", "ReplicationConfiguration.Role"
        )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="wrong-consumer-")
)
def test_saved_reference_wrong_consumer_cannot_match(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_wrong_consumer)


def _execute_wrong_consumer(case):
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", case["data"]["vpc"])
    desired = prepared(comparison, row).require_value()
    TestCase().assertTrue(
        comparison.reference_decision(
            desired, desired, "ECS.TaskDefinition", "TaskRoleArn"
        ).equal
        is not True
    )
    expression = Expression("Join", ["", ["prefix", desired]])
    actual = comparison.evaluate("producer", {"Ref": "Vpc"})
    for left, right in (
        (expression, expression),
        (desired, actual),
        (desired, case["data"]["vpc"]),
    ):
        TestCase().assertTrue(
            comparison.reference_decision(
                left, right, "ECS.TaskDefinition", "TaskRoleArn"
            ).equal
            is not True
        )
    return {
        "decision": _reference_decision_data(
            comparison.reference_decision(
                desired, actual, "ECS.TaskDefinition", "TaskRoleArn"
            )
        )
    }


def test_unregistered_ecs_target_group_rejects_wrong_producer():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    assert (
        comparison.reference_decision(
            symbol, symbol, "ECS.Service", "LoadBalancers[].TargetGroupArn"
        ).equal
        is not True
    )


def test_unregistered_instance_subnet_rejects_wrong_producer():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    assert (
        comparison.reference_decision(
            symbol, symbol, "EC2.Instance", "NetworkInterfaces[].SubnetId"
        ).equal
        is not True
    )


def test_unregistered_rds_proxy_secret_rejects_wrong_producer():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    assert (
        comparison.reference_decision(
            symbol, symbol, "RDS.DBProxy", "Auth[].SecretArn"
        ).equal
        is not True
    )


@pytest.mark.parametrize("prop", sorted(IMPORT_PROPERTIES))
def test_registered_contract_rejects_same_wrong_producer(prop):
    declared = receiving_contract(prop)
    assert declared
    producer = "S3.Bucket" if "S3.Bucket" not in declared else "IAM.Role"
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    service, resource_name, path = prop.split(".", 2)
    expression = Expression("Join", ["", [symbol]])
    for left, right in (
        (symbol, symbol),
        (expression, expression),
        (symbol, "arn:aws:s3:::fixture"),
    ):
        assert (
            comparison.reference_decision(
                left, right, service + "." + resource_name, path
            ).equal
            is not True
        )


def test_missing_arn_contract_does_not_prove_same_wrong_reference():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    expression = Expression("Join", ["", [symbol]])
    for left, right in (
        (symbol, symbol),
        (symbol, "arn:aws:s3:::example"),
        (expression, expression),
    ):
        assert (
            comparison.reference_decision(left, right, "Events.Rule", "RoleArn").equal
            is None
        )


def test_unproven_gateway_contract_cannot_match_wrong_resource():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    assert (
        comparison.reference_decision(symbol, symbol, "EC2.Route", "GatewayId").equal
        is not True
    )


def test_cloudtrail_topic_name_rejects_bucket_name():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "BucketName"}
    )
    assert (
        comparison.reference_decision(
            symbol, symbol, "CloudTrail.Trail", "SnsTopicName"
        ).equal
        is not True
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
