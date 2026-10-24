"""Resolve evaluated string expressions without discarding literal affixes."""
import re

from utils.cloudformation.format import intrinsic_shape_error
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, same
from utils.reference_contracts import ATTRIBUTE_SUFFIXES


def parts(value, resource_type=None):
    """Retain symbolic producers and literal affixes in existing Sub/Join values."""
    if isinstance(value, ResourceReference):
        suffix = ATTRIBUTE_SUFFIXES.get((resource_type(value), value['$attribute'])) if resource_type else None
        return [ResourceReference(dict(value, **{'$attribute': suffix[0]})), suffix[1]] if suffix else [value]
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, Expression):
        raise Blocked('string expression operands unproven')
    if intrinsic_shape_error('Fn::' + value.operation, value.operands):
        raise Blocked('string expression syntax unproven')
    if value.operation == 'Select':
        return [value]
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


def exact_same(left, right, path=''):
    """Expression tokens require the same Producer and attribute, without form coercion."""
    if any(isinstance(value, Expression) for value in (left, right)):
        if (not all(isinstance(value, Expression) for value in (left, right))
                or left.operation != right.operation or left.operation == 'Unverified'):
            return None
        if left.operation in {'Sub', 'Join'}:
            try:
                return symbolic_same(parts(left), parts(right))
            except (Blocked, ValueError, KeyError, TypeError):
                return None
        return same(left.operands, right.operands, reference=exact_same, path=path)
    if any(isinstance(value, ResourceReference) for value in (left, right)):
        return same(left, right)
    return NotImplemented


def symbolic_same(left, right):
    """Exact tokens prove equality; identical symbols also prove total length differences."""
    if same(left, right, reference=exact_same) is True:
        return True
    left_symbols = [part for part in left if isinstance(part, (ResourceReference, Expression))]
    right_symbols = [part for part in right if isinstance(part, (ResourceReference, Expression))]
    if same(left_symbols, right_symbols, reference=exact_same) is True and sum(len(part) for part in left if isinstance(part, str)) != sum(
            len(part) for part in right if isinstance(part, str)):
        return False
    return None


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
    if intrinsic_shape_error('Fn::' + value.operation, value.operands):
        raise Blocked('expression_unresolved: invalid intrinsic operands')
    if value.operation == 'Join':
        delimiter, parts = value.operands
        if not isinstance(delimiter, str) or not isinstance(parts, list):
            raise Blocked('expression_unresolved: invalid Join operands')
        return delimiter.join(string(part, resolve) for part in parts)
    if value.operation == 'Sub':
        text, variables = value.operands
        if not isinstance(text, str) or not isinstance(variables, dict):
            raise Blocked('expression_unresolved: invalid Sub operands')
        return re.sub(r'\$\{([^}]+)\}', lambda match: replacement(match, variables, resolve), text)
    raise Blocked('expression_unresolved: unsupported expression')
