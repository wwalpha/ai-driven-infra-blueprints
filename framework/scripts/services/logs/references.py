"""Logs reference declarations."""

from ..reference_data import ReferenceTables

KMS_KEY = "Logs.LogGroup.KmsKeyId"

REFERENCES = ReferenceTables(
    ref_attributes={
        "Logs.LogGroup": "LogGroupName",
        "Logs.ResourcePolicy": "PolicyName",
        "Logs.SubscriptionFilter": "FilterName",
    },
    import_properties={
        "Logs.SubscriptionFilter.RoleArn": ("IAM.Role", "Arn"),
        KMS_KEY: (("KMS.Key", "KMS.Alias"), "Arn"),
    },
    arn_shapes={
        "Logs.LogGroup": (
            "LogGroupName",
            "arn:{partition}:logs:{region}:{account}:log-group:{id}:*",
            {"id": r"[.\-_/#A-Za-z0-9]{1,512}"},
        ),
    },
    format_limits={
        KMS_KEY: {"KeyArn", "AliasArn"},
    },
)
