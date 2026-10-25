"""athena: selected properties -> read-only SDK responses; inputs in fetch()."""

APIS = {("athena", "get_work_group")}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call("athena", "get_work_group", WorkGroup=r.value("Name"))["WorkGroup"]
