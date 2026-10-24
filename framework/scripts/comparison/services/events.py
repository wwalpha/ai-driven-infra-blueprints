"""EventBridge ARN components; evaluation remains shared."""
import re

from utils.cloudformation.inputs import Blocked


def arn_components(properties, evaluate):
    bus = evaluate(properties.get('EventBusName', 'default'))
    if not isinstance(bus, str) or re.fullmatch(r'[A-Za-z0-9._-]{1,256}', bus) is None:
        raise Blocked('rule ARN requires a confirmed event bus name')
    return {'bus': '' if bus == 'default' else bus + '/'}
