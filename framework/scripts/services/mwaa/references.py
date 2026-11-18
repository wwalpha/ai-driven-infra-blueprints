"""MWAA reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    linked_subnets={
        "MWAA.Environment.NetworkConfiguration.SubnetIds",
    },
    reference_forms={
        "MWAA.Environment.KmsKey": {"KeyId", "Arn", "AliasName"},
    },
    reference_properties={
        "MWAA.Environment.KmsKey": (("KMS.Key", "KMS.Alias"), None),
        "MWAA.Environment.NetworkConfiguration.SecurityGroupIds[]": (
            "EC2.SecurityGroup",
            "GroupId",
        ),
        "MWAA.Environment.NetworkConfiguration.SubnetIds[]": ("EC2.Subnet", "SubnetId"),
    },
    import_properties={
        "MWAA.Environment.ExecutionRoleArn": ("IAM.Role", "Arn"),
        "MWAA.Environment.SourceBucketArn": ("S3.Bucket", "Arn"),
    },
    arn_shapes={
        "MWAA.Environment": (
            "Name",
            "arn:{partition}:airflow:{region}:{account}:environment/{id}",
            {"id": r"[A-Za-z][A-Za-z0-9_-]{0,79}"},
        ),
    },
)
