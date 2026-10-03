"""security-hub: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import fields, unavailable, metadata, one, select, MISSING, Unresolved, AcquisitionError

RESOURCE_TYPES = ('SecurityHub.Hub',)
APIS = {('securityhub', 'describe_hub')}
IDENTITIES = {'SecurityHub.Hub': ('base', 'HubArn', 'HubArn', None)}
FIELDS = {}
FIELDS.update(fields('SecurityHub.Hub', 'base', {
    'AutoEnableControls': 'AutoEnableControls',
    'ControlFindingGenerator': 'ControlFindingGenerator',
}))


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    return ctx.call('securityhub', 'describe_hub')
