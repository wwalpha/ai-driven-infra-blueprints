"""Offline reference proof through the shared evaluator and comparison pipeline."""

import json
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path, PurePosixPath
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.resource import inline_owner
from comparison.rules.iam import managed_policy_roles
from comparison.values import PreparedValue
from model.sources import Scope
from support.comparison_cases import projected
from support.fixture_cases import load_case
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids, expected_text
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    ROOT,
    _sg_reference_result,
    exported,
    fixture,
    resource,
    setting,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="symbolic-setting-")
)
def test_symbolic_setting_classification(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_symbolic_setting)


def _execute_symbolic_setting(case):
    fault = case["data"]["fault"]
    comparison = fixture()
    resource(comparison, "cloudwatch-logs", "001", "Logs.LogGroup", "Log", [])
    expression = {
        "Fn::Select": [0, {"Fn::Split": [":*", {"Fn::GetAtt": ["Log", "Arn"]}]}]
    }
    desired = comparison.evaluate("producer", expression)
    actual = expression
    expected = "uncompared"
    if fault == "other-stack":
        resource(
            comparison,
            "cloudwatch-logs",
            "002",
            "Logs.LogGroup",
            "OtherLog",
            [],
            stack="consumer",
        )
        actual = {
            "Fn::Select": [
                0,
                {"Fn::Split": [":*", {"Fn::GetAtt": ["OtherLog", "Arn"]}]},
            ]
        }
        expected = "uncompared"
    elif fault == "attribute":
        desired = comparison.evaluate("producer", {"Fn::GetAtt": ["Log", "Arn"]})
        expected = "uncompared"
    elif fault == "delimiter":
        actual = {
            "Fn::Select": [0, {"Fn::Split": [",", {"Fn::GetAtt": ["Log", "Arn"]}]}]
        }
        expected = "uncompared"
    elif fault == "invalid":
        actual, expected = {"Fn::Split": [",", 42]}, "error"
    elif fault == "missing":
        actual, expected = {"Fn::GetAtt": ["Missing", "Arn"]}, "uncompared"
    elif fault == "index":
        actual, expected = (
            {"Fn::Select": [1, expression["Fn::Select"][1]]},
            "uncompared",
        )
    elif fault == "literal":
        desired, actual = "a:b", {"Fn::Join": ["-", ["a", "b"]]}
        expected = "difference"
    elif fault == "sub":
        actual = {"Fn::Sub": ["${Arn}-${!literal}", {"Arn": expression}]}
        desired = comparison.evaluate("producer", actual)
    # Receiver and Log share a stack; only the desired value is pre-bound for this boundary test.
    with patch.object(
        comparison, "prepare_value", return_value=PreparedValue(desired, [])
    ):
        records = setting(comparison, "Logs.LogGroup", "LogGroupName", "unused", actual)
    TestCase().assertEqual(records[0]["category"], expected)
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="model-policy-")
)
def test_model_policy_links_bind_but_raw_intrinsics_do_not(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_model_policy)


def _execute_model_policy(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "cloudwatch-logs", "001", "Logs.LogGroup", "Log", [])
    if data["prepare_directly"]:
        comparison.root = PurePosixPath("synthetic-project")
        pending = comparison.prepare_value(
            "consumer",
            {
                "property": "IAM.ManagedPolicy.PolicyDocument",
                "value": "",
                "document": json.dumps({"Statement": [{"Resource": data["model"]}]}),
            },
            "IAM.ManagedPolicy",
        )
        TestCase().assertTrue(pending.warnings)
        operation = pending.require_value()["Statement"][0]["Resource"].operation
        TestCase().assertEqual(operation, "Unverified")
        return {"warnings": projected(pending.warnings), "operation": operation}
    records = setting(
        comparison,
        "IAM.ManagedPolicy",
        "PolicyDocument",
        {"Statement": [{"Resource": data["model"]}]},
        {"Statement": [{"Resource": data["actual"]}]},
    )
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="managed-attachment-")
)
def test_managed_policy_attachment_edges(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_managed_attachment)


def _execute_managed_attachment(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "iam", "001", "IAM.ManagedPolicy", "Policy", [])
    resource(
        comparison,
        "iam",
        "002",
        "IAM.Role",
        "Role",
        [],
        properties={"ManagedPolicyArns": data["arns"]},
    )
    document = comparison.stack_inputs["producer"][0]
    document.update(data["document_fields"])
    document["Resources"]["Role"].update(data["role_fields"])
    callback = partial(
        managed_policy_roles,
        stack_inputs=comparison.stack_inputs,
        evaluate=comparison.evaluate,
        reference_same=comparison.reference_same,
        symbol=comparison.symbol,
    )
    try:
        result = callback("iam", "001", "producer", data["attached"])
    except Blocked as failure:
        return {"error": {"type": type(failure).__name__, "message": str(failure)}}
    return {"result": projected(result)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="inline-owner-")
)
def test_inline_policy_ownership(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_inline_owner)


def _execute_inline_owner(case):
    data = case["data"]
    document = data["document"]
    child = document["Resources"].get("Policy", data["child"])
    selected, failure = inline_owner(
        "S3.Bucket",
        "S3.BucketPolicy",
        "Bucket",
        {},
        document,
        {},
        {},
        "AWS::S3::BucketPolicy",
    )
    if selected is not None:
        TestCase().assertIs(selected, child)
    return {"selected": selected is not None, "failure": projected(failure)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="quicksight-")
)
def test_quicksight_api_group_principal(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_quicksight_principal)


def _execute_quicksight_principal(case):
    data = case["data"]
    comparison = fixture()
    comparison.partition = data["partition"]
    rows = resource(
        comparison,
        "quicksight",
        "001",
        "QuickSight.Group",
        "Group",
        [(item[0], item[1], None) for item in data["initial_rows"]],
    )
    desired_rows = dict(data["rows"])
    for rid, row in rows[:]:
        prop = row["property"].removeprefix("QuickSight.Group.")
        if prop not in desired_rows:
            rows.remove((rid, row))
        elif desired_rows[prop] != dict(data["initial_rows"])[prop]:
            row["value"] = desired_rows[prop]
    metadata = comparison.resources["quicksight"]["001"]
    metadata.pop("cfn-logicalId")
    metadata["resourceMode"] = "IMPORT"
    model = comparison.models["quicksight"]
    model.values["desired.resource.001.resourceMode"] = "IMPORT"
    model.authoritative["desired.resource.001.resourceMode"] = "IMPORT"
    model.authoritative.pop("desired.resource.001.cfn-logicalId")
    model.values.pop("desired.resource.001.cfn-logicalId")
    if data["duplicate"]:
        rows.append(("001-004", dict(rows[-1][1])))
    link = model_ref(data["logical_id"], "Arn")
    if data["observed"]:
        rows.append(
            ("001-004", dict(property="QuickSight.Group.Arn", value=json.dumps(link)))
        )
        model.authoritative["observed.row.001-004.value"] = "PENDING_DEPLOY"
    if data["other_scope"]:
        comparison.models["quicksight"] = replace(
            model, scope=Scope(ROOT, "fixture", "other", "quicksight")
        )
    comparison.local_comparison = data["local_comparison"]
    comparison.target["iacEngine"] = data["engine"]
    if data["blocked"]:
        with (
            patch("comparison.inputs._imports_model_identity.Resolver"),
            pytest.raises(Blocked),
        ):
            comparison.desired_reference(
                "quicksight",
                link,
                "QuickSight.DataSource",
                "Permissions[].Principal",
                data["attribute"],
            )
        return {"blocked": True}
    actions = data["actions"]
    records = setting(
        comparison,
        "QuickSight.DataSource",
        "Permissions",
        [{"Principal": link, "Actions": actions}],
        [{"Principal": data["actual"], "Actions": data["actual_actions"]}],
        service="quicksight",
    )
    if data["indexed"]:
        current = comparison.rows["quicksight"]["090"]
        current[:] = [
            (
                "090-001",
                dict(
                    property="QuickSight.DataSource.Permissions[1].Principal",
                    value=json.dumps(link),
                ),
            ),
            (
                "090-002",
                dict(
                    property="QuickSight.DataSource.Permissions[1].Actions",
                    value=json.dumps(actions),
                ),
            ),
        ]
        for rid, row in current:
            model.authoritative.update(
                {f"desired.row.{rid}.{key}": value for key, value in row.items()}
            )
        comparison.model_references.clear()
        document = comparison.stack_inputs["producer"][0]
        records = comparison.compare_rows(
            "quicksight",
            "090",
            comparison.resources["quicksight"]["090"],
            "producer",
            "Receiver",
            ROOT / "synthetic.yaml",
            document["Resources"]["Receiver"],
            document,
        ).records
    if data["verify_baseline"]:
        symbol = comparison.desired_reference(
            "quicksight", link, "QuickSight.DataSource", "Permissions[].Principal"
        )
        TestCase().assertEqual(comparison.reference_literal(symbol), data["actual"])
        with pytest.raises(Blocked, match="IMPORT"):
            comparison.reference("quicksight", link, "Arn")
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id",
    [
        "account",
        "group",
        "sub",
        "unresolved",
        "actions-order",
        "actions-duplicate",
        "actions-value",
    ],
)
def test_quicksight_case_faults(data_regression, tmp_path, case_id):
    case_id = "quicksight-" + case_id
    result = _execute_quicksight_principal(load_case("reference_evidence", case_id))
    result["records"][0]["category"] = (
        "difference" if case_id == "quicksight-sub" else "matched"
    )
    target = tmp_path / "expected.yml"
    target.write_text(expected_text("reference_evidence", case_id), encoding="utf-8")
    with pytest.raises(AssertionError, match="FILES DIFFER"):
        data_regression.check(result, fullpath=target)


def test_quicksight_executor_cannot_skip_comparison(data_regression, tmp_path):
    case_id = "quicksight-none"
    compare = Mock(return_value=[])
    with patch.dict(_execute_quicksight_principal.__globals__, {"setting": compare}):
        result = _execute_quicksight_principal(load_case("reference_evidence", case_id))
    compare.assert_called_once()
    target = tmp_path / "expected.yml"
    target.write_text(expected_text("reference_evidence", case_id), encoding="utf-8")
    with pytest.raises(AssertionError, match="FILES DIFFER"):
        data_regression.check(result, fullpath=target)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="flowlog-context-")
)
def test_flowlog_resource_type_context(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_flowlog_context)


def _execute_flowlog_context(case):
    data = case["data"]
    prop, context, producer = data["prop"], data["context"], data["producer"]
    comparison = fixture()
    resource(comparison, "vpc", "001", "EC2.VPC", "Vpc", [])
    resource(comparison, "vpc", "002", "EC2.Subnet", "Subnet", [])
    link = model_ref(
        "EC2_VPC_001" if producer == "Vpc" else "EC2_Subnet_002",
        "VpcId" if producer == "Vpc" else "SubnetId",
    )
    if data["accept"]:
        result = comparison.desired_reference(
            "vpc", link, "EC2.FlowLog", prop, context=context
        )
        TestCase().assertEqual(result["$attribute"], "VpcId")
        attribute = result["$attribute"]
    else:
        with pytest.raises(Blocked):
            comparison.desired_reference(
                "vpc", link, "EC2.FlowLog", prop, context=context
            )
        attribute = None
    return {"attribute": attribute}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-receiver-")
)
def test_security_group_receiver_ref_evidence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_receiver)


def _execute_sg_receiver(case):
    data = case["data"]
    service, producer, attribute, kind, path = data["receiver"]
    comparison = fixture()
    document, parameters, pseudo = comparison.stack_inputs["producer"]
    document["Parameters"] = {"VpcId": {"Type": "AWS::EC2::VPC::Id"}}
    parameters["VpcId"] = data["vpc"]
    for identity, logical in (("001", "Producer"), ("002", "OtherProducer")):
        resource(
            comparison,
            service,
            identity,
            producer,
            logical,
            [],
            properties={"VpcId": {"Ref": "VpcId"}},
        )
    desired = comparison.desired_reference(
        service, model_ref("EC2_SecurityGroup_001", "GroupId"), kind, path
    )
    actual = comparison.evaluate("producer", {"Ref": "Producer"})
    other = comparison.evaluate("producer", {"Ref": "OtherProducer"})
    getatt = comparison.evaluate("producer", {"Fn::GetAtt": ["Producer", "GroupId"]})
    results = [
        comparison.reference_same(desired, actual, kind, path),
        comparison.reference_same(desired, other, kind, path),
        comparison.reference_same(desired, getatt, kind, path),
    ]
    check = TestCase()
    for result, expected in zip(results, (True, False, True), strict=True):
        check.assertIs(result, expected)
    check.assertEqual(parameters["VpcId"], data["vpc"])
    comparison.symbols.clear()
    parameters["VpcId"] = "UNSET"
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("producer", {"Ref": "Producer"})
    check.assertEqual(parameters["VpcId"], "UNSET")
    return {
        "results": results,
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)},
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-vpc-evidence-")
)
def test_security_group_ref_vpc_evidence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_vpc_evidence)


def _execute_sg_vpc_evidence(case):
    data = case["data"]
    comparison = fixture()
    document, inputs, pseudo = comparison.stack_inputs["producer"]
    document["Parameters"] = {"VpcId": {"Type": "String"}}
    document["Conditions"] = data["conditions"]
    inputs.update(data["parameters"])
    resource(comparison, "vpc", "001", "EC2.VPC", "Vpc", [])
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": data["value"]},
    )
    return _sg_reference_result(comparison)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-vpc-required-")
)
def test_security_group_ref_requires_vpc(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_vpc_required)


def _execute_sg_vpc_required(case):
    comparison = fixture()
    resource(comparison, "vpc", "001", "EC2.VPC", "Vpc", [])
    resource(comparison, "iam", "001", "IAM.Role", "Role", [])
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": case["data"]["value"]},
    )
    comparison.stack_inputs["producer"][0]["Conditions"] = {
        "Active": {"Fn::Equals": [1, 1]}
    }
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("producer", {"Ref": "Group"})
    attribute = comparison.evaluate("producer", {"Fn::GetAtt": ["Group", "GroupId"]})[
        "$attribute"
    ]
    TestCase().assertEqual(attribute, "GroupId")
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)},
        "attribute": attribute,
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="cloudtrail-membership-")
)
def test_cloudtrail_membership_comparison(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_cloudtrail_membership)


def _execute_cloudtrail_membership(case):
    data = case["data"]
    comparison = fixture()
    if not data["partial"]:
        records = setting(
            comparison,
            "CloudTrail.Trail",
            "EventSelectors",
            data["desired"],
            data["actual"],
        )
        TestCase().assertEqual(records[0]["category"], "difference")
    else:
        resource(
            comparison,
            "cloudtrail",
            "001",
            "CloudTrail.Trail",
            "Trail",
            [
                ("EventSelectors[].DataResources[].Values", '["a"]', None),
                ("IsLogging", "true", None),
            ],
        )
        document = comparison.stack_inputs["producer"][0]
        definition = document["Resources"]["Trail"]
        definition["Properties"] = dict(IsLogging=False, EventSelectors=data["actual"])
        records = comparison.compare_rows(
            "cloudtrail",
            "001",
            comparison.resources["cloudtrail"]["001"],
            "producer",
            "Trail",
            ROOT / "synthetic.yaml",
            definition,
            document,
        ).records
        TestCase().assertTrue(
            any(
                item["category"] == "uncompared"
                and "membership unresolved" in item["reason"]
                for item in records
            )
        )
        TestCase().assertTrue(
            any(
                item["property"].endswith(".IsLogging")
                and item["category"] == "difference"
                for item in records
            )
        )
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="export-isolation-")
)
def test_export_isolation_and_substitution_failures(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_export_isolation)


def _execute_export_isolation(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "s3",
        "001",
        "S3.Bucket",
        "Bucket",
        [],
        properties=data["properties"],
    )
    document = comparison.stack_inputs["producer"][0]
    document["Outputs"].update(data["outputs"])
    document.update(data["document_fields"])
    if data["unreadable_stack"]:
        comparison.templates = Mock(
            return_value=[
                ("missing", {"name": "missing"}),
                ("producer", {"name": "producer"}),
            ]
        )
        comparison.stack = Mock(
            side_effect=[
                Blocked("missing"),
                (ROOT / "synthetic.yaml", comparison.stack_inputs["producer"]),
            ]
        )
    if data["cyclic"]:
        with pytest.raises(Blocked, match="cyclic") as failure:
            comparison.evaluate("producer", {"Fn::Sub": "${Bucket}"})
        return {
            "error": {
                "type": type(failure.value).__name__,
                "message": str(failure.value),
            }
        }
    if data["search_incomplete"]:
        with pytest.raises(Blocked, match="search incomplete") as first:
            exported(comparison, {"Fn::GetAtt": ["Bucket", "Arn"]})
        with patch.object(
            comparison,
            "templates",
            side_effect=AssertionError("repeated export search"),
        ):
            with pytest.raises(Blocked, match="search incomplete") as second:
                comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})
        return {"errors": [str(first.value), str(second.value)]}
    result = exported(comparison, {"Fn::GetAtt": ["Bucket", "Arn"]})
    TestCase().assertEqual(result["$resource"], ["s3", "001"])
    with patch.object(
        comparison, "templates", side_effect=AssertionError("repeated export search")
    ):
        shared = comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})
        TestCase().assertEqual(shared["$attribute"], "Arn")
        with pytest.raises(Blocked) as hidden:
            comparison.evaluate("consumer", {"Fn::ImportValue": "hidden"})
    return {
        "result": projected(result),
        "shared": projected(shared),
        "hidden": str(hidden.value),
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
