"""Fixed kinesis_firehose design definitions; no display-engine dependencies."""


RESOURCE_REFERENCE_PROPERTIES = {
    'KinesisFirehose.DeliveryStream.DeliveryStreamEncryptionConfigurationInput.KeyARN': ('KMS.Key', 'KeyId'),
    'KinesisFirehose.DeliveryStream.S3DestinationConfiguration.BucketARN': ('S3.Bucket', 'BucketName'),
    'KinesisFirehose.DeliveryStream.S3DestinationConfiguration.RoleARN': ('IAM.Role', 'RoleName'),
}
