"""EventBridge ARN components; evaluation remains shared."""
import re

from utils.cloudformation.inputs import Blocked


def arn_components(properties, evaluate):
    bus = evaluate(properties.get('EventBusName', 'default'))
    components = {}
    if isinstance(bus, str) and bus.startswith('arn:'):
        match = re.fullmatch(r'arn:([^:]+):events:([^:]+):([0-9]{12}):event-bus/([A-Za-z0-9._-]{1,256})', bus)
        if match is None:
            raise Blocked('rule ARN requires a valid EventBus ARN')
        partition, region, account, bus = match.groups()
        components = dict(partition=partition, region=region, account=account)
    if (not isinstance(bus, str) or bus in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}
            or re.fullmatch(r'[A-Za-z0-9._-]{1,256}', bus) is None):
        raise Blocked('rule ARN requires a confirmed event bus name')
    return dict(components, bus='' if bus == 'default' else bus + '/')
