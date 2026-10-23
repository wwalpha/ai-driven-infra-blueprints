"""events comparison contracts and projections."""

from cloudformation_inputs import Blocked
SUB_ARN_KINDS = {'Events.Rule'}
NAMED_ARN = ('Name', r'[.\-_A-Za-z0-9]{1,64}', 'events', 'rule/', '')

def validate_arn_context(properties, evaluate):
    bus = evaluate(properties.get('EventBusName', 'default'))
    if bus != 'default':
        raise Blocked('rule ARN requires a confirmed default event bus')
