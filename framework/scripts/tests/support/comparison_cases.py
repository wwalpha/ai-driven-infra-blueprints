"""Explicit comparison-only typed operands and lossless outcome projections."""

from dataclasses import fields, replace
from unittest import TestCase

from comparison.methods import (
    MISSING,
    OBJECT,
    ORDERED,
    REFERENCE,
    SCALAR,
    UNORDERED,
    CompareOutcome,
    Difference,
    keyed,
)
from utils.iac_values import Expression, ResourceReference


def operand(value):
    if type(value) is list:
        return [operand(item) for item in value]
    if type(value) is dict:
        if "$caseType" not in value:
            return {key: operand(item) for key, item in value.items()}
        if value == {
            "$caseType": "Expression",
            "operation": "Unverified",
            "operands": [],
        }:
            result = Expression("Unverified", [])
            TestCase().assertIs(type(result), Expression)
            return result
        if (
            value.keys() == {"$caseType", "value"}
            and value["$caseType"] == "ResourceReference"
        ):
            content = value["value"]
            if (
                type(content) is dict
                and content.keys() == {"$resource", "$attribute"}
                and type(content["$resource"]) is list
                and len(content["$resource"]) == 2
                and all(type(item) is str for item in content["$resource"])
                and type(content["$attribute"]) is str
            ):
                result = ResourceReference(operand(content))
                TestCase().assertIs(type(result), ResourceReference)
                return result
        raise ValueError("unknown comparison fixture operand")
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise TypeError("unsupported comparison fixture operand")


def projected(value):
    if value is MISSING:
        return {"$caseType": "MISSING"}
    if value is NotImplemented:
        return {"$caseType": "NotImplemented"}
    if type(value) is Expression:
        return {
            "$caseType": "Expression",
            **{
                field.name: projected(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if type(value) is ResourceReference:
        return {"$caseType": "ResourceReference", "value": projected(dict(value))}
    if type(value) in (dict,):
        return {key: projected(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [projected(item) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise TypeError("unsupported comparison result type")


def outcome_data(outcome):
    TestCase().assertIs(type(outcome), CompareOutcome)
    if outcome.equal is not None and type(outcome.equal) is not bool:
        raise TypeError("comparison equality must be bool or None")
    TestCase().assertIs(type(outcome.equivalent), bool)
    for field in fields(outcome):
        if field.name not in {"equal", "equivalent"}:
            TestCase().assertIs(type(getattr(outcome, field.name)), tuple)
    differences = []
    for difference in outcome.differences:
        TestCase().assertIs(type(difference), Difference)
        for pointer in (difference.model_pointer, difference.iac_pointer):
            if pointer is not None:
                TestCase().assertIs(type(pointer), tuple)
        differences.append(
            {
                field.name: projected(getattr(difference, field.name))
                for field in fields(difference)
            }
        )
    return {
        **{
            field.name: projected(getattr(outcome, field.name))
            for field in fields(outcome)
            if field.name != "differences"
        },
        "differences": differences,
    }


def declared_rules(declarations):
    rules = {}
    for path, declaration in declarations.items():
        if type(declaration) is str:
            try:
                rules[path] = {
                    "SCALAR": SCALAR,
                    "OBJECT": OBJECT,
                    "ORDERED": ORDERED,
                    "UNORDERED": UNORDERED,
                    "REFERENCE": REFERENCE,
                }[declaration]
            except KeyError:
                raise ValueError("unknown comparison fixture rule") from None
        elif (
            type(declaration) is dict
            and declaration.keys() == {"keyed"}
            and type(declaration["keyed"]) is str
        ):
            rules[path] = keyed(declaration["keyed"])
        elif (
            type(declaration) is dict
            and declaration.keys() == {"unordered_key"}
            and type(declaration["unordered_key"]) is str
        ):
            rules[path] = replace(UNORDERED, key=declaration["unordered_key"])
        else:
            raise ValueError("unknown comparison fixture rule")
    return rules
