"""kms: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('KMS.Alias', 'KMS.Key')
APIS = {('kms', 'list_aliases'), ('kms', 'get_key_rotation_status'), ('kms', 'get_key_policy'), ('kms', 'describe_key')}
IDENTITIES = {'KMS.Key': ('base', 'KeyId', 'Arn', None), 'KMS.Alias': ('alias', 'TargetKeyId', 'AliasArn', 'AliasName')}
FIELDS = {}
FIELDS.update(fields('KMS.Key', 'base', {
    'Description': 'Description',
    'Enabled': 'Enabled',
    'KeyId': 'KeyId',
    'KeySpec': 'KeySpec',
    'KeyUsage': 'KeyUsage',
    'MultiRegion': 'MultiRegion',
    'Origin': 'Origin',
}))
FIELDS.update(fields('KMS.Key', 'rotation', {
    'EnableKeyRotation': 'KeyRotationEnabled',
    'RotationPeriodInDays': 'RotationPeriodInDays',
}))
FIELDS.update(fields('KMS.Key', 'policy', {
    'KeyPolicy': 'Policy',
}, norms={'KeyPolicy': 'policy'}))
FIELDS.update(fields('KMS.Alias', 'alias', {
    'AliasName': 'AliasName',
}))
FIELDS['KMS.Key.PendingWindowInDays'] = unavailable('ScheduleKeyDeletion input; DescribeKey does not retain the future deletion waiting period on an active key.')


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if r.kind == 'KMS.Alias':
        alias = one([v for v in ctx.pages('kms','list_aliases').get('Aliases',[]) if v['AliasName'] == r.value('AliasName')], 'kms.list_aliases')
        parent = r.parent()
        if alias.get('TargetKeyId') != parent.identity('id'):
            # Preserve membership drift as a real difference instead of losing it.
            alias = dict(alias, ParentMismatch=True)
        return alias
    current = r.current('KeyId')
    if not current:
        aliases = [child.value('AliasName') for child in r.model.resources if child.kind == 'KMS.Alias' and child.spec.get('parentReference') and child.parent().number == r.number]
        if not aliases:
            raise Unresolved('KMS key requires a confirmed KeyId or associated alias')
        ids = {ctx.call('kms','describe_key',KeyId=alias)['KeyMetadata']['KeyId'] for alias in aliases}
        if len(ids) != 1:
            raise Unresolved('associated KMS aliases identify different keys')
        current = ids.pop()
    if getter == 'rotation':
        return ctx.call('kms','get_key_rotation_status',KeyId=current)
    if getter == 'policy':
        return ctx.call('kms','get_key_policy',KeyId=current,PolicyName='default')
    return ctx.call('kms','describe_key',KeyId=current)['KeyMetadata']
