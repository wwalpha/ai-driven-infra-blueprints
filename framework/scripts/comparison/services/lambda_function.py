"""lambda function comparison contracts and projections."""

import re

import utils.iac_values as _imports_iac_values
from utils.cloudformation.inputs import Blocked

REF_ATTRIBUTES = {'Lambda.Function': 'FunctionName'}




def literal_arn(properties, pseudo, substitute, reference):
    ResourceReference = _imports_iac_values.ResourceReference
    if 'FunctionName' not in properties:
        raise Blocked('Lambda ARN requires explicit FunctionName')
    function = substitute(ResourceReference(dict(reference, **{'$attribute': 'FunctionName'})))
    if not isinstance(function, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', function):
        raise Blocked('Lambda FunctionName is not a proven unqualified name')
    return f"arn:{pseudo['AWS::Partition']}:lambda:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:function:{function}"
