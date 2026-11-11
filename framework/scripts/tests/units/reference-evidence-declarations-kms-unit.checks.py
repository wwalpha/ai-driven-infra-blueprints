"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.rules.kms import compare_forms
from support.fixture_cases import load_case
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids
from utils.cloudformation.inputs import Blocked
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
    VPC,
    _execute_negative,
    _reference_decision_data,
    consumer,
    declaration,
    exported,
    fixture,
    kms_key,
    prepared,
    resource,
    vpc,
)
from support.reference_evidence_shared import (
    offline as offline,
)


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="negative-"))
def test_declared_reference_negative_cases(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_negative)


def test_declared_security_group_uses_existing_ref_output_mapping():
    comparison = fixture()
    fixed = "sg-0123456789abcdef0"
    resource(
        comparison,
        "security-group",
        "001",
        "EC2.SecurityGroup",
        "Group",
        [("Id", "PENDING_DEPLOY", fixed)],
        properties={"VpcId": VPC},
    )
    row = consumer(comparison, fixed)
    declaration(
        comparison,
        "desired.row.010-001.value",
        fixed,
        producer="security-group",
        logical="Group",
        kind="EC2.SecurityGroup",
        prop="EC2.SecurityGroup.Id",
    )
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {"Ref": "Group"})
    assert desired["$attribute"] == "GroupId" and actual["$attribute"] == "GroupId"
    assert (
        comparison.reference_decision(
            desired, actual, "EC2.Instance", "SecurityGroupIds[]"
        ).equal
        is True
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="different-identifier-")
)
def test_same_producer_different_identifier_form_is_not_equated(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_different_identifier)


def _execute_different_identifier(case):
    comparison = fixture()
    resource(
        comparison,
        "repository",
        "001",
        "CodeCommit.Repository",
        "Repository",
        [("RepositoryName", case["data"]["value"], None)],
        properties={"RepositoryName": case["data"]["value"]},
    )
    row = consumer(comparison, case["data"]["value"])
    declaration(
        comparison,
        "desired.row.010-001.value",
        case["data"]["value"],
        producer="repository",
        logical="Repository",
        kind="CodeCommit.Repository",
        prop="CodeCommit.Repository.RepositoryName",
        mode="name",
    )
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {"Ref": "Repository"})
    TestCase().assertTrue(
        comparison.reference_decision(desired, actual, "IAM.Role", "").equal is None
    )
    return {
        "decision": _reference_decision_data(
            comparison.reference_decision(desired, actual, "IAM.Role", "")
        )
    }


def test_pointer_mismatch_is_not_silently_applied():
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    row[1]["document"] = json.dumps({"ids": [VPC]})
    comparison.models["consumer"].authoritative["desired.row.010-001.document"] = row[
        1
    ]["document"]
    declaration(comparison, "desired.row.010-001.document", VPC, pointer="/ids/1")
    assert isinstance(prepared(comparison, row).error, Blocked)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="export-blocked-")
)
def test_export_resolution_failures_remain_blocked(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_export_blocked)


@pytest.mark.parametrize(
    ("case_id", "message"),
    [
        (
            "export-blocked-01",
            "ImportValue handoff matches=2 or same-stack export: shared",
        ),
        ("export-blocked-02", "cyclic ImportValue: other"),
    ],
)
def test_export_duplicate_and_cycle_with_confirmed_scope(case_id, message):
    result = _execute_export_blocked(
        load_case("reference_evidence", case_id), confirmed_scope=True
    )
    TestCase().assertEqual(result, {"error": {"type": "Blocked", "message": message}})


def _execute_export_blocked(case, *, confirmed_scope=False):
    data = case["data"]
    comparison = fixture()
    vpc(comparison)
    if data["other"] is not None:
        pseudo = dict(comparison.stack_inputs["producer"][2]) if confirmed_scope else {}
        comparison.stack_inputs["other"] = (data["other"], {}, pseudo)
    comparison.stack_inputs["producer"][0]["Outputs"].update(data["producer_outputs"])
    with pytest.raises(Blocked) as failure:
        comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})
    return {
        "error": {"type": type(failure.value).__name__, "message": str(failure.value)}
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="unresolved-")
)
def test_unresolved_intrinsics_never_match(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_unresolved)


def _execute_unresolved(case):
    expression = case["data"]["expression"]
    comparison = fixture()
    before = copy.deepcopy(expression)
    with pytest.raises(Blocked) as caught:
        comparison.evaluate("consumer", expression)
    decision = comparison.reference_decision(
        "value", Expression("Unverified", [expression]), "IAM.Role", ""
    )
    TestCase().assertEqual(expression, before)
    return {
        "error": {"type": "Blocked", "message": str(caught.value)},
        "decision": _reference_decision_data(decision),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="correspondence-")
)
def test_recorded_value_cannot_bypass_current_correspondence(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_correspondence)


def _execute_correspondence(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison)
    actual = exported(comparison, {"Ref": "Vpc"})
    document = comparison.stack_inputs["producer"][0]
    document.update(data["document_fields"])
    document["Resources"]["Vpc"].update(data["resource_fields"])
    if data["duplicate"]:
        vpc(comparison, "002", "OtherVpc")
        comparison.models["vpc"].values["desired.resource.002.cfn-logicalId"] = (
            "producer-Vpc"
        )
        comparison._index = None
    comparison.symbols.clear()
    decision = comparison.reference_decision(VPC, actual, "EC2.Subnet", "VpcId")
    TestCase().assertIsNone(decision.equal)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="kms-link-"))
def test_kms_link_contract_and_id_arn_separation(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_link)


def _execute_kms_link(case):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", case["data"]["key_id"])],
    )
    key = comparison.evaluate("producer", {"Ref": "Key"})
    arn = exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    desired = comparison.desired_reference(
        "kms", model_ref("KMS_Key_001", "Arn"), "Athena.WorkGroup", ATHENA_KMS
    )
    results = [
        comparison.reference_decision(desired, arn, "Athena.WorkGroup", ATHENA_KMS),
        comparison.reference_decision(key, arn, "Athena.WorkGroup", ATHENA_KMS),
        comparison.reference_decision(
            case["data"]["arn"], key, "Athena.WorkGroup", ATHENA_KMS
        ),
    ]
    TestCase().assertEqual([d.equal for d in results], [True, False, False])
    return {"decisions": [_reference_decision_data(d) for d in results]}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-export-")
)
def test_kms_recorded_arn_export_import(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_export)


def _execute_kms_export(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", data["key_id"])],
    )
    before = copy.deepcopy(comparison.models["kms"].authoritative)
    actual = exported(comparison, data["expression"])
    decision = comparison.reference_decision(
        KEY_ARN.replace(KEY_ID, data["key_id"]), actual, data["kind"], data["path"]
    )
    check = TestCase()
    check.assertIsNone(decision.equal)
    check.assertFalse(decision.equivalent)
    detail = decision.diagnostics[0]
    check.assertEqual(detail["evidence_type"], "recorded_observed")
    check.assertIs(detail["current_aws_verified"], False)
    check.assertEqual(
        detail["exports"], [{"export_name": "shared", "export_stack": "producer"}]
    )
    if data["expression"] == {"Fn::GetAtt": ["Key", "Arn"]}:
        check.assertEqual(
            detail["producers"],
            [
                dict(
                    producer="kms/001",
                    attribute="Arn",
                    source_property="KMS.Key.KeyId",
                    evidence_type="recorded_observed",
                    derived_format="KeyArn",
                    current_aws_verified=False,
                )
            ],
        )
    check.assertEqual(comparison.models["kms"].authoritative, before)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-observed-")
)
def test_kms_arn_requires_recorded_key_id(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_observation)


def _execute_kms_observation(case):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", KEY_ARN, case["data"]["observed"])],
    )
    actual = exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    decision = comparison.reference_decision(
        KEY_ARN, actual, "Athena.WorkGroup", ATHENA_KMS
    )
    TestCase().assertIsNone(decision.equal)
    TestCase().assertTrue(
        any(
            word in decision.diagnostics[0]["reason"]
            for word in ("unobserved", "format_unproven")
        )
    )
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-observation-only-")
)
def test_kms_arn_identifier_evidence_comes_from_observation_only(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_observation_only)


def _execute_kms_observation_only(case):
    comparison = fixture()
    key_id = case["data"]["key_id"]
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", key_id, None)],
        properties={"KeyId": key_id},
    )
    actual = exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    decision = comparison.reference_decision(
        KEY_ARN, actual, "Athena.WorkGroup", ATHENA_KMS
    )
    TestCase().assertIsNone(decision.equal)
    TestCase().assertIn("identifier_unobserved", decision.diagnostics[0]["reason"])
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-context-")
)
def test_kms_arn_uses_only_producer_context(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_context)


def _execute_kms_context(case):
    data = case["data"]
    field, value = data["field"], data["value"]
    comparison = fixture()
    kms_key(comparison)
    pseudo = dict(comparison.stack_inputs["producer"][2])
    pseudo[field] = value
    document, parameters, _ = comparison.stack_inputs["producer"]
    comparison.stack_inputs["producer"] = document, parameters, pseudo
    with pytest.raises(Blocked, match="confirmed|handoff matches=0"):
        exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    actual = comparison.evaluate("producer", {"Fn::GetAtt": ["Key", "Arn"]})
    decision = comparison.reference_decision(
        KEY_ARN, actual, "Athena.WorkGroup", ATHENA_KMS
    )
    check = TestCase()
    check.assertIsNone(decision.equal)
    check.assertIs(decision.diagnostics[0]["current_aws_verified"], False)
    result = {"decision": _reference_decision_data(decision)}
    if data["mismatched_context"]:
        check.assertTrue(
            decision.diagnostics[0]["reason"].startswith("recorded_identifier_mismatch")
        )
        other = comparison.reference_decision(
            KEY_ARN.replace(data["original"], value, 1),
            actual,
            "Athena.WorkGroup",
            ATHENA_KMS,
        )
        check.assertIsNone(other.equal)
        result["same_context"] = _reference_decision_data(other)
    return result


def test_kms_conflicting_recorded_identifier_is_uncompared():
    comparison = fixture()
    kms_key(comparison)
    actual = exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    decision = comparison.reference_decision(
        KEY_ARN.replace(KEY_ID, "mrk-" + "b" * 32),
        actual,
        "Athena.WorkGroup",
        ATHENA_KMS,
    )
    assert decision.equal is None and decision.diagnostics[0]["reason"].startswith(
        "recorded_identifier_mismatch"
    )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-handoff-")
)
def test_kms_recorded_arn_preserves_correspondence_and_handoff(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_handoff)


def _execute_kms_handoff(case):
    data = case["data"]
    comparison = fixture()
    kms_key(comparison)
    actual = exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]})
    document = comparison.stack_inputs["producer"][0]
    if data["resource"] is None:
        del document["Resources"]["Key"]
    else:
        document["Resources"]["Key"] = data["resource"]
    document.update(data["document_fields"])
    comparison.resources["kms"]["001"].update(data["metadata"])
    if data["duplicate_resource"]:
        resource(
            comparison,
            "kms",
            "002",
            "KMS.Key",
            "Other",
            [("KeyId", "PENDING_DEPLOY", KEY_ID)],
        )
        comparison.models["kms"].values["desired.resource.002.cfn-logicalId"] = (
            "producer-Key"
        )
    if data["duplicate_row"]:
        comparison.rows["kms"]["001"].append(
            ("001-002", dict(comparison.rows["kms"]["001"][0][1]))
        )
    if not data["templates_available"]:
        comparison.templates = Mock(return_value=[])
    comparison.symbols.clear()
    comparison._index = None
    decision = comparison.reference_decision(
        KEY_ARN, actual, "Athena.WorkGroup", ATHENA_KMS
    )
    TestCase().assertIsNone(decision.equal)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="kms-forms-"))
def test_kms_expression_cannot_bypass_allowed_forms(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_forms)


def _execute_kms_forms(case):
    comparison = fixture()
    kms_key(comparison)
    decision = comparison.reference_decision(
        KEY_ARN,
        exported(comparison, case["data"]["actual"]),
        "Athena.WorkGroup",
        ATHENA_KMS,
    )
    TestCase().assertIs(decision.equal, False)
    TestCase().assertEqual(
        decision.diagnostics[0]["code"], "kms.format_outside_allowed"
    )
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-literal-")
)
def test_kms_declared_literal_cannot_bypass_allowed_forms(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_literal)


def _execute_kms_literal(case):
    data = case["data"]
    comparison = fixture()
    kms_key(comparison)
    row = consumer(comparison, KEY_ID)
    declaration(
        comparison,
        "desired.row.010-001.value",
        KEY_ID,
        producer="kms",
        logical="Key",
        kind="KMS.Key",
        prop="KMS.Key.KeyId",
    )
    desired = prepared(comparison, row).require_value()
    value = (
        data["literal"]
        if data["expression"] is None
        else exported(comparison, data["expression"])
    )
    decision = comparison.reference_decision(
        desired, value, "Athena.WorkGroup", ATHENA_KMS
    )
    TestCase().assertIs(decision.equal, False)
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-alias-only-")
)
def test_key_arn_does_not_override_alias_only_service_contract(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_alias_only)


def _execute_kms_alias_only(case):
    comparison = fixture()
    kms_key(comparison)
    decision = comparison.reference_decision(
        KEY_ARN,
        exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]}),
        case["data"]["kind"],
        case["data"]["path"],
    )
    TestCase().assertIs(decision.equal, False)
    TestCase().assertNotIn("KeyArn", decision.diagnostics[0]["allowed_forms"])
    return {"decision": _reference_decision_data(decision)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="kms-matrix-")
)
def test_kms_existing_service_form_matrix(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_kms_matrix)


def _execute_kms_matrix(case):
    data = case["data"]
    kind, path = data["kind"], data["path"]
    allowed = set(data["allowed"])
    model_form, iac_form = data["model_form"], data["iac_form"]
    comparison = fixture()
    kms_key(comparison)
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/fixture", None)],
        properties={"AliasName": "alias/fixture", "TargetKeyId": {"Ref": "Key"}},
    )
    forms = {
        form: ResourceReference(
            {"$resource": ["kms", identity], "$attribute": attribute}
        )
        for form, identity, attribute in data["forms"]
    }
    decision = comparison.reference_decision(
        forms[model_form], forms[iac_form], kind, path
    )
    check = TestCase()
    check.assertIs(decision.equal, model_form == iac_form and model_form in allowed)
    outcome = compare_forms(
        forms[model_form],
        forms[iac_form],
        allowed,
        resolve_literal=comparison.reference_literal,
        format_of=comparison.kms_format,
    )
    if model_form not in allowed or iac_form not in allowed:
        check.assertIs(outcome.equal, False)
        check.assertEqual(outcome.code, "kms.format_outside_allowed")
    elif model_form != iac_form:
        check.assertIs(outcome.equal, False)
        check.assertEqual(outcome.code, "kms.format_mismatch")
    return {
        "decision": _reference_decision_data(decision),
        "outcome": {
            "equal": outcome.equal,
            "code": outcome.code,
            "message": outcome.message,
        },
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
