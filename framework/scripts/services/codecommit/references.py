"""CodeCommit reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    return_attribute_properties={
        ("CodeCommit.Repository", "Name"): "RepositoryName",
    },
    ref_attributes={
        "CodeCommit.Repository": "RepositoryId",
    },
    reference_forms={
        "CodeCommit.Repository.KmsKeyId": {"KeyId", "Arn", "AliasName"},
    },
    reference_properties={
        "CodeCommit.Repository.KmsKeyId": (("KMS.Key", "KMS.Alias"), None),
    },
    import_properties={
        "CodeCommit.Repository.Code.S3.Bucket": ("S3.Bucket", "BucketName"),
    },
    arn_shapes={
        "CodeCommit.Repository": (
            "RepositoryName",
            "arn:{partition}:codecommit:{region}:{account}:{id}",
            {"id": r"(?!.*\.git$)[A-Za-z0-9_.-]{1,100}"},
        ),
    },
)
