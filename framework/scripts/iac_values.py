"""Symbolic IaC values, strict/selected comparison and display masking. No I/O."""
import json
import re
from dataclasses import dataclass

def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate policy JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def cfn_resource_identity(value):
    """A hyphen cannot occur in a template resource ID, so the final one is unambiguous."""
    stack, separator, logical = value.rpartition("-")
    if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", stack) or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", logical):
        raise ValueError(f"invalid cfn-logicalId (expected StackName-TemplateResourceId): {value!r}")
    return stack, logical


def strict_json(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


class ResourceReference(dict):
    """A confirmed identity, distinct from a same-shaped JSON literal."""


@dataclass(frozen=True, eq=False)
class Expression:
    """An evaluated intrinsic with unresolved operands; never a JSON literal."""
    operation: str
    operands: list

    def __eq__(self, other):
        return type(self) is type(other) and self.operation == other.operation and same(self.operands, other.operands)


def safe_value(value, property_name=''):
    """Do not publish secrets, dynamic secrets or current/generated ARN strings."""
    if re.search(r'password|secretstring|secretbinary|token|credential|privatekey', property_name, re.I):
        return '<masked>'
    if isinstance(value, Expression):
        return {'$expression': value.operation, '$operands': safe_value(value.operands, property_name)}
    if isinstance(value, str):
        if '{{resolve:' in value or re.search(r'arn:aws[a-z-]*:', value, re.I):
            return '<masked ARN/secret>'
        return value
    if isinstance(value, list):
        return [safe_value(item, property_name) for item in value]
    if isinstance(value, dict):
        selected_name = value.get('Name', value.get('Key', ''))
        if isinstance(selected_name, str) and re.search(r'password|secret|token|credential|privatekey', selected_name, re.I) and 'Value' in value:
            value = dict(value, Value='<masked>')
        return {key: safe_value(item, key) for key, item in value.items()}
    return value


def comparison_result(values, *, any_match=False):
    """A confirmed difference wins over uncertainty; a match must prove every leaf."""
    decisive = True if any_match else False
    uncertain = False
    for value in values:
        if value is decisive:
            return decisive
        uncertain |= value is None
    return None if uncertain else not decisive


def same(left, right, *, reference=None, path=''):
    """Preserve types, array order, duplicates and object membership."""
    if reference:
        result = reference(left, right, path)
        if result is not NotImplemented:
            return result
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and comparison_result(
            same(left[key], right[key], reference=reference, path=f'{path}.{key}' if path else key) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and comparison_result(
            same(a, b, reference=reference, path=path + '[]') for a, b in zip(left, right))
    return left == right


def selected_same(desired, actual, property_name='', *, reference=None, path=''):
    """Only selected nested settings constrain IaC. Tags have confirmed keyed semantics."""
    if reference:
        result = reference(desired, actual, path)
        if result is not NotImplemented:
            return result
    if type(desired) is not type(actual):
        return False
    if isinstance(desired, dict):
        return desired.keys() <= actual.keys() and comparison_result(
            selected_same(item, actual[key], key, reference=reference, path=f'{path}.{key}' if path else key)
            for key, item in desired.items())
    if isinstance(desired, list):
        if property_name in {'Tags', 'HostedZoneTags'} and all(isinstance(item, dict) and 'Key' in item for item in desired):
            keys = [item['Key'] for item in desired]
            selected = [item for item in actual if isinstance(item, dict) and item.get('Key') in keys]
            if len(set(keys)) != len(keys) or len(selected) != len(keys):
                return False
            return comparison_result(comparison_result(
                (selected_same(item, candidate, reference=reference, path=path + '[]') for candidate in selected), any_match=True)
                for item in desired)
        return len(desired) == len(actual) and comparison_result(
            selected_same(a, b, reference=reference, path=path + '[]') for a, b in zip(desired, actual))
    return desired == actual


