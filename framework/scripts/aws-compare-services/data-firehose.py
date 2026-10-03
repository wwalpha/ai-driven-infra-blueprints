"""data-firehose: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('KinesisFirehose.DeliveryStream',)
APIS = {('firehose', 'describe_delivery_stream')}
IDENTITIES = {'KinesisFirehose.DeliveryStream': ('base', 'DeliveryStreamName', 'DeliveryStreamARN', 'DeliveryStreamName')}
FIELDS = {}
FIELDS.update(fields('KinesisFirehose.DeliveryStream', 'base', {
    'DeliveryStreamEncryptionConfigurationInput.KeyType': 'DeliveryStreamEncryptionConfiguration.KeyType',
    'DeliveryStreamName': 'DeliveryStreamName',
    'DeliveryStreamType': 'DeliveryStreamType',
}))
FIELDS.update(fields('KinesisFirehose.DeliveryStream', 'destination', {
    'S3DestinationConfiguration.BucketARN': 'BucketARN',
    'S3DestinationConfiguration.BufferingHints.IntervalInSeconds': 'BufferingHints.IntervalInSeconds',
    'S3DestinationConfiguration.BufferingHints.SizeInMBs': 'BufferingHints.SizeInMBs',
    'S3DestinationConfiguration.CloudWatchLoggingOptions.Enabled': 'CloudWatchLoggingOptions.Enabled',
    'S3DestinationConfiguration.CloudWatchLoggingOptions.LogGroupName': 'CloudWatchLoggingOptions.LogGroupName',
    'S3DestinationConfiguration.CloudWatchLoggingOptions.LogStreamName': 'CloudWatchLoggingOptions.LogStreamName',
    'S3DestinationConfiguration.CompressionFormat': 'CompressionFormat',
    'S3DestinationConfiguration.ErrorOutputPrefix': 'ErrorOutputPrefix',
    'S3DestinationConfiguration.Prefix': 'Prefix',
    'S3DestinationConfiguration.RoleARN': 'RoleARN',
}, norms={'S3DestinationConfiguration.BucketARN': 'arn', 'S3DestinationConfiguration.RoleARN': 'arn', 'S3DestinationConfiguration.CloudWatchLoggingOptions.LogGroupName': 'name'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    name = r.value('DeliveryStreamName')
    record = ctx.call('firehose', 'describe_delivery_stream', DeliveryStreamName=name)['DeliveryStreamDescription']
    if getter == 'base':
        return record
    destinations = list(record.get('Destinations', []))
    seen=set()
    while record.get('HasMoreDestinations'):
        if not record.get('Destinations'):
            raise Unresolved('destination continuation is missing')
        continuation=record['Destinations'][-1]['DestinationId']
        if continuation in seen:
            raise Unresolved('destination continuation repeated')
        seen.add(continuation)
        record = ctx.call('firehose', 'describe_delivery_stream', DeliveryStreamName=name, ExclusiveStartDestinationId=continuation)['DeliveryStreamDescription']
        destinations.extend(record.get('Destinations', []))
    destination = one(destinations, 'firehose.describe_delivery_stream')
    return destination.get('ExtendedS3DestinationDescription', destination.get('S3DestinationDescription', {}))
