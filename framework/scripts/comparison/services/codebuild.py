"""codebuild comparison contracts and projections."""

REF_ATTRIBUTES = {'CodeBuild.Project': 'Name'}

import re
from cloudformation_inputs import Blocked
from comparison_rows import put_row
from iac_values import ResourceReference, Expression, same
from policy_tables import literal
from model.identity import resource_link
from utils.json_format import policy_json as strict_json


def contexts(rows):
    variables, contexts = {}, {}
    for rid, row in rows:
        short = row['property'].removeprefix('CodeBuild.Project.')
        if re.fullmatch(r'Environment.EnvironmentVariables\[\d*\]\.(Name|Type|Value)', short):
            put_row(variables, short, rid if short.endswith('.Value') else literal(row['value']))
    for variable in variables.get('Environment', {}).get('EnvironmentVariables', []):
        if 'Value' in variable:
            contexts[variable['Value']] = variable
    return contexts


def reference_contract(path, attribute, context):
    if path != 'Environment.EnvironmentVariables[].Value':
        return NotImplemented
    variable_type = context.get('Type')
    if variable_type == 'SECRETS_MANAGER':
        return 'SecretsManager.Secret', 'Id'
    if variable_type != 'PLAINTEXT':
        raise Blocked('reference property contract unproven: CodeBuild environment Type is required')
    return None, attribute


def validate_reference(path, attribute, context, refkind):
    if (path == 'Environment.EnvironmentVariables[].Value' and context.get('Type') == 'PLAINTEXT'
            and attribute is None and refkind != 'S3.Bucket'):
        raise Blocked(f'CodeBuild PLAINTEXT reference requires an explicit attribute for {refkind}; only S3.Bucket defaults to BucketName')


def structured_path(path):
    return path == 'Environment.EnvironmentVariables[].Value'


def structured_reference(item, context):
    if (set(item) != {'$resource', '$attribute'} or not context or context.get('Type') != 'PLAINTEXT'
            or not all(isinstance(part, str) and part for part in item.values()) or not resource_link(item['$resource'])):
        raise Blocked('Model environment reference requires PLAINTEXT, an explicit resource link and attribute')
    return item['$resource'], item['$attribute']


def validate_attribute(symbol, property_schema):
    if property_schema.get('type') != 'string':
        raise Blocked('Model environment reference attribute must be a proven string')


def decode_selector(value, path):
    if structured_path(re.sub(r'\[\d+\]', '[]', path)) and isinstance(value, str) and value.startswith('{'):
        try:
            selector = strict_json(value)
        except ValueError:
            selector = None
        if isinstance(selector, dict) and {'$resource', '$attribute'} & selector.keys():
            return selector, re.sub(r'\[\d+\]', '[]', path)
    return value, path


def reference_compare(left, right, path, resolve_literal, kms_format, resource_type, reference):
    if path == 'Environment.EnvironmentVariables[].Value':
        if isinstance(left, Expression) or isinstance(right, Expression):
            try:
                values = [resolve_literal(value) if isinstance(value, (Expression, ResourceReference)) else value for value in (left, right)]
                return same(*values)
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                return None
        if isinstance(left, ResourceReference) and isinstance(right, ResourceReference):
            return same(left, right)
        if isinstance(left, ResourceReference) != isinstance(right, ResourceReference):
            symbol, other = (left, right) if isinstance(left, ResourceReference) else (right, left)
            if isinstance(other, str):
                forms = kms_format(symbol), kms_format(other)
                if all(form not in {None, 'invalid'} for form in forms) and forms[0] != forms[1]:
                    return False
                try:
                    return same(resolve_literal(symbol), other)
                except (Blocked, ValueError, KeyError, TypeError, OSError):
                    return None
    if (path.endswith('EnvironmentVariables[]') and isinstance(left, dict) and isinstance(right, dict)
            and left.get('Type') == right.get('Type') == 'SECRETS_MANAGER'):
        def secret_value(a, b, p):
            if p == path:
                return NotImplemented
            if p.endswith('.Value') and isinstance(a, ResourceReference) != isinstance(b, ResourceReference):
                symbol, text = (a, b) if isinstance(a, ResourceReference) else (b, a)
                if resource_type(symbol) == 'SecretsManager.Secret' and isinstance(text, str) and not text.startswith('arn:'):
                    try:
                        name = resolve_literal(ResourceReference(dict(symbol, **{'$attribute': 'Name'})))
                    except (Blocked, ValueError, KeyError, TypeError, OSError):
                        return None
                    return same(name, text)
            return reference(a, b, p)
        return same(left, right, reference=secret_value, path=path)
    return NotImplemented

DIRECT_ATTRIBUTES = {'CodeBuild.Project.ServiceRole': 'Arn'}

SUB_ARN_KINDS = {'CodeBuild.Project'}
NAMED_ARN = ('Name', r'[A-Za-z0-9][A-Za-z0-9_-]{1,254}', 'codebuild', 'project/', '')
