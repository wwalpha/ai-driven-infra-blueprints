"""Validate typed Resource symbols under explicit receiving-property contracts."""

import re
from copy import copy

from services.reference_engine import REFERENCES
from services.registry import REGISTRY
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression


def desired_reference(
    service,
    value,
    kind,
    path,
    attribute=None,
    context=None,
    *,
    local_comparison,
    reference,
    resource_type,
    forms_for,
    protect_import,
):
    path = re.sub(r"\[\d+\]", "[]", path)
    context = context or {}
    declared = (
        (REFERENCES.import_targets(kind + "." + path, context) or {})
        if local_comparison
        else {}
    )
    if (
        local_comparison
        and not declared
        and REFERENCES.context_required_at(kind + "." + path, context)
    ):
        raise Blocked(
            f"reference context or receiving property contract unproven: {kind}.{path}"
        )
    if local_comparison and (error := REFERENCES.error_at(kind + "." + path, context)):
        raise Blocked(error)
    expected_kind = None
    contract = REFERENCES.direct_reference(kind + "." + path)
    if local_comparison:
        if declared:
            if len(declared) == 1:
                (expected_kind,) = declared
        elif contract:
            expected_kind, default_attribute = contract
            if attribute is None:
                attribute = default_attribute
        elif attribute is None and forms_for(kind, path) == {"Arn"}:
            attribute = "Arn"
        elif attribute is None and forms_for(kind, path) is None:
            raise Blocked(f"reference property contract unproven: {kind}.{path}")
    symbol = reference(service, value, attribute, protect_import=False)
    forms = forms_for(kind, path) if local_comparison else None
    refservice, identity = symbol["$resource"]
    refkind = resource_type(symbol)
    if (
        forms
        and REGISTRY.comparison_property_rule(kind, path).forms is None
        and symbol["$attribute"]
        not in {REFERENCES.formal_attribute(refkind, form) for form in forms}
    ):
        error = Blocked(
            f"reference attribute {symbol['$attribute']} is outside property contract: {kind}.{path}"
        )
        error.reference_detail = (symbol, path)
        raise error
    if expected_kind:
        if refkind not in (
            (expected_kind,) if isinstance(expected_kind, str) else expected_kind
        ):
            raise Blocked(f"reference target must be {expected_kind}: {kind}.{path}")
    if declared and (
        refkind not in declared
        or symbol["$attribute"]
        not in {
            REFERENCES.formal_attribute(refkind, form) for form in declared[refkind]
        }
    ):
        raise Blocked(
            f"reference target or attribute is outside receiving property contract: {kind}.{path}"
        )
    # IMPORT may wait only after every receiving/producer contract has passed.
    symbol = protect_import(
        symbol, kind + "." + path if declared or contract or forms else None
    )
    if (
        declared
        and context
        and REFERENCES.context_required_at(kind + "." + path, context)
    ):
        symbol = copy(symbol)
        symbol.receiving_context = dict(context)
        symbol.receiving_property = kind + "." + path
    suffix = REFERENCES.attribute_suffix(refkind, symbol["$attribute"])
    if suffix:
        child = copy(symbol)
        child["$attribute"] = suffix[0]
        return Expression(
            "Join",
            [
                "",
                [
                    child,
                    suffix[1],
                ],
            ],
        )
    return symbol
