"""security-hub: selected properties -> read-only SDK responses; inputs in fetch()."""

APIS = {("securityhub", "describe_hub")}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call("securityhub", "describe_hub")
