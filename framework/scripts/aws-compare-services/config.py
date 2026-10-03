"""config: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Config.ConfigurationRecorder', 'Config.DeliveryChannel')
APIS = {('config', 'describe_configuration_recorders'), ('config', 'describe_delivery_channels'), ('iam', 'get_role')}
IDENTITIES = {'Config.ConfigurationRecorder': ('recorder', 'name', None, 'Name'), 'Config.DeliveryChannel': ('channel', 'name', None, 'Name')}
FIELDS = {}
FIELDS.update(fields('Config.ConfigurationRecorder', 'recorder', {
    'Id': 'name',
    'Name': 'name',
    'RecordingGroup.AllSupported': 'recordingGroup.allSupported',
    'RecordingGroup.ExclusionByResourceTypes.ResourceTypes': 'recordingGroup.exclusionByResourceTypes.resourceTypes',
    'RecordingGroup.IncludeGlobalResourceTypes': 'recordingGroup.includeGlobalResourceTypes',
    'RecordingGroup.RecordingStrategy.UseOnly': 'recordingGroup.recordingStrategy.useOnly',
    'RecordingGroup.ResourceTypes': 'recordingGroup.resourceTypes',
    'RecordingMode.RecordingFrequency': 'recordingMode.recordingFrequency',
    'RoleARN': 'roleARN',
}, norms={'RoleARN': 'iam_role', 'RecordingGroup.ResourceTypes': 'set', 'RecordingGroup.ExclusionByResourceTypes.ResourceTypes': 'set'}, defaults={'RecordingGroup.ResourceTypes': [], 'RecordingGroup.ExclusionByResourceTypes.ResourceTypes': []}))
FIELDS.update(fields('Config.DeliveryChannel', 'channel', {
    'Name': 'name',
    'S3BucketName': 's3BucketName',
}, norms={'S3BucketName': 'name'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter == 'recorder':
        return one(ctx.call('config', 'describe_configuration_recorders', ConfigurationRecorderNames=[r.value('Name')]).get('ConfigurationRecorders', []), 'config.describe_configuration_recorders')
    return one(ctx.call('config', 'describe_delivery_channels', DeliveryChannelNames=[r.value('Name')]).get('DeliveryChannels', []), 'config.describe_delivery_channels')
