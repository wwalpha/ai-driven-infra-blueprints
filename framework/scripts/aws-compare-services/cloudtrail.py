"""cloudtrail: selected properties -> read-only SDK responses; inputs in fetch()."""


APIS = {('cloudtrail', 'get_trail_status'), ('cloudtrail', 'get_trail'), ('cloudtrail', 'get_event_selectors')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    name = r.value('TrailName')
    if getter == 'base':
        return ctx.call('cloudtrail', 'get_trail', Name=name)['Trail']
    if getter == 'status':
        return ctx.call('cloudtrail', 'get_trail_status', Name=name)
    return ctx.call('cloudtrail', 'get_event_selectors', TrailName=name)
