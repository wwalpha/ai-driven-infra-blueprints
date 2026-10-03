"""eventbridge: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('Events.Rule', 'Scheduler.Schedule')
APIS = {('events', 'describe_rule'), ('events', 'list_targets_by_rule'), ('scheduler', 'get_schedule')}
IDENTITIES = {'Events.Rule': ('base', 'Name', 'Arn', 'Name'), 'Scheduler.Schedule': ('schedule', 'Name', 'Arn', 'Name')}
FIELDS = {}
FIELDS.update(fields('Events.Rule', 'base', {
    'EventBusName': 'EventBusName',
    'EventPattern': 'EventPattern',
    'Name': 'Name',
    'State': 'State',
}, norms={'EventPattern': 'json'}))
FIELDS.update(fields('Events.Rule', 'targets', {
    'Targets[].Arn': 'Targets[].Arn',
    'Targets[].DeadLetterConfig.Arn': 'Targets[].DeadLetterConfig.Arn',
    'Targets[].Id': 'Targets[].Id',
    'Targets[].RetryPolicy.MaximumEventAgeInSeconds': 'Targets[].RetryPolicy.MaximumEventAgeInSeconds',
    'Targets[].RetryPolicy.MaximumRetryAttempts': 'Targets[].RetryPolicy.MaximumRetryAttempts',
}, norms={'Targets[].Arn': 'arn', 'Targets[].DeadLetterConfig.Arn': 'arn'}))
FIELDS.update(fields('Scheduler.Schedule', 'schedule', {
    'FlexibleTimeWindow.Mode': 'FlexibleTimeWindow.Mode',
    'Name': 'Name',
    'ScheduleExpression': 'ScheduleExpression',
    'ScheduleExpressionTimezone': 'ScheduleExpressionTimezone',
    'State': 'State',
    'Target.Arn': 'Target.Arn',
    'Target.RoleArn': 'Target.RoleArn',
}, norms={'Target.Arn': 'arn', 'Target.RoleArn': 'arn'}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter == 'schedule':
        return ctx.call('scheduler', 'get_schedule', Name=r.value('Name'))
    inputs = {'Name' if getter == 'base' else 'Rule': r.value('Name'), 'EventBusName': r.optional('EventBusName', 'default')}
    if getter == 'targets':
        return ctx.pages('events', 'list_targets_by_rule', **inputs)
    return ctx.call('events', 'describe_rule', **inputs)
