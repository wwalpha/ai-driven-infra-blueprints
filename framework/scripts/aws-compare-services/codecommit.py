"""codecommit: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('CodeCommit.Repository',)
APIS = {('codecommit', 'get_repository')}
IDENTITIES = {'CodeCommit.Repository': ('base', 'repositoryName', 'Arn', 'RepositoryName')}
FIELDS = {}
FIELDS.update(fields('CodeCommit.Repository', 'base', {
    'KmsKeyId': 'kmsKeyId',
    'RepositoryDescription': 'repositoryDescription',
    'RepositoryName': 'repositoryName',
}, norms={'KmsKeyId': 'kms'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call('codecommit', 'get_repository', repositoryName=r.value('RepositoryName'))['repositoryMetadata']
