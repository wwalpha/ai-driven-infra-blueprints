"""ECR reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "ECR.Repository": "RepositoryName",
    },
    reference_forms={
        "ECR.Repository.EncryptionConfiguration.KmsKey": {"KeyId", "Arn", "AliasName"},
    },
    import_properties={
        "ECR.Repository.EncryptionConfiguration.KmsKey": (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
    },
    arn_shapes={
        "ECR.Repository": (
            "RepositoryName",
            "arn:{partition}:ecr:{region}:{account}:repository/{id}",
            {"id": r"(?=.{2,256}$)[a-z0-9]+(?:(?:[._/-]|__|-+)[a-z0-9]+)*"},
        ),
    },
)
