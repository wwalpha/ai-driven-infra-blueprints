"""cloudwatch-logs: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import one

APIS = {('logs', 'describe_log_groups')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    name = r.value('LogGroupName')
    return one([v for v in ctx.pages('logs', 'describe_log_groups', logGroupNamePrefix=name).get('logGroups', []) if v['logGroupName'] == name], 'logs.describe_log_groups')
