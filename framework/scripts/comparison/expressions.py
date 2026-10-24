"""Resolve evaluated string expressions without discarding literal affixes."""
import re

from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference
from utils.reference_contracts import ATTRIBUTE_SUFFIXES


def parts(value, resource_type):
    """Retain symbolic producers and literal affixes in existing Sub/Join values."""
    if isinstance(value, ResourceReference):
        suffix = ATTRIBUTE_SUFFIXES.get((resource_type(value), value['$attribute']))
        return [ResourceReference(dict(value, **{'$attribute': suffix[0]})), suffix[1]] if suffix else [value]
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, Expression):
        raise Blocked('string expression operands unproven')
    if value.operation == 'Join':
        delimiter, values = value.operands
        children = [child for index, item in enumerate(values) for child in ([delimiter, item] if index else [item])]
    elif value.operation == 'Sub':
        text, variables = value.operands
        children, start = [], 0
        for match in re.finditer(r'\$\{([^}]+)\}', text):
            children.extend([text[start:match.start()], '${' + match[1][1:] + '}' if match[1].startswith('!') else variables[match[1]]])
            start = match.end()
        children.append(text[start:])
    else:
        raise Blocked('string expression operation unproven')
    result = []
    for child in children:
        for part in parts(child, resource_type):
            if result and isinstance(result[-1], str) and isinstance(part, str):
                result[-1] += part
            else:
                result.append(part)
    return result


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
