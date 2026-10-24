"""Public domain ARNs exclude the generated identifier used by private domains."""
from utils.cloudformation.inputs import Blocked


def arn_components(properties, evaluate):
    configuration = evaluate(properties.get('EndpointConfiguration', {}))
    types = configuration.get('Types', ['EDGE']) if isinstance(configuration, dict) else None
    if not isinstance(types, list) or len(types) != 1 or types[0] not in ('EDGE', 'REGIONAL'):
        raise Blocked('domain ARN requires a proven public endpoint; private domains need an AWS-generated identifier')
    return {}
