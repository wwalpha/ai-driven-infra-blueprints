"""Resolve evaluated string expressions without discarding literal affixes."""
import re

from iac_values import Expression, ResourceReference
from utils.cloudformation.inputs import Blocked


def string(value, resolve):
    if isinstance(value, (ResourceReference, Expression)):
        value = resolve(value)
    if not isinstance(value, str):
        raise Blocked('expression_unresolved: string operand required')
    return value


def replacement(match, variables, resolve):
    key = match.group(1)
    if key.startswith('!'):
        return '${' + key[1:] + '}'
    if key not in variables:
        raise Blocked('expression_unresolved: Sub variable missing')
    return string(variables[key], resolve)


def literal(value, resolve):
    if value.operation == 'Join':
        delimiter, parts = value.operands
        if not isinstance(delimiter, str) or not isinstance(parts, list):
            raise Blocked('expression_unresolved: invalid Join operands')
        return delimiter.join(string(part, resolve) for part in parts)
    if value.operation == 'Sub':
        text, variables = value.operands
        return re.sub(r'\$\{([^}]+)\}', lambda match: replacement(match, variables, resolve), text)
    raise Blocked('expression_unresolved: unsupported expression')
