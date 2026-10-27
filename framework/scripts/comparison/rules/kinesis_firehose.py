"""Static KinesisFirehose comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "KinesisFirehose.DeliveryStream": properties(
        objects="""
            DeliveryStreamEncryptionConfigurationInput
            S3DestinationConfiguration
            S3DestinationConfiguration.BufferingHints
            S3DestinationConfiguration.CloudWatchLoggingOptions
            S3DestinationConfiguration.EncryptionConfiguration
            S3DestinationConfiguration.EncryptionConfiguration.KMSEncryptionConfig
            Tags[]
        """,
        scalars="""
            DeliveryStreamEncryptionConfigurationInput.KeyARN
            DeliveryStreamEncryptionConfigurationInput.KeyType
            DeliveryStreamName
            DeliveryStreamType
            S3DestinationConfiguration.BucketARN
            S3DestinationConfiguration.BufferingHints.IntervalInSeconds
            S3DestinationConfiguration.BufferingHints.SizeInMBs
            S3DestinationConfiguration.CloudWatchLoggingOptions.Enabled
            S3DestinationConfiguration.CloudWatchLoggingOptions.LogGroupName
            S3DestinationConfiguration.CloudWatchLoggingOptions.LogStreamName
            S3DestinationConfiguration.CompressionFormat
            S3DestinationConfiguration.EncryptionConfiguration.KMSEncryptionConfig.AWSKMSKeyARN
            S3DestinationConfiguration.EncryptionConfiguration.NoEncryptionConfig
            S3DestinationConfiguration.ErrorOutputPrefix
            S3DestinationConfiguration.Prefix
            S3DestinationConfiguration.RoleARN
            Tags[].Key
            Tags[].Value
        """,
        tags="""
            Tags
        """,
    ),
}
