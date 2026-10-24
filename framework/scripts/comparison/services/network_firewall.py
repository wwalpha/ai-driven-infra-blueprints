"""Network Firewall's rule group type is part of its ARN identity."""
from utils.cloudformation.inputs import Blocked


def arn_components(properties, evaluate):
    group_type = evaluate(properties.get('Type'))
    if group_type not in ('STATEFUL', 'STATELESS'):
        raise Blocked('rule group ARN requires a confirmed STATEFUL or STATELESS Type')
    return {'type': group_type.lower()}
