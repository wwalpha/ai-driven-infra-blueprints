"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
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
from comparison import Comparison
from comparison.deferral import ImportReferenceDeferred, failure_category
from comparison.evaluation import project_actual
from comparison.methods import ORDERED, UNORDERED, CompareOutcome, compare_values, keyed
from comparison.reference_evidence import Evidence, compare_expression
from comparison.references import ReferenceDecision
from comparison.registry import rules
from comparison.resource import inactive_evidence, inline_owner
from comparison.result import identifier, setting_result, value_differences
from comparison.rows import validated_rows
from comparison.rules.iam import managed_policy_roles
from comparison.rules.kms import FormOutcome, compare_forms, kms_format
from comparison.runner import Settings
from comparison.values import PreparedValue
from design.catalog import DesignSchemaCatalog
from issues.aggregate import aggregate, comparison_status, iac_dataset, iac_summary
from issues.artifact import detail_payload
from issues.materials import naming_materials
from issues.publication import save_scan
from issues.review import review_snapshot
from model.references import declarations
from model.sources import ModelSnapshot, Scope
from support.comparison_cases import outcome_data, projected
from support.fixture_cases import load_case
from support.issues_scan_fixtures import (
    review_for,
    snapshot_artifact,
    stamp_naming_scan,
    task,
)
from support.model_reference_fixtures import reference as model_ref
from support.regression_cases import case_ids, expected_path
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.iac_values import (
    Expression,
    ResourceReference,
    safe_value,
    same,
    unordered_same,
)
from utils.reference_contracts import (
    IMPORT_PROPERTIES,
    REFERENCE_PROPERTIES,
    reference_attribute,
    row_contexts,
)
from utils.reference_contracts import (
    contract as receiving_contract,
)
from utils.source_reads import FileReads

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

ROOT = Path(__file__).resolve().parents[4]
VPC = "vpc-0123456789abcdef0"
KEY_ID = "12345678-1234-1234-1234-123456789012"
KEY_ARN = "arn:aws:kms:ap-northeast-1:123456789012:key/" + KEY_ID
ATHENA_KMS = "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey"
KMS_RECEIVERS = [
    ("Athena.WorkGroup", ATHENA_KMS),
    ("Lambda.Function", "KmsKeyArn"),
    ("Logs.LogGroup", "KmsKeyId"),
    (
        "S3.Bucket",
        "BucketEncryption.ServerSideEncryptionConfiguration[].ServerSideEncryptionByDefault.KMSMasterKeyID",
    ),
]


class MutableSnapshot(ModelSnapshot):
    """Synthetic builders edit dictionaries; production snapshots remain immutable."""

    def __post_init__(self):
        pass


def stack_input(comparison, unit):
    return ROOT / "infra/cloudformation/templates/team" / (
        unit["name"] + ".yaml"
    ), comparison.stack_inputs[unit["name"]]


def fixture():
    comparison = Comparison.__new__(Comparison)
    comparison.root, comparison.environment, comparison.directory = (
        ROOT,
        "fixture",
        "team",
    )
    comparison.target = {
        "iacEngine": "cloudformation",
        "awsAccountId": "123456789012",
        "awsRegion": "ap-northeast-1",
    }
    comparison.catalog = DesignSchemaCatalog(ROOT)
    comparison.local_comparison = comparison.reference_models_loaded = True
    comparison.models, comparison.resources, comparison.rows = {}, {}, {}
    comparison.symbols, comparison.reference_formats, comparison.model_references = (
        {},
        {},
        {},
    )
    comparison.exports, comparison.export_failures, comparison.export_provenance = (
        None,
        [],
        {},
    )
    comparison._index = None
    comparison.sensitive_values, comparison.inputs, comparison.model_observations = (
        set(),
        set(),
        set(),
    )
    comparison.read_hashes, comparison.model_reads = {}, FileReads()
    comparison.services, comparison.load_errors, comparison.warnings = [], [], []
    (
        comparison.reference_unavailable,
        comparison.results,
        comparison.display_differences,
    ) = {}, [], {}
    comparison.template_locations = {}
    pseudo = {
        "AWS::Partition": "aws",
        "AWS::Region": "ap-northeast-1",
        "AWS::AccountId": "123456789012",
    }
    comparison.stack_inputs = {
        name: ({"Resources": {}, "Outputs": {}}, {}, pseudo)
        for name in ("producer", "consumer")
    }
    comparison.templates = lambda: [
        (name, {"name": name, "template": name + ".yaml", "parameters": name + ".json"})
        for name in comparison.stack_inputs
    ]
    comparison.stack = partial(stack_input, comparison)
    return comparison


def resource(
    comparison,
    service,
    identity,
    kind,
    logical,
    rows,
    *,
    properties=None,
    stack="producer",
):
    metadata = {
        "resourceType": kind,
        "logicalId": kind.replace(".", "_") + "_" + identity,
        "anchor": logical.lower(),
        "cfn-logicalId": stack + "-" + logical,
        "resourceMode": "CREATE",
    }
    comparison.resources.setdefault(service, {})[identity] = metadata
    if service not in comparison.models:
        authority = {f"desired.service.{service}.serviceId": service}
        comparison.models[service] = MutableSnapshot(
            Scope(ROOT, "fixture", "team", service), authority, {}, {}, {}, {}, {}, ()
        )
    snapshot = comparison.models[service]
    counters = json.loads(
        snapshot.authoritative.get("desired.service.identity.lastAllocated", "{}")
    )
    counters[kind] = max(counters.get(kind, 0), int(identity))
    snapshot.authoritative["desired.service.identity.lastAllocated"] = json.dumps(
        counters
    )
    snapshot.authoritative.update(
        {f"desired.resource.{identity}.{key}": value for key, value in metadata.items()}
    )
    parsed = []
    for number, (prop, value, observed) in enumerate(rows, 1):
        rid = identity + "-" + f"{number:03}"
        row = {
            "property": kind + "." + prop,
            "value": "`"
            + (value if isinstance(value, str) else json.dumps(value))
            + "`",
        }
        parsed.append((rid, row))
        snapshot.authoritative.update(
            {f"desired.row.{rid}.{key}": value for key, value in row.items()}
        )
        if observed is not None:
            snapshot.authoritative[f"observed.row.{rid}.value"] = "`" + observed + "`"
    comparison.rows.setdefault(service, {})[identity] = parsed
    snapshot.values.update(snapshot.authoritative)
    comparison.stack_inputs[stack][0]["Resources"][logical] = {
        "Type": "AWS::" + kind.replace(".", "::"),
        "Properties": properties or {},
    }
    comparison._index = None
    return parsed


def vpc(comparison, identity="001", logical="Vpc", observed=VPC):
    return resource(
        comparison,
        "vpc",
        identity,
        "EC2.VPC",
        logical,
        [("VpcId", "PENDING_DEPLOY", observed)],
    )


def exported(comparison, expression, name="shared", stack="producer"):
    comparison.stack_inputs[stack][0]["Outputs"][name] = {
        "Value": expression,
        "Export": {"Name": name},
    }
    return comparison.evaluate("consumer", {"Fn::ImportValue": name})


def declaration(
    comparison,
    key,
    text,
    *,
    service="consumer",
    producer="vpc",
    logical="Vpc",
    kind="EC2.VPC",
    prop="EC2.VPC.VpcId",
    mode="identifier",
    pointer=None,
    occurrence="1",
    name="ref",
    target="team",
):
    matches = [
        item["logicalId"]
        for item in comparison.resources.get(producer, {}).values()
        if item["cfn-logicalId"].endswith("-" + logical)
    ]
    logical = matches[0] if len(matches) == 1 else logical
    spec = dict(
        consumerKey=key,
        text=text,
        occurrence=occurrence,
        producerKind="resource",
        producerScope="fixture/" + target + "/" + producer,
        producerLogicalId=logical,
        resourceType=kind,
        format=mode,
        property=prop,
        labelPolicy="none",
    )
    if pointer is not None:
        spec["pointer"] = pointer
    comparison.models[service].authoritative.update(
        {f"desired.reference.{name}.{field}": value for field, value in spec.items()}
    )


def consumer(comparison, value=VPC):
    return resource(
        comparison,
        "consumer",
        "010",
        "EC2.Subnet",
        "Consumer",
        [("VpcId", value, None)],
        properties={"VpcId": {"Fn::ImportValue": "shared"}},
        stack="consumer",
    )[0]


def policy_reference(comparison, left, right, path):
    return comparison.reference_decision(left, right, "IAM.Role", path)


def prepared(comparison, row):
    rid, value = row
    return comparison.prepare_value(
        "consumer",
        value,
        value["property"].rsplit(".", 1)[0],
        row_id=rid,
        stack="consumer",
    )


def _reference_decision_data(decision):
    TestCase().assertIs(type(decision), ReferenceDecision)
    if decision.equal is not None:
        TestCase().assertIs(type(decision.equal), bool)
    TestCase().assertIs(type(decision.diagnostics), tuple)
    return {
        "equal": decision.equal,
        "equivalent": decision.equivalent,
        "diagnostics": projected(decision.diagnostics),
        "comparisons": projected(decision.comparisons),
    }


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


@pytest.mark.parametrize("text", ['["a/","b/"]', "[]", '["a/",]'])
def test_array_member_string_remains_literal(text):
    comparison = fixture()
    kind = "GuardDuty.MalwareProtectionPlan"
    for field in (
        "Tags[].Value",
        "Tags[1].Value",
        "ProtectedResource.S3Bucket.BucketName",
        "ProtectedResource.S3Bucket.ObjectPrefixes[1]",
    ):
        value = comparison.prepare_value(
            "guardduty",
            {"property": kind + "." + field, "value": "`" + text + "`"},
            kind,
        )
        assert value.require_value() == text


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


@pytest.fixture(autouse=True)
def offline():
    with (
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
        patch(
            "comparison.inputs.load_model",
            side_effect=AssertionError("synthetic snapshots must be reused"),
        ),
    ):
        yield


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


def test_declared_scalar_and_no_reparsing_or_snapshot_reload():
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", VPC)
    with patch("comparison.model_reference.declarations", wraps=declarations) as parse:
        first = prepared(comparison, row).require_value()
        second = prepared(comparison, row).require_value()
        assert parse.call_count == 1
    assert isinstance(first, ResourceReference) and first == second
    actual = exported(comparison, {"Ref": "Vpc"})
    assert (
        comparison.reference_decision(first, actual, "EC2.Subnet", "VpcId").equal
        is True
    )
    assert (
        comparison.reference_decision(first, VPC, "EC2.Subnet", "VpcId").equal is None
    )
    assert (
        comparison.reference_decision(
            first, "vpc-different", "EC2.Subnet", "VpcId"
        ).equal
        is None
    )


def test_declared_name_checks_producer_model_and_return_attribute_mapping():
    comparison = fixture()
    resource(
        comparison,
        "repository",
        "001",
        "CodeCommit.Repository",
        "Repository",
        [("RepositoryName", "fixture-name", None)],
        properties={"RepositoryName": "fixture-name"},
    )
    row = consumer(comparison, "fixture-name")
    declaration(
        comparison,
        "desired.row.010-001.value",
        "fixture-name",
        producer="repository",
        logical="Repository",
        kind="CodeCommit.Repository",
        prop="CodeCommit.Repository.RepositoryName",
        mode="name",
    )
    desired = prepared(comparison, row).require_value()
    assert desired["$attribute"] == "Name"
    actual = exported(comparison, {"Fn::GetAtt": ["Repository", "Name"]})
    assert comparison.reference_decision(desired, actual, "IAM.Role", "").equal is True
    comparison.rows["repository"]["001"][0][1]["value"] = "`different-model-name`"
    assert comparison.reference_decision(desired, actual, "IAM.Role", "").equal is None
    assert (
        comparison.reference_decision(desired, "fixture-name", "IAM.Role", "").equal
        is None
    )


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


@pytest.mark.parametrize("case_id", case_ids("reference_evidence", prefix="negative-"))
def test_declared_reference_negative_cases(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_negative)


def _execute_negative(case):
    change = case["data"]["change"]
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    kwargs = {}
    if change == "type":
        kwargs["kind"] = "EC2.Subnet"
    if change == "cross-target":
        kwargs["target"] = "other-team"
    if change == "logical-id":
        kwargs["logical"] = "OldVpc"
    if change == "occurrence":
        kwargs["occurrence"] = "2"
    if change == "partial":
        kwargs["text"] = "vpc-"
    declaration(comparison, "desired.row.010-001.value", **({"text": VPC} | kwargs))
    if change == "duplicate":
        declaration(comparison, "desired.row.010-001.value", VPC, name="duplicate")
    selected = prepared(comparison, row)
    if change not in {"resource", "attribute", "partial"}:
        assert isinstance(selected.error, Blocked)
        return {"error": {"type": "Blocked", "message": str(selected.error)}}
    desired = selected.require_value()
    if change == "partial":
        actual = exported(comparison, {"Ref": "Vpc"})
    elif change == "resource":
        vpc(comparison, "002", "OtherVpc")
        actual = exported(comparison, {"Ref": "OtherVpc"})
    else:
        actual = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "Arn"})
    TestCase().assertIs(
        type(desired), ResourceReference if change != "partial" else Expression
    )
    decision = comparison.reference_decision(desired, actual, "EC2.Subnet", "VpcId")
    return {"decision": _reference_decision_data(decision)}


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


def test_same_producer_different_identifier_form_is_not_equated():
    comparison = fixture()
    resource(
        comparison,
        "repository",
        "001",
        "CodeCommit.Repository",
        "Repository",
        [("RepositoryName", "fixture-name", None)],
        properties={"RepositoryName": "fixture-name"},
    )
    row = consumer(comparison, "fixture-name")
    declaration(
        comparison,
        "desired.row.010-001.value",
        "fixture-name",
        producer="repository",
        logical="Repository",
        kind="CodeCommit.Repository",
        prop="CodeCommit.Repository.RepositoryName",
        mode="name",
    )
    desired = prepared(comparison, row).require_value()
    actual = exported(comparison, {"Ref": "Repository"})
    assert comparison.reference_decision(desired, actual, "IAM.Role", "").equal is None


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


def _execute_export_blocked(case):
    data = case["data"]
    comparison = fixture()
    vpc(comparison)
    if data["other"] is not None:
        comparison.stack_inputs["other"] = (data["other"], {}, {})
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    decision = comparison.reference_decision(
        KEY_ARN,
        exported(comparison, {"Fn::GetAtt": ["Key", "Arn"]}),
        case["data"]["kind"],
        case["data"]["path"],
    )
    TestCase().assertIs(decision.equal, False)
    TestCase().assertEqual(decision.diagnostics[0]["allowed_forms"], ["AliasArn"])
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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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


RECEIVERS = [
    ("s3", "S3.Bucket", "BucketName", "CloudTrail.Trail", "S3BucketName"),
    (
        "s3",
        "S3.Bucket",
        "BucketName",
        "CodePipeline.Pipeline",
        "ArtifactStore.Location",
    ),
    ("s3", "S3.Bucket", "BucketName", "Lambda.Function", "Code.S3Bucket"),
    (
        "cloudwatch-logs",
        "Logs.LogGroup",
        "LogGroupName",
        "CodeBuild.Project",
        "LogsConfig.CloudWatchLogs.GroupName",
    ),
    (
        "cloudwatch-logs",
        "Logs.LogGroup",
        "LogGroupName",
        "Lambda.Function",
        "LoggingConfig.LogGroup",
    ),
    ("cloudwatch-logs", "Logs.LogGroup", "LogGroupName", "EC2.FlowLog", "LogGroupName"),
    ("vpc", "EC2.VPC", "VpcId", "CodeBuild.Project", "VpcConfig.VpcId"),
    ("vpc", "EC2.VPC", "VpcId", "EC2.Subnet", "VpcId"),
    ("vpc", "EC2.VPC", "VpcId", "EC2.SecurityGroup", "VpcId"),
    ("vpc", "EC2.VPC", "VpcId", "EC2.RouteTable", "VpcId"),
    ("vpc", "EC2.VPC", "VpcId", "EC2.VPCEndpoint", "VpcId"),
    ("vpc", "EC2.VPC", "VpcId", "Route53.HostedZone", "VPCs[].VPCId"),
    ("vpc", "EC2.Subnet", "SubnetId", "EC2.Instance", "SubnetId"),
    ("vpc", "EC2.Subnet", "SubnetId", "CodeBuild.Project", "VpcConfig.Subnets[]"),
    ("vpc", "EC2.Subnet", "SubnetId", "Lambda.Function", "VpcConfig.SubnetIds[]"),
    ("vpc", "EC2.Subnet", "SubnetId", "EC2.VPCEndpoint", "SubnetIds[]"),
    (
        "vpc",
        "EC2.Subnet",
        "SubnetId",
        "Glue.Connection",
        "ConnectionInput.PhysicalConnectionRequirements.SubnetId",
    ),
    (
        "vpc",
        "EC2.Subnet",
        "SubnetId",
        "MWAA.Environment",
        "NetworkConfiguration.SubnetIds[]",
    ),
    ("vpc", "EC2.Subnet", "SubnetId", "QuickSight.VPCConnection", "SubnetIds[]"),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "CodeBuild.Project",
        "VpcConfig.SecurityGroupIds[]",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.Instance",
        "SecurityGroupIds[]",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.SecurityGroupIngress",
        "GroupId",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.SecurityGroupIngress",
        "SourceSecurityGroupId",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.SecurityGroupEgress",
        "GroupId",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.SecurityGroupEgress",
        "DestinationSecurityGroupId",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.SecurityGroup",
        "SecurityGroupEgress[].DestinationSecurityGroupId",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "EC2.VPCEndpoint",
        "SecurityGroupIds[]",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "Glue.Connection",
        "ConnectionInput.PhysicalConnectionRequirements.SecurityGroupIdList[]",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "Lambda.Function",
        "VpcConfig.SecurityGroupIds[]",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "MWAA.Environment",
        "NetworkConfiguration.SecurityGroupIds[]",
    ),
    (
        "security-group",
        "EC2.SecurityGroup",
        "GroupId",
        "QuickSight.VPCConnection",
        "SecurityGroupIds[]",
    ),
    (
        "vpc",
        "EC2.RouteTable",
        "RouteTableId",
        "EC2.SubnetRouteTableAssociation",
        "RouteTableId",
    ),
    ("vpc", "EC2.RouteTable", "RouteTableId", "EC2.VPCEndpoint", "RouteTableIds[]"),
    ("iam", "IAM.Role", "RoleName", "Glue.Job", "Role"),
    ("iam", "IAM.Role", "RoleName", "IAM.InstanceProfile", "Roles[]"),
    (
        "iam",
        "IAM.InstanceProfile",
        "InstanceProfileName",
        "EC2.Instance",
        "IamInstanceProfile",
    ),
    ("glue", "Glue.SecurityConfiguration", "Name", "Glue.Job", "SecurityConfiguration"),
    ("lambda", "Lambda.Function", "FunctionName", "Lambda.Permission", "FunctionName"),
    ("route53", "Route53.HostedZone", "Id", "Route53.RecordSet", "HostedZoneId"),
    (
        "secrets-manager",
        "SecretsManager.Secret",
        "Id",
        "SecretsManager.RotationSchedule",
        "SecretId",
    ),
    ("sqs", "SQS.Queue", "QueueUrl", "SQS.QueuePolicy", "Queues[]"),
    ("kms", "KMS.Alias", "AliasName", "CodeCommit.Repository", "KmsKeyId"),
    (
        "kms",
        "KMS.Alias",
        "AliasName",
        "EC2.Instance",
        "BlockDeviceMappings[].Ebs.KmsKeyId",
    ),
    ("kms", "KMS.Alias", "AliasName", "MWAA.Environment", "KmsKey"),
    ("kms", "KMS.Alias", "AliasName", "SecretsManager.Secret", "KmsKeyId"),
    ("kms", "KMS.Key", "KeyId", "KMS.Alias", "TargetKeyId"),
]


def setting(comparison, kind, prop, desired, actual, *, service="consumer"):
    """One setting, in-memory snapshots; never scan, lint or generate project files."""
    resource(
        comparison,
        service,
        "090",
        kind,
        "Receiver",
        [(prop, desired if isinstance(desired, str) else json.dumps(desired), None)],
        stack="producer",
    )
    document = comparison.stack_inputs["producer"][0]
    properties = {}
    put_row(properties, prop, actual)
    definition = document["Resources"]["Receiver"]
    definition["Properties"] = properties
    result = comparison.compare_rows(
        service,
        "090",
        comparison.resources[service]["090"],
        "producer",
        "Receiver",
        ROOT / "synthetic.yaml",
        definition,
        document,
    )
    assert result.failure is None, result.failure
    return result.records


@pytest.mark.parametrize("service,producer,attribute,kind,path", RECEIVERS)
def test_receiver_contracts(service, producer, attribute, kind, path):
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
    assert desired == ResourceReference(
        {"$resource": [service, "001"], "$attribute": attribute}
    )
    assert (
        comparison.reference_same(
            desired, comparison.evaluate("producer", {"Ref": "Producer"}), kind, path
        )
        is True
    )
    assert (
        comparison.reference_same(
            desired,
            ResourceReference(dict(desired, **{"$resource": [service, "002"]})),
            kind,
            path,
        )
        is False
    )
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
    "kind,ref_attribute,attribute,invalid",
    [
        ("Glue.Connection", "Name", "Name", "Arn"),
        ("SecretsManager.Secret", "Id", "Id", "Arn"),
        ("IAM.ManagedPolicy", "PolicyArn", "PolicyArn", "Arn"),
        ("CodeCommit.Repository", "RepositoryId", "Name", "Unknown"),
        ("QuickSight.VPCConnection", None, "Arn", "VPCConnectionId"),
    ],
)
def test_formal_return_attributes(kind, ref_attribute, attribute, invalid):
    comparison = fixture()
    resource(comparison, "producer", "001", kind, "Producer", [])
    symbol = comparison.evaluate("producer", {"Fn::GetAtt": ["Producer", attribute]})
    assert symbol["$attribute"] == attribute
    if ref_attribute:
        assert (
            comparison.evaluate("producer", {"Ref": "Producer"})["$attribute"]
            == ref_attribute
        )
    else:
        with pytest.raises(Blocked):
            comparison.evaluate("producer", {"Ref": "Producer"})
    with pytest.raises((Blocked, KeyError)):
        comparison.evaluate("producer", {"Fn::GetAtt": ["Producer", invalid]})


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
    "bad", [None, "Category", "Owner", "Provider", "Version", "target"]
)
def test_action_context_requires_own_codecommit_contract(bad):
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
        assert (
            comparison.desired_reference(
                "codecommit",
                link,
                "CodePipeline.Pipeline",
                path,
                context={"ActionTypeId": action},
            )["$attribute"]
            == "Name"
        )
    else:
        with pytest.raises(Blocked):
            comparison.desired_reference(
                "codecommit",
                link,
                "CodePipeline.Pipeline",
                path,
                context={"ActionTypeId": action},
            )
        if bad != "target":
            action.pop(bad)
            with pytest.raises(Blocked):
                comparison.desired_reference(
                    "codecommit",
                    link,
                    "CodePipeline.Pipeline",
                    path,
                    context={"ActionTypeId": action},
                )


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


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "other-stack",
        "attribute",
        "delimiter",
        "invalid",
        "missing",
        "index",
        "literal",
        "sub",
    ],
)
def test_symbolic_setting_classification(fault):
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
    assert records[0]["category"] == expected, records


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
    target.write_bytes(expected_path("reference_evidence", case_id).read_bytes())
    with pytest.raises(AssertionError, match="FILES DIFFER"):
        data_regression.check(result, fullpath=target)


def test_quicksight_executor_cannot_skip_comparison(data_regression, tmp_path):
    case_id = "quicksight-none"
    compare = Mock(return_value=[])
    with patch.dict(_execute_quicksight_principal.__globals__, {"setting": compare}):
        result = _execute_quicksight_principal(load_case("reference_evidence", case_id))
    compare.assert_called_once()
    target = tmp_path / "expected.yml"
    target.write_bytes(expected_path("reference_evidence", case_id).read_bytes())
    with pytest.raises(AssertionError, match="FILES DIFFER"):
        data_regression.check(result, fullpath=target)


@pytest.mark.parametrize(
    "prop,context,producer,expected",
    [
        ("ResourceId", {"ResourceType": "VPC"}, "Vpc", True),
        ("ResourceId", {}, "Vpc", False),
        ("ResourceId", {"ResourceType": "Subnet"}, "Vpc", False),
        ("ResourceId", {"ResourceType": "UNSET"}, "Vpc", False),
        ("ResourceId", {"ResourceType": "VPC"}, "Subnet", False),
    ],
)
def test_flowlog_resource_type_context(prop, context, producer, expected):
    comparison = fixture()
    resource(comparison, "vpc", "001", "EC2.VPC", "Vpc", [])
    resource(comparison, "vpc", "002", "EC2.Subnet", "Subnet", [])
    link = model_ref(
        "EC2_VPC_001" if producer == "Vpc" else "EC2_Subnet_002",
        "VpcId" if producer == "Vpc" else "SubnetId",
    )
    if expected:
        assert (
            comparison.desired_reference(
                "vpc", link, "EC2.FlowLog", prop, context=context
            )["$attribute"]
            == "VpcId"
        )
    else:
        with pytest.raises(Blocked):
            comparison.desired_reference(
                "vpc", link, "EC2.FlowLog", prop, context=context
            )


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


def _sg_reference_result(comparison):
    try:
        result = comparison.evaluate("producer", {"Ref": "Group"})
    except (Blocked, ValueError) as failure:
        return {"error": {"type": type(failure).__name__, "message": str(failure)}}
    TestCase().assertEqual(result["$attribute"], "GroupId")
    return {"attribute": result["$attribute"]}


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


@pytest.mark.parametrize(
    "field,context",
    [
        ("UnknownPolicyArns[]", {}),
        ("ManagedPolicyArns", {}),
        ("Description[]", {}),
        ("Tags[].Value", {}),
        ("ArnLikeNames[]", {}),
        ("Groups[]", {}),
        ("Environment.EnvironmentVariables[].Value", {}),
        ("ResourceRecords[]", {}),
    ],
)
def test_unknown_reference_property_never_infers_from_name(field, context):
    comparison = fixture()
    resource(comparison, "iam", "001", "IAM.ManagedPolicy", "Policy", [])
    kind = (
        "CodeBuild.Project"
        if field.startswith("Environment")
        else "Route53.RecordSet"
        if field.startswith("ResourceRecords")
        else "IAM.User"
        if field == "Groups[]"
        else "IAM.Role"
    )
    with pytest.raises(Blocked):
        comparison.desired_reference(
            "iam", "[policy](iam.md#policy)", kind, field, context=context
        )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-secret-")
)
def test_codebuild_secret_context(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_secret)


def _execute_codebuild_secret(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "secrets-manager",
        "001",
        "SecretsManager.Secret",
        "Secret",
        [],
        properties={"Name": "app/secret"},
    )
    link = model_ref("SecretsManager_Secret_001", "Id")
    try:
        symbol = comparison.desired_reference(
            "secrets-manager",
            link,
            "CodeBuild.Project",
            "Environment.EnvironmentVariables[].Value",
            context=data["context"],
        )
    except Blocked as failure:
        return {"error": {"type": type(failure).__name__, "message": str(failure)}}
    desired = {"Name": "SECRET", "Type": data["context"]["Type"], "Value": symbol}
    callback = partial(reference_for, comparison, "CodeBuild.Project")
    same_value = same(
        desired,
        dict(desired, Value="app/secret"),
        path="Environment.EnvironmentVariables[]",
        reference=callback,
    )
    suffix_value = same(
        desired,
        dict(desired, Value="app/secret:key:AWSPREVIOUS"),
        path="Environment.EnvironmentVariables[]",
        reference=callback,
    )
    TestCase().assertIs(same_value, True)
    TestCase().assertIs(suffix_value, False)
    return {"same": same_value, "suffix": suffix_value}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="policy-bijection-")
)
def test_policy_statement_bijection(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_policy_bijection)


def _execute_policy_bijection(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Key", "Key", [])
    left, right, path = data["left"], data["right"], data["path"]
    if data["reference_left"]:
        left[0]["Resource"] = comparison.evaluate(
            "producer", {"Fn::GetAtt": ["Key", "Arn"]}
        )
    declared = {path: ORDERED} if data["ordered"] else rules("IAM.Role")
    outcome = compare_values(
        left,
        right,
        path,
        rules=declared,
        whole=True,
        reference=partial(policy_reference, comparison),
    )
    if outcome.equal is not None:
        TestCase().assertIs(type(outcome.equal), bool)
    return {"equal": outcome.equal}


def reference_for(comparison, kind, left, right, path):
    return comparison.reference_same(left, right, kind, path)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="incomplete-codebuild-")
)
def test_incomplete_codebuild_missing_structure(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_incomplete_codebuild)


def _execute_incomplete_codebuild(case):
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    rows = [
        ("Environment.EnvironmentVariables[1].Name", "RELEASE_BUCKET_KMS_KEY_ID", None),
        ("Environment.EnvironmentVariables[1].Type", "PLAINTEXT", None),
        (
            "Environment.EnvironmentVariables[1].Value",
            model_ref("KMS_Alias_001", "Arn"),
            None,
        ),
    ]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        rows,
        properties=case["data"]["properties"],
    )
    document = comparison.stack_inputs["producer"][0]
    result = comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )
    check = TestCase()
    check.assertIsNone(result.failure)
    differences = [item for item in result.records if item["category"] == "difference"]
    unresolved = [item for item in result.records if item["category"] == "uncompared"]
    check.assertEqual(len(differences), 1)
    check.assertEqual(len(unresolved), 1)
    check.assertIn("PLAINTEXTではResource linkは禁止", unresolved[0]["reason"])
    check.assertFalse(
        any(item["category"] in {"error", "matched"} for item in result.records)
    )
    shown = json.dumps(result.display_differences)
    check.assertIn("RELEASE_BUCKET_KMS_KEY_ID", shown)
    check.assertIn("Environment", shown)
    return {
        "records": projected(result.records),
        "display": projected(result.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="nested-diagnostic-")
)
def test_nested_diagnostics_retain_format_and_failures(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_nested_diagnostic)


def _execute_nested_diagnostic(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Key", "Key", [])
    resource(
        comparison,
        "athena",
        "001",
        "Athena.WorkGroup",
        "WorkGroup",
        data["rows"],
        properties=data["properties"],
    )
    comparison.sensitive_values.add("private")
    document = comparison.stack_inputs["producer"][0]
    result = comparison.compare_rows(
        "athena",
        "001",
        comparison.resources["athena"]["001"],
        "producer",
        "WorkGroup",
        ROOT / "synthetic.yaml",
        document["Resources"]["WorkGroup"],
        document,
    ).records
    record = next(
        item
        for item in result
        if item["property"] == "Athena.WorkGroup.WorkGroupConfiguration"
    )
    check = TestCase()
    check.assertEqual(record["category"], "difference")
    diagnostic = record["reference_diagnostics"][0]
    check.assertEqual(diagnostic["path"], "Athena.WorkGroup." + ATHENA_KMS)
    check.assertEqual(diagnostic["identity"], "same")
    check.assertEqual(diagnostic["allowed_forms"], ["KeyArn"])
    check.assertEqual(diagnostic["model"]["$attribute"], "Arn")
    check.assertEqual(diagnostic["iac"]["$attribute"], "KeyId")
    if data["deferred"]:
        children = [
            child
            for child in result
            if child["property"]
            in {
                "Athena.WorkGroup.WorkGroupConfiguration#/ExecutionRole",
                "Athena.WorkGroup.WorkGroupConfiguration#/ResultConfiguration/ExpectedBucketOwner",
            }
        ]
        check.assertEqual(len(children), 2)
        check.assertEqual({child["category"] for child in children}, {"uncompared"})
        check.assertTrue(all(child["reason"] for child in children))
    check.assertNotIn("private", json.dumps(result))
    return {"records": projected(result)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="incomplete-setting-")
)
def test_incomplete_setting_presence_and_siblings(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_incomplete_setting)


def _execute_incomplete_setting(case):
    data = case["data"]
    comparison = fixture()
    comparison.stack_inputs["producer"][2]["AWS::NoValue"] = {"$noValue": True}
    comparison.stack_inputs["producer"][0]["Conditions"] = data["conditions"]
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        data["rows"],
        properties={"Environment": data["environment"]},
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
    check = TestCase()
    check.assertIsNone(batch.failure)
    check.assertFalse(
        any(item["category"] in {"matched", "error"} for item in batch.records)
    )
    children = [
        item for item in batch.records if item["property"].endswith("[1].Value")
    ]
    check.assertEqual(len(children), 1)
    check.assertEqual(children[0]["category"], "uncompared")
    check.assertIn("PLAINTEXTではResource linkは禁止", children[0]["reason"])
    check.assertEqual(children[0]["iac"]["path"], "synthetic.yaml")
    return {
        "records": projected(batch.records),
        "display": projected(batch.display_differences),
    }


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="children-failed-")
)
def test_all_children_failed_preserve_parent_and_categories(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_children_failed)


def _execute_children_failed(case):
    data = case["data"]
    comparison = fixture()
    rows = [
        ("Environment.Image", model_ref("KMS_Key_999", "Arn"), None),
        ("Environment.PrivilegedMode", "invalid-json", None),
    ]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        rows,
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
        sorted(item["category"] for item in batch.records),
        ["error", "uncompared"]
        if data["present"]
        else ["difference", "error", "uncompared"],
    )
    if not data["present"]:
        parent = next(
            item for item in batch.records if item["category"] == "difference"
        )
        TestCase().assertEqual(parent["property"], "CodeBuild.Project.Environment")
        TestCase().assertEqual(parent["reason"], "property missing")
        TestCase().assertEqual(
            {
                item["category"]
                for item in batch.records
                if item["property"] != parent["property"]
            },
            {"error", "uncompared"},
        )
    return {"records": projected(batch.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="incomplete-json-")
)
def test_incomplete_json_preserves_declared_children(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_incomplete_json)


def _execute_incomplete_json(case):
    data = case["data"]
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Alias", "Alias", [])
    rows = resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("Environment", json.dumps(data["desired"]), None)],
        properties={"Environment": data["actual"]},
    )
    if data["document_row"]:
        rows[0][1]["document"] = json.dumps(data["desired"])
    prepared_value = comparison.prepare_value(
        "codebuild", rows[0][1], "CodeBuild.Project", stack="producer", row_id="001-001"
    )
    with pytest.raises(Blocked, match="PLAINTEXTではResource linkは禁止"):
        prepared_value.require_value()
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
    unresolved = next(
        item for item in batch.records if item["category"] == "uncompared"
    )
    TestCase().assertTrue(
        unresolved["property"].endswith("EnvironmentVariables[].Value")
    )
    TestCase().assertEqual(
        unresolved["model"]["pointer"], "/EnvironmentVariables/0/Value"
    )
    TestCase().assertIn("PLAINTEXTではResource linkは禁止", unresolved["reason"])
    return {"records": projected(batch.records)}


def fail_image_preparation(error, original, service, row, kind, **kwargs):
    if row["property"].endswith(".Image"):
        raise error("synthetic preparation failure")
    return original(service, row, kind, **kwargs)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="preparation-error-")
)
def test_preparation_error_retains_confirmed_difference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_preparation_error)


def _execute_preparation_error(case):
    error = {
        "ValueError": ValueError,
        "TypeError": TypeError,
        "OSError": OSError,
        "ImportError": ImportError,
        "IndexError": IndexError,
    }[case["data"]["error_type"]]
    comparison = fixture()
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [
            ("Environment.Image", "image", None),
            ("Environment.Type", "LINUX_CONTAINER", None),
        ],
        properties={"Environment": {}},
    )
    comparison.prepare_value = partial(
        fail_image_preparation, error, comparison.prepare_value
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
    check = TestCase()
    check.assertIsNone(batch.failure)
    check.assertEqual(
        sorted(item["category"] for item in batch.records), ["difference", "error"]
    )
    check.assertTrue(
        any(item["reason"] == "synthetic preparation failure" for item in batch.records)
    )
    return {"records": projected(batch.records)}


def test_naming_materials_mode_and_root_targets():
    comparison = fixture()
    comparison.services = ["vpc", "codebuild", "codepipeline", "glue", "kms"]
    for identity, mode, rows in [
        ("001", "CREATE", []),
        ("002", "IMPORT", []),
        ("003", "CREATE", [("Name", "bad_pattern_value", None)]),
    ]:
        parsed = resource(
            comparison, "vpc", identity, "EC2.VPC", "Vpc" + identity, rows
        )
        comparison.resources["vpc"][identity]["resourceMode"] = mode
        for _, row in parsed:
            row["comment"] = "component evidence unconfirmed"
    specs = [
        (
            "codebuild",
            "CodeBuild.Project",
            ["Environment.EnvironmentVariables[].Name", "Artifacts.Name"],
        ),
        (
            "codepipeline",
            "CodePipeline.Pipeline",
            ["Stages[].Name", "Stages[].Actions[].Name"],
        ),
        ("glue", "Glue.Job", ["Command.Name"]),
    ]
    for service, kind, nested in specs:
        rows = resource(
            comparison,
            service,
            "001",
            kind,
            service.title(),
            [
                ("Name", "invalid_root_name", None),
                *[(prop, "nested", None) for prop in nested],
            ],
        )
        for _, row in rows:
            row["comment"] = "fixture name"
    alias_rows = resource(
        comparison,
        "kms",
        "001",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/HumanActual", None)],
    )
    comparison.resources["kms"]["001"]["resourceMode"] = "IMPORT"
    alias_rows[0][1]["comment"] = "human exception"
    material, _ = naming_materials(comparison)
    names = material["names"]
    assert next(
        item for item in names if item["service"] == "vpc" and item["resource"] == "001"
    )["required_missing"]
    assert not next(
        item for item in names if item["service"] == "vpc" and item["resource"] == "002"
    )["required_missing"]
    selected = next(
        item for item in names if item["service"] == "vpc" and item["resource"] == "003"
    )
    assert (
        selected["pattern_review"] == "Scan mandatory-constraint decision"
        and selected["value"] == "`bad_pattern_value`"
    )
    assert "未確認componentを名前から推測せず" in material["review_policy"]
    assert "その不足だけでIssueや未検証にしない" in material["review_policy"]
    alias = next(item for item in names if item["service"] == "kms")
    assert (
        alias["resourceMode"] == "IMPORT"
        and alias["value"] == "`alias/HumanActual`"
        and not alias["required_missing"]
    )
    assert {
        (item["service"], item["property"])
        for item in names
        if item["service"] not in {"vpc", "kms"}
    } == {("codebuild", "Name"), ("codepipeline", "Name"), ("glue", "Name")}


@pytest.mark.parametrize(
    ("value", "violation", "expected", "actual"),
    [
        ("vpc-app-dev", None, None, None),
        ("UNSET", None, None, None),
        ("wrong-app-dev", "format", None, None),
        ("vpc-app", "format", None, None),
        ("vpc-app-stg", "confirmed_mismatch", "dev", "stg"),
        (None, "required_missing", None, None),
    ],
)
def test_naming_materials_review_save(tmp_path, value, violation, expected, actual):
    comparison = fixture()
    comparison.services = ["vpc"]
    comparison.target["environment"] = "dev"
    rows = resource(
        comparison,
        "vpc",
        "001",
        "EC2.VPC",
        "Vpc",
        [] if value is None else [("Name", value, None)],
    )
    for _, row in rows:
        row["comment"] = ""
    material, judgments = naming_materials(comparison)
    data = snapshot_artifact(tmp_path, services=["vpc"])
    data["naming_context"] = {
        key: val for key, val in material.items() if key != "names"
    }
    data["naming"]["names"] = material["names"]
    stamp_naming_scan(data)
    data["judgments"] = judgments
    item = next(item for item in data["naming"]["names"] if item["property"] == "Name")
    review = review_for(data)
    pattern = "vpc-{{application}}-{{environment}}"
    issue = dict(
        service="vpc",
        resource="001",
        property="Name",
        rule="review.naming",
        naming_item_id=item["id"],
        applied_rule=pattern,
        violation=violation or "format",
        evidence="Reviewed the recorded name and rule",
        message="Naming finding",
    )
    if expected:
        issue.update(expected=expected, actual=actual)
    if violation:
        review["issues"] = [issue]
    with task(tmp_path, ["vpc"]):
        _, snapshot, _ = save_scan(tmp_path, data, review)
    result = json.loads(snapshot.data)
    assert len(result["ordinary"]) == bool(violation)
    assert result["unverified"] == []
    for invalid in (
        dict(issue, applied_rule="not-a-rule"),
        dict(issue, rule="naming"),
        dict(issue, resource="002"),
        dict(issue, property="Other"),
    ):
        review["issues"] = [invalid]
        with pytest.raises(ValueError):
            save_scan(tmp_path, data, review)
    if not violation:
        review["issues"] = [issue]
        with pytest.raises(ValueError, match="format"):
            save_scan(tmp_path, data, review)
        review["issues"] = [
            dict(
                service="vpc",
                resource="001",
                property="Name",
                rule="naming",
                message="Unknown component",
            )
        ]
        with pytest.raises(ValueError, match="naming_item_id"):
            save_scan(tmp_path, data, review)
        review["unverified"] = [
            dict(
                service="vpc",
                check="naming",
                reason="Unknown component",
                failure_kind="read_failure",
            )
        ]
        review["issues"] = []
        with pytest.raises(ValueError, match="recorded scan failure"):
            save_scan(tmp_path, data, review)
    if violation == "confirmed_mismatch":
        for invalid in (
            dict(issue, expected="unknown"),
            dict(issue, actual="invented"),
        ):
            review["issues"] = [invalid]
            with pytest.raises(ValueError, match="mismatch"):
                save_scan(tmp_path, data, review)


def test_naming_import_provider_constraint_from_materials(tmp_path):
    comparison = fixture()
    comparison.services = ["kms"]
    rows = resource(
        comparison,
        "kms",
        "001",
        "KMS.Alias",
        "Alias",
        [("AliasName", "invalid alias", None)],
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
        item for item in data["naming"]["names"] if item["property"] == "AliasName"
    )
    assert item["provider_errors"]
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
    assert len(json.loads(snapshot.data)["ordinary"]) == 1
    review["issues"][0].update(
        violation="format",
        applied_rule="alias/{{application}}-{{environment}}-{{purpose}}[-{{suffix}}]",
    )
    with pytest.raises(ValueError, match="IMPORT"):
        save_scan(tmp_path, data, review)


def test_naming_missing_rule_from_materials(tmp_path):
    comparison = fixture()
    comparison.services = ["cdn"]
    rows = resource(
        comparison,
        "cdn",
        "001",
        "CloudFront.CachePolicy",
        "Policy",
        [("CachePolicyConfig.Name", "test-name", None)],
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
        item
        for item in data["naming"]["names"]
        if item["property"] == "CachePolicyConfig.Name"
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
    assert len(json.loads(snapshot.data)["ordinary"]) == 1


def test_naming_input_unavailable_from_materials(tmp_path):
    comparison = fixture()
    comparison.services = ["vpc"]
    comparison.reference_unavailable["vpc"] = "unresolved reference"
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
    assert (
        json.loads(review_snapshot(data, review).data)["unverified"]
        == review["unverified"]
    )


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


def test_grouped_parent_reference():
    comparison = fixture()
    resource(comparison, "kms", "001", "KMS.Key", "Key", [])
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/fixture", None)],
        properties={"AliasName": "alias/fixture", "TargetKeyId": {"Ref": "Key"}},
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
    assert any(
        item["property"] == "KMS.Alias.TargetKeyId" and item["category"] == "matched"
        for item in result
    ), result


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
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
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


QUEUE_ARN = "arn:aws:sqs:ap-northeast-1:123456789012:fixture-dlq"
RULE_ARN = "arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule"


def sqs_policy_fixture():
    comparison = fixture()
    resource(
        comparison,
        "sqs",
        "001",
        "SQS.Queue",
        "Queue",
        [("QueueName", "fixture-dlq", None)],
        properties={"QueueName": "fixture-dlq"},
    )
    resource(
        comparison,
        "eventbridge",
        "001",
        "Events.Rule",
        "Rule",
        [("Name", "fixture-rule", None)],
        properties={"Name": "fixture-rule", "EventBusName": "default"},
    )
    desired = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "events.amazonaws.com"},
                "Action": "sqs:SendMessage",
                "Resource": QUEUE_ARN,
                "Condition": {"ArnEquals": {"aws:SourceArn": RULE_ARN}},
            }
        ],
    }
    actual = copy.deepcopy(desired)
    actual["Statement"][0]["Resource"] = {"Fn::GetAtt": ["Queue", "Arn"]}
    actual["Statement"][0]["Condition"]["ArnEquals"]["aws:SourceArn"] = {
        "Fn::GetAtt": ["Rule", "Arn"]
    }
    return comparison, desired, actual


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


def _execute_sqs_context(case):
    data = case["data"]
    comparison, desired, actual = sqs_policy_fixture()
    pseudo = comparison.stack_inputs["producer"][2]
    if data["value"] is None:
        pseudo.pop("AWS::" + data["field"])
    else:
        pseudo["AWS::" + data["field"]] = data["value"]
    reference = comparison.evaluate("producer", {"Fn::GetAtt": ["Queue", "Arn"]})
    decision = comparison.reference_decision(
        QUEUE_ARN, reference, "SQS.QueuePolicy", "PolicyDocument.Statement[].Resource"
    )
    TestCase().assertIsNone(decision.equal)
    TestCase().assertEqual(decision.diagnostics[0]["local_comparison"], "uncompared")
    TestCase().assertIn(data["field"], decision.diagnostics[0]["reason"])
    records = setting(comparison, "SQS.QueuePolicy", "PolicyDocument", desired, actual)
    TestCase().assertEqual([record["category"] for record in records], ["uncompared"])
    return {
        "decision": _reference_decision_data(decision),
        "records": projected(records),
    }


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


@pytest.mark.parametrize("operation", ["Arn", "Sub", "Join", "SplitSelect"])
def test_replacement_and_old_observed_cannot_prove_physical_identity(operation):
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
        assert decision.equal is None and not decision.equivalent
        assert decision.diagnostics[0]["evidence_type"] == "recorded_observed"
        assert "cannot prove" in decision.diagnostics[0]["reason"]
    assert (
        comparison.reference_decision(
            value, copy.deepcopy(value), "IAM.Role", "Policies"
        ).equal
        is True
    )
    other = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "VpcId"})
    assert (
        comparison.reference_decision(symbol, other, "IAM.Role", "Policies").equal
        is not True
    )
    vpc(comparison, "002", "OtherVpc")
    different = ResourceReference({"$resource": ["vpc", "002"], "$attribute": "Arn"})
    assert (
        comparison.reference_decision(symbol, different, "IAM.Role", "Policies").equal
        is False
    )


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
    "producer,kind,prop,text,full,expression,properties",
    [
        (
            "s3",
            "S3.Bucket",
            "BucketName",
            "fixture-bucket",
            "arn:aws:s3:::fixture-bucket/*",
            {
                "Fn::Sub": [
                    "${BucketArn}/*",
                    {"BucketArn": {"Fn::GetAtt": ["Producer", "Arn"]}},
                ]
            },
            {"BucketName": "fixture-bucket"},
        ),
        (
            "kms",
            "KMS.Key",
            "KeyId",
            KEY_ID,
            KEY_ARN,
            {"Fn::GetAtt": ["Producer", "Arn"]},
            {},
        ),
    ],
)
def test_declared_arn_fragment_reproduction(
    producer, kind, prop, text, full, expression, properties
):
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
        properties=properties,
    )
    row = consumer(comparison, full)
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
    assert isinstance(desired, Expression) and desired.operation == "Join"
    actual = exported(comparison, expression)
    decision = comparison.reference_decision(desired, actual, "IAM.Role", "Policies")
    assert decision.equal is True and decision.equivalent
    detail = decision.diagnostics[-1]
    assert (
        detail["evidence_type"] == "logical_reference"
        and detail["current_aws_verified"] is False
    )
    assert detail["producers"] and all(
        item["producer"] == producer + "/001" for item in detail["producers"]
    )
    assert detail["exports"] == [{"export_name": "shared", "export_stack": "producer"}]


def fragment_fixture(kind="KMS.Key", value=None):
    comparison = fixture()
    service, prop, text = (
        ("kms", "KeyId", KEY_ID)
        if kind == "KMS.Key"
        else ("s3", "BucketName", "fixture-bucket")
    )
    full = KEY_ARN if kind == "KMS.Key" else "arn:aws:s3:::fixture-bucket/*"
    resource(
        comparison,
        service,
        "001",
        kind,
        "Producer",
        [
            (
                prop,
                "PENDING_DEPLOY" if service == "kms" else text,
                text if service == "kms" else None,
            )
        ],
        properties={} if service == "kms" else {prop: text},
    )
    row = consumer(comparison, full if value is None else value)
    declaration(
        comparison,
        "desired.row.010-001.value",
        text,
        producer=service,
        logical="Producer",
        kind=kind,
        prop=kind + "." + prop,
        mode="identifier" if service == "kms" else "name",
    )
    return comparison, row


def fragment_actual(comparison, kind="KMS.Key", logical="Producer"):
    arn = {"Fn::GetAtt": [logical, "Arn"]}
    return exported(
        comparison, arn if kind == "KMS.Key" else {"Fn::Join": ["", [arn, "/*"]]}
    )


def test_fragment_nested_sub_import_export_contract_and_unchanged_model():
    comparison, row = fragment_fixture("S3.Bucket")
    comparison.stack_inputs["consumer"][0]["Parameters"] = {
        "Suffix": {"Type": "String"}
    }
    comparison.stack_inputs["consumer"][1]["Suffix"] = "One"
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
    assert reference.saved_literal == "fixture-bucket"
    assert reference.saved_property == "S3.Bucket.BucketName"
    for left, right in [(desired, actual), (actual, desired)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        assert decision.equal is True and decision.equivalent
        detail = decision.diagnostics[0]
        assert detail["evidence_type"] == "logical_reference"
        assert detail["declarations"] == [
            {"producer": "s3/001", "property": "S3.Bucket.BucketName"}
        ]
        assert detail["exports"] == [
            {"export_name": "QuarantineBucketArnOne", "export_stack": "producer"}
        ]
        assert detail["current_aws_verified"] is False
    assert before == {
        service: snapshot.authoritative
        for service, snapshot in comparison.models.items()
    }


@pytest.mark.parametrize(
    "kind,fault",
    [
        (kind, fault)
        for kind in ["S3.Bucket", "KMS.Key"]
        for fault in [
            "partition",
            "prefix",
            "suffix",
            "same-length-suffix",
            "region",
            "account",
        ]
        if kind != "S3.Bucket" or fault not in {"region", "account"}
    ],
)
def test_fragment_arn_fixed_parts_are_differences(kind, fault):
    full = KEY_ARN if kind == "KMS.Key" else "arn:aws:s3:::fixture-bucket/*"
    replacements = {
        "partition": ("arn:aws:", "arn:aws-cn:"),
        "prefix": ("arn:", "xrn:"),
        "suffix": ("", "/extra"),
        "same-length-suffix": ("key/", "kez/") if kind == "KMS.Key" else ("/*", "/?"),
        "region": ("ap-northeast-1", "us-east-1"),
        "account": ("123456789012:key", "999999999999:key"),
    }
    source, target = replacements[fault]
    full = full + target if fault == "suffix" else full.replace(source, target, 1)
    comparison, row = fragment_fixture(kind, full)
    desired = prepared(comparison, row).require_value()
    actual = fragment_actual(comparison, kind)
    for left, right in [(desired, actual), (actual, desired)]:
        decision = comparison.reference_decision(left, right, "IAM.Role", "Policies")
        assert decision.equal is False and not decision.equivalent, decision
        assert decision.diagnostics[0]["current_aws_verified"] is False


@pytest.mark.parametrize(
    "text,occurrence,value,expected",
    [
        (
            "fixture-bucket",
            "1",
            "pre/fixture-bucket/post",
            ["pre/", "fixture-bucket", "/post"],
        ),
        (
            "fixture-bucket",
            "2",
            "fixture-bucket/fixture-bucket",
            ["fixture-bucket/", "fixture-bucket"],
        ),
        ("`fixture-bucket`", "1", "fixture-bucket", ["fixture-bucket"]),
        ("fixture-bucket", "1", "`fixture-bucket`", ["`", "fixture-bucket", "`"]),
    ],
)
def test_fragment_scalar_backtick_coordinates(text, occurrence, value, expected):
    comparison, row = fragment_fixture("S3.Bucket", value)
    authority = comparison.models["consumer"].authoritative
    authority["desired.reference.ref.text"] = text
    authority["desired.reference.ref.occurrence"] = occurrence
    desired = prepared(comparison, row).require_value()
    parts = desired.operands[1] if isinstance(desired, Expression) else [desired]
    assert [
        part.saved_literal if isinstance(part, ResourceReference) else part
        for part in parts
    ] == expected
    actual_parts = [
        comparison.evaluate("producer", {"Ref": "Producer"})
        if isinstance(part, ResourceReference)
        else part
        for part in parts
    ]
    decision = comparison.reference_decision(
        desired, Expression("Join", ["", actual_parts]), "IAM.Role", "Policies"
    )
    assert decision.equal is True


def test_fragment_json_pointer_and_multiple_nonoverlapping_declarations():
    comparison, row = fragment_fixture("S3.Bucket")
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    body = {
        "a/b~c": [{"Resource": "arn:aws:s3:::fixture-bucket/*|" + KEY_ARN}],
        "sibling": KEY_ID,
    }
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
    assert [
        part.saved_literal
        for part in leaf.operands[1]
        if isinstance(part, ResourceReference)
    ] == ["fixture-bucket", KEY_ID]
    assert desired["sibling"] == KEY_ID
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
    assert decision.equal is True and decision.equivalent
    assert {item["producer"] for item in decision.diagnostics[0]["declarations"]} == {
        "s3/001",
        "kms/002",
    }
    comparison.models["kms"].authoritative["observed.row.002-001.value"] = (
        "`PENDING_DEPLOY`"
    )
    decision = comparison.reference_decision(leaf, actual, "IAM.Role", "Policies")
    assert decision.equal is None and not decision.equivalent
    assert "identifier_unobserved" in decision.diagnostics[0]["reason"]


@pytest.mark.parametrize(
    "fault",
    [
        "overlap",
        "duplicate",
        "occurrence",
        "cross-target",
        "unknown",
        "ambiguous",
        "type",
        "property",
    ],
)
def test_fragment_invalid_declarations_fail_closed(fault):
    comparison, row = fragment_fixture("S3.Bucket")
    authority = comparison.models["consumer"].authoritative
    if fault in {"overlap", "duplicate"}:
        declaration(
            comparison,
            "desired.row.010-001.value",
            "bucket" if fault == "overlap" else "fixture-bucket",
            producer="s3",
            logical="Producer",
            kind="S3.Bucket",
            prop="S3.Bucket.BucketName",
            mode="name",
            name="other",
        )
    elif fault == "ambiguous":
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
    else:
        field, value = {
            "occurrence": ("occurrence", "2"),
            "cross-target": ("producerScope", "fixture/other/s3"),
            "unknown": ("producerLogicalId", "S3_Bucket_999"),
            "type": ("resourceType", "KMS.Key"),
            "property": ("property", "KMS.Key.KeyId"),
        }[fault]
        authority["desired.reference.ref." + field] = value
    assert isinstance(prepared(comparison, row).error, Blocked)


@pytest.mark.parametrize("kind", ["S3.Bucket", "KMS.Key"])
@pytest.mark.parametrize(
    "fault",
    [
        "different-producer",
        "missing-correspondence",
        "wrong-type",
        "import-mode",
        "literal",
        "unknown-attribute",
        "no-arn-contract",
    ],
)
def test_fragment_producer_and_attribute_evidence_cannot_be_replaced_by_values(
    kind, fault
):
    comparison, row = fragment_fixture(kind)
    desired = prepared(comparison, row).require_value()
    service = "kms" if kind == "KMS.Key" else "s3"
    if fault == "different-producer":
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
        actual = fragment_actual(comparison, kind, "Other")
    elif fault == "literal":
        actual = KEY_ARN if service == "kms" else "arn:aws:s3:::fixture-bucket/*"
    elif fault == "unknown-attribute":
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
        actual = fragment_actual(comparison, kind)
        if fault == "missing-correspondence":
            comparison.stack_inputs["producer"][0]["Resources"].pop("Producer")
            comparison.symbols.clear()
        elif fault == "wrong-type":
            comparison.stack_inputs["producer"][0]["Resources"]["Producer"]["Type"] = (
                "AWS::EC2::VPC"
            )
            comparison.symbols.clear()
        elif fault == "import-mode":
            comparison.resources[service]["001"]["resourceMode"] = "IMPORT"
    if fault == "no-arn-contract":
        with patch.dict("comparison.reference_evidence.ARN_SHAPES", clear=True):
            decision = comparison.reference_decision(
                desired, actual, "IAM.Role", "Policies"
            )
    else:
        decision = comparison.reference_decision(
            desired, actual, "IAM.Role", "Policies"
        )
    assert decision.equal is (False if fault == "different-producer" else None), (
        decision
    )
    assert not decision.equivalent


@pytest.mark.parametrize(
    "observed",
    [None, "", "PENDING_DEPLOY", "UNSET", "TODO", "TBD", "未確定", "other-key"],
)
def test_fragment_all_observed_uncertainties_remain_uncompared(observed):
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
    assert decision.equal is None and not decision.equivalent
    assert decision.diagnostics[0]["current_aws_verified"] is False


@pytest.mark.parametrize("fault", ["missing", "duplicate", "scope", "literal-export"])
def test_fragment_import_export_requires_proven_origin(fault):
    comparison, row = fragment_fixture()
    desired = prepared(comparison, row).require_value()
    if fault == "literal-export":
        actual = exported(comparison, KEY_ARN)
        assert (
            comparison.reference_decision(desired, actual, "IAM.Role", "Policies").equal
            is None
        )
        return
    exported(comparison, {"Fn::GetAtt": ["Producer", "Arn"]})
    comparison.exports = None
    if fault == "missing":
        comparison.stack_inputs["producer"][0]["Outputs"].clear()
    elif fault == "duplicate":
        comparison.stack_inputs["consumer"][0]["Outputs"]["other"] = {
            "Value": {"Ref": "Consumer"},
            "Export": {"Name": "shared"},
        }
    else:
        document, parameters, pseudo = comparison.stack_inputs["producer"]
        comparison.stack_inputs["producer"] = (
            document,
            parameters,
            dict(pseudo, **{"AWS::AccountId": "999999999999"}),
        )
    with pytest.raises(Blocked):
        comparison.evaluate("consumer", {"Fn::ImportValue": "shared"})


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


def test_fragment_undeclared_identifier_and_replacement_stay_uncompared():
    comparison, row = fragment_fixture()
    comparison.stack_inputs["producer"][0]["Resources"]["Producer"]["Properties"][
        "Description"
    ] = "changed-next-deploy"
    desired = prepared(comparison, row).require_value()
    actual = fragment_actual(comparison)
    # Logical expression identity is proven; physical/current identity is never asserted.
    decision = comparison.reference_decision(desired, actual, "IAM.Role", "Policies")
    assert (
        decision.equal is True
        and decision.diagnostics[0]["current_aws_verified"] is False
    )
    assert (
        comparison.reference_decision(KEY_ARN, actual, "IAM.Role", "Policies").equal
        is None
    )
    undeclared = Expression(
        "Join", ["", ["arn:aws:kms:ap-northeast-1:123456789012:key/", KEY_ID]]
    )
    assert (
        comparison.reference_decision(undeclared, actual, "IAM.Role", "Policies").equal
        is None
    )


@pytest.mark.parametrize(
    "observed,phase",
    [
        (None, "unobserved"),
        ("PENDING_DEPLOY", "pending_deploy"),
        (VPC, "awaiting_handoff"),
    ],
)
@pytest.mark.parametrize(
    "shape", ["link", "json-link", "model-ref", "intrinsic-link", "intrinsic-model-ref"]
)
def test_import_wait_propagates_without_parent_issue(observed, phase, shape):
    comparison = fixture()
    vpc(comparison, observed=observed)
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    comparison.models["vpc"].authoritative["desired.resource.001.resourceMode"] = (
        "IMPORT"
    )
    comparison.models["vpc"].values["desired.resource.001.resourceMode"] = "IMPORT"
    link = model_ref("EC2_VPC_001", "VpcId")
    value = (
        link
        if shape in {"link", "json-link", "intrinsic-link"}
        else {"$modelRef": {"logicalId": "EC2_VPC_001", "attribute": "VpcId"}}
    )
    if shape.startswith("intrinsic"):
        value = {"Fn::Join": ["", [value]]}
    desired = (
        link
        if shape == "link"
        else json.dumps({"VpcId": value, "Subnets": ["subnet-fixed"]})
    )
    kind, prop, actual = (
        ("EC2.Subnet", "VpcId", "vpc-external")
        if shape == "link"
        else (
            "CodeBuild.Project",
            "VpcConfig",
            {"VpcId": "vpc-external", "Subnets": ["subnet-fixed"]},
        )
    )
    resource(
        comparison,
        "consumer",
        "001",
        kind,
        "Receiver",
        [(prop, desired, None)],
        properties={prop: actual},
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
    assert batch.failure is None and len(batch.records) == 1, batch.records
    (item,) = batch.records
    assert item["category"] == ("excluded" if phase == "pending_deploy" else "deferred")
    assert item["cause"]["phase"] == phase
    assert item["cause"]["producer"] == dict(
        service="vpc", resource="001", resourceType="EC2.VPC", attribute="VpcId"
    )
    data = aggregate(batch.records, "fixture", "team", ["consumer"])
    assert (
        data["overview"]["issue_count"] == 0
        and data["record_meta"][0]["issue_id"] is None
    )
    assert comparison_status(data["overview"]["records"]) == (
        "no compared records" if phase == "pending_deploy" else "partial"
    )
    assert data["overview"]["pending_deploy_excluded"] == (
        1 if phase == "pending_deploy" else 0
    )


@pytest.mark.parametrize(
    "fault,observed",
    [
        (fault, observed)
        for fault in ("missing", "ambiguous", "type", "attribute", "consumer")
        for observed in (VPC, "PENDING_DEPLOY")
    ]
    + [
        (value, value)
        for value in ("", "UNSET", "TODO", "TBD", "invalid/vpc", "${unresolved}")
    ],
)
def test_import_invalid_contract_or_identifier_stays_an_issue(fault, observed):
    comparison = fixture()
    vpc(comparison, observed=observed)
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    link, prop = model_ref("EC2_VPC_001", "VpcId"), "EC2.Subnet.VpcId"
    if fault == "missing":
        link = model_ref("EC2_VPC_999", "VpcId")
    elif fault == "ambiguous":
        resource(comparison, "duplicate", "001", "EC2.VPC", "Duplicate", [])
    elif fault == "type":
        prop = "EC2.Instance.SubnetId"
    elif fault == "consumer":
        prop = "CodeBuild.Project.Name"
    elif fault == "attribute":
        link = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "Arn"})
    kind, path = ".".join(prop.split(".")[:2]), ".".join(prop.split(".")[2:])
    with pytest.raises((Blocked, KeyError)) as failure:
        comparison.desired_reference("consumer", link, kind, path)
    assert failure_category(failure.value) == "uncompared"
    item = comparison.make_record(
        failure_category(failure.value), "consumer", "001", prop, str(failure.value)
    )
    assert (
        aggregate([item], "fixture", "team", ["consumer"])["overview"]["issue_count"]
        == 1
    )


@pytest.mark.parametrize("observed", [None, "PENDING_DEPLOY"])
@pytest.mark.parametrize("shape", ["json-link", "model-ref", "intrinsic", "array"])
def test_import_wait_preserves_known_json_difference(shape, observed):
    comparison = fixture()
    vpc(comparison, observed=observed)
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    comparison.models["vpc"].authoritative["desired.resource.001.resourceMode"] = (
        "IMPORT"
    )
    comparison.models["vpc"].values["desired.resource.001.resourceMode"] = "IMPORT"
    value = (
        model_ref("EC2_VPC_001", "VpcId")
        if shape == "json-link"
        else {"$modelRef": {"logicalId": "EC2_VPC_001", "attribute": "VpcId"}}
    )
    if shape == "intrinsic":
        value = {"Fn::Join": ["", [value]]}
    desired = {"VpcId": value, "Subnets": ["subnet-first"]}
    actual = {"VpcId": "vpc-unknown", "Subnets": ["subnet-second"]}
    if shape == "array":
        resource(
            comparison,
            "vpc",
            "002",
            "EC2.Subnet",
            "Subnet",
            [("SubnetId", "PENDING_DEPLOY", observed)],
        )
        comparison.resources["vpc"]["002"]["resourceMode"] = "IMPORT"
        comparison.models["vpc"].authoritative["desired.resource.002.resourceMode"] = (
            "IMPORT"
        )
        comparison.models["vpc"].values["desired.resource.002.resourceMode"] = "IMPORT"
        desired = {
            "VpcId": VPC,
            "Subnets": [model_ref("EC2_Subnet_002", "SubnetId"), "subnet-first"],
        }
        actual = {"VpcId": VPC, "Subnets": ["subnet-external", "subnet-second"]}
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("VpcConfig", json.dumps(desired), None)],
        properties={"VpcConfig": actual},
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
    category = "excluded" if observed == "PENDING_DEPLOY" else "deferred"
    assert sorted(item["category"] for item in batch.records) == sorted(
        [category, "difference"]
    ), batch.records
    parent = next(item for item in batch.records if item["category"] == "difference")
    assert not parent.get("deferred_children")
    assert "subnet-first" in json.dumps(batch.display_differences)


@pytest.mark.parametrize("environment", ["dev", "stg"])
@pytest.mark.parametrize(
    "desired,category",
    [
        ("PENDING_DEPLOY", "excluded"),
        ("UNSET", "uncompared"),
        ("TODO", "uncompared"),
        ("TBD", "uncompared"),
        ("未確定", "uncompared"),
        ("desired.example", "difference"),
    ],
)
def test_route53_direct_pending_deploy_classification(environment, desired, category):
    comparison = fixture()
    comparison.environment, comparison.directory = environment, "cde"
    resource(
        comparison,
        "route53",
        "003",
        "Route53.RecordSet",
        "Alias",
        [("AliasTarget.DNSName", desired, None)],
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
    assert batch.failure is None
    assert {item["category"] for item in batch.records} == {category}, batch.records
    data = aggregate(batch.records, environment, "cde", ["route53"])
    if category == "excluded":
        assert len(batch.records) == 1
        assert batch.records[0]["cause"] == dict(
            kind="desired-value-excluded",
            phase="pending_deploy",
            consumer_property="Route53.RecordSet.AliasTarget.DNSName",
        )
        assert data["overview"]["issue_count"] == 0
        assert data["overview"]["pending_deploy_excluded"] == 1
        assert not data["overview"]["comparison_incomplete"]
    else:
        assert data["overview"]["issue_count"] > 0
        assert data["overview"]["pending_deploy_excluded"] == 0


@pytest.mark.parametrize("sibling", ["Name", "AliasTarget.HostedZoneId"])
@pytest.mark.parametrize(
    "desired,category",
    [
        ("PENDING_DEPLOY", "excluded"),
        ("fixed", "matched"),
        ("different", "difference"),
        ("TODO", "uncompared"),
    ],
)
def test_direct_pending_deploy_preserves_sibling_comparison(sibling, desired, category):
    comparison = fixture()
    resource(
        comparison,
        "route53",
        "003",
        "Route53.RecordSet",
        "Alias",
        [("AliasTarget.DNSName", "PENDING_DEPLOY", None), (sibling, desired, None)],
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
    assert batch.failure is None
    assert {item["category"] for item in batch.records} == {"excluded", category}
    data = aggregate(batch.records, "dev", "cde", ["route53"])
    assert data["overview"]["pending_deploy_excluded"] == (
        2 if category == "excluded" else 1
    )
    assert data["overview"]["records"]["uncompared"] == (
        1 if category == "uncompared" else 0
    )
    assert data["overview"]["issue_count"] == (
        1 if category in {"difference", "uncompared"} else 0
    )
    assert all(
        "DNSName" not in item["property"]
        for item in batch.records
        if item["category"] != "excluded"
    )


@pytest.mark.parametrize("unknown", ["DNSName", "HostedZoneId"])
def test_direct_pending_deploy_retains_actual_sibling_failures(unknown):
    comparison = fixture()
    actual = {"DNSName": "actual.example", "HostedZoneId": "fixed"}
    actual[unknown] = {"Ref": "Missing"}
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
        properties={"AliasTarget": actual},
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
    assert batch.failure is None
    assert {item["category"] for item in batch.records} == {
        "excluded",
        "uncompared" if unknown == "HostedZoneId" else "matched",
    }
    view = aggregate(batch.records, "dev", "cde", ["route53"])["overview"]
    assert view["pending_deploy_excluded"] == 1
    assert view["records"]["uncompared"] == (1 if unknown == "HostedZoneId" else 0)


def evaluate_actual_wait(original, error, stack, value, *args):
    if value == {"Ref": "External"}:
        raise error
    return original(stack, value, *args)


@pytest.mark.parametrize("phase", ["unobserved", "pending_deploy", "awaiting_handoff"])
@pytest.mark.parametrize("mismatch", [False, True])
def test_actual_wait_retains_pointer_and_known_siblings(mismatch, phase):
    error = ImportReferenceDeferred(
        phase,
        "vpc",
        "004",
        "EC2.Subnet",
        "SubnetId",
        "CodeBuild.Project.VpcConfig.Subnets[]",
    )
    comparison = fixture()
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("VpcConfig", json.dumps({"VpcId": VPC, "Subnets": ["subnet-fixed"]}), None)],
        properties={
            "VpcConfig": {
                "VpcId": "vpc-different" if mismatch else VPC,
                "Subnets": [{"Ref": "External"}],
            }
        },
    )
    evaluate = partial(evaluate_actual_wait, comparison.evaluate, error)
    comparison.evaluate = evaluate
    projected = project_actual(
        {"VpcId": VPC, "Subnets": [{"Ref": "External"}]},
        evaluate=lambda value: evaluate("producer", value),
        property_name="CodeBuild.Project.VpcConfig",
        model_path=ROOT / "synthetic.yaml",
    )
    assert len(projected.failures) == 1 and projected.failures[0][1] == "/Subnets/0"
    assert projected.failures[0][2] is error and not projected.warnings
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
    category = "excluded" if phase == "pending_deploy" else "deferred"
    assert sorted(item["category"] for item in batch.records) == sorted(
        [category, "difference"] if mismatch else [category]
    ), batch.records


@pytest.mark.parametrize(
    "failure,category",
    [
        (Blocked("not proven"), "uncompared"),
        (ValueError("malformed"), "error"),
        ("pending_deploy", "excluded"),
        ("unobserved", "deferred"),
        ("awaiting_handoff", "deferred"),
    ],
)
def test_resource_failure_uses_shared_classification(failure, category):
    comparison = fixture()
    comparison.services = ["codebuild"]
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("Name", "build", None)],
    )
    if isinstance(failure, str):
        failure = ImportReferenceDeferred(
            failure,
            "vpc",
            "004",
            "EC2.Subnet",
            "SubnetId",
            "CodeBuild.Project.VpcConfig.Subnets[]",
        )
    comparison.compare_rows = Mock(side_effect=failure)
    with patch.object(Path, "is_file", return_value=True):
        (item,) = comparison.run()
    assert item["category"] == category, item
    if category in {"deferred", "excluded"}:
        assert item["cause"] == failure.iac_cause


@pytest.mark.parametrize("observed", [None, "PENDING_DEPLOY"])
@pytest.mark.parametrize("unknown", [{"Ref": "Missing"}, {"Fn::Join": ["", 1]}])
def test_deferred_intrinsic_does_not_hide_other_operand_failures(unknown, observed):
    comparison = fixture()
    vpc(comparison, observed=observed)
    comparison.resources["vpc"]["001"]["resourceMode"] = "IMPORT"
    comparison.models["vpc"].authoritative["desired.resource.001.resourceMode"] = (
        "IMPORT"
    )
    comparison.models["vpc"].values["desired.resource.001.resourceMode"] = "IMPORT"
    expression = {
        "Fn::Join": [
            "",
            [
                {"$modelRef": {"logicalId": "EC2_VPC_001", "attribute": "VpcId"}},
                unknown,
            ],
        ]
    }
    resource(
        comparison,
        "codebuild",
        "001",
        "CodeBuild.Project",
        "Build",
        [("VpcConfig", json.dumps({"VpcId": expression}), None)],
        properties={"VpcConfig": {"VpcId": "external"}},
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
    assert any(item["category"] in {"uncompared", "error"} for item in batch.records), (
        batch.records
    )
    assert not any(
        item["category"] in {"matched", "difference"} for item in batch.records
    ), batch.records


@pytest.mark.parametrize("observed", [KEY_ID, None, "PENDING_DEPLOY"])
def test_iac_reference_display_pipeline_preserves_comparison_and_issues(observed):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", observed)],
    )
    resource(
        comparison,
        "kms",
        "008",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/fixture", None)],
        properties={"AliasName": "alias/fixture", "TargetKeyId": {"Ref": "Key"}},
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "FIRST", "Type": "PLAINTEXT", "Value": "same"},
            {"Name": "SECOND", "Type": "PLAINTEXT", "Value": "same"},
            {"Name": "KEY_ID", "Type": "PLAINTEXT", "Value": "alias/fixture"},
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][2]["Value"] = {"Fn::GetAtt": ["Key", "KeyId"]}
    actual = comparison.evaluate("producer", actual)
    decision = compare_values(
        desired, actual, "Environment", rules=rules("CodeBuild.Project")
    )

    # This boundary receives an already detected difference; service decisions stay upstream.
    args = (
        "codebuild",
        "002",
        "CodeBuild.Project.Environment",
        desired,
        actual,
        decision,
        "producer",
        [{}],
        {},
    )
    before = setting_result(*args, actual_error=None, redact=comparison.redacted)
    authority = copy.deepcopy(comparison.models["kms"].authoritative)
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        after = setting_result(
            *args,
            actual_error=None,
            redact=comparison.redacted,
            display_reference=comparison.display_reference,
        )
    assert after.failure is None, after.failure
    assert before.records == after.records and before.warnings == after.warnings
    assert authority == comparison.models["kms"].authoritative
    (record,) = after.records
    assert record["category"] == "difference", record
    (field,) = after.display_differences[identifier(record)]
    assert field["path"] == "EnvironmentVariables[2].Value"
    assert field["model"] == "alias/fixture"
    assert "参照: kms/007.KeyId" in field["iac"]
    assert "alias/fixture" not in field["iac"]
    if observed == KEY_ID:
        assert field["iac"].startswith(json.dumps(KEY_ID) + " (参照:"), field
        assert "Observed（記録値・現在AWS未確認）" in field["iac"]
    else:
        assert field["iac"].startswith("未解決")
        assert "理由: identifier_unobserved" in field["iac"]
    args = ("fixture", "team", ["codebuild"])
    old_dataset = iac_dataset(before.records, *args, before.display_differences)
    dataset = iac_dataset(after.records, *args, after.display_differences)
    assert (
        old_dataset[:2] == dataset[:2]
    )  # Record IDs, Issue IDs, causes and categories.
    assert dataset[2] == after.display_differences
    old_summary = iac_summary(before.records, *args, dataset=old_dataset)
    summary = iac_summary(after.records, *args, dataset=dataset)
    assert summary["groups"][0]["examples"][0]["fields"][0]["iac"]
    for report in (old_summary, summary):
        for group in report["groups"]:
            for example in group["examples"]:
                example["fields"] = []
    assert (
        old_summary == summary
    )  # Includes all Issue/record counts and cause summaries.
    artifact = dict(
        version=6, **aggregate(after.records, *args, after.display_differences)
    )
    assert detail_payload(artifact, "iac")["items"][0]["value_differences"] == [field]


@pytest.mark.parametrize("shape", ["direct", "nested", "join", "sub", "select"])
def test_iac_reference_display_local_expression_and_cache(shape):
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
    ref = ResourceReference({"$resource": ["s3", "001"], "$attribute": "BucketName"})
    actual = {
        "direct": ref,
        "nested": {"Items": [ref, ref]},
        "join": Expression("Join", ["/", [ref, ref]]),
        "sub": Expression("Sub", ["prefix/${bucket}", {"bucket": ref}]),
        "select": Expression(
            "Select",
            [0, Expression("Split", ["/", Expression("Join", ["/", [ref, "tail"]])])],
        ),
    }[shape]
    decision = compare_values(
        "different", actual, "Setting", rules={"Setting": ORDERED}
    )
    original = copy.deepcopy(actual)
    with patch.object(
        comparison, "reference_literal", wraps=comparison.reference_literal
    ) as resolve:
        fields = value_differences(
            decision,
            "different",
            actual,
            "Setting",
            redact=comparison.redacted,
            display_reference=comparison.display_reference,
        )
        assert resolve.call_count == 1
    assert actual == original
    shown = fields[0]["iac"]
    assert "fixture-bucket" in shown and "s3/001.BucketName" in shown
    assert "IaC（ローカル評価）" in shown and "Observed" not in shown
    assert "$resource" not in shown and "$expression" not in shown
    if shape == "join":
        assert shown.startswith("fixture-bucket/fixture-bucket")
    if shape == "sub":
        assert shown.startswith("prefix/fixture-bucket")


@pytest.mark.parametrize(
    "mask", ["property", "environment", "sensitive", "producer", "expression"]
)
def test_iac_reference_display_retains_masks(mask):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    prop, actual = "Setting", ref
    if mask == "property":
        prop = "SecretString"
    elif mask == "environment":
        actual = {"Name": "SECRET_TOKEN", "Value": ref}
    elif mask == "sensitive":
        comparison.sensitive_values.add(KEY_ID)
    elif mask == "producer":
        ref["$attribute"] = "SecretString"
    elif mask == "expression":
        actual = Expression(
            "Sub", ["${Password}/${key}", {"Password": "never-expose", "key": ref}]
        )
    decision = compare_values("different", actual, prop, rules={prop: ORDERED})
    with patch.object(comparison, "reference_literal", return_value=KEY_ID) as resolve:
        fields = value_differences(
            decision,
            "different",
            actual,
            prop,
            redact=comparison.redacted,
            display_reference=comparison.display_reference,
        )
    text = json.dumps(fields, ensure_ascii=False)
    assert "never-expose" not in text
    if mask != "expression":
        assert KEY_ID not in text and "masked" in text
    if mask in {"property", "environment"}:
        resolve.assert_not_called()
    batch = setting_result(
        "codebuild",
        "002",
        prop,
        "different",
        actual,
        decision,
        "producer",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=comparison.display_reference,
    )
    artifact = dict(
        version=6,
        **aggregate(
            batch.records,
            "fixture",
            "team",
            ["codebuild"],
            batch.display_differences,
            redact=comparison.redacted,
        ),
    )
    text = json.dumps(detail_payload(artifact, "iac"), ensure_ascii=False)
    assert "never-expose" not in text
    if mask != "expression":
        assert KEY_ID not in text


@pytest.mark.parametrize("failure", ["absent", "context", "blocked", "bug"])
def test_iac_reference_display_expected_failures_only(failure):
    comparison = fixture()
    vpc(comparison)
    ref = ResourceReference({"$resource": ["vpc", "001"], "$attribute": "VpcId"})
    if failure == "absent":
        ref["$resource"][1] = "999"
    if failure == "context":
        comparison.reference_models_loaded = False
    decision = compare_values("different", ref, "Setting", rules={"Setting": ORDERED})
    error = (
        ValueError("implementation bug")
        if failure == "bug"
        else Blocked("identifier_unobserved")
    )
    with patch.object(comparison, "reference_literal", side_effect=error) as resolve:
        if failure == "bug":
            with pytest.raises(ValueError, match="implementation bug"):
                value_differences(
                    decision,
                    "different",
                    ref,
                    display_reference=comparison.display_reference,
                )
            return
        for _ in range(2):
            fields = value_differences(
                decision,
                "different",
                ref,
                display_reference=comparison.display_reference,
            )
            assert "未解決" in fields[0]["iac"] and "理由:" in fields[0]["iac"]
            assert "vpc/" in fields[0]["iac"]
        assert resolve.call_count == (1 if failure == "blocked" else 0)


@pytest.mark.parametrize(
    "actual", [None, "ordinary", {}, Expression("Join", ["/", ["a", "b"]])]
)
def test_iac_reference_display_preserves_nonreferences_and_missing(actual):
    decision = compare_values({"a": 1}, actual, "Setting", rules={"Setting": ORDERED})
    expected = value_differences(decision, {"a": 1}, actual)
    resolver = Mock(side_effect=AssertionError("non-reference must not resolve"))
    assert (
        value_differences(decision, {"a": 1}, actual, display_reference=resolver)
        == expected
    )
    resolver.assert_not_called()


@pytest.mark.parametrize(
    "desired,expected",
    [
        ("fixture-bucket", "matched"),
        ("different", "difference"),
        ("vpc-literal", "uncompared"),
    ],
)
def test_iac_reference_display_runner_decisions_unchanged(desired, expected):
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
    vpc(comparison)
    actual = {"Ref": "Vpc" if expected == "uncompared" else "Bucket"}
    settings = Settings(desired={"Description": desired}, sources={"Description": [{}]})

    args = (
        "iam",
        "002",
        "IAM.Role",
        "Description",
        desired,
        settings,
        "producer",
        {"Properties": {"Description": actual}},
        ROOT / "synthetic.yaml",
    )
    with patch.object(comparison, "display_reference", None):
        before = comparison.compare_setting(*args)
    with patch.object(
        comparison, "display_reference", wraps=comparison.display_reference
    ) as resolve:
        after = comparison.compare_setting(*args)
    assert before.records == after.records
    assert [item["category"] for item in after.records] == [expected], after.records
    assert resolve.call_count == (0 if expected == "matched" else 1)
    if expected == "difference":
        assert (
            "参照: s3/001.BucketName"
            in next(iter(after.display_differences.values()))[0]["iac"]
        )


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-env-")
)
def test_codebuild_plaintext_iac_reference_environment(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_environment)


def _execute_codebuild_environment(case):
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
        stack="producer",
    )
    if data["export"]:
        comparison.stack_inputs["producer"][0]["Outputs"]["Shared"] = {
            "Value": {"Ref": "Bucket"},
            "Export": {"Name": "shared"},
        }
    desired = {
        "EnvironmentVariables": [
            {"Name": data["name"], "Type": data["selector"], "Value": data["literal"]}
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][0]["Value"] = data["reference"]
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    outcome = comparison.compare_setting(
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        data["stack"],
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    if data["check_evidence"]:
        (record,) = outcome.records
        (evidence,) = record["reference_diagnostics"]
        TestCase().assertEqual(evidence["evidence_type"], "local_evaluation")
        TestCase().assertEqual(evidence["local_comparison"], record["category"])
        TestCase().assertIs(evidence["current_aws_verified"], False)
    return {"records": projected(outcome.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-producer-")
)
def test_codebuild_wrong_producer_expression(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_environment)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-bucket-arn-")
)
def test_codebuild_plaintext_getatt_bucket_arn(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_environment)


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="lambda-env-")
)
def test_lambda_environment_iac_reference(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_lambda_environment)


def _execute_lambda_environment(case):
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
    desired = {"Variables": {"BUCKET": data["literal"]}}
    actual = {"Variables": {"BUCKET": data["reference"]}}
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    outcome = comparison.compare_setting(
        "lambda",
        "002",
        "Lambda.Function",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    (record,) = outcome.records
    if record["category"] != "uncompared":
        (evidence,) = record["reference_diagnostics"]
        TestCase().assertEqual(evidence["evidence_type"], "local_evaluation")
        TestCase().assertEqual(evidence["local_comparison"], record["category"])
        TestCase().assertIs(evidence["current_aws_verified"], False)
    return {"records": projected(outcome.records)}


@pytest.mark.parametrize(
    "case_id", case_ids("reference_evidence", prefix="codebuild-kms-form-")
)
def test_codebuild_material_key_id_reference_formats(case_runner, case_id):
    case_runner.run("reference_evidence", case_id, _execute_codebuild_kms_form)


def _execute_codebuild_kms_form(case):
    data = case["data"]
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    resource(
        comparison,
        "kms",
        "002",
        "KMS.Alias",
        "Alias",
        [("AliasName", "alias/material", None)],
        properties={"AliasName": "alias/material", "TargetKeyId": {"Ref": "Key"}},
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "MATERIAL_KEY_ID", "Type": "PLAINTEXT", "Value": data["literal"]}
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][0]["Value"] = data["reference"]
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    outcome = comparison.compare_setting(
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    (record,) = outcome.records
    (evidence,) = record["reference_diagnostics"]
    TestCase().assertEqual(evidence["local_comparison"], record["category"])
    TestCase().assertIs(evidence["current_aws_verified"], False)
    TestCase().assertTrue(evidence["reason"])
    return {"records": projected(outcome.records)}


def test_codebuild_observed_only_and_difference_are_preserved():
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "KEY", "Type": "PLAINTEXT", "Value": KEY_ID},
            {"Name": "SETTING", "Type": "PLAINTEXT", "Value": "before"},
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][0]["Value"] = {"Fn::GetAtt": ["Key", "KeyId"]}
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    args = (
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    outcome = comparison.compare_setting(*args)
    (record,) = outcome.records
    TestCase().assertEqual(record["category"], "uncompared")
    TestCase().assertTrue(record["reference_diagnostics"][0]["reason"])
    actual["EnvironmentVariables"][1]["Value"] = "after"
    outcome = comparison.compare_setting(*args)
    (record,) = outcome.records
    TestCase().assertEqual(record["category"], "difference")
    TestCase().assertTrue(record["reference_diagnostics"][0]["reason"])


@pytest.mark.parametrize("observed", [KEY_ID, None])
def test_codebuild_uncompared_reference_display_real_path(observed):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", observed)],
    )
    desired = {
        "EnvironmentVariables": [
            {"Name": "FIRST", "Type": "PLAINTEXT", "Value": "same"},
            {"Name": "SECOND", "Type": "PLAINTEXT", "Value": "same"},
            {
                "Name": "KEY",
                "Type": "PLAINTEXT",
                "Value": "alias/venusinf-stg-material",
            },
        ]
    }
    actual = copy.deepcopy(desired)
    actual["EnvironmentVariables"][2]["Value"] = {"Fn::GetAtt": ["Key", "KeyId"]}
    settings = Settings(desired={"Environment": desired}, sources={"Environment": [{}]})
    args = (
        "codebuild",
        "002",
        "CodeBuild.Project",
        "Environment",
        desired,
        settings,
        "producer",
        {"Properties": {"Environment": actual}},
        ROOT / "synthetic.yaml",
    )
    with patch.object(comparison, "display_reference", None):
        before = comparison.compare_setting(*args)
    with patch("socket.socket", side_effect=AssertionError("network forbidden")):
        after = comparison.compare_setting(*args)
    assert before.records == after.records
    (record,) = after.records
    assert record["category"] == "uncompared"
    (diagnostic,) = record["reference_diagnostics"]
    TestCase().assertEqual(diagnostic["local_comparison"], "uncompared")
    TestCase().assertTrue(diagnostic["reason"])
    TestCase().assertFalse(diagnostic["current_aws_verified"])
    (field,) = after.display_differences[identifier(record)]
    assert "EnvironmentVariables[2].Value" in field["path"]
    assert field["model"] == "alias/venusinf-stg-material"
    assert "kms/007.KeyId" in field["iac"]
    if observed:
        assert observed in field["iac"] and "Observed" in field["iac"]
    else:
        assert "未解決" in field["iac"] and "理由" in field["iac"]
    args = ("fixture", "team", ["codebuild"])
    old = iac_dataset(before.records, *args, before.display_differences)
    new = iac_dataset(after.records, *args, after.display_differences)
    assert old[:2] == new[:2]
    summary = iac_summary(after.records, *args, dataset=new)
    assert summary["groups"][0]["examples"][0]["fields"] == [field]
    artifact = dict(
        version=6, **aggregate(after.records, *args, after.display_differences)
    )
    assert detail_payload(artifact, "iac")["items"][0]["value_differences"] == [field]


@pytest.mark.parametrize("shape", ["nested", "expression", "secret", "sensitive"])
def test_uncompared_reference_display_preserves_redaction(shape):
    comparison = fixture()
    resource(
        comparison,
        "kms",
        "007",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
    )
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    actual = {"Items": [ref]}
    prop = "Setting"
    if shape == "expression":
        actual = Expression("Join", ["/", ["prefix", ref]])
    elif shape == "secret":
        actual = {"Name": "SECRET_TOKEN", "Value": ref}
    elif shape == "sensitive":
        comparison.sensitive_values.add(KEY_ID)
    batch = setting_result(
        "codebuild",
        "002",
        prop,
        "unknown",
        actual,
        CompareOutcome(None),
        "producer",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=comparison.display_reference,
    )
    rendered = json.dumps(batch.display_differences, ensure_ascii=False)
    if shape == "secret":
        assert KEY_ID not in rendered and "kms/007" not in rendered
    else:
        assert "kms/007.KeyId" in rendered
        assert (KEY_ID not in rendered) == (shape == "sensitive")


def unproven_reference(left, right, path):
    if isinstance(right, ResourceReference):
        return ReferenceDecision(
            None,
            (
                {
                    "path": path,
                    "model": left,
                    "iac": right,
                    "local_comparison": "uncompared",
                    "reason": "unproven",
                },
            ),
        )
    return ReferenceDecision(NotImplemented)


def unordered_reference(refs, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    if right == refs[0]:
        equal = True if left == "confirmed" else False
    else:
        equal = None if left == "pending" else False
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": left,
                "iac": right,
                "local_comparison": "matched"
                if equal is True
                else "uncompared"
                if equal is None
                else "difference",
                "reason": "fixture",
                "identity": "unproven",
                "allowed_forms": None,
                "format": {},
            },
        ),
    )


@pytest.mark.parametrize(
    "mode", ["scalar", "ordered", "keyed", "unordered", "ambiguous"]
)
def test_uncompared_shows_only_proven_model_correspondence(mode):
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    if mode == "scalar":
        desired, actual, rule = "model-value", ref, ORDERED
    elif mode == "ordered":
        desired, actual, rule = [{"Value": "model-value"}], [{"Value": ref}], ORDERED
    else:
        desired = [
            {"Name": "A", "Value": "model-value"},
            {"Name": "B", "Value": "other"},
        ]
        actual = [{"Name": "B", "Value": "other"}, {"Name": "A", "Value": ref}]
        rule = keyed("Name") if mode == "keyed" else UNORDERED
        if mode == "ambiguous":
            desired = [{"Value": "model-value"}, {"Value": "other"}]
            actual = [{"Value": ref}, {"Value": ref}]

    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": rule},
        reference=unproven_reference,
    )
    assert decision.equal is None
    batch = setting_result(
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
        redact=lambda v, *args: v,
        display_reference=lambda ref: ("resolved", "fixture"),
    )
    if mode == "ambiguous":
        fields = next(iter(batch.display_differences.values()))
        assert [field["model"] for field in fields] == ["対応未確定"] * 2
    else:
        fields = next(iter(batch.display_differences.values()))
        assert [field["model"] for field in fields] == ["model-value"]


def test_uncompared_model_correspondence_respects_sensitive_redaction():
    comparison = fixture()
    comparison.sensitive_values.add("model-secret")
    desired = {"Value": "model-secret"}
    actual = {
        "Value": ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    }
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=lambda left, right, path: ReferenceDecision(
            None,
            (
                comparison.redacted(
                    {
                        "path": path,
                        "model": left,
                        "iac": right,
                        "local_comparison": "uncompared",
                        "reason": "unproven",
                    }
                ),
            ),
        )
        if isinstance(right, ResourceReference)
        else ReferenceDecision(NotImplemented),
    )
    batch = setting_result(
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
        display_reference=lambda ref: ("resolved", "fixture"),
    )
    field = next(iter(batch.display_differences.values()))[0]
    assert "model-secret" not in json.dumps(field)
    assert "masked" in field["model"]


@pytest.mark.parametrize(
    "equal,actual_error",
    [
        (None, None),
        (False, None),
        (None, Blocked("original error")),
        (False, Blocked("original error")),
    ],
)
def test_display_failure_does_not_change_comparison(equal, actual_error):
    ref = ResourceReference({"$resource": ["s3", "001"], "$attribute": "BucketName"})
    decision = CompareOutcome(equal, diagnostics=({"reason": "original evidence"},))
    if equal is False:
        decision = compare_values("other", ref, "Setting", rules={"Setting": ORDERED})
    args = ("s3", "001", "Setting", "other", ref, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=actual_error, redact=safe_value)
    resolver = Mock(side_effect=ValueError("display bug"))
    after = setting_result(
        *args, actual_error=actual_error, redact=safe_value, display_reference=resolver
    )
    assert after.records == before.records
    if actual_error is not None:
        resolver.assert_not_called()
        assert not after.warnings
    else:
        assert "ValueError: display bug" in after.warnings[0]["message"]
        if equal is False:
            field = next(iter(after.display_differences.values()))[0]
            assert "未解決" in field["iac"] and "s3/001.BucketName" in field["iac"]


@pytest.mark.parametrize("nested", [False, True])
def test_unordered_uncompared_displays_only_diagnosed_reference(nested):
    refs = [
        ResourceReference({"$resource": ["kms", f"00{i}"], "$attribute": "KeyId"})
        for i in (1, 2)
    ]
    desired = ["confirmed", "pending"]
    actual = refs
    ruleset = {"Setting": UNORDERED}
    if nested:
        desired = [{"Value": value} for value in desired]
        actual = [{"Value": value} for value in refs]

    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules=ruleset,
        reference=partial(unordered_reference, refs),
    )
    assert decision.equal is None
    resolver = Mock(side_effect=[("resolved", "fixture")])
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    assert after.records == before.records and not after.warnings
    fields = after.display_differences[identifier(after.records[0])]
    assert len(fields) == 1
    assert fields[0]["model"] == "pending"
    assert "kms/002.KeyId" in fields[0]["iac"]
    resolver.assert_called_once_with(refs[1])
    old = iac_dataset(
        before.records, "fixture", "team", ["test"], before.display_differences
    )
    new = iac_dataset(
        after.records, "fixture", "team", ["test"], after.display_differences
    )
    assert old[:2] == new[:2]
    artifact = dict(
        version=6,
        **aggregate(
            after.records, "fixture", "team", ["test"], after.display_differences
        ),
    )
    assert detail_payload(artifact, "iac")["items"][0]["value_differences"] == fields


def many_reference(left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    number = int(right["$resource"][1])
    equal = (None if number == 30 else True) if left == str(number) else False
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": left,
                "iac": right,
                "local_comparison": "uncompared"
                if equal is None
                else "matched"
                if equal
                else "difference",
            },
        ),
    )


def test_many_unordered_references_resolve_only_pending():
    refs = [
        ResourceReference({"$resource": ["kms", f"{i:03}"], "$attribute": "KeyId"})
        for i in range(1, 31)
    ]
    desired = [str(i) for i in range(1, 31)]
    decision = compare_values(
        desired, refs, "Setting", rules={"Setting": UNORDERED}, reference=many_reference
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        refs,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    assert decision.equal is None and not result.warnings
    fields = result.display_differences[identifier(result.records[0])]
    assert len(fields) == 1 and "kms/030.KeyId" in fields[0]["iac"]
    resolver.assert_called_once_with(refs[-1])


def test_unordered_ambiguous_reference_has_no_individual_claim():
    refs = [
        ResourceReference({"$resource": ["kms", f"00{i}"], "$attribute": "KeyId"})
        for i in (1, 2)
    ]

    decision = compare_values(
        ["one", "two"],
        refs,
        "Setting",
        rules={"Setting": UNORDERED},
        reference=unproven_reference,
    )
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        "test",
        "001",
        "Setting",
        ["one", "two"],
        refs,
        decision,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    assert decision.equal is None and result.records[0]["category"] == "uncompared"
    fields = result.display_differences[identifier(result.records[0])]
    assert [field["model"] for field in fields] == ["対応未確定"] * 2
    assert resolver.call_count == 2


def expression_unconfirmed_reference(left, right, path):
    if not isinstance(right, (Expression, ResourceReference)):
        return ReferenceDecision(NotImplemented)
    equal = True if left == "matched" else None if left == "pending" else False
    if isinstance(right, Expression) and left == "matched":
        equal = right.operands[1][1]["$resource"][1] == "001"
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": safe_value(left),
                "iac": safe_value(right),
                "local_comparison": "matched"
                if equal is True
                else "uncompared"
                if equal is None
                else "difference",
                "identity": "unproven",
                "allowed_forms": None,
                "format": {},
                "reason": "fixture",
            },
        ),
    )


@pytest.mark.parametrize("shape", ["join", "nested", "nested_join", "sub", "reference"])
def test_uncompared_expression_real_correspondence_and_issue_display(shape):
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    expr = Expression("Join", ["", ["prefix/", ref]])
    actual = {
        "join": expr,
        "nested": {"Value": expr},
        "nested_join": Expression("Join", ["", ["outer/", expr]]),
        "sub": Expression("Sub", ["prefix/${Key}", {"Key": ref}]),
        "reference": ref,
    }[shape]
    desired = {"Value": "pending"} if shape == "nested" else "pending"
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=expression_unconfirmed_reference,
    )
    assert decision.equal is None and decision.correspondence and decision.diagnostics
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args,
        actual_error=None,
        redact=safe_value,
        display_reference=lambda ref: ("resolved", "fixture"),
    )
    assert before.records == after.records and not after.warnings
    field = after.display_differences[identifier(after.records[0])][0]
    assert field["model"] == "pending"
    assert (
        "resolved" in field["iac"]
        and "kms/001.KeyId" in field["iac"]
        and "fixture" in field["iac"]
    )
    artifact = dict(
        version=6,
        **aggregate(
            after.records, "fixture", "team", ["test"], after.display_differences
        ),
    )
    assert detail_payload(artifact, "iac")["items"][0]["value_differences"] == [field]


def test_unordered_expression_only_uncompared_selected_and_ambiguous():
    refs = [
        ResourceReference({"$resource": ["kms", f"00{i}"], "$attribute": "KeyId"})
        for i in (1, 2)
    ]
    actual = [Expression("Join", ["", ["prefix/", ref]]) for ref in refs]
    desired = ["matched", "pending"]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": UNORDERED},
        reference=expression_unconfirmed_reference,
    )
    assert decision.equal is None and decision.correspondence and decision.diagnostics
    resolver = Mock(return_value=("resolved", "fixture"))
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    assert before.records == after.records and not after.warnings
    fields = after.display_differences[identifier(after.records[0])]
    assert [field["model"] for field in fields] == ["pending"]
    assert "kms/002.KeyId" in fields[0]["iac"]
    resolver.assert_called_once_with(refs[1])
    ambiguous = compare_values(
        ["pending", "pending"],
        actual,
        "Setting",
        rules={"Setting": UNORDERED},
        reference=expression_unconfirmed_reference,
    )
    result = setting_result(
        "test",
        "001",
        "Setting",
        ["pending", "pending"],
        actual,
        ambiguous,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    assert ambiguous.equal is None
    fields = result.display_differences[identifier(result.records[0])]
    assert [field["model"] for field in fields] == ["対応未確定"] * 2


def test_uncompared_expression_redaction_and_resolution_failure():
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    actual = Expression("Join", ["", ["{{resolve:secretsmanager:never-expose}}", ref]])
    decision = compare_values(
        "pending",
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=expression_unconfirmed_reference,
    )
    args = ("test", "001", "Setting", "pending", actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args,
        actual_error=None,
        redact=safe_value,
        display_reference=Mock(side_effect=ValueError("display bug")),
    )
    assert decision.equal is None and decision.correspondence and decision.diagnostics
    assert (
        before.records == after.records and after.records[0]["category"] == "uncompared"
    )
    assert "never-expose" not in json.dumps(
        [after.records, after.warnings, after.display_differences]
    )
    assert "ValueError: display bug" in after.warnings[0]["message"]
    assert "未解決" in after.display_differences[identifier(after.records[0])][0]["iac"]


def test_uncompared_duplicate_positions_and_ambiguous_evidence():
    ref = ResourceReference({"$resource": ["kms", "007"], "$attribute": "KeyId"})
    desired = ["first", "second"]
    actual = [ref, ref]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=lambda left, right, path: ReferenceDecision(None),
    )
    assert decision.equal is None and not decision.diagnostics
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    batch = setting_result(
        *args,
        actual_error=None,
        redact=safe_value,
        display_reference=lambda ref: ("resolved", "Observed"),
    )
    fields = batch.display_differences[identifier(batch.records[0])]
    assert [field["model"] for field in fields] == desired
    assert [field["path"] for field in fields] == [
        "IaC:[0]（参照情報）",
        "IaC:[1]（参照情報）",
    ]
    assert all("kms/007.KeyId" in field["iac"] for field in fields)
    ambiguous = CompareOutcome(
        None, correspondence=(((0,), (0,)), ((0,), (1,)), ((1,), (1,)))
    )
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        ambiguous,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=lambda ref: ("resolved", "Observed"),
    )
    assert [
        field["model"]
        for field in result.display_differences[identifier(result.records[0])]
    ] == ["対応未確定", "second"]


def pending_only_display(ref):
    if ref["$resource"][1] != "002":
        raise ValueError("unnecessary")
    return "resolved", "fixture"


def alternating_duplicate_reference(outcomes, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    equal = next(outcomes)
    return ReferenceDecision(
        equal,
        (
            {
                "path": path,
                "model": left,
                "iac": right,
                "local_comparison": "matched" if equal else "uncompared",
            },
        ),
    )


@pytest.mark.parametrize("join", [False, True])
def test_ordered_duplicate_matched_reference_is_not_displayed(join):
    refs = [
        ResourceReference({"$resource": ["kms", identity], "$attribute": "KeyId"})
        for identity in ("001", "001", "002")
    ]
    actual = (
        [Expression("Join", ["", ["prefix/", ref]]) for ref in refs] if join else refs
    )
    desired = ["matched", "matched", "pending"]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=expression_unconfirmed_reference,
    )
    resolver = Mock(side_effect=pending_only_display)
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    before = setting_result(*args, actual_error=None, redact=safe_value)
    after = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    assert (
        decision.equal is None
        and before.records == after.records
        and not after.warnings
    )
    fields = after.display_differences[identifier(after.records[0])]
    assert len(fields) == 1 and fields[0]["model"] == "pending"
    assert "kms/002.KeyId" in fields[0]["iac"] and "fixture" in fields[0]["iac"]
    resolver.assert_called_once_with(refs[2])
    artifact = dict(
        version=6,
        **aggregate(
            after.records, "fixture", "team", ["test"], after.display_differences
        ),
    )
    assert detail_payload(artifact, "iac")["items"][0]["value_differences"] == fields


def test_duplicate_key_with_different_statuses_uses_positions():
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    desired, actual = ["same", "same"], [ref, ref]
    outcomes = iter((True, None))
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(alternating_duplicate_reference, outcomes),
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
        redact=safe_value,
        display_reference=resolver,
    )
    assert decision.equal is None
    fields = result.display_differences[identifier(result.records[0])]
    assert len(fields) == 1 and fields[0]["path"] == "IaC:[1]（比較未確定）"
    resolver.assert_called_once()


def missing_duplicate_reference(outcomes, left, right, path):
    if not isinstance(right, ResourceReference):
        return ReferenceDecision(NotImplemented)
    has_evidence = next(outcomes)
    diagnostic = {
        "path": path,
        "model": left,
        "iac": right,
        "local_comparison": "matched",
    }
    return ReferenceDecision(
        True if has_evidence else None, (diagnostic,) if has_evidence else ()
    )


def test_duplicate_position_evidence_missing_or_correspondence_ambiguous():
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    desired, actual = ["same", "same"], [ref, ref]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(missing_duplicate_reference, iter((True, False))),
    )
    args = ("test", "001", "Setting", desired, actual, decision, "stack", [{}], {})
    resolver = Mock(return_value=("resolved", "fixture"))
    result = setting_result(
        *args, actual_error=None, redact=safe_value, display_reference=resolver
    )
    fields = result.display_differences[identifier(result.records[0])]
    assert len(fields) == 1 and fields[0]["path"] == "IaC:[1]（参照情報）"
    ambiguous = replace(
        decision, correspondence=(((0,), (0,)), ((0,), (1,)), ((1,), (1,)))
    )
    result = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        ambiguous,
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=safe_value,
        display_reference=resolver,
    )
    fields = result.display_differences[identifier(result.records[0])]
    assert len(fields) == 2 and fields[0]["model"] == "対応未確定"


def typed_duplicate_reference(comparison, outcomes, left, right, path):
    if not isinstance(right, (ResourceReference, Expression)):
        return ReferenceDecision(NotImplemented)
    equal = next(outcomes)
    detail = comparison.reference_diagnostic(left, right, "KMS.Key", path, "fixture")
    detail["local_comparison"] = "matched" if equal is True else "uncompared"
    return ReferenceDecision(equal, (detail,))


@pytest.mark.parametrize("shape", ["reference", "join", "sub"])
@pytest.mark.parametrize("masked", [False, True])
def test_typed_duplicate_position_evidence(shape, masked):
    comparison = fixture()
    if masked:
        comparison.sensitive_values.add("confirmed")
    refs = [
        ResourceReference({"$resource": ["kms", identity], "$attribute": "KeyId"})
        for identity in ("001", "001", "002")
    ]
    actual = refs
    if shape == "join":
        actual = [Expression("Join", ["", ["prefix/", ref]]) for ref in refs]
    elif shape == "sub":
        actual = [Expression("Sub", ["${Key}", {"Key": ref}]) for ref in refs]
    desired = ["confirmed", "confirmed", "pending"]
    decision = compare_values(
        desired,
        actual,
        "Setting",
        rules={"Setting": ORDERED},
        reference=partial(
            typed_duplicate_reference, comparison, iter((True, True, None))
        ),
        diagnostic_kind="KMS.Key",
    )
    baseline_resolver = Mock(return_value=("resolved", "fixture"))
    baseline = setting_result(
        "test",
        "001",
        "Setting",
        desired,
        actual,
        replace(decision, reference_positions=()),
        "stack",
        [{}],
        {},
        actual_error=None,
        redact=comparison.redacted,
        display_reference=baseline_resolver,
    )
    assert len(baseline.display_differences[identifier(baseline.records[0])]) == 3
    assert baseline_resolver.call_count == 3
    resolver = Mock(side_effect=pending_only_display)
    batch = setting_result(
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
    assert decision.equal is None
    assert [d["path"] for d in decision.diagnostics] == ["KMS.Key.Setting[]"] * 3
    assert decision.reference_positions == (
        ((0,), (0,), "matched"),
        ((1,), (1,), "matched"),
        ((2,), (2,), "uncompared"),
    )
    fields = batch.display_differences[identifier(batch.records[0])]
    assert len(fields) == 1 and fields[0]["model"] == "pending"
    assert "kms/002.KeyId" in fields[0]["iac"]
    resolver.assert_called_once_with(refs[2])
    assert not batch.warnings
    artifact = dict(
        version=6,
        **aggregate(
            batch.records, "fixture", "team", ["test"], batch.display_differences
        ),
    )
    assert detail_payload(artifact, "iac")["items"][0]["value_differences"] == fields
    if masked:
        assert "confirmed" not in json.dumps(
            [batch.records, batch.warnings, batch.display_differences]
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


def test_typed_same_reference_mixed_statuses():
    comparison = fixture()
    ref = ResourceReference({"$resource": ["kms", "001"], "$attribute": "KeyId"})
    desired, actual = ["same", "same"], [ref, ref]
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
    assert decision.reference_positions == (
        ((0,), (0,), "matched"),
        ((1,), (1,), "uncompared"),
    )
    fields = result.display_differences[identifier(result.records[0])]
    assert len(fields) == 1 and fields[0]["path"] == "IaC:[1]（比較未確定）"
    resolver.assert_called_once_with(ref)


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
    "kind,path,producer,attribute",
    [
        ("ApiGatewayV2.VpcLink", "SubnetIds[]", "EC2.Subnet", "SubnetId"),
        ("EC2.TransitGatewayVpcAttachment", "SubnetIds", "EC2.Subnet", "SubnetId"),
        (
            "ECS.CapacityProvider",
            "ManagedInstancesProvider.InstanceLaunchTemplate.NetworkConfiguration.Subnets[]",
            "EC2.Subnet",
            "SubnetId",
        ),
        (
            "ECS.Service",
            "NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
            "EC2.Subnet",
            "SubnetId",
        ),
        ("ElasticLoadBalancingV2.LoadBalancer", "Subnets[]", "EC2.Subnet", "SubnetId"),
        ("GuardDuty.MalwareProtectionPlan", "Role", "IAM.Role", "Arn"),
        ("RDS.DBProxy", "VpcSubnetIds[]", "EC2.Subnet", "SubnetId"),
        ("RDS.DBProxyEndpoint", "VpcSubnetIds[]", "EC2.Subnet", "SubnetId"),
        ("RDS.DBSubnetGroup", "SubnetIds[]", "EC2.Subnet", "SubnetId"),
        ("SageMaker.Domain", "SubnetIds[]", "EC2.Subnet", "SubnetId"),
        (
            "Scheduler.Schedule",
            "Target.EcsParameters.NetworkConfiguration.AwsvpcConfiguration.Subnets[]",
            "EC2.Subnet",
            "SubnetId",
        ),
        (
            "SecretsManager.RotationSchedule",
            "HostedRotationLambda.VpcSubnetIds",
            "EC2.Subnet",
            "SubnetId",
        ),
    ],
)
def test_import_only_receiving_contract_prepares_link(kind, path, producer, attribute):
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    symbol = comparison.desired_reference(
        "producer",
        model_ref(producer.replace(".", "_") + "_001", attribute),
        kind,
        path,
    )
    assert symbol == ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": attribute}
    )


@pytest.mark.parametrize(
    "kind,path",
    [
        ("ECS.TaskDefinition", "TaskRoleArn"),
        ("ECS.TaskDefinition", "ExecutionRoleArn"),
        ("Route53.HostedZone", "QueryLoggingConfig.CloudWatchLogsLogGroupArn"),
        ("Scheduler.Schedule", "Target.RoleArn"),
    ],
)
def test_same_wrong_producer_cannot_match(kind, path):
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference({"$resource": ["producer", "001"], "$attribute": "Arn"})
    assert comparison.reference_decision(symbol, symbol, kind, path).equal is not True


@pytest.mark.parametrize(
    "kind,path,producer,attribute",
    [
        (
            "ApiGatewayV2.Stage",
            "AccessLogSettings.DestinationArn",
            "Logs.LogGroup",
            "Arn",
        ),
        (
            "S3.Bucket",
            "ReplicationConfiguration.Rules[1].Destination.Bucket",
            "S3.Bucket",
            "Arn",
        ),
        (
            "RDS.DBInstance",
            "DBSubnetGroupName",
            "RDS.DBSubnetGroup",
            "DBSubnetGroupName",
        ),
        ("Glue.Crawler", "Role", "IAM.Role", "Arn"),
        ("Glue.Crawler", "Role", "IAM.Role", "RoleName"),
        ("CodeBuild.Project", "EncryptionKey", "KMS.Key", "Arn"),
        ("CodeBuild.Project", "EncryptionKey", "KMS.Alias", "AliasName"),
        (
            "S3.Bucket",
            "ReplicationConfiguration.Rules[1].Destination.EncryptionConfiguration.ReplicaKmsKeyID",
            "KMS.Key",
            "Arn",
        ),
        (
            "S3.Bucket",
            "ReplicationConfiguration.Rules[1].Destination.EncryptionConfiguration.ReplicaKmsKeyID",
            "KMS.Alias",
            "AliasArn",
        ),
        ("SageMaker.Domain", "VpcId", "EC2.VPC", "VpcId"),
        ("NetworkFirewall.Firewall", "VpcId", "EC2.VPC", "VpcId"),
        (
            "ECS.Service",
            "LoadBalancers[1].TargetGroupArn",
            "ElasticLoadBalancingV2.TargetGroup",
            "TargetGroupArn",
        ),
        ("EC2.Instance", "NetworkInterfaces[1].SubnetId", "EC2.Subnet", "SubnetId"),
        (
            "EC2.LaunchTemplate",
            "LaunchTemplateData.NetworkInterfaces[1].SubnetId",
            "EC2.Subnet",
            "SubnetId",
        ),
        ("EC2.NatGateway", "SubnetId", "EC2.Subnet", "SubnetId"),
        ("EC2.SubnetRouteTableAssociation", "SubnetId", "EC2.Subnet", "SubnetId"),
        (
            "NetworkFirewall.Firewall",
            "SubnetMappings[1].SubnetId",
            "EC2.Subnet",
            "SubnetId",
        ),
        (
            "ElasticLoadBalancingV2.LoadBalancer",
            "SubnetMappings[1].SubnetId",
            "EC2.Subnet",
            "SubnetId",
        ),
        ("MWAA.Environment", "ExecutionRoleArn", "IAM.Role", "Arn"),
        ("MWAA.Environment", "SourceBucketArn", "S3.Bucket", "Arn"),
        ("RDS.DBProxy", "Auth[1].SecretArn", "SecretsManager.Secret", "Id"),
        ("RDS.DBProxy", "RoleArn", "IAM.Role", "Arn"),
        ("Scheduler.Schedule", "Target.DeadLetterConfig.Arn", "SQS.Queue", "Arn"),
        ("S3.Bucket", "ReplicationConfiguration.Role", "IAM.Role", "Arn"),
        ("ECS.TaskDefinition", "TaskRoleArn", "IAM.Role", "Arn"),
        ("ECS.TaskDefinition", "ExecutionRoleArn", "IAM.Role", "Arn"),
        (
            "Route53.HostedZone",
            "QueryLoggingConfig.CloudWatchLogsLogGroupArn",
            "Logs.LogGroup",
            "Arn",
        ),
        ("Scheduler.Schedule", "Target.RoleArn", "IAM.Role", "Arn"),
    ],
)
def test_new_receiving_contracts(kind, path, producer, attribute):
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    wrong_kind, wrong_attribute = (
        ("IAM.Role", "RoleName")
        if producer == "EC2.Subnet"
        else ("EC2.Subnet", "SubnetId")
    )
    resource(comparison, "wrong", "001", wrong_kind, "Wrong", [])
    valid = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": attribute}
    )
    wrong = ResourceReference({"$resource": ["wrong", "001"], "$attribute": "SubnetId"})
    assert comparison.desired_reference("producer", valid, kind, path) == valid
    expected = None if kind == "Route53.HostedZone" else True
    assert comparison.reference_decision(valid, valid, kind, path).equal is expected
    assert comparison.reference_decision(wrong, wrong, kind, path).equal is not True
    with pytest.raises(Blocked):
        comparison.desired_reference("wrong", wrong, kind, path)
    invalid = ResourceReference(dict(valid, **{"$attribute": "Invalid"}))
    assert comparison.reference_decision(invalid, invalid, kind, path).equal is not True
    with pytest.raises(Blocked):
        comparison.desired_reference("producer", invalid, kind, path)


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


def test_saved_reference_wrong_consumer_cannot_match():
    comparison = fixture()
    vpc(comparison)
    row = consumer(comparison)
    declaration(comparison, "desired.row.010-001.value", VPC)
    desired = prepared(comparison, row).require_value()
    assert (
        comparison.reference_decision(
            desired, desired, "ECS.TaskDefinition", "TaskRoleArn"
        ).equal
        is not True
    )
    expression = Expression("Join", ["", ["prefix", desired]])
    actual = comparison.evaluate("producer", {"Ref": "Vpc"})
    for left, right in ((expression, expression), (desired, actual), (desired, VPC)):
        assert (
            comparison.reference_decision(
                left, right, "ECS.TaskDefinition", "TaskRoleArn"
            ).equal
            is not True
        )


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
    "kind,path",
    [
        ("EC2.FlowLog", "ResourceId"),
        ("CodePipeline.Pipeline", "Stages[].Actions[].Configuration.ProjectName"),
        ("CloudTrail.Trail", "EventSelectors[].DataResources[].Values[]"),
    ],
)
def test_unknown_context_cannot_match_wrong_producer(kind, path):
    comparison = fixture()
    resource(comparison, "producer", "001", "S3.Bucket", "Producer", [])
    symbol = ResourceReference(
        {"$resource": ["producer", "001"], "$attribute": "BucketName"}
    )
    assert comparison.reference_decision(symbol, symbol, kind, path).equal is not True


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
    "kind,path,producer",
    [("Glue.Crawler", "Role", "IAM.Role"), ("ECS.Service", "Cluster", "ECS.Cluster")],
)
def test_new_multiple_attribute_contract_does_not_guess_legacy_link(
    kind, path, producer
):
    comparison = fixture()
    resource(comparison, "producer", "001", producer, "Producer", [])
    with pytest.raises(Blocked):
        comparison.desired_reference(
            "producer",
            model_ref(producer.replace(".", "_") + "_001", "Unknown"),
            kind,
            path,
        )


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
    "kind,path,desired,prefix",
    [
        ("EC2.Subnet", "VpcId", "vpc-123abc", "vpc-"),
        ("Lambda.Function", "Code.S3Bucket", "bucket-123abc", "bucket-"),
    ],
)
@pytest.mark.parametrize("form", ["ref", "sub", "map", "join", "if", "import"])
def test_unresolved_expression_is_uncompared_for_other_resources(
    kind, path, desired, prefix, form
):
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Value": {"Type": "String"}}
    document["Conditions"] = {"Active": {"Fn::Equals": ["yes", "yes"]}}
    parameters["Value"] = "PENDING_DEPLOY"
    expression = {
        "ref": {"Ref": "Value"},
        "sub": {"Fn::Sub": prefix + "${Value}"},
        "map": {"Fn::Sub": [prefix + "${Id}", {"Id": {"Ref": "Value"}}]},
        "join": {"Fn::Join": ["", [prefix, {"Ref": "Value"}]]},
        "if": {"Fn::If": ["Active", {"Ref": "Value"}, desired]},
        "import": {"Fn::ImportValue": {"Fn::Sub": "External${Value}"}},
    }[form]
    records = setting(comparison, kind, path, desired, expression)
    assert [record["category"] for record in records] == ["uncompared"], records


@pytest.mark.parametrize("condition", ["active", "unresolved"])
def test_unresolved_condition_and_unselected_branch(condition):
    comparison = fixture()
    document, parameters, _ = comparison.stack_inputs["producer"]
    document["Parameters"] = {"Value": {"Type": "String"}}
    parameters["Value"] = "PENDING_DEPLOY"
    document["Conditions"] = {
        "Choose": {
            "Fn::Equals": ["yes", "yes"]
            if condition == "active"
            else [{"Ref": "Value"}, "yes"]
        }
    }
    expression = {
        "Fn::If": [
            "Choose",
            "vpc-123abc",
            "vpc-456def" if condition == "unresolved" else {"Ref": "Value"},
        ]
    }
    records = setting(comparison, "EC2.Subnet", "VpcId", "vpc-123abc", expression)
    assert [record["category"] for record in records] == (
        ["matched"] if condition == "active" else ["uncompared"]
    ), records


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
