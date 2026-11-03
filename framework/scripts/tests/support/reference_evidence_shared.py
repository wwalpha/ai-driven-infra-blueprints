"""Offline reference proof through the shared evaluator and comparison pipeline."""

import copy
import json
import sys
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison import Comparison
from comparison.references import ReferenceDecision
from design.catalog import DesignSchemaCatalog
from model.sources import ModelSnapshot, Scope
from support.comparison_cases import projected
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import put_row
from utils.iac_values import (
    Expression,
    ResourceReference,
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


def kms_key(comparison):
    return resource(
        comparison,
        "kms",
        "001",
        "KMS.Key",
        "Key",
        [("KeyId", "PENDING_DEPLOY", KEY_ID)],
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


def codebuild_batch(comparison, document):
    return comparison.compare_rows(
        "codebuild",
        "001",
        comparison.resources["codebuild"]["001"],
        "producer",
        "Build",
        ROOT / "synthetic.yaml",
        document["Resources"]["Build"],
        document,
    )


def _sg_reference_result(comparison):
    try:
        result = comparison.evaluate("producer", {"Ref": "Group"})
    except (Blocked, ValueError) as failure:
        return {"error": {"type": type(failure).__name__, "message": str(failure)}}
    TestCase().assertEqual(result["$attribute"], "GroupId")
    return {"attribute": result["$attribute"]}


def reference_for(comparison, kind, left, right, path):
    return comparison.reference_same(left, right, kind, path)


def _portable_synthetic_root(comparison):
    comparison.root = Path("synthetic-project")
    comparison.models = {
        name: replace(model, scope=replace(model.scope, root=comparison.root))
        for name, model in comparison.models.items()
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


def typed_duplicate_reference(comparison, outcomes, left, right, path):
    if not isinstance(right, (ResourceReference, Expression)):
        return ReferenceDecision(NotImplemented)
    equal = next(outcomes)
    detail = comparison.reference_diagnostic(left, right, "KMS.Key", path, "fixture")
    detail["local_comparison"] = "matched" if equal is True else "uncompared"
    return ReferenceDecision(equal, (detail,))
