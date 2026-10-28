"""Symbolic IaC values, strict/selected comparison and display masking. No I/O."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback

from utils.json_format import fingerprint as fingerprint
from utils.json_format import invalid_constant as invalid_constant
from utils.json_format import policy_json
from utils.json_format import unique_object as unique_object

strict_json = policy_json


def cfn_resource_identity(value):
    """A hyphen cannot occur in a template resource ID, so the final one is unambiguous."""
    stack, separator, logical = value.rpartition("-")
    if (
        not separator
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", stack)
        or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", logical)
    ):
        raise ValueError(
            f"invalid cfn-logicalId (expected StackName-TemplateResourceId): {value!r}"
        )
    return stack, logical


class ResourceReference(dict):
    """A confirmed identity, distinct from a same-shaped JSON literal."""


@dataclass(frozen=True, eq=False)
class Expression:
    """An evaluated intrinsic with unresolved operands; never a JSON literal."""

    operation: str
    operands: list

    def __eq__(self, other):
        return (
            type(self) is type(other)
            and self.operation == other.operation
            and same(self.operands, other.operands)
        )


def safe_value(value, property_name=""):
    """Mask secret properties and dynamic references; preserve ordinary ARN strings."""
    if re.search(
        r"password|secretstring|secretbinary|token|credential|privatekey",
        property_name,
        re.I,
    ):
        return "<masked>"
    if isinstance(value, Expression):
        if value.operation == "Unverified" and not value.operands:
            return "<unresolved>"
        return {
            "$expression": value.operation,
            "$operands": safe_value(value.operands, property_name),
        }
    if isinstance(value, str):
        if "{{resolve:" in value:
            return "<masked ARN/secret>"
        return value
    if isinstance(value, list):
        return [safe_value(item, property_name) for item in value]
    if isinstance(value, dict):
        selected_name = value.get("Name", value.get("Key", ""))
        if (
            isinstance(selected_name, str)
            and re.search(
                r"password|secret|token|credential|privatekey", selected_name, re.I
            )
            and "Value" in value
        ):
            value = dict(value, Value="<masked>")
        return {key: safe_value(item, key) for key, item in value.items()}
    return value


def comparison_result(values, *, any_match=False):
    """A difference wins; consume all leaves to retain diagnostic callbacks."""
    decisive = True if any_match else False
    uncertain = decided = False
    for value in values:
        if value is decisive:
            decided = True
        uncertain |= value is None
    return decisive if decided else None if uncertain else not decisive


def unknown_value(value):
    return isinstance(value, Expression) and value.operation == "Unverified"


def array_presence(values):
    """A failed element may be omitted; only the prefix has proven positional alignment."""
    unknown = [i for i, value in enumerate(values) if unknown_value(value)]
    return len(values) - len(unknown), unknown[0] if unknown else len(values)


def ordered_comparison(left, right, compare, *, indexed=False):
    known, prefix = array_presence(right)
    length = (
        len(left) == len(right)
        if known == len(right)
        else (False if not known <= len(left) <= len(right) else None)
    )
    return comparison_result(
        [
            length,
            *(
                compare(a, b, i) if indexed else compare(a, b)
                for i, (a, b) in enumerate(zip(left, right[:prefix], strict=False))
            ),
        ]
    )


def same(
    left,
    right,
    *,
    reference=None,
    path="",
    trace=None,
    position_reference=None,
    lp=(),
    rp=(),
):
    """Preserve types, array order, duplicates and object membership."""
    if reference or position_reference:
        result = (
            position_reference(left, right, path, lp, rp)
            if position_reference
            else reference(left, right, path)
        )
        if result is not NotImplemented:
            if trace is not None and result is not True:
                trace(left, right, path, result)
            return result
    if type(left) is not type(right):
        result = False
    elif isinstance(left, dict):
        extra = right.keys() - left.keys()
        membership = (
            False
            if left.keys() - right.keys()
            or any(not unknown_value(right[key]) for key in extra)
            else None
            if extra
            else True
        )
        result = comparison_result(
            [
                membership,
                *(
                    same(
                        left[key],
                        right[key],
                        reference=reference,
                        path=f"{path}.{key}" if path else key,
                        trace=trace,
                        position_reference=position_reference,
                        lp=lp + (key,),
                        rp=rp + (key,),
                    )
                    for key in left
                    if key in right
                ),
            ]
        )
    elif isinstance(left, list):
        result = ordered_comparison(
            left,
            right,
            lambda a, b, i: same(
                a,
                b,
                reference=reference,
                path=path + "[]",
                trace=trace,
                position_reference=position_reference,
                lp=lp + (i,),
                rp=rp + (i,),
            ),
            indexed=True,
        )
    else:
        result = left == right
    if trace is not None and result is not True:
        trace(left, right, path, result)
    return result


def _recursive_unordered_same_matching_assign(
    allow_unknown, matrix, owners, /, row, seen
):
    for column, result in enumerate(matrix[row]):
        if column in seen or not (result is True or allow_unknown and result is None):
            continue
        seen.add(column)
        if column not in owners or _recursive_unordered_same_matching_assign(
            allow_unknown, matrix, owners, owners[column], seen
        ):
            owners[column] = row
            return True
    return False


def unordered_matching(matrix, *, allow_unknown=False):
    owners = {}
    assign = _bind_framework_callback(
        _recursive_unordered_same_matching_assign, allow_unknown, matrix, owners
    )
    for row in range(len(matrix)):
        assign(row, set())
    return owners


def unordered_same(
    left, right, *, reference=None, path="", trace=None, evidence=None, candidate=None
):
    """Prove a multiset match, retaining uncertainty and duplicate multiplicity."""
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    compare = candidate or _bind_framework_callback(
        same, reference=reference, path=path + "[]", trace=trace
    )
    if len(left) != len(right):
        known, _ = array_presence(right)
        if known == len(right) or not known <= len(left) <= len(right):
            return False
        confirmed = [item for item in right if not unknown_value(item)]
        matrix = [[compare(a, b) for b in left] for a in confirmed]
        possible = unordered_matching(matrix, allow_unknown=True)
        if evidence is not None:
            evidence(matrix, None, possible)
        return None if len(possible) == len(confirmed) else False
    matrix = [[compare(a, b) for b in right] for a in left]

    owners = unordered_matching(matrix)
    possible = (
        owners
        if len(owners) == len(left)
        else unordered_matching(matrix, allow_unknown=True)
    )
    if evidence is not None:
        evidence(matrix, owners, possible)
    if len(owners) == len(left):
        return True
    return None if len(possible) == len(left) else False


def selected_same(
    desired,
    actual,
    property_name="",
    *,
    reference=None,
    path="",
    trace=None,
    position_reference=None,
    lp=(),
    rp=(),
):
    """Only selected nested settings constrain IaC; arrays retain order and duplicates."""
    if reference or position_reference:
        result = (
            position_reference(desired, actual, path, lp, rp)
            if position_reference
            else reference(desired, actual, path)
        )
        if result is not NotImplemented:
            if trace is not None and result is not True:
                trace(desired, actual, path, result)
            return result
    if type(desired) is not type(actual):
        result = False
    elif isinstance(desired, dict):
        result = comparison_result(
            [
                desired.keys() <= actual.keys(),
                *(
                    selected_same(
                        item,
                        actual[key],
                        key,
                        reference=reference,
                        path=f"{path}.{key}" if path else key,
                        trace=trace,
                        position_reference=position_reference,
                        lp=lp + (key,),
                        rp=rp + (key,),
                    )
                    for key, item in desired.items()
                    if key in actual
                ),
            ]
        )
    elif isinstance(desired, list):
        result = ordered_comparison(
            desired,
            actual,
            lambda a, b, i: selected_same(
                a,
                b,
                reference=reference,
                path=path + "[]",
                trace=trace,
                position_reference=position_reference,
                lp=lp + (i,),
                rp=rp + (i,),
            ),
            indexed=True,
        )
    else:
        result = desired == actual
    if trace is not None and result is not True:
        trace(desired, actual, path, result)
    return result
