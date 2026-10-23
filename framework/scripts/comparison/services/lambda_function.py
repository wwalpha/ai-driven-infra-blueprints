"""lambda function comparison contracts and projections."""

REF_ATTRIBUTES = {'Lambda.Function': 'FunctionName'}

import re
from cloudformation_inputs import Blocked

def literal_arn(properties, pseudo, substitute, reference):
    from iac_values import ResourceReference
    if 'FunctionName' not in properties:
        raise Blocked('Lambda ARN requires explicit FunctionName')
    function = substitute(ResourceReference(dict(reference, **{'$attribute': 'FunctionName'})))
    if not isinstance(function, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', function):
        raise Blocked('Lambda FunctionName is not a proven unqualified name')
    return f"arn:{pseudo['AWS::Partition']}:lambda:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:function:{function}"
