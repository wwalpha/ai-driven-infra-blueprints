"""S3 reference declarations."""

from ..reference_data import ReferenceTables, arn_pattern

S3_KMS_MASTER_KEY_ID = (
    "S3.Bucket.BucketEncryption.ServerSideEncryptionConfiguration[]"
    ".ServerSideEncryptionByDefault.KMSMasterKeyID"
)
SSE_KMS_KEY_CONDITIONS = tuple(
    "S3.BucketPolicy.PolicyDocument.Statement"
    + statement
    + ".Condition.StringNotEquals.s3:x-amz-server-side-encryption-aws-kms-key-id"
    + values
    for statement in ("", "[]")
    for values in ("", "[]")
)
BUCKET_ARN = (
    "BucketName",
    "arn:{partition}:s3:::{id}",
    {"id": r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"},
)

REFERENCES = ReferenceTables(
    model_attributes={"S3.Bucket": {"DomainName": "DomainName"}},
    ref_attributes={
        "S3.Bucket": "BucketName",
    },
    reference_forms={
        S3_KMS_MASTER_KEY_ID: {
            "KeyId",
            "Arn",
            "AliasName",
        },
        "S3.Bucket.ReplicationConfiguration.Rules[].Destination.EncryptionConfiguration.ReplicaKmsKeyID": {
            "Arn"
        },
    },
    reference_properties={
        "S3.Bucket.NotificationConfiguration.LambdaConfigurations[].Function": (
            "Lambda.Function",
            "Arn",
        ),
        "S3.Bucket.NotificationConfiguration.QueueConfigurations[].Queue": (
            "SQS.Queue",
            "Arn",
        ),
        "S3.Bucket.NotificationConfiguration.TopicConfigurations[].Topic": (
            "SNS.Topic",
            "Arn",
        ),
    },
    import_properties={
        "S3.BucketPolicy.Bucket": ("S3.Bucket", "BucketName"),
        "S3.Bucket.LoggingConfiguration.DestinationBucketName": (
            "S3.Bucket",
            "BucketName",
        ),
        "S3.Bucket.ReplicationConfiguration.Rules[].Destination.EncryptionConfiguration.ReplicaKmsKeyID": (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
        "S3.Bucket.ReplicationConfiguration.Rules[].Destination.Bucket": (
            "S3.Bucket",
            "Arn",
        ),
        "S3.Bucket.ReplicationConfiguration.Role": ("IAM.Role", "Arn"),
        S3_KMS_MASTER_KEY_ID: (
            ("KMS.Key", "KMS.Alias"),
            None,
        ),
    },
    arn_shapes={
        "S3.Bucket": BUCKET_ARN,
    },
    attribute_suffixes={
        ("S3.Bucket", "ObjectArn"): ("Arn", "/"),
    },
    special_properties=dict.fromkeys(SSE_KMS_KEY_CONDITIONS, ("KMS.Key", "Arn")),
    local_comparison=dict.fromkeys(
        SSE_KMS_KEY_CONDITIONS, {"KMS.Key": ("Arn", "KeyId")}
    ),
    arn_forms={
        ("S3.Bucket", "ObjectArn"): (
            "BucketName",
            arn_pattern(BUCKET_ARN) + r"/(?P<prefix>[^*]*)",
        )
    },
)
