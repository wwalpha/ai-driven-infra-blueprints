"""KMS reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "KMS.Key": "KeyId",
        "KMS.Alias": "AliasName",
    },
    arn_attributes={
        "KMS.Alias": "AliasArn",
    },
    reference_forms={
        "KMS.Alias.TargetKeyId": {"KeyId", "Arn"},
    },
    import_properties={
        "KMS.Alias.TargetKeyId": (("KMS.Key",), None),
    },
    arn_shapes={
        "KMS.Key": (
            "KeyId",
            "arn:{partition}:kms:{region}:{account}:key/{id}",
            {
                "id": r"(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})"
            },
        ),
        "KMS.Alias": (
            "AliasName",
            "arn:{partition}:kms:{region}:{account}:{id}",
            {"id": r"alias/[A-Za-z0-9:/_-]+"},
        ),
    },
    type_forms={"KMS.Key": {"KeyId", "Arn"}, "KMS.Alias": {"AliasName", "Arn"}},
    format_names={"KMS.Key": {"Arn": "KeyArn"}, "KMS.Alias": {"Arn": "AliasArn"}},
)
