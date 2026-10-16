"""mwaa: selected properties -> read-only SDK responses; inputs in fetch()."""


APIS = {('mwaa', 'get_environment')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call('mwaa', 'get_environment', Name=r.value('Name'))['Environment']
