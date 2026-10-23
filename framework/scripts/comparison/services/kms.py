"""kms comparison contracts and projections."""

import re

from cloudformation_inputs import Blocked
from iac_values import Expression, ResourceReference, same

REF_ATTRIBUTES = {'KMS.Key': 'KeyId', 'KMS.Alias': 'AliasName'}




def kms_format(value, resources):
    if isinstance(value, ResourceReference):
        service, identity = value['$resource']
        kind = resources[service][identity]['resourceType']
        return {('KMS.Key', 'KeyId'): 'KeyId', ('KMS.Key', 'Arn'): 'KeyArn',
                ('KMS.Alias', 'AliasName'): 'AliasName', ('KMS.Alias', 'AliasArn'): 'AliasArn'}.get((kind, value['$attribute']), 'invalid')
    if isinstance(value, Expression):
        return None
    if not isinstance(value, str):
        return 'invalid'
    if '{{resolve:' in value or '${' in value:
        return None
    key = r'(?:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}|mrk-[a-fA-F0-9]{32})'
    alias = r'alias/[A-Za-z0-9:/_-]+'
    arn = r'arn:[a-z0-9-]+:kms:[a-z0-9-]+:\d{12}:'
    for form, pattern in [('KeyId', key), ('KeyArn', arn + 'key/' + key), ('AliasName', alias), ('AliasArn', arn + alias)]:
        if re.fullmatch(pattern, value):
            return form
    return 'invalid'

SPECIAL_ATTRIBUTES = {('KMS.Alias', 'AliasArn')}
SUB_ARN_KINDS = set()

def alias_arn(alias, pseudo):
    if kms_format(alias, {}) != 'AliasName':
        raise Blocked('alias ARN requires a valid explicit AliasName')
    return f"arn:{pseudo['AWS::Partition']}:kms:{pseudo['AWS::Region']}:{pseudo['AWS::AccountId']}:{alias}"


IDENTITY_KINDS = {'KMS.Key', 'KMS.Alias'}


def arn_attribute(kind, default):
    return {'KMS.Alias': 'AliasArn', 'KMS.Key': 'Arn'}.get(kind, default)


def identity_same(left, right, forms):
    if left['$resource'] != right['$resource']:
        return False, None, False
    if forms is not None:
        if left['$attribute'] == right['$attribute'] and left['$attribute'] not in forms:
            return None, 'same reference identity; both attributes are outside the allowed property forms', False
        equal = left['$attribute'] in forms and right['$attribute'] in forms
        return equal, None, bool(equal and left['$attribute'] != right['$attribute'])
    if left['$attribute'] == right['$attribute']:
        return True, None, False
    return None, 'same reference identity; no property contract proves equivalence of these attributes', False


def compare_forms(left, right, allowed, *, resolve_literal, format_of):
    forms = format_of(left), format_of(right)
    reason = None
    if any(form is not None and form not in allowed for form in forms):
        result, reason = False, f'KMS format outside allowed forms: model={forms[0]}, iac={forms[1]}'
    elif None in forms:
        result, reason = None, 'KMS format is unproven'
    elif forms[0] != forms[1]:
        result, reason = False, f'KMS format mismatch: model={forms[0]}, iac={forms[1]}'
    elif isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
        result = same(left, right)
    else:
        try:
            values = [resolve_literal(value) if isinstance(value, ResourceReference) else value for value in (left, right)]
            result = same(*values)
        except (Blocked, ValueError, KeyError, TypeError, OSError):
            result, reason = None, 'same KMS format; physical value is unproven'
    return result, reason
