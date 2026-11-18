"""DynamoDB reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "DynamoDB.Table": "TableName",
        "DynamoDB.GlobalTable": "TableName",
    },
    reference_forms={
        "DynamoDB.Table.SSESpecification.KMSMasterKeyId": {"KeyId", "Arn", "AliasName"},
    },
    import_properties={
        "DynamoDB.Table.ImportSourceSpecification.S3BucketSource.S3Bucket": (
            "S3.Bucket",
            "BucketName",
        ),
        "DynamoDB.Table.SSESpecification.KMSMasterKeyId": (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
    },
    arn_shapes={
        "DynamoDB.Table": (
            "TableName",
            "arn:{partition}:dynamodb:{region}:{account}:table/{id}",
            {"id": r"[A-Za-z0-9_.-]{3,255}"},
        ),
        "DynamoDB.GlobalTable": (
            "TableName",
            "arn:{partition}:dynamodb:{region}:{account}:table/{id}",
            {"id": r"[A-Za-z0-9_.-]{3,255}"},
        ),
    },
)
