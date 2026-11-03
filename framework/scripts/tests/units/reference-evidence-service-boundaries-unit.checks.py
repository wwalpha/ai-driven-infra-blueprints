"""Offline reference proof through the shared evaluator and comparison pipeline."""

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from support.comparison_cases import projected
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    ResourceReference,
)
from utils.reference_contracts import (
    row_contexts,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    ROOT,
    VPC,
    _portable_synthetic_root,
    _reference_decision_data,
    _sg_reference_result,
    fixture,
    resource,
    setting,
)
from support.reference_evidence_shared import (
    offline as offline,
)


def test_federated_catalog_identifier_does_not_assume_connection_identity():
    comparison = fixture()
    resource(comparison, "producer", "001", "Glue.Connection", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Name"})
    assert (
        comparison.reference_decision(
            symbol, symbol, "Glue.Catalog", "FederatedCatalog.Identifier"
        ).equal
        is None
    )


def test_lambda_source_access_uri_rejects_wrong_producer():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    assert (
        comparison.reference_decision(
            symbol,
            symbol,
            "Lambda.EventSourceMapping",
            "SourceAccessConfigurations[].URI",
            context={"Type": "BASIC_AUTH"},
        ).equal
        is not True
    )
    assert (
        comparison.reference_decision(
            symbol,
            symbol,
            "Lambda.EventSourceMapping",
            "SourceAccessConfigurations[].URI",
        ).equal
        is None
    )


def test_lambda_source_access_uri_context_is_bound_to_entry():
    comparison = fixture()
    resource(comparison, "secret", "001", "SecretsManager.Secret", "Secret", [])
    rows = setting(
        comparison,
        "Lambda.EventSourceMapping",
        "SourceAccessConfigurations",
        [{"Type": "BASIC_AUTH", "URI": model_ref("SecretsManager_Secret_001", "Id")}],
        [{"Type": "BASIC_AUTH", "URI": {"Ref": "Secret"}}],
    )
    assert [row["category"] for row in rows] == ["matched"], rows


def test_lambda_source_access_secret_contract_requires_context():
    comparison = fixture()
    resource(comparison, "secret", "001", "SecretsManager.Secret", "Secret", [])
    symbol = ResourceReference({"$resource": ["secret", "001"], "$attribute": "Id"})
    kind, path = "Lambda.EventSourceMapping", "SourceAccessConfigurations[].URI"
    assert (
        comparison.reference_decision(
            symbol, symbol, kind, path, context={"Type": "BASIC_AUTH"}
        ).equal
        is True
    )
    assert comparison.reference_decision(symbol, symbol, kind, path).equal is None
    assert (
        comparison.reference_decision(
            symbol, symbol, kind, path.replace("[]", "[1]")
        ).equal
        is None
    )
    assert (
        comparison.reference_decision(
            symbol, symbol, kind, path, context={"Type": "VPC_SUBNET"}
        ).equal
        is None
    )


def test_lambda_source_access_split_rows_bind_only_the_same_index():
    rows = [
        (
            "001-001",
            {
                "property": "Lambda.EventSourceMapping.SourceAccessConfigurations[1].Type",
                "value": "`BASIC_AUTH`",
            },
        ),
        (
            "001-002",
            {
                "property": "Lambda.EventSourceMapping.SourceAccessConfigurations[2].Type",
                "value": "`VPC_SUBNET`",
            },
        ),
    ]
    contexts = row_contexts("Lambda.EventSourceMapping", rows)
    assert contexts["SourceAccessConfigurations[1]"] == {"Type": "BASIC_AUTH"}
    assert contexts["SourceAccessConfigurations[2]"] == {"Type": "VPC_SUBNET"}
    rows.append(
        (
            "001-003",
            {
                "property": "Lambda.EventSourceMapping.SourceAccessConfigurations[1].Type",
                "value": "`BASIC_AUTH`",
            },
        )
    )
    assert "SourceAccessConfigurations[1]" not in row_contexts(
        "Lambda.EventSourceMapping", rows
    )


def test_lambda_source_access_split_model_rows_compare():
    comparison = fixture()
    resource(comparison, "secret", "001", "SecretsManager.Secret", "Secret", [])
    resource(
        comparison,
        "consumer",
        "090",
        "Lambda.EventSourceMapping",
        "Receiver",
        [
            ("SourceAccessConfigurations[1].Type", "BASIC_AUTH", None),
            (
                "SourceAccessConfigurations[1].URI",
                model_ref("SecretsManager_Secret_001", "Id"),
                None,
            ),
        ],
        properties={
            "SourceAccessConfigurations": [
                {"Type": "BASIC_AUTH", "URI": {"Ref": "Secret"}}
            ]
        },
    )
    document = comparison.stack_inputs["producer"][0]
    definition = document["Resources"]["Receiver"]
    result = comparison.compare_rows(
        "consumer",
        "090",
        comparison.resources["consumer"]["090"],
        "producer",
        "Receiver",
        ROOT / "synthetic.yaml",
        definition,
        document,
    )
    assert result.failure is None, result.failure
    assert [row["category"] for row in result.records] == ["matched"], result.records


def test_codebuild_artifact_s3_location_rejects_wrong_producer():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    assert (
        comparison.reference_decision(
            symbol,
            symbol,
            "CodeBuild.Project",
            "Artifacts.Location",
            context={"Type": "S3"},
        ).equal
        is not True
    )


def test_codebuild_artifact_s3_location_context():
    comparison = fixture()
    resource(comparison, "bucket", "001", "S3.Bucket", "Bucket", [])
    rows = setting(
        comparison,
        "CodeBuild.Project",
        "Artifacts",
        {"Type": "S3", "Location": model_ref("S3_Bucket_001", "BucketName")},
        {"Type": "S3", "Location": {"Ref": "Bucket"}},
    )
    assert [row["category"] for row in rows] == ["matched"], rows
    symbol = ResourceReference(
        {"$resource": ["bucket", "001"], "$attribute": "BucketName"}
    )
    assert (
        comparison.reference_decision(
            symbol, symbol, "CodeBuild.Project", "Artifacts.Location"
        ).equal
        is None
    )


def test_codebuild_source_s3_location_does_not_match_role():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    assert (
        comparison.reference_decision(
            symbol,
            symbol,
            "CodeBuild.Project",
            "Source.Location",
            context={"Type": "S3"},
        ).equal
        is not True
    )


def test_codebuild_cache_s3_location_does_not_match_role():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    assert (
        comparison.reference_decision(
            symbol,
            symbol,
            "CodeBuild.Project",
            "Cache.Location",
            context={"Type": "S3"},
        ).equal
        is None
    )


def test_glue_crawler_s3_path_does_not_match_role_name():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    assert (
        comparison.reference_decision(
            symbol, symbol, "Glue.Crawler", "Targets.S3Targets[].Path"
        ).equal
        is not True
    )


def test_unproven_s3_output_location_does_not_match_role():
    comparison = fixture()
    resource(comparison, "producer", "001", "IAM.Role", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "RoleName"}
    )
    assert (
        comparison.reference_decision(
            symbol,
            symbol,
            "Athena.WorkGroup",
            "WorkGroupConfiguration.ResultConfiguration.OutputLocation",
        ).equal
        is None
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="unknown-context-")
)
def test_unknown_context_cannot_match_wrong_producer(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_unknown_context)


def _execute_unknown_context(case):
    kind, path = (case["data"][key] for key in ("kind", "path"))
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "BucketName"}
    )
    decision = comparison.reference_decision(symbol, symbol, kind, path)
    TestCase().assertIsNot(decision.equal, True)
    return {"decision": _reference_decision_data(decision)}


def test_cloudtrail_object_context_rejects_malformed_desired_expression():
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    expression = Expression("Join", ["", [symbol, "/wrong/"]])
    assert (
        comparison.reference_decision(
            expression,
            expression,
            "CloudTrail.Trail",
            "EventSelectors[].DataResources[].Values[]",
            context={"Type": "AWS::S3::Object"},
        ).equal
        is None
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="multi-attribute-")
)
def test_new_multiple_attribute_contract_does_not_guess_legacy_link(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_multi_attribute)


def _execute_multi_attribute(case):
    kind, path, producer = (case["data"][key] for key in ("kind", "path", "producer"))
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    _portable_synthetic_root(comparison)
    with pytest.raises(Blocked) as failure:
        comparison.desired_reference(
            "producer",
            model_ref(producer.replace(".", "_") + "_001", "Unknown"),
            kind,
            path,
        )
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-import-proof-")
)
def test_security_group_import_vpc_evidence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_import_proof)


def _execute_sg_import_proof(case):
    comparison = fixture()
    resource(comparison, "vpc", "001", "EC2.VPC", "Vpc", [], stack="consumer")
    resource(comparison, "iam", "001", "IAM.Role", "Role", [], stack="consumer")
    comparison.stack_inputs["consumer"][0]["Outputs"]["Shared"] = {
        "Value": case["data"]["export"],
        "Export": {"Name": "shared"},
    }
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": {"Fn::ImportValue": "shared"}},
    )
    return _sg_reference_result(comparison)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-invalid-evidence-")
)
def test_security_group_invalid_evidence_receiver_rows(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_invalid_evidence)


def _execute_sg_invalid_evidence(case):
    data = case["data"]
    service, producer, attribute, kind, path = data["receiver"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"VpcId": {"Type": "String"}, "Suffix": {"Type": "String"}}
    parameters.update(VpcId="UNSET", Suffix="ZZZZZZZZ")
    resource(comparison, "iam", "001", "IAM.Role", "Role", [], stack="consumer")
    comparison.stack_inputs["consumer"][0]["Outputs"]["Shared"] = {
        "Value": {"Ref": "Role"},
        "Export": {"Name": "shared"},
    }
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
    TestCase().assertEqual([record["category"] for record in records], ["uncompared"])
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-sub-form-")
)
def test_sg_sub_equivalent_forms(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_sub_form)


def _execute_sg_sub_form(case):
    data = case["data"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Suffix": {"Type": "String"}}
    parameters["Suffix"] = data["suffix"]
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": data["expression"]},
    )
    return _sg_reference_result(comparison)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-sub-map-")
)
def test_sg_sub_invalid_map(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_sub_map)


def _execute_sg_sub_map(case):
    comparison = fixture()
    resource(comparison, "iam", "001", "IAM.Role", "Role", [])
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": case["data"]["expression"]},
    )
    with pytest.raises((Blocked, ValueError)) as failure:
        comparison.evaluate("producer", {"Ref": "Group"})
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-import-form-")
)
def test_sg_import_equivalent_forms(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_import_form)


def _execute_sg_import_form(case):
    data = case["data"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Stage": {"Type": "String"}}
    parameters["Stage"] = "VpcId"
    resource(comparison, "vpc", "001", "EC2.VPC", "Vpc", [], stack="consumer")
    resource(comparison, "iam", "001", "IAM.Role", "Role", [], stack="consumer")
    if data["export"] is not None:
        comparison.stack_inputs["consumer"][0]["Outputs"]["Shared"] = {
            "Value": data["export"],
            "Export": {"Name": "ExternalVpcId"},
        }
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": {"Fn::ImportValue": data["name"]}},
    )
    return _sg_reference_result(comparison)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="sg-import-ambiguous-")
)
def test_sg_import_ambiguous_is_blocked(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_sg_import_ambiguous)


def _execute_sg_import_ambiguous(case):
    data = case["data"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Stage": {"Type": "String"}}
    parameters["Stage"] = data["stage"]
    document["Outputs"].update(data["producer_outputs"])
    comparison.stack_inputs["consumer"][0]["Outputs"].update(data["consumer_outputs"])
    comparison.stack_inputs["consumer"][0].update(data["consumer_fields"])
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": {"Fn::ImportValue": {"Fn::Sub": "External${Stage}"}}},
    )
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("producer", {"Ref": "Group"})
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


def test_sg_sub_pending_does_not_hide_invalid_known_value():
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {
        "Pending": {"Type": "String"},
        "Known": {"Type": "String"},
    }
    parameters.update(Pending="PENDING_DEPLOY", Known="ZZZZ")
    expression = {
        "Fn::Sub": ["vpc-${A}${B}", {"A": {"Ref": "Pending"}, "B": {"Ref": "Known"}}]
    }
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [],
        properties={"VpcId": expression},
    )
    with pytest.raises(Blocked):
        comparison.evaluate("producer", {"Ref": "Group"})


def test_security_group_vpc_comparison_retains_sub_map_uncertainty():
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Suffix": {"Type": "String"}}
    parameters["Suffix"] = "PENDING_DEPLOY"
    records = setting(
        comparison,
        "EC2.SecurityGroup",
        "VpcId",
        VPC,
        {"Fn::Sub": ["vpc-${Id}", {"Id": {"Ref": "Suffix"}}]},
    )
    assert [record["category"] for record in records] == ["uncompared"], records


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="other-unresolved-")
)
def test_unresolved_expression_is_uncompared_for_other_resources(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_other_unresolved)


def _execute_other_unresolved(case):
    data = case["data"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Value": {"Type": "String"}}
    document["Conditions"] = {"Active": {"Fn::Equals": ["yes", "yes"]}}
    parameters["Value"] = "PENDING_DEPLOY"
    records = setting(
        comparison, data["kind"], data["path"], data["desired"], data["expression"]
    )
    TestCase().assertEqual([record["category"] for record in records], ["uncompared"])
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="condition-unresolved-")
)
def test_unresolved_condition_and_unselected_branch(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_condition_unresolved)


def _execute_condition_unresolved(case):
    data = case["data"]
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Value": {"Type": "String"}}
    parameters["Value"] = "PENDING_DEPLOY"
    document["Conditions"] = {"Choose": {"Fn::Equals": data["condition"]}}
    records = setting(
        comparison, "EC2.Subnet", "VpcId", "vpc-123abc", data["expression"]
    )
    return {"records": projected(records)}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
