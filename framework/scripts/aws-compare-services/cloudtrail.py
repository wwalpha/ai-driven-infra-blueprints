"""cloudtrail: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('CloudTrail.Trail',)
APIS = {('cloudtrail', 'get_trail_status'), ('cloudtrail', 'get_trail'), ('cloudtrail', 'get_event_selectors')}
IDENTITIES = {'CloudTrail.Trail': ('base', 'Name', 'TrailARN', 'TrailName')}
FIELDS = {}
FIELDS.update(fields('CloudTrail.Trail', 'base', {
    'CloudWatchLogsLogGroupArn': 'CloudWatchLogsLogGroupArn',
    'CloudWatchLogsRoleArn': 'CloudWatchLogsRoleArn',
    'EnableLogFileValidation': 'LogFileValidationEnabled',
    'IncludeGlobalServiceEvents': 'IncludeGlobalServiceEvents',
    'IsMultiRegionTrail': 'IsMultiRegionTrail',
    'KMSKeyId': 'KmsKeyId',
    'S3BucketName': 'S3BucketName',
    'TrailName': 'Name',
}, norms={'KMSKeyId': 'kms', 'CloudWatchLogsLogGroupArn': 'log_group_arn', 'CloudWatchLogsRoleArn': 'arn', 'S3BucketName': 'name'}))
FIELDS.update(fields('CloudTrail.Trail', 'status', {
    'IsLogging': 'IsLogging',
}))
FIELDS.update(fields('CloudTrail.Trail', 'selectors', {
    'EventSelectors[].DataResources[].Type': 'EventSelectors[].DataResources[].Type',
    'EventSelectors[].DataResources[].Values': 'EventSelectors[].DataResources[].Values',
    'EventSelectors[].IncludeManagementEvents': 'EventSelectors[].IncludeManagementEvents',
    'EventSelectors[].ReadWriteType': 'EventSelectors[].ReadWriteType',
}, norms={'EventSelectors[].DataResources[].Values': 'arn'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    name = r.value('TrailName')
    if getter == 'base':
        return ctx.call('cloudtrail', 'get_trail', Name=name)['Trail']
    if getter == 'status':
        return ctx.call('cloudtrail', 'get_trail_status', Name=name)
    return ctx.call('cloudtrail', 'get_event_selectors', TrailName=name)
