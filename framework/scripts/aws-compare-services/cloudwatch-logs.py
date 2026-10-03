"""cloudwatch-logs: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Logs.LogGroup',)
APIS = {('logs', 'describe_log_groups')}
IDENTITIES = {'Logs.LogGroup': ('base', 'logGroupName', 'logGroupArn', 'LogGroupName')}
FIELDS = {}
FIELDS.update(fields('Logs.LogGroup', 'base', {
    'DeletionProtectionEnabled': 'deletionProtectionEnabled',
    'KmsKeyId': 'kmsKeyId',
    'LogGroupClass': 'logGroupClass',
    'LogGroupName': 'logGroupName',
    'RetentionInDays': 'retentionInDays',
}, norms={'KmsKeyId': 'kms'}, defaults={'DeletionProtectionEnabled': False, 'LogGroupClass': 'STANDARD'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    name = r.value('LogGroupName')
    return one([v for v in ctx.pages('logs', 'describe_log_groups', logGroupNamePrefix=name).get('logGroups', []) if v['logGroupName'] == name], 'logs.describe_log_groups')
