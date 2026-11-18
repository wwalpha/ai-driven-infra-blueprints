"""KinesisFirehose reference declarations."""

from ..reference_data import ReferenceTables

REFERENCES = ReferenceTables(
    ref_attributes={
        "KinesisFirehose.DeliveryStream": "DeliveryStreamName",
    },
    import_properties={
        "KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN": (
            "KMS.Key",
            "Arn",
        ),
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN": (
            "S3.Bucket",
            "Arn",
        ),
        "KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN": (
            "IAM.Role",
            "Arn",
        ),
        "KinesisFirehose.DeliveryStream.ExtendedS3DestinationConfiguration.BucketARN": (
            "S3.Bucket",
            "Arn",
        ),
        "KinesisFirehose.DeliveryStream.ExtendedS3DestinationConfiguration.RoleARN": (
            "IAM.Role",
            "Arn",
        ),
    },
    arn_shapes={
        "KinesisFirehose.DeliveryStream": (
            "DeliveryStreamName",
            "arn:{partition}:firehose:{region}:{account}:deliverystream/{id}",
            {"id": r"[A-Za-z0-9_.-]{1,64}"},
        ),
    },
)
