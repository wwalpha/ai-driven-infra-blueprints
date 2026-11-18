"""Athena reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "Athena.WorkGroup": "Name",
    },
    reference_forms={
        "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": {
            "Arn"
        },
    },
    import_properties={
        "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
    },
    arn_shapes={
        "Athena.WorkGroup": (
            "Name",
            "arn:{partition}:athena:{region}:{account}:workgroup/{id}",
            {"id": r"[A-Za-z0-9._-]{1,128}"},
        ),
    },
    format_limits={
        "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey": {
            "KeyArn"
        },
    },
    unproven_document={
        "Athena.WorkGroup": (
            "Athena.WorkGroup.WorkGroupConfiguration.ResultConfiguration.OutputLocation",
        )
    },
)
