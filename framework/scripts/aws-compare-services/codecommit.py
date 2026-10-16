"""codecommit: selected properties -> read-only SDK responses; inputs in fetch()."""


APIS = {('codecommit', 'get_repository')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call('codecommit', 'get_repository', repositoryName=r.value('RepositoryName'))['repositoryMetadata']
