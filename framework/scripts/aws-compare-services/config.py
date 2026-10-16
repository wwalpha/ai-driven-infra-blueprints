"""config: selected properties -> read-only SDK responses; inputs in fetch()."""

from model_aws_compare import one

APIS = {('config', 'describe_configuration_recorders'), ('config', 'describe_delivery_channels'), ('iam', 'get_role')}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter == 'recorder':
        return one(ctx.call('config', 'describe_configuration_recorders', ConfigurationRecorderNames=[r.value('Name')]).get('ConfigurationRecorders', []), 'config.describe_configuration_recorders')
    return one(ctx.call('config', 'describe_delivery_channels', DeliveryChannelNames=[r.value('Name')]).get('DeliveryChannels', []), 'config.describe_delivery_channels')
