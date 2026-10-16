"""eventbridge: selected properties -> read-only SDK responses; inputs in fetch()."""


APIS = {('events', 'describe_rule'), ('events', 'list_targets_by_rule'), ('scheduler', 'get_schedule')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter == 'schedule':
        return ctx.call('scheduler', 'get_schedule', Name=r.value('Name'))
    inputs = {'Name' if getter == 'base' else 'Rule': r.value('Name'), 'EventBusName': r.optional('EventBusName', 'default')}
    if getter == 'targets':
        return ctx.pages('events', 'list_targets_by_rule', **inputs)
    return ctx.call('events', 'describe_rule', **inputs)
