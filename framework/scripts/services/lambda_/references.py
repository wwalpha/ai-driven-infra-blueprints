"""Lambda reference declarations."""

import re
from collections.abc import Mapping

from ..reference_data import ReferenceTables

SOURCE_ACCESS_CONTAINER = "SourceAccessConfigurations[]"
_SOURCE_ACCESS = r"SourceAccessConfigurations\[\d+\]"


def row_contexts(
    rows: list[tuple[str, Mapping[str, str]]], /
) -> dict[str, dict[str, str]]:
    kind = "Lambda.EventSourceMapping"
    types: dict[str, list[str]] = {}
    for _, row in rows:
        prop = row["property"].removeprefix(kind + ".")
        if match := re.fullmatch(rf"({_SOURCE_ACCESS})\.Type", prop):
            value = row["value"]
            if value.startswith("`") and value.endswith("`"):
                value = value[1:-1]
            types.setdefault(match[1], []).append(value)
    contexts = {
        path: {"Type": values[0]} for path, values in types.items() if len(values) == 1
    }
    for identity, row in rows:
        prop = row["property"]
        if (
            match := re.fullmatch(
                rf"Lambda\.EventSourceMapping\.({_SOURCE_ACCESS})\.URI", prop
            )
        ) and match[1] in contexts:
            contexts[identity] = contexts[match[1]]
    return contexts


REFERENCES = ReferenceTables(
    ref_attributes={
        "Lambda.Function": "FunctionName",
        "Lambda.EventSourceMapping": "Id",
        "Lambda.EventInvokeConfig": "Ref",
    },
    arn_attributes={
        "Lambda.EventSourceMapping": "EventSourceMappingArn",
    },
    linked_subnets={
        "Lambda.Function.VpcConfig.SubnetIds",
    },
    reference_forms={
        "Lambda.Permission.FunctionName": {"FunctionName", "Arn"},
        "Lambda.EventSourceMapping.FunctionName": {"FunctionName", "Arn"},
    },
    reference_properties={
        "Lambda.Function.Code.S3Bucket": ("S3.Bucket", "BucketName"),
        "Lambda.Function.LoggingConfig.LogGroup": ("Logs.LogGroup", "LogGroupName"),
        "Lambda.Function.VpcConfig.SecurityGroupIds[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "Lambda.Function.VpcConfig.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
        "Lambda.Permission.FunctionName": ("Lambda.Function", "FunctionName"),
    },
    import_properties={
        "Lambda.EventSourceMapping.FunctionName": ("Lambda.Function", "FunctionName"),
        "Lambda.EventInvokeConfig.FunctionName": ("Lambda.Function", "FunctionName"),
        "Lambda.Function.Role": ("IAM.Role", "Arn"),
        "Lambda.Function.KmsKeyArn": ("KMS.Key", "Arn"),
    },
    arn_shapes={
        "Lambda.Function": (
            "FunctionName",
            "arn:{partition}:lambda:{region}:{account}:function:{id}",
            {"id": r"[A-Za-z0-9_-]{1,64}"},
        ),
    },
    context_properties={
        "Lambda.EventSourceMapping.SourceAccessConfigurations[].URI": (
            "Lambda.EventSourceMapping.SourceAccessConfigurations[].Type",
            {
                "BASIC_AUTH": ("SecretsManager.Secret", "Arn"),
                "SASL_SCRAM_256_AUTH": ("SecretsManager.Secret", "Arn"),
                "SASL_SCRAM_512_AUTH": ("SecretsManager.Secret", "Arn"),
                "CLIENT_CERTIFICATE_TLS_AUTH": ("SecretsManager.Secret", "Arn"),
                "SERVER_ROOT_CA_CERTIFICATE": ("SecretsManager.Secret", "Arn"),
            },
        ),
    },
    local_comparison={
        "Lambda.Permission.SourceArn": {"S3.Bucket": ("Arn",), "Events.Rule": ("Arn",)},
    },
    context_paths={"Lambda.EventSourceMapping": (SOURCE_ACCESS_CONTAINER,)},
    context_suffixes={"Lambda.EventSourceMapping": ("." + SOURCE_ACCESS_CONTAINER,)},
    row_contexts={"Lambda.EventSourceMapping": row_contexts},
)
