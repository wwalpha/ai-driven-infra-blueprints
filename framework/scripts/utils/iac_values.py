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
    """Do not publish secrets, dynamic secrets or current/generated ARN strings."""
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
        if "{{resolve:" in value or re.search(r"arn:aws[a-z-]*:", value, re.I):
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


def ordered_comparison(left, right, compare):
    known, prefix = array_presence(right)
    length = (
        len(left) == len(right)
        if known == len(right)
        else (False if not known <= len(left) <= len(right) else None)
    )
    return comparison_result(
        [length, *(compare(a, b) for a, b in zip(left, right[:prefix], strict=False))]
    )


def same(left, right, *, reference=None, path=""):
    """Preserve types, array order, duplicates and object membership."""
    if reference:
        result = reference(left, right, path)
        if result is not NotImplemented:
            return result
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        extra = right.keys() - left.keys()
        membership = (
            False
            if left.keys() - right.keys()
            or any(not unknown_value(right[key]) for key in extra)
            else None
            if extra
            else True
        )
        return comparison_result(
            [
                membership,
                *(
                    same(
                        left[key],
                        right[key],
                        reference=reference,
                        path=f"{path}.{key}" if path else key,
                    )
                    for key in left
                    if key in right
                ),
            ]
        )
    if isinstance(left, list):
        return ordered_comparison(
            left, right, lambda a, b: same(a, b, reference=reference, path=path + "[]")
        )
    return left == right


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


def _callback_unordered_same_matching(left, matrix, /, allow_unknown):
    owners = {}
    assign = _bind_framework_callback(
        _recursive_unordered_same_matching_assign, allow_unknown, matrix, owners
    )
    return all(assign(row, set()) for row in range(len(left)))


def unordered_same(left, right, *, reference=None, path=""):
    """Prove a multiset match, retaining uncertainty and duplicate multiplicity."""
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    if len(left) != len(right):
        known, _ = array_presence(right)
        if known == len(right) or not known <= len(left) <= len(right):
            return False
        confirmed = [item for item in right if not unknown_value(item)]
        matrix = [
            [same(a, b, reference=reference, path=path + "[]") for b in left]
            for a in confirmed
        ]
        return (
            None
            if _callback_unordered_same_matching(confirmed, matrix, True)
            else False
        )
    matrix = [
        [same(a, b, reference=reference, path=path + "[]") for b in right] for a in left
    ]

    matching = _bind_framework_callback(_callback_unordered_same_matching, left, matrix)

    if matching(False):
        return True
    return None if matching(True) else False


def selected_same(desired, actual, property_name="", *, reference=None, path=""):
    """Only selected nested settings constrain IaC. Tags have confirmed keyed semantics."""
    if reference:
        result = reference(desired, actual, path)
        if result is not NotImplemented:
            return result
    if type(desired) is not type(actual):
        return False
    if isinstance(desired, dict):
        return comparison_result(
            [
                desired.keys() <= actual.keys(),
                *(
                    selected_same(
                        item,
                        actual[key],
                        key,
                        reference=reference,
                        path=f"{path}.{key}" if path else key,
                    )
                    for key, item in desired.items()
                    if key in actual
                ),
            ]
        )
    if isinstance(desired, list):
        if property_name in {"Tags", "HostedZoneTags"} and all(
            isinstance(item, dict) and "Key" in item for item in desired
        ):
            keys = [item["Key"] for item in desired]
            selected = [
                item
                for item in actual
                if isinstance(item, dict) and item.get("Key") in keys
            ]
            unknown = sum(
                unknown_value(item)
                or isinstance(item, dict)
                and unknown_value(item.get("Key"))
                for item in actual
            )
            if len(set(keys)) != len(keys) or any(
                sum(item.get("Key") == key for item in selected) > 1 for key in keys
            ):
                return False
            membership = (
                False
                if len(selected) + unknown < len(keys)
                else None
                if unknown
                else len(selected) == len(keys)
            )
            return comparison_result(
                [
                    membership,
                    *(
                        selected_same(
                            item, candidate, reference=reference, path=path + "[]"
                        )
                        for item in desired
                        for candidate in selected
                        if item["Key"] == candidate["Key"]
                    ),
                ]
            )
        return ordered_comparison(
            desired,
            actual,
            lambda a, b: selected_same(a, b, reference=reference, path=path + "[]"),
        )
    return desired == actual
