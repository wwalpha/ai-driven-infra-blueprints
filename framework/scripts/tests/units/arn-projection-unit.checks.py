"""ARN projection combinations live here; callers test wiring and evidence only."""

import copy
import json
import sys
from functools import partial
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.arn_projection import project as project_arn
from comparison.methods import compare_values
from model.identity import COUNTERS
from services.registry import REGISTRY
from services.s3.references import SSE_KMS_KEY_CONDITIONS
from support.model_reference_fixtures import (
    FRAMEWORK,
    comparison,
    project,
    resource,
    resource_values,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


KMS_FORMS = {
    kind + "." + path: forms
    for kind in REGISTRY
    if (receiver := REGISTRY.receiver(kind))
    for path, forms in receiver.format_limits.items()
}


PREFIX = "arn:aws:kms:ap-northeast-1:123456789012:"
KEY_ID = "12345678-1234-1234-1234-123456789012"


def cached_stack(inputs, unit):
    return inputs.root / "synthetic.yaml", inputs.stack_inputs[unit["name"]]


def reference(identity="002", attribute="AliasArn"):
    return ResourceReference({"$resource": ["kms", identity], "$attribute": attribute})


def construction(source=None, *, prefix=PREFIX, suffix="", operation="Sub"):
    source = reference(attribute="AliasName") if source is None else source
    if operation == "Sub":
        return Expression("Sub", [prefix + "${R}" + suffix, {"R": source}])
    return Expression("Join", ["", [prefix, source, suffix]])


@pytest.fixture
def inputs(tmp_path):
    with (
        mapping_alias(FRAMEWORK, tmp_path),
        patch("socket.socket", side_effect=AssertionError("network forbidden")),
    ):
        _, values, _, _ = project(tmp_path)
        for identity in ("002", "003"):
            scope, alias = resource(
                tmp_path, "kms", "KMS.Alias", number=identity, attribute="AliasName"
            )
            alias[f"desired.row.{identity}-001.value"] = "`alias/fixture`"
            values.update(alias)
        scope, key = resource_values(tmp_path, "kms", "KMS.Key", number="004")
        values.update(key)
        values[COUNTERS] = json.dumps({"KMS.Key": 4, "KMS.Alias": 3})
        save(scope, values)
        result = comparison(tmp_path)
        result.stack = partial(cached_stack, result)
        result.stack_inputs["producer"][0]["Resources"].update(
            {
                "Resource004": {"Type": "AWS::KMS::Key"},
                "Resource002": {
                    "Type": "AWS::KMS::Alias",
                    "Properties": {"AliasName": "alias/fixture"},
                },
                "Resource003": {
                    "Type": "AWS::KMS::Alias",
                    "Properties": {"AliasName": "alias/fixture"},
                },
            }
        )
        yield result


@pytest.mark.parametrize(
    "identity,source,projected,tail",
    [("002", "AliasName", "AliasArn", ""), ("001", "KeyId", "Arn", "key/")],
)
@pytest.mark.parametrize("operation", ["Sub", "Join", "nested"])
def test_projection_and_symbolic_comparison(
    inputs, identity, source, projected, tail, operation
):
    value = construction(
        reference(identity, source),
        prefix=PREFIX + tail,
        operation="Join" if operation == "Join" else "Sub",
    )
    if operation == "nested":
        value = Expression("Join", ["", [Expression("Sub", ["${R}", {"R": value}])]])
    before = copy.deepcopy(value)
    expected = reference(identity, projected)
    assert inputs.project_arn(value) == expected
    decision = inputs.reference_decision(expected, value, "Logs.LogGroup", "KmsKeyId")
    assert (
        decision.equal is True
        and decision.diagnostics[0]["current_aws_verified"] is False
    )
    assert decision.diagnostics[0]["evidence_type"] == "logical_reference"
    assert value == before
    if source == "KeyId":
        assert (
            inputs.reference_decision(
                PREFIX + "key/" + KEY_ID, value, "Logs.LogGroup", "KmsKeyId"
            ).equal
            is None
        )


@pytest.mark.parametrize("prop", list(KMS_FORMS))
def test_projection_only_uses_registered_receiving_forms(inputs, prop):
    kind, path = ".".join(prop.split(".")[:2]), ".".join(prop.split(".")[2:])
    decision = inputs.reference_decision(reference(), construction(), kind, path)
    assert decision.equal is ("AliasArn" in KMS_FORMS[prop])
    with patch.object(
        inputs,
        "project_arn",
        side_effect=AssertionError("unregistered receiving property"),
    ):
        assert (
            inputs.reference_decision(
                reference(), construction(), "Glue.Job", "DefaultArguments"
            ).equal
            is True
        )


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("extra/" + PREFIX, ""),
        (PREFIX, "/extra"),
        (PREFIX, ":"),
        (PREFIX.replace("arn:aws:", "arn:aws-cn:"), ""),
        (PREFIX.replace("ap-northeast-1", "us-east-1"), ""),
        (PREFIX.replace("123456789012", "999999999999"), ""),
    ],
)
def test_unproven_shape_or_scope_never_falls_back(inputs, prefix, suffix):
    value = construction(prefix=prefix, suffix=suffix)
    assert inputs.project_arn(value) is None
    for left, right in [(reference(), value), (value, copy.deepcopy(value))]:
        assert (
            inputs.reference_decision(left, right, "Logs.LogGroup", "KmsKeyId").equal
            is None
        )
    assert (
        inputs.reference_decision(
            prefix + "alias/fixture" + suffix, value, "Logs.LogGroup", "KmsKeyId"
        ).equal
        is not True
    )


def test_different_producers_with_equal_names_cannot_match(inputs):
    value = construction(reference("003", "AliasName"))
    decision = inputs.reference_decision(
        reference(), value, "Logs.LogGroup", "KmsKeyId"
    )
    assert decision.equal is False
    assert "different KMS ARN Producer" in decision.diagnostics[0]["reason"]
    other = construction()
    assert (
        inputs.reference_decision(other, value, "Logs.LogGroup", "KmsKeyId").equal
        is False
    )


@pytest.mark.parametrize(
    "field,old,new",
    [
        ("Partition", "aws", "aws-cn"),
        ("Region", "ap-northeast-1", "us-east-1"),
        ("AccountId", "123456789012", "999999999999"),
    ],
)
def test_projection_uses_producer_context_without_borrowing_consumer_context(
    inputs, field, old, new
):
    document, parameters, pseudo = inputs.stack_inputs["producer"]
    inputs.stack_inputs["producer"] = (
        document,
        parameters,
        dict(pseudo, **{"AWS::" + field: new}),
    )
    assert inputs.project_arn(construction()) is None
    value = construction(prefix=PREFIX.replace(old, new, 1))
    assert inputs.project_arn(value) == reference()
    assert (
        inputs.reference_decision(reference(), value, "Logs.LogGroup", "KmsKeyId").equal
        is True
    )


def test_saved_reference_evidence_is_checked_before_projection(inputs):
    source = reference(attribute="AliasName")
    source.saved_literal = "alias/fixture"
    source.saved_property = "KMS.Alias.AliasName"
    source.declared_format = "identifier"
    decision = inputs.reference_decision(
        reference(), construction(source), "Logs.LogGroup", "KmsKeyId"
    )
    assert decision.equal is not True
    assert decision.diagnostics


def test_key_and_alias_arn_are_different(inputs):
    value = construction(reference("001", "KeyId"), prefix=PREFIX + "key/")
    assert (
        inputs.reference_decision(reference(), value, "Logs.LogGroup", "KmsKeyId").equal
        is False
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "import",
        "stack",
        "duplicate",
        "type",
        "transform",
        "condition",
        "partition",
        "region",
        "account",
    ],
)
def test_producer_scope_requires_the_owning_stack(inputs, fault):
    document, parameters, pseudo = inputs.stack_inputs["producer"]
    # Consumer context remains valid and must never substitute for the Producer.
    pseudo = dict(pseudo)
    inputs.stack_inputs["producer"] = document, parameters, pseudo
    if fault in {"partition", "region", "account"}:
        pseudo.pop(
            {
                "partition": "AWS::Partition",
                "region": "AWS::Region",
                "account": "AWS::AccountId",
            }[fault]
        )
    elif fault == "missing":
        source = reference("999", "AliasName")
        assert (
            inputs.reference_decision(
                reference(), construction(source), "Logs.LogGroup", "KmsKeyId"
            ).equal
            is None
        )
        return
    elif fault == "import":
        inputs.resources["kms"]["002"]["resourceMode"] = "IMPORT"
    elif fault == "stack":
        inputs._templates = []
    elif fault == "duplicate":
        inputs._index = dict(inputs.index())
        inputs._index["producer", "Resource002"].append(
            inputs._index["producer", "Resource003"][0]
        )
    elif fault == "type":
        document["Resources"]["Resource002"]["Type"] = "AWS::KMS::Key"
    elif fault == "transform":
        document["Transform"] = "Unknown"
    else:
        document["Resources"]["Resource002"]["Condition"] = "Unknown"
    assert inputs.project_arn(construction()) is None
    assert (
        inputs.reference_decision(
            reference(), construction(), "Logs.LogGroup", "KmsKeyId"
        ).equal
        is None
    )


@pytest.mark.parametrize(
    "value",
    [
        Expression("Sub", ["${Unknown}", {}]),
        Expression("Future", []),
        Expression("Select", [0, Expression("Split", [":", reference()])]),
        construction(Expression("Unverified", [])),
        Expression(
            "Join",
            [
                "",
                [
                    PREFIX,
                    reference(attribute="AliasName"),
                    reference("003", "AliasName"),
                ],
            ],
        ),
        Expression(
            "Sub",
            [
                PREFIX + "${R}",
                {
                    "R": reference(attribute="AliasName"),
                    "Other": reference("003", "AliasName"),
                },
            ],
        ),
        construction(reference(attribute="TargetKeyId")),
    ],
)
def test_incomplete_or_unregistered_expressions_are_uncompared(inputs, value):
    assert inputs.project_arn(value) is None
    assert (
        inputs.reference_decision(reference(), value, "Logs.LogGroup", "KmsKeyId").equal
        is None
    )
    assert (
        inputs.reference_decision(
            value, copy.deepcopy(value), "Logs.LogGroup", "KmsKeyId"
        ).equal
        is not True
    )


@pytest.mark.parametrize("operation", ["direct", "Sub", "Join", "literal"])
def test_existing_reference_and_literal_results(inputs, operation):
    symbol = reference()
    value = {
        "direct": symbol,
        "Sub": Expression("Sub", ["${R}", {"R": symbol}]),
        "Join": Expression("Join", ["", [symbol]]),
        "literal": PREFIX + "alias/fixture",
    }[operation]
    assert (
        inputs.reference_decision(symbol, value, "Logs.LogGroup", "KmsKeyId").equal
        is True
    )
    assert (
        inputs.reference_decision(
            PREFIX + "alias/fixture", value, "Logs.LogGroup", "KmsKeyId"
        ).equal
        is True
    )


def test_alias_arn_projection_does_not_authorize_getatt(inputs):
    assert inputs.project_arn(construction()) == reference()
    with pytest.raises(Blocked, match="GetAtt"):
        inputs.evaluate("producer", {"Fn::GetAtt": ["Resource002", "AliasArn"]})


def test_normalizer_reuses_a_non_kms_shape_without_enabling_a_service():
    symbol = ResourceReference(
        {"$resource": ["bucket", "001"], "$attribute": "BucketName"}
    )
    value = Expression("Join", ["", ["arn:aws:s3:::", symbol]])
    result = project_arn(
        value,
        resource_type=lambda value: "S3.Bucket",
        producer_scope=lambda value: {
            "partition": "aws",
            "region": "ap-northeast-1",
            "account": "123456789012",
        },
    )
    assert result == ResourceReference(
        {"$resource": ["bucket", "001"], "$attribute": "Arn"}
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


@pytest.mark.parametrize(
    "kind,path",
    [
        ("CodeBuild.Project", "EncryptionKey"),
        ("IAM.Role", "Policies[].PolicyDocument.Statement[].Resource"),
        (
            "S3.Bucket",
            "BucketEncryption.ServerSideEncryptionConfiguration[]."
            "ServerSideEncryptionByDefault.KMSMasterKeyID",
        ),
    ],
)
def test_constructed_key_arn_in_normal_comparison(inputs, kind, path):
    expected = reference("001", "Arn")
    key_id = reference("001", "KeyId")
    prefix = PREFIX + "key/"
    assert (
        inputs.reference_same(expected, construction(key_id, prefix=prefix), kind, path)
        is True
    )
    other = construction(reference("004", "KeyId"), prefix=prefix)
    assert inputs.reference_same(expected, other, kind, path) is not True
    for wrong_prefix in (
        prefix.replace("aws:", "aws-cn:"),
        prefix.replace("ap-northeast-1", "us-east-1"),
        prefix.replace("123456789012", "999999999999"),
    ):
        assert (
            inputs.reference_same(
                expected, construction(key_id, prefix=wrong_prefix), kind, path
            )
            is not True
        )


@pytest.mark.parametrize("property_name", SSE_KMS_KEY_CONDITIONS)
def test_s3_key_condition_preserves_exact_forms(inputs, property_name):
    kind = "S3.BucketPolicy"
    path = property_name.removeprefix(kind + ".")
    arn = reference("001", "Arn")
    key_id = reference("001", "KeyId")
    selection = Expression("Select", [1, Expression("Split", ["/", arn])])
    constructed = construction(key_id, prefix=PREFIX + "key/")
    assert inputs.reference_forms(kind, path) == {"Arn", "KeyId"}
    assert inputs.reference_same(selection, key_id, kind, path) is True
    assert inputs.reference_same(arn, constructed, kind, path) is True
    assert inputs.reference_same(arn, key_id, kind, path) is False
    assert inputs.reference_same(selection, constructed, kind, path) is False
    assert (
        inputs.reference_same(selection, reference("004", "KeyId"), kind, path) is False
    )
    for index, delimiter, source in (
        (0, "/", arn),
        (1, ":", arn),
        (1, "/", reference()),
    ):
        invalid = Expression(
            "Select", [index, Expression("Split", [delimiter, source])]
        )
        assert inputs.reference_same(invalid, key_id, kind, path) is not True
    outside = path.replace("StringNotEquals", "StringEquals")
    assert inputs.reference_same(selection, key_id, kind, outside) is not True


@pytest.mark.parametrize(
    "target", ["QuarantinePipelineTarget", "ReleasePipelineTarget"]
)
def test_eventbridge_compares_codepipeline_targets(inputs, target):
    kind = "Events.Rule"
    scope, pipeline = resource_values(
        inputs.root, "codepipeline", "CodePipeline.Pipeline", number="005"
    )
    pipeline["desired.row.005-001.property"] = "CodePipeline.Pipeline.Name"
    pipeline["desired.row.005-001.value"] = "`fixture-pipeline`"
    save(scope, pipeline)
    inputs.model("codepipeline")
    inputs.resources["iam"]["006"] = {"resourceType": "IAM.Role"}
    inputs.stack_inputs["producer"][0]["Resources"].update(
        {
            "Resource005": {
                "Type": "AWS::CodePipeline::Pipeline",
                "Properties": {"Name": "fixture-pipeline"},
            },
        }
    )
    pipeline_name = ResourceReference(
        {"$resource": ["codepipeline", "005"], "$attribute": "Name"}
    )
    role_arn = ResourceReference({"$resource": ["iam", "006"], "$attribute": "Arn"})
    prefix = PREFIX.replace(":kms:", ":codepipeline:")
    model_arn = construction(pipeline_name, prefix=prefix)
    iac_arn = Expression(
        "Sub",
        [
            "arn:${Partition}:codepipeline:${Region}:${Account}:${Pipeline}",
            {
                "Partition": "aws",
                "Region": "ap-northeast-1",
                "Account": "123456789012",
                "Pipeline": pipeline_name,
            },
        ],
    )
    settings = {
        "Id": target,
        "RoleArn": role_arn,
        "InputTransformer": {
            "InputPathsMap": {"key": "$.detail.object.key"},
            "InputTemplate": '{"key":"<key>"}',
        },
    }
    desired = {"Arn": model_arn, **settings}
    actual = {"Arn": iac_arn, **settings}

    def compare():
        return compare_values(
            [desired],
            [actual],
            "Targets",
            rules=REGISTRY.require_comparison(kind),
            whole=True,
            reference=lambda left, right, path: inputs.reference_decision(
                left, right, kind, path
            ),
        ).equal

    assert compare() is True
    actual["InputTransformer"] = dict(settings["InputTransformer"], InputTemplate="{}")
    assert compare() is False
