"""athena: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Athena.WorkGroup',)
APIS = {('athena', 'get_work_group')}
IDENTITIES = {'Athena.WorkGroup': ('base', 'Name', None, 'Name')}
FIELDS = {}
FIELDS.update(fields('Athena.WorkGroup', 'base', {
    'Description': 'Description',
    'Name': 'Name',
    'State': 'State',
    'WorkGroupConfiguration.EnforceWorkGroupConfiguration': 'Configuration.EnforceWorkGroupConfiguration',
    'WorkGroupConfiguration.EngineVersion.SelectedEngineVersion': 'Configuration.EngineVersion.SelectedEngineVersion',
    'WorkGroupConfiguration.PublishCloudWatchMetricsEnabled': 'Configuration.PublishCloudWatchMetricsEnabled',
    'WorkGroupConfiguration.RequesterPaysEnabled': 'Configuration.RequesterPaysEnabled',
    'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.EncryptionOption': 'Configuration.ResultConfiguration.EncryptionConfiguration.EncryptionOption',
    'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': 'Configuration.ResultConfiguration.EncryptionConfiguration.KmsKey',
    'WorkGroupConfiguration.ResultConfiguration.ExpectedBucketOwner': 'Configuration.ResultConfiguration.ExpectedBucketOwner',
    'WorkGroupConfiguration.ResultConfiguration.OutputLocation': 'Configuration.ResultConfiguration.OutputLocation',
}, norms={'WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration.KmsKey': 'kms'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call('athena', 'get_work_group', WorkGroup=r.value('Name'))['WorkGroup']
