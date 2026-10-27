"""Convert Model resource links under explicit receiving-property contracts."""

import re

from model.projection import reference_attribute
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference
from utils.reference_contracts import (
    ATTRIBUTE_SUFFIXES,
    CONTEXT_DEFAULT_ON_MISMATCH,
    REFERENCE_PROPERTIES,
    reference_error,
    requires_context,
)
from utils.reference_contracts import (
    contract as receiving_contract,
)

from . import registry


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
        receiving_contract(kind + "." + path, context) if local_comparison else {}
    )
    if (
        local_comparison
        and not declared
        and requires_context(kind + "." + path, context)
    ):
        raise Blocked(
            f"reference context or receiving property contract unproven: {kind}.{path}"
        )
    if local_comparison and (error := reference_error(kind + "." + path, context)):
        raise Blocked(error)
    if (
        local_comparison
        and not isinstance(value, ResourceReference)
        and registry.property_rule(kind, path).forms is not None
    ):
        symbol = reference(service, value, protect_import=False)
        refservice, identity = symbol["$resource"]
        refkind = resource_type(symbol)
        if registry.property_rule(kind, path).forms <= {"KeyArn", "AliasArn"}:
            selected = registry.resource(refkind).arn_attribute or symbol["$attribute"]
            symbol = ResourceReference(dict(symbol, **{"$attribute": selected}))
        value = symbol
        attribute = value["$attribute"] if attribute is None else attribute
    expected_kind = None
    contract = REFERENCE_PROPERTIES.get(kind + "." + path)
    if local_comparison:
        if requires_context(kind + "." + path, context) and declared:
            (expected_kind,) = declared
            forms = declared[expected_kind]
            if not isinstance(value, ResourceReference):
                if attribute is None or (
                    attribute not in forms
                    and kind + "." + path in CONTEXT_DEFAULT_ON_MISMATCH
                ):
                    attribute = forms[0]
                elif attribute not in forms:
                    raise Blocked(
                        f"reference attribute is outside property contract: {kind}.{path}"
                    )
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
        and registry.property_rule(kind, path).forms is None
        and symbol["$attribute"]
        not in {reference_attribute(refkind, form) for form in forms}
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
        not in {reference_attribute(refkind, form) for form in declared[refkind]}
    ):
        raise Blocked(
            f"reference target or attribute is outside receiving property contract: {kind}.{path}"
        )
    # IMPORT may wait only after every receiving/producer contract has passed.
    symbol = protect_import(
        symbol, kind + "." + path if declared or contract or forms else None
    )
    suffix = ATTRIBUTE_SUFFIXES.get((refkind, symbol["$attribute"]))
    if suffix:
        return Expression(
            "Join",
            [
                "",
                [
                    ResourceReference(dict(symbol, **{"$attribute": suffix[0]})),
                    suffix[1],
                ],
            ],
        )
    return symbol
