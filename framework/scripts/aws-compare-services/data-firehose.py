"""data-firehose: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import one, Unresolved

APIS = {('firehose', 'describe_delivery_stream')}


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


SDK_OPERATIONS = {'KinesisFirehose.DeliveryStream': 'describe_delivery_stream'}


def fetch_sdk(ctx, r, operation):
    ctx.fetch(r, 'destination')  # Validate the complete paginated destination selection.
    return ctx.call('firehose', operation, DeliveryStreamName=r.value('DeliveryStreamName'))
