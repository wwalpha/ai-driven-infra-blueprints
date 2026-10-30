"""Reference contracts and identity decisions over supplied values and tracked lookups."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback

from model.projection import reference_attribute
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, same
from utils.reference_contracts import (
    ATTRIBUTE_SUFFIXES,
    REFERENCE_EQUIVALENT_FORMS,
    REFERENCE_FORMS,
    REFERENCE_PROPERTIES,
    VALUE_IDENTITIES,
    contract,
    policy_condition,
    reference_error,
    requires_context,
    unproven_document_reference,
)

from . import expressions, registry


@dataclass(frozen=True)
class ReferenceDecision:
    equal: object
    diagnostics: tuple = ()
    equivalent: bool = False
    comparisons: tuple = ()


def reference_forms(kind, path, *, local_comparison, property_schema):
    key = kind + "." + path
    override = registry.property_rule(kind, path).forms
    if local_comparison and override is not None:
        return override
    try:
        node = property_schema(kind, path)
    except KeyError:
        node = {}
    registered = REFERENCE_PROPERTIES.get(key)
    forms = REFERENCE_FORMS.get(key)
    if forms is None and local_comparison and policy_condition(key):
        declared = contract(key)
        if declared:
            forms = {form for attributes in declared.values() for form in attributes}
    if forms is None and registered and registered[1]:
        forms = {registered[1]}
    return (
        {"Arn"}
        if node.get("pattern", "").startswith("^arn:")
        or node.get("type") == "string"
        and path.removesuffix("[]").lower().endswith(("arn", "arns"))
        else forms
    )


def _callback_reference_diagnostic_format_status(
    forms, kind, kms_format, local_comparison, path, resource_type, /, value
):
    if local_comparison and registry.property_rule(kind, path).forms is not None:
        form = kms_format(value)
        return (
            "unproven"
            if form is None
            else "allowed"
            if form in forms
            else "outside allowed forms"
        )
    if forms is None or not isinstance(value, ResourceReference):
        return "unproven"
    service, identity = value["$resource"]
    refkind = resource_type(value)
    return (
        "allowed"
        if value["$attribute"] in {reference_attribute(refkind, form) for form in forms}
        else "outside allowed forms"
    )


def reference_diagnostic(
    left,
    right,
    kind,
    path,
    reason,
    *,
    local_comparison,
    forms_for,
    kms_format,
    resource_type,
    redact,
):
    forms = forms_for(kind, path)
    symbols = all(isinstance(value, ResourceReference) for value in (left, right))
    identity = (
        ("same" if left["$resource"] == right["$resource"] else "different")
        if symbols
        else "unproven"
    )
    format_status = _bind_framework_callback(
        _callback_reference_diagnostic_format_status,
        forms,
        kind,
        kms_format,
        local_comparison,
        path,
        resource_type,
    )
    return redact(
        dict(
            path=kind + "." + path,
            model=redact(left, path),
            iac=redact(right, path),
            identity=identity,
            allowed_forms=sorted(forms) if forms is not None else None,
            format=dict(model=format_status(left), iac=format_status(right)),
            reason=reason,
        )
    )


def _callback_reference_same_unproven(
    decision, diagnostic, kind, left, path, right, /, reason
):
    return decision(None, [diagnostic(left, right, kind, path, reason)])


def _decision(equal, diagnostics=(), equivalent=False):
    return ReferenceDecision(equal, tuple(diagnostics), equivalent)


def _context_reference(root, context, results, compare, kind, /, left, right, path):
    if path == root:
        return NotImplemented
    outcome = compare(left, right, kind, path, context=context)
    results.append((left, right, path, outcome))
    return outcome.equal


def reference_same(
    left,
    right,
    kind,
    path,
    *,
    local_comparison,
    forms_for,
    resolve_literal,
    resource_type,
    kms_format,
    diagnostic,
    evidence=None,
    project_arn=None,
    context=None,
):
    if (
        local_comparison
        and context is not None
        and expressions.references(left)
        and reference_error(kind + "." + path, context)
    ):
        return ReferenceDecision(None)
    prop = kind + "." + path
    nested_symbols = expressions.references([left, right])
    if local_comparison and context is None:
        normalized = re.sub(r"\[\d+\]", "[]", prop)
        proven = [
            ref.receiving_context
            for ref in expressions.references(left)
            if getattr(ref, "receiving_property", None) == normalized
            and hasattr(ref, "receiving_context")
        ]
        if proven and all(item == proven[0] for item in proven):
            context = proven[0]
    rule = registry.property_rule(kind, path)
    if (
        local_comparison
        and nested_symbols
        and rule.whole == "SCALAR"
        and rule.forms is None
        and rule.direct_attribute is None
        and not requires_context(prop, context)
        and not contract(prop, context)
        and (
            forms_for(kind, path) == {"Arn"}
            or path.removesuffix("[]").lower().endswith(("id", "identifier"))
        )
    ):
        if evidence is not None and any(
            isinstance(value, str) for value in (left, right)
        ):
            result = evidence(left, right, kind, path)
            if result.equal is False:
                return result
        return ReferenceDecision(None)
    if (
        local_comparison
        and nested_symbols
        and (
            not (policy_condition(prop) or unproven_document_reference(prop))
            or expressions.references(left)
        )
        and requires_context(prop, context)
    ):
        declared = contract(prop, context)
        for symbol in nested_symbols:
            try:
                refkind = resource_type(symbol)
            except (KeyError, ValueError, TypeError):
                return ReferenceDecision(None)
            allowed = {
                reference_attribute(refkind, form) for form in declared.get(refkind, ())
            }
            for form in declared.get(refkind, ()):
                suffix = ATTRIBUTE_SUFFIXES.get((refkind, form))
                if suffix and isinstance(left, Expression):
                    try:
                        parts = expressions.parts(left, resource_type)
                    except (Blocked, ValueError, KeyError, TypeError):
                        return ReferenceDecision(None)
                    if (
                        len(parts) == 2
                        and isinstance(parts[0], ResourceReference)
                        and parts[1] == suffix[1]
                        and parts[0]["$attribute"] == suffix[0]
                    ):
                        allowed.add(suffix[0])
            if refkind not in declared or symbol["$attribute"] not in allowed:
                return ReferenceDecision(None)
    elif (
        local_comparison
        and registry.property_rule(kind, path).forms is None
        and not any(hasattr(value, "saved_literal") for value in (left, right))
    ):
        declared = contract(prop, context)
        symbols = [
            value
            for value in (left, right)
            if isinstance(value, ResourceReference)
            and not hasattr(value, "saved_literal")
        ]
        for value in (left, right):
            if isinstance(value, Expression):
                expression_symbols = expressions.references(value)
                if declared and expression_symbols:
                    try:
                        if not any(
                            resource_type(item) in declared
                            for item in expression_symbols
                        ):
                            return ReferenceDecision(None)
                    except (KeyError, ValueError, TypeError):
                        return ReferenceDecision(None)
                try:
                    parts = expressions.parts(value)
                except (Blocked, ValueError, KeyError, TypeError):
                    continue
                if len(parts) == 1 and isinstance(parts[0], ResourceReference):
                    symbols.append(parts[0])
                elif (
                    declared
                    and expression_symbols
                    and not any(
                        hasattr(item, "saved_literal") for item in nested_symbols
                    )
                ):
                    projected = project_arn(value) if project_arn is not None else None
                    if projected is None and len(expression_symbols) == 1:
                        source = expression_symbols[0]
                        try:
                            refkind = resource_type(source)
                            candidate = ResourceReference(
                                dict(
                                    source,
                                    **{
                                        "$attribute": reference_attribute(
                                            refkind, "Arn"
                                        )
                                    },
                                )
                            )
                            if (
                                refkind in declared
                                and "Arn" in declared[refkind]
                                and same(
                                    resolve_literal(value), resolve_literal(candidate)
                                )
                                is True
                            ):
                                projected = candidate
                        except (Blocked, ValueError, KeyError, TypeError, OSError):
                            pass
                    if projected is None:
                        return ReferenceDecision(None)
                    symbols.append(projected)
        for symbol in symbols if declared else ():
            try:
                refkind = resource_type(symbol)
            except (KeyError, ValueError, TypeError):
                return ReferenceDecision(None)
            if refkind not in declared or symbol["$attribute"] not in {
                reference_attribute(refkind, form) for form in declared[refkind]
            }:
                if evidence is not None and len(symbols) == 1:
                    result = evidence(left, right, kind, path)
                    if result.equal is False:
                        return result
                return ReferenceDecision(
                    False
                    if len(symbols) == 2 and same(left, right) is not True
                    else None
                )
    if evidence is not None and any(
        isinstance(value, Expression) for value in (left, right)
    ):
        if any(
            hasattr(source, "saved_literal")
            for source in expressions.references([left, right])
        ):
            return evidence(left, right, kind, path)
    if evidence is not None and any(
        hasattr(value, "saved_literal") for value in (left, right)
    ):
        return evidence(left, right, kind, path)
    if any(
        isinstance(value, Expression) and value.operation == "Unverified"
        for value in (left, right)
    ):
        return ReferenceDecision(None)
    decision = _decision
    rule = registry.property_rule(kind, path)
    if (
        local_comparison
        and rule.reference_context
        and rule.whole == "OBJECT"
        and isinstance(left, dict)
        and isinstance(right, dict)
    ):
        results = []
        compare = _bind_framework_callback(
            reference_same,
            local_comparison=local_comparison,
            forms_for=forms_for,
            resolve_literal=resolve_literal,
            resource_type=resource_type,
            kms_format=kms_format,
            diagnostic=diagnostic,
            evidence=evidence,
            project_arn=project_arn,
        )
        equal = same(
            left,
            right,
            path=path,
            reference=_bind_framework_callback(
                _context_reference, path, left, results, compare, kind
            ),
        )
        return ReferenceDecision(
            equal,
            tuple(d for _, _, _, result in results for d in result.diagnostics),
            any(result.equivalent for _, _, _, result in results),
            tuple((a, b, p, result.equal) for a, b, p, result in results),
        )
    symbols = [value for value in (left, right) if isinstance(value, ResourceReference)]
    prop = kind + "." + path
    if (
        local_comparison
        and context is not None
        and symbols
        and requires_context(prop, context)
    ):
        declared = contract(prop, context)
        if not declared:
            return decision(None)
        for symbol in symbols:
            refkind = resource_type(symbol)
            if refkind not in declared or symbol["$attribute"] not in {
                reference_attribute(refkind, form) for form in declared[refkind]
            }:
                return decision(None)
        if len(symbols) == 2:
            return decision(same(left, right))
        other = right if isinstance(left, ResourceReference) else left
        if not isinstance(other, str) or "{{resolve:" in other or "${" in other:
            return decision(None)
        symbol = symbols[0]
        refkind = resource_type(symbol)
        alternatives = REFERENCE_EQUIVALENT_FORMS.get(
            (prop, refkind, symbol["$attribute"]), ()
        )
        unknown = False
        for form in declared[refkind]:
            if (
                reference_attribute(refkind, form) != symbol["$attribute"]
                and form not in alternatives
            ):
                continue
            pattern = VALUE_IDENTITIES.get((refkind, form))
            if pattern and not re.fullmatch(pattern, other):
                continue
            candidate = ResourceReference(
                dict(symbol, **{"$attribute": reference_attribute(refkind, form)})
            )
            try:
                concrete = resolve_literal(candidate)
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                unknown = True
                continue
            if (
                not isinstance(concrete, str)
                or "{{resolve:" in concrete
                or "${" in concrete
            ):
                unknown = True
            elif same(concrete, other) is True:
                return decision(True, equivalent=True)
        return decision(None if unknown else False)
    allowed = registry.property_rule(kind, path).forms if local_comparison else None
    if allowed:
        result, reason = registry.property_rule(kind, path).form_compare(
            left,
            right,
            allowed,
            resolve_literal=resolve_literal,
            format_of=kms_format,
            project_arn=project_arn,
        )
        if result is NotImplemented:
            if evidence is not None:
                return evidence(left, right, kind, path)
            result = None
        details = [diagnostic(left, right, kind, path, reason)] if reason else []
        for detail in details:
            detail.update(evidence_type="logical_reference", current_aws_verified=False)
        return decision(result, details)
    if evidence is not None:
        if isinstance(left, str) and isinstance(right, (ResourceReference, Expression)):
            return evidence(left, right, kind, path)
        if isinstance(right, str) and isinstance(left, (ResourceReference, Expression)):
            return evidence(left, right, kind, path)
    unproven = _bind_framework_callback(
        _callback_reference_same_unproven, decision, diagnostic, kind, left, path, right
    )

    if isinstance(left, Expression) or isinstance(right, Expression):
        try:
            left_parts, right_parts = (
                expressions.parts(left, resource_type),
                expressions.parts(right, resource_type),
            )
            equal = expressions.symbolic_same(left_parts, right_parts)
            if equal is not None:
                return decision(equal)
        except (Blocked, ValueError, KeyError, TypeError):
            pass
        if (
            isinstance(left, Expression)
            and isinstance(right, Expression)
            and left.operation == right.operation
            and left.operation in {"Split", "Select"}
        ):
            equal = expressions.exact_same(left, right)
            if equal is True:
                return decision(True)
            if equal is None:
                return unproven("expression contains an unresolved reference operand")
        expression, other = (
            (left, right) if isinstance(left, Expression) else (right, left)
        )
        if isinstance(other, (Expression, ResourceReference)):
            left_refs, right_refs = (
                expressions.references(left),
                expressions.references(right),
            )
            if (
                left_refs
                and right_refs
                and same(
                    [ref["$resource"] for ref in left_refs],
                    [ref["$resource"] for ref in right_refs],
                )
                is not True
            ):
                return unproven("expression Producer correspondence is unproven")
            try:
                return decision(
                    same(resolve_literal(expression), resolve_literal(other))
                )
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                return unproven("expression string equivalence is unproven")
        if not isinstance(other, str):
            return unproven(
                "unresolved expression; reference identity and format cannot be proven"
            )
        try:
            equal = same(resolve_literal(expression), other)
        except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
            return unproven(str(error))
        return decision(equal, equivalent=bool(equal))
    symbols = [value for value in (left, right) if isinstance(value, ResourceReference)]
    if not symbols:
        return decision(NotImplemented)
    if not any(
        registry.resource(resource_type(value)).identity_same is not None
        for value in symbols
    ):
        if len(symbols) == 2:
            if left["$resource"] != right["$resource"]:
                return decision(False)
            if left["$attribute"] == right["$attribute"]:
                return decision(True)
            try:
                return decision(same(resolve_literal(left), resolve_literal(right)))
            except (Blocked, ValueError, KeyError, TypeError, OSError):
                return unproven("attribute equivalence is unproven")
        other = right if isinstance(left, ResourceReference) else left
        if not isinstance(other, str):
            return unproven("literal versus reference has no proven string contract")
        forms = forms_for(kind, path)
        refkind = resource_type(symbols[0])
        if (
            forms
            and "Arn" in forms
            and other.startswith("arn:")
            and symbols[0]["$attribute"] != reference_attribute(refkind, "Arn")
        ):
            return unproven(
                "literal uses an alternative allowed format; local reference value is unproven"
            )
        try:
            concrete = resolve_literal(symbols[0])
        except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
            return unproven(str(error))
        equal = same(concrete, other)
        return decision(equal, equivalent=bool(equal))
    if len(symbols) != 2:
        # No observed/AWS values: a literal cannot prove this symbolic identity.
        return unproven(
            "literal versus symbolic reference; no observed value proves identity or format"
        )
    provider = (
        registry.resource(resource_type(left)).identity_same
        or registry.resource(resource_type(right)).identity_same
    )
    forms = forms_for(kind, path)
    forms = (
        {reference_attribute(resource_type(left), form) for form in forms}
        if forms
        else forms
    )
    equal, reason, equivalent = provider(left, right, forms)
    return decision(
        equal,
        [diagnostic(left, right, kind, path, reason)] if reason else (),
        equivalent,
    )


def literal_expression(value, *, resolve_literal):
    if value.operation in {"Split", "Select"}:
        first, source = value.operands
        if isinstance(source, (ResourceReference, Expression)):
            source = resolve_literal(source)
        if (
            value.operation == "Split"
            and isinstance(first, str)
            and first
            and isinstance(source, str)
        ):
            return source.split(first)
        if (
            value.operation == "Select"
            and isinstance(source, list)
            and re.fullmatch(r"\d+", str(first))
            and int(first) < len(source)
        ):
            selected = source[int(first)]
            return (
                resolve_literal(selected)
                if isinstance(selected, (ResourceReference, Expression))
                else selected
            )
        raise Blocked("Split/Select requires concrete operands and an in-bounds index")
    return expressions.literal(value, resolve_literal)
