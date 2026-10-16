"""codebuild: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import one

APIS = {('codebuild', 'batch_get_projects')}


def sensitive(prop):
    return prop.endswith('EnvironmentVariables[].Value') or prop.endswith('Source.BuildSpec')


def fetch(ctx, r, getter):
    return one(ctx.call('codebuild', 'batch_get_projects', names=[r.value('Name')]).get('projects', []), 'codebuild.batch_get_projects')


SDK_OPERATIONS = {'CodeBuild.Project': 'batch_get_projects'}


def fetch_sdk(ctx, r, operation):
    return ctx.call('codebuild', operation, names=[r.value('Name')])
