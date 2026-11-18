"""Reference scope and producer identities exposed by the Wave 2 registry."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from services.contracts import ReferenceMode
from services.reference_engine import ReferenceEngine
from services.registry import REGISTRY
from support.pytest_cli import run


@pytest.mark.parametrize(
    ("kind", "path", "producer", "design_form"),
    [
        ("Config.ConfigurationRecorder", "RoleARN", "IAM.Role", "RoleName"),
        (
            "KinesisFirehose.DeliveryStream",
            "DeliveryStreamEncryptionConfigurationInput.KeyARN",
            "KMS.Key",
            "KeyId",
        ),
        (
            "KinesisFirehose.DeliveryStream",
            "S3DestinationConfiguration.BucketARN",
            "S3.Bucket",
            "BucketName",
        ),
        (
            "KinesisFirehose.DeliveryStream",
            "S3DestinationConfiguration.RoleARN",
            "IAM.Role",
            "RoleName",
        ),
        (
            "QuickSight.DataSource",
            "Permissions[2].Principal",
            "QuickSight.Group",
            "GroupName",
        ),
    ],
)
def check_design_and_import_keep_distinct_attributes(kind, path, producer, design_form):
    engine = ReferenceEngine()
    definition = REGISTRY.design(kind)["RESOURCE_REFERENCE_PROPERTIES"]
    assert definition[kind + "." + re.sub(r"\[\d+\]", "[]", path)] == (
        producer,
        design_form,
    )
    assert engine.receiver_forms(kind, path, mode=ReferenceMode.IMPORT) == {
        producer: ("Arn",)
    }
    assert not engine.allows(
        kind, path, producer, design_form, mode=ReferenceMode.IMPORT
    )


def check_kms_producer_and_receiver_ownership():
    engine = ReferenceEngine()
    assert REGISTRY.owner("KMS.Key") == "kms"
    assert REGISTRY.producer("KMS.Key").format_names == {"Arn": "KeyArn"}
    assert REGISTRY.producer("KMS.Alias").format_names == {"Arn": "AliasArn"}
    assert engine.model_attribute("KMS.Alias", "Arn") == "AliasArn"
    kind = "Logs.LogGroup"
    path = "KmsKeyId"
    assert REGISTRY.owner(kind) == "logs"
    assert REGISTRY.comparison_property_rule(kind, path).forms == {"KeyArn", "AliasArn"}
    for mode in ReferenceMode:
        assert engine.receiver_forms(kind, path, mode=mode) == {
            "KMS.Key": ("Arn",),
            "KMS.Alias": ("Arn",),
        }
    assert (
        engine.allows(kind, path, "KMS.Alias", "AliasName", mode=ReferenceMode.IMPORT)
        is False
    )
    athena = "WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey"
    assert engine.receiver_forms(
        "Athena.WorkGroup", athena, mode=ReferenceMode.IMPORT
    ) == {"KMS.Key": ("Arn",)}


def check_secret_and_s3_producer_shapes():
    secret = REGISTRY.producer("SecretsManager.Secret")
    assert secret.attribute_for("Arn") == "Id"
    assert secret.attribute_for("Name") == "Name"
    assert (
        re.fullmatch(secret.value_identities["Name"], "secret-name:AWSCURRENT")["id"]
        == "secret-name"
    )
    s3 = REGISTRY.producer("S3.Bucket")
    assert s3.attribute_suffixes["ObjectArn"] == ("Arn", "/")
    attribute, pattern = REGISTRY.arn("S3.Bucket").forms["ObjectArn"]
    assert attribute == "BucketName"
    assert re.fullmatch(pattern, "arn:aws:s3:::a-bucket/path")["id"] == "a-bucket"
    assert re.fullmatch(pattern, "arn:aws:s3:::a-bucket/*") is None


def check_lambda_context_and_comparison_only_targets():
    engine = ReferenceEngine()
    kind = "Lambda.EventSourceMapping"
    path = "SourceAccessConfigurations[1].URI"
    hook = REGISTRY.receiver(kind).row_contexts
    rows = [
        (
            "type",
            {
                "property": kind + ".SourceAccessConfigurations[1].Type",
                "value": "`BASIC_AUTH`",
            },
        ),
        ("uri", {"property": kind + "." + path, "value": "reference"}),
    ]
    context = hook(rows)["uri"]
    assert engine.requires_context(kind, path)
    assert engine.receiver_forms(
        kind, path, mode=ReferenceMode.IMPORT, context=context
    ) == {"SecretsManager.Secret": ("Arn",)}
    assert (
        engine.receiver_forms(
            kind, path, mode=ReferenceMode.IMPORT, context={"Type": "VPC_SUBNET"}
        )
        == {}
    )
    assert engine.receiver_forms(
        "Lambda.Permission", "SourceArn", mode=ReferenceMode.COMPARISON
    ) == {"Events.Rule": ("Arn",), "S3.Bucket": ("Arn",)}


def check_iam_condition_keeps_operator_and_property_scope():
    engine = ReferenceEngine()
    kind = "IAM.Role"
    condition = "Policies[1].PolicyDocument.Statement[2].Condition."
    assert engine.receiver_forms(
        kind, condition + "ArnLike.aws:SourceArn[]", mode=ReferenceMode.IMPORT
    ) == {"S3.Bucket": ("Arn",), "SecretsManager.Secret": ("Arn",)}
    unsupported = condition + "StringEquals.aws:SourceArn[]"
    assert engine.requires_context(kind, unsupported)
    assert engine.receiver_forms(kind, unsupported, mode=ReferenceMode.IMPORT) is None


if __name__ == "__main__":
    raise SystemExit(run(__file__))
