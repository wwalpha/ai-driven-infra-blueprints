"""ARN assembly owns format/default/context/generated-ID checks, without Model or IaC."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from utils.arn_values import named_arn
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


PSEUDO = {
    "AWS::Partition": "aws",
    "AWS::Region": "ap-northeast-1",
    "AWS::AccountId": "123456789012",
}
KEY = "12345678-1234-1234-1234-123456789012"


def identity(value):
    return value


def assemble(kind, properties, pseudo=None, **kwargs):
    return named_arn(
        kind,
        properties,
        PSEUDO if pseudo is None else pseudo,
        evaluate=identity,
        schema=kwargs.pop("schema", {}),
        **kwargs,
    )


@pytest.mark.parametrize(
    "kind,properties,expected",
    [
        ("S3.Bucket", {"BucketName": "fixture-bucket"}, "arn:aws:s3:::fixture-bucket"),
        ("IAM.Role", {"RoleName": "fixture"}, "arn:aws:iam::123456789012:role/fixture"),
        (
            "Events.Rule",
            {"Name": "fixture"},
            "arn:aws:events:ap-northeast-1:123456789012:rule/fixture",
        ),
        (
            "Events.Rule",
            {"Name": "fixture", "EventBusName": "custom"},
            "arn:aws:events:ap-northeast-1:123456789012:rule/custom/fixture",
        ),
        (
            "Glue.Table",
            {
                "CatalogId": "123456789012",
                "TableInput": {"Name": "fixture"},
                "DatabaseName": "db",
            },
            "arn:aws:glue:ap-northeast-1:123456789012:table/db/fixture",
        ),
        (
            "NetworkFirewall.RuleGroup",
            {"RuleGroupName": "fixture", "Type": "STATEFUL"},
            "arn:aws:network-firewall:ap-northeast-1:123456789012:stateful-rulegroup/fixture",
        ),
    ],
)
def test_named_arns(kind, properties, expected):
    assert assemble(kind, properties) == expected


@pytest.mark.parametrize("field", ["Partition", "Region", "AccountId"])
@pytest.mark.parametrize(
    "value", [None, "", "UNSET", "${Unresolved}", 123, "invalid:context"]
)
def test_context_requires_proof(field, value):
    pseudo = dict(PSEUDO)
    pseudo["AWS::" + field] = value
    with pytest.raises(Blocked, match=field):
        assemble("CodeBuild.Project", {"Name": "fixture"}, pseudo)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "UNSET",
        "PENDING_DEPLOY",
        "TBD",
        "TODO",
        "bad name",
        "bad*name",
        "${name}",
        "{{resolve:name}}",
        123,
        {},
    ],
)
def test_invalid_identity(value):
    with pytest.raises(Blocked):
        assemble("S3.Bucket", {"BucketName": value})


def test_s3_needs_no_account_or_region():
    assert (
        assemble(
            "S3.Bucket", {"BucketName": "fixture-bucket"}, {"AWS::Partition": "aws"}
        )
        == "arn:aws:s3:::fixture-bucket"
    )


def test_generated_identity_requires_recording():
    schema = {"readOnlyProperties": ["/properties/KeyId"]}
    with pytest.raises(Blocked, match="generated identifier"):
        assemble("KMS.Key", {"KeyId": KEY}, schema=schema)
    assert (
        assemble("KMS.Key", {}, schema=schema, recorded=dict(KeyId=KEY).get)
        == "arn:aws:kms:ap-northeast-1:123456789012:key/" + KEY
    )
    with pytest.raises(Blocked, match="format"):
        assemble("KMS.Key", {}, schema=schema, recorded={}.get)


def test_symbolic_reference_keeps_validated_context():
    value = assemble("S3.Bucket", {"BucketName": "fixture-bucket"}, reference=identity)
    assert isinstance(value, Expression)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
