"""secrets-manager: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('SecretsManager.RotationSchedule', 'SecretsManager.Secret')
APIS = {('secretsmanager', 'describe_secret')}
IDENTITIES = {'SecretsManager.Secret': ('base', 'Name', 'ARN', 'Name'), 'SecretsManager.RotationSchedule': ('rotation', 'Name', 'ARN', None)}
FIELDS = {}
FIELDS.update(fields('SecretsManager.Secret', 'base', {
    'Description': 'Description',
    'Id': 'ARN',
    'KmsKeyId': 'KmsKeyId',
    'Name': 'Name',
    'Type': 'Type',
}, norms={'KmsKeyId': 'kms'}))
FIELDS.update(fields('SecretsManager.RotationSchedule', 'rotation', {
    'ExternalSecretRotationMetadata[].Key': 'ExternalSecretRotationMetadata[].Key',
    'ExternalSecretRotationMetadata[].Value': 'ExternalSecretRotationMetadata[].Value',
    'ExternalSecretRotationRoleArn': 'ExternalSecretRotationRoleArn',
    'Id': 'ARN',
    'RotationRules.AutomaticallyAfterDays': 'RotationRules.AutomaticallyAfterDays',
    'RotationRules.Duration': 'RotationRules.Duration',
    'SecretId': 'Name',
}, norms={'ExternalSecretRotationRoleArn': 'arn', 'SecretId': 'name'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    parent = r.parent() if r.kind.endswith('RotationSchedule') else r
    record = ctx.call('secretsmanager', 'describe_secret', SecretId=parent.value('Name'))
    if r.kind.endswith('RotationSchedule') and r.value('SecretId', 'name') != parent.value('Name'):
        raise Unresolved('rotation schedule SecretId does not identify its parent')
    return record
