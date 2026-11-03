"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import sys
from functools import partial
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.reference_evidence import Evidence
from comparison.rules.kms import compare_forms, kms_format
from support.comparison_cases import projected
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.iac_values import (
    Expression,
    ResourceReference,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


from support.reference_evidence_shared import (
    ATHENA_KMS,
    KEY_ARN,
    KEY_ID,
    ROOT,
    VPC,
    _reference_decision_data,
    consumer,
    declaration,
    exported,
    fixture,
    resource,
    setting,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-unresolved-")
)
def test_kms_unresolved_expressions_do_not_gain_symbolic_equality(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_unresolved)


def _execute_kms_unresolved(case):
    comparison = fixture()
    expression = Expression("Sub", [case["data"]["expression"], {}])
    same_decision = comparison.reference_decision(
        expression, expression, "Athena.WorkGroup", ATHENA_KMS
    )
    TestCase().assertIsNone(same_decision.equal)
    outcome = compare_forms(
        expression,
        expression,
        {"KeyArn"},
        resolve_literal=str,
        format_of=partial(kms_format, resources={}),
    )
    TestCase().assertIsNone(outcome.equal)
    TestCase().assertEqual(outcome.code, "kms.format_unproven")
    future = comparison.reference_decision(
        KEY_ARN, Expression("Future", []), "Athena.WorkGroup", ATHENA_KMS
    )
    TestCase().assertIsNone(future.equal)
    return {
        "same": _reference_decision_data(same_decision),
        "outcome": {
            "equal": outcome.equal,
            "code": outcome.code,
            "message": outcome.message,
        },
        "future": _reference_decision_data(future),
    }


def test_kms_derived_producer_diagnostics_are_unique():
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    actual = exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    proof = Evidence(comparison)
    assert proof.resolve(actual) == proof.resolve(actual) == KEY_ARN
    assert len(proof.producers) == 1


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-runner-")
)
def test_kms_runner_reports_uncompared_with_recorded_proof(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_runner)


def _execute_kms_runner(case):
    kind, path = case["data"]["kind"], case["data"]["path"]
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    properties = {}
    put_row(properties, path, {"Fn::ImportValue": "shared"})
    resource(
        comparison,
        "consumer",
        "010",
        kind,
        "Consumer",
        [(path, KEY_ARN, None)],
        properties=properties,
        stack="consumer",
    )
    exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    comparison.services = ["consumer"]
    document = comparison.stack_inputs["consumer"][0]
    results = comparison.compare_rows(
        "consumer",
        "010",
        comparison.resources["consumer"]["010"],
        "consumer",
        "Consumer",
        ROOT / "synthetic.yaml",
        document["Resources"]["Consumer"],
        document,
    ).records
    TestCase().assertEqual([item["category"] for item in results], ["uncompared"])
    TestCase().assertEqual(
        results[0]["reference_diagnostics"][0]["evidence_type"], "recorded_observed"
    )
    return {"records": projected(results)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="alias-handoff-")
)
def test_alias_arn_sub_import_ref_pipeline_preserves_export_evidence(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_alias_handoff)


def _execute_alias_handoff(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Alias",
        "Alias",
        [("AliasName", data["alias"], None)],
        properties={"AliasName": data["alias"]},
    )
    comparison.stack_inputs["producer"][0]["Outputs"].update(data["outputs"])
    comparison.stack_inputs["producer"][1]["Suffix"] = data["suffix"]
    comparison.stack_inputs["consumer"][1]["Suffix"] = data["suffix"]
    resource(
        comparison,
        "logs",
        "010",
        "Logs.LogGroup",
        "Log",
        [("KmsKeyId", model_ref("KMS_Alias_002", "Arn"), None)],
        properties={"KmsKeyId": data["expression"]},
        stack="consumer",
    )
    before = copy.deepcopy(comparison.models["kms"].authoritative)
    document = comparison.stack_inputs["consumer"][0]
    batch = comparison.compare_rows(
        "logs",
        "010",
        comparison.resources["logs"]["010"],
        "consumer",
        "Log",
        ROOT / "synthetic.yaml",
        document["Resources"]["Log"],
        document,
    )
    TestCase().assertIsNone(batch.failure)
    TestCase().assertEqual([item["category"] for item in batch.records], ["matched"])
    detail = batch.records[0]["reference_diagnostics"][0]
    TestCase().assertEqual(
        detail["exports"],
        [{"export_name": "KmsLogKeyAliasNameFixture", "export_stack": "producer"}],
    )
    TestCase().assertEqual(detail["evidence_type"], "logical_reference")
    TestCase().assertIs(detail["current_aws_verified"], False)
    TestCase().assertEqual(comparison.models["kms"].authoritative, before)
    return {"records": projected(batch.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="export-chain-")
)
def test_export_chain_retains_each_handoff(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_export_chain)


def _execute_export_chain(case):
    comparison = fixture()
    vpc(comparison)
    exported(comparison, {"Ref": "Vpc"}, name="base")
    comparison.stack_inputs["relay"] = (
        case["data"]["relay"],
        {},
        dict(comparison.stack_inputs["producer"][2]),
    )
    comparison.exports = None
    actual = comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})
    decision = comparison.reference_decision(VPC, actual, "EC2.Subnet", "VpcId")
    TestCase().assertIsNone(decision.equal)
    TestCase().assertFalse(decision.equivalent)
    TestCase().assertEqual(
        decision.diagnostics[0]["exports"],
        [
            {"export_name": "shared", "export_stack": "relay"},
            {"export_name": "base", "export_stack": "producer"},
        ],
    )
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="runner-evidence-")
)
def test_runner_keeps_recorded_evidence_and_does_not_write_authority(
    case_runner, case_id
):
    case_runner.run("reference_evidence", case_id, _execute_runner_evidence)


def _execute_runner_evidence(case):
    comparison = fixture()
    vpc(comparison)
    consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", case["data"]["vpc"])
    exported(comparison, {"Ref": "Vpc"})
    comparison.services = ["consumer"]
    before = {
        service: copy.deepcopy(model.authoritative)
        for service, model in comparison.models.items()
    }
    document = comparison.stack_inputs["consumer"][0]
    results = comparison.compare_rows(
        "consumer",
        "010",
        comparison.resources["consumer"]["010"],
        "consumer",
        "Consumer",
        ROOT / "synthetic.yaml",
        document["Resources"]["Consumer"],
        document,
    ).records
    TestCase().assertEqual([item["category"] for item in results], ["matched"])
    TestCase().assertEqual(
        results[0]["reference_diagnostics"][0]["evidence_type"], "logical_reference"
    )
    TestCase().assertEqual(
        {service: model.authoritative for service, model in comparison.models.items()},
        before,
    )
    return {"records": projected(results)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="receiver-contract-")
)
def test_receiver_contracts(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_receiver_contract)


def _execute_receiver_contract(case):
    data = case["data"]
    service, producer, attribute, kind, path = (
        data[k] for k in ("service", "producer", "attribute", "kind", "path")
    )
    comparison = fixture()
    resource(
        comparison,
        service,
        "001",
        producer,
        "Producer",
        [],
        properties={"VpcId": VPC} if producer == "EC2.SecurityGroup" else {},
    )
    resource(
        comparison,
        service,
        "002",
        producer,
        "OtherProducer",
        [],
        properties={"VpcId": VPC} if producer == "EC2.SecurityGroup" else {},
    )
    link = model_ref(producer.replace(".", "_") + "_001", attribute)
    desired = comparison.desired_reference(service, link, kind, path)
    TestCase().assertEqual(
        desired,
        ResourceReference({"$resource": [service, "001"], "$attribute": attribute}),
    )
    same = comparison.reference_same(
        desired, comparison.evaluate("producer", {"Ref": "Producer"}), kind, path
    )
    TestCase().assertIs(same, True)
    different = comparison.reference_same(
        desired,
        ResourceReference(dict(desired, **{"$resource": [service, "002"]})),
        kind,
        path,
    )
    TestCase().assertIs(different, False)
    for bad_link, requested in (
        (link, "Unknown"),
        (model_ref(producer.replace(".", "_") + "_999", attribute), None),
    ):
        with pytest.raises(Blocked):
            comparison.desired_reference(service, bad_link, kind, path, requested)
    resource(
        comparison,
        "wrong",
        "001",
        "IAM.Role" if producer != "IAM.Role" else "SecretsManager.Secret",
        "Wrong",
        [],
    )
    with pytest.raises(Blocked):
        comparison.desired_reference(
            service,
            model_ref(
                "IAM_Role_001"
                if producer != "IAM.Role"
                else "SecretsManager_Secret_001",
                "Arn",
            ),
            kind,
            path,
        )
    return {
        "resource": desired["$resource"],
        "attribute": desired["$attribute"],
        "same": same,
        "different": different,
    }


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="glue-name-"))
def test_glue_connection_name(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_glue_name)


def _execute_glue_name(case):
    expression = case["data"]["expression"]
    comparison = fixture()
    resource(
        comparison,
        "glue",
        "001",
        "Glue.Connection",
        "Connection",
        [],
        properties={"ConnectionInput": {"Name": expression}}
        if expression is not None
        else {"Name": "fixture"},
    )
    resource(
        comparison,
        "glue",
        "002",
        "Glue.Connection",
        "OtherConnection",
        [],
        properties={"ConnectionInput": {"Name": {"Ref": "Connection"}}},
    )
    document, parameters, _ = comparison.stack_inputs["producer"]
    parameters["Name"] = "fixture"
    document["Conditions"] = {"Active": {"Fn::Equals": [1, 1]}}
    document["Mappings"] = {"Names": {"dev": {"Connection": "fixture"}}}
    records = setting(
        comparison,
        "Glue.Job",
        "Connections",
        {"Connections": [model_ref("Glue_Connection_001", "Name")]},
        {"Connections": ["fixture"]},
    )
    record = records[0]
    if record["category"] == "matched":
        TestCase().assertEqual(
            comparison.reference_literal(
                comparison.evaluate("producer", {"Fn::Sub": "prefix-${Connection}"})
            ),
            "prefix-fixture",
        )
        TestCase().assertEqual(
            comparison.reference_literal(
                comparison.evaluate("producer", {"Fn::Sub": "${Connection.Name}"})
            ),
            "fixture",
        )
    if expression is None:
        TestCase().assertEqual(
            record["reference_diagnostics"][0]["reason"],
            "identifier_unobserved: missing or ambiguous identifier Property",
        )
    if expression == {"Ref": "Connection"}:
        with pytest.raises(Blocked, match="cyclic resource substitution"):
            comparison.evaluate("producer", {"Fn::Sub": "${Connection}"})
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="return-attribute-")
)
def test_formal_return_attributes(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_return_attribute)


def _execute_return_attribute(case):
    data = case["data"]
    kind, ref_attribute, attribute, invalid = (
        data[k] for k in ("kind", "ref_attribute", "attribute", "invalid")
    )
    comparison = fixture()
    resource(comparison, "producer", "001", kind, "Producer", [])
    symbol = comparison.evaluate("producer", {"Fn::GetAtt": ["Producer", attribute]})
    TestCase().assertEqual(symbol["$attribute"], attribute)
    if ref_attribute:
        ref = comparison.evaluate("producer", {"Ref": "Producer"})["$attribute"]
        TestCase().assertEqual(ref, ref_attribute)
    else:
        with pytest.raises(Blocked):
            comparison.evaluate("producer", {"Ref": "Producer"})
        ref = None
    with pytest.raises((Blocked, KeyError)):
        comparison.evaluate("producer", {"Fn::GetAtt": ["Producer", invalid]})
    return {"attribute": symbol["$attribute"], "ref_attribute": ref}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="glue-secret-")
)
def test_glue_secret_identity(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_glue_secret)


def _execute_glue_secret(case):
    comparison = fixture()
    for identity, logical in [("001", "Secret"), ("002", "OtherSecret")]:
        resource(
            comparison,
            "secrets-manager",
            identity,
            "SecretsManager.Secret",
            logical,
            [],
            properties={"Name": "same-name"},
        )
    records = setting(
        comparison,
        "Glue.Connection",
        "ConnectionInput.AuthenticationConfiguration.SecretArn",
        model_ref("SecretsManager_Secret_001", "Id"),
        case["data"]["actual"],
    )
    return {"records": projected(records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="action-context-")
)
def test_action_context_requires_own_codecommit_contract(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_action_context)


def _execute_action_context(case):
    bad = case["data"]["bad"]
    comparison = fixture()
    resource(comparison, "codecommit", "001", "CodeCommit.Repository", "Repository", [])
    resource(comparison, "lambda", "001", "Lambda.Function", "Function", [])
    action = dict(Category="Source", Owner="AWS", Provider="CodeCommit", Version="1")
    link = model_ref("CodeCommit_Repository_001", "Name")
    path = "Stages[].Actions[].Configuration.RepositoryName"
    if bad == "target":
        link = model_ref("Lambda_Function_001", "Arn")
    elif bad:
        action[bad] = "wrong"
    if bad is None:
        result = comparison.desired_reference(
            "codecommit",
            link,
            "CodePipeline.Pipeline",
            path,
            context={"ActionTypeId": action},
        )
        TestCase().assertEqual(result["$attribute"], "Name")
        return {"attribute": result["$attribute"]}
    with pytest.raises(Blocked) as failure:
        comparison.desired_reference(
            "codecommit",
            link,
            "CodePipeline.Pipeline",
            path,
            context={"ActionTypeId": action},
        )
    errors = [{"type": type(failure.value).__name__, "message": str(failure.value)}]
    if bad != "target":
        action.pop(bad)
        with pytest.raises(Blocked) as missing:
            comparison.desired_reference(
                "codecommit",
                link,
                "CodePipeline.Pipeline",
                path,
                context={"ActionTypeId": action},
            )
        errors.append(
            {"type": type(missing.value).__name__, "message": str(missing.value)}
        )
    return {"errors": errors}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="event-lambda-")
)
def test_eventbridge_literal_requires_exact_lambda_identity(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_event_lambda)


def _execute_event_lambda(case):
    data = case["data"]
    comparison = fixture()
    for identity, logical in (("001", "Function"), ("002", "Other")):
        resource(
            comparison,
            "lambda",
            identity,
            "Lambda.Function",
            logical,
            [],
            properties={"FunctionName": "fixture"},
        )
    function = comparison.evaluate("producer", {"Fn::GetAtt": ["Function", "Arn"]})
    arn = "arn:aws:lambda:ap-northeast-1:123456789012:function:fixture"
    TestCase().assertIs(
        comparison.reference_same(function, arn, "Events.Rule", ""), True
    )
    definition = comparison.stack_inputs["producer"][0]["Resources"]["Function"]
    definition.update(data["definition_fields"])
    comparison.resources["lambda"]["001"].update(data["metadata"])
    comparison.stack_inputs["producer"][0].update(data["document_fields"])
    comparison.symbols.clear()
    actual = (
        ResourceReference(data["actual"])
        if isinstance(data["actual"], dict)
        else data["actual"]
    )
    result = comparison.reference_same(function, actual, "Events.Rule", "")
    TestCase().assertEqual(comparison.redacted(arn), arn)
    comparison.sensitive_values.add(arn)
    TestCase().assertEqual(comparison.redacted(arn), "<masked sensitive parameter>")
    return {"result": result}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
