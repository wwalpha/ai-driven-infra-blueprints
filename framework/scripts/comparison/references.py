"""Reference contracts and identity decisions over supplied values and tracked lookups."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback

from services.reference_engine import REFERENCES
from services.registry import REGISTRY
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, same

from . import expressions


@dataclass(frozen=True)
class ReferenceDecision:
    equal: object
    diagnostics: tuple = ()
    equivalent: bool = False
    comparisons: tuple = ()


def reference_forms(kind, path, *, local_comparison, property_schema):
    key = kind + "." + path
    override = REGISTRY.comparison_property_rule(kind, path).forms
    if local_comparison and override is not None:
        return override
    try:
        node = property_schema(kind, path)
    except KeyError:
        node = {}
    registered = REFERENCES.direct_reference(key)
    forms = REFERENCES.declared_consumer_forms(key)
    if forms is not None:
        return forms
    if local_comparison and REFERENCES.policy_condition(key):
        declared = REFERENCES.comparison_targets(key) or {}
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
    if (
        local_comparison
        and REGISTRY.comparison_property_rule(kind, path).forms is not None
    ):
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
        if value["$attribute"]
        in {REFERENCES.formal_attribute(refkind, form) for form in forms}
        else "outside allowed forms"
    )


def reference_diagnostic(
    left,
    right,
    kind,
    path,
    reason,
    *,
    code=None,
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
            **({"code": code} if code is not None else {}),
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
    proven_export=False,
):
    receiver = REGISTRY.comparison_contract(kind)
    if (
        local_comparison
        and context is not None
        and expressions.references(left)
        and REFERENCES.error_at(kind + "." + path, context)
    ):
        # External declarations describe saved strings without adding Model Resource links.
        if (
            evidence is not None
            and receiver.identifier_evidence is not None
            and receiver.identifier_evidence(left, right, context)
        ):
            return evidence(left, right, kind, path)
        return ReferenceDecision(None)
    prop = kind + "." + path
    if (
        local_comparison
        and path in receiver.defer_reference_arrays
        and isinstance(left, list)
        and isinstance(right, list)
    ):
        # The receiving Type is attached to each Values[] reference.
        return ReferenceDecision(NotImplemented)
    if (
        local_comparison
        and type(left) is dict
        and type(right) is dict
        and prop.rpartition(".")[0].endswith(".Condition")
        and REFERENCES.policy_condition(prop)
    ):
        # The receiving contract belongs to the condition key inside the operator.
        return ReferenceDecision(NotImplemented)
    nested_symbols = expressions.references([left, right])
    blocked = (
        receiver.blocked_reference_attributes.get(path) if local_comparison else None
    )
    if blocked is not None:
        try:
            if any(
                (resource_type(symbol), symbol["$attribute"]) == blocked
                for symbol in nested_symbols
            ):
                return ReferenceDecision(None)
        except (Blocked, KeyError, ValueError, TypeError):
            return ReferenceDecision(None)
    normalized = re.sub(r"\[\d+\]", "[]", prop) if local_comparison else prop
    if local_comparison and context is None:
        proven = [
            ref.receiving_context
            for ref in expressions.references(left)
            if getattr(ref, "receiving_property", None) == normalized
            and hasattr(ref, "receiving_context")
        ]
        if proven and all(item == proven[0] for item in proven):
            context = proven[0]
    rule = REGISTRY.comparison_property_rule(kind, path)
    declared = (
        (REFERENCES.comparison_targets(prop, context) or {}) if local_comparison else {}
    )
    if (
        local_comparison
        and nested_symbols
        and rule.whole == "SCALAR"
        and rule.forms is None
        and rule.direct_attribute is None
        and not REFERENCES.context_required_at(prop, context)
        and not declared
    ):
        export_attribute = receiver.export_attributes.get(path)
        try:
            exported = (
                proven_export
                and export_attribute is not None
                and all(
                    (resource_type(symbol), symbol["$attribute"]) == export_attribute
                    for symbol in nested_symbols
                )
            )
        except (Blocked, KeyError, ValueError, TypeError):
            exported = False
        if not exported:
            if evidence is not None and any(
                isinstance(value, str) for value in (left, right)
            ):
                result = evidence(left, right, kind, path)
                if result.equal is False or (
                    result.equal is True
                    and forms_for(kind, path) != {"Arn"}
                    and not path.removesuffix("[]")
                    .lower()
                    .endswith(("id", "identifier"))
                ):
                    return result
            return ReferenceDecision(None)
    if (
        local_comparison
        and nested_symbols
        and (
            not (
                REFERENCES.policy_condition(prop)
                or REFERENCES.unproven_document_reference(prop)
            )
            or expressions.references(left)
        )
        and REFERENCES.context_required_at(prop, context)
    ):
        for symbol in nested_symbols:
            try:
                refkind = resource_type(symbol)
            except (KeyError, ValueError, TypeError):
                return ReferenceDecision(None)
            allowed = {
                REFERENCES.formal_attribute(refkind, form)
                for form in declared.get(refkind, ())
            }
            for form in declared.get(refkind, ()):
                suffix = REFERENCES.attribute_suffix(refkind, form)
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
    elif local_comparison:
        for value in (left, right):
            for symbol in expressions.references(value) if declared else ():
                try:
                    refkind = resource_type(symbol)
                    if refkind not in declared:
                        if rule.forms is not None and REFERENCES.identifier_forms(
                            refkind
                        ):
                            return ReferenceDecision(
                                False,
                                (
                                    diagnostic(
                                        left,
                                        right,
                                        kind,
                                        path,
                                        "resource_type_mismatch",
                                    ),
                                ),
                            )
                        return ReferenceDecision(None)
                    if rule.forms is not None and REFERENCES.identifier_forms(refkind):
                        if symbol["$attribute"] not in {
                            REFERENCES.formal_attribute(refkind, form)
                            for form in REFERENCES.identifier_forms(refkind)
                        }:
                            return ReferenceDecision(None)
                        continue
                    allowed = {
                        REFERENCES.formal_attribute(refkind, form)
                        for form in declared.get(refkind, ())
                    }
                    if symbol["$attribute"] not in allowed and not hasattr(
                        symbol, "saved_literal"
                    ):
                        projected = (
                            project_arn(value)
                            if isinstance(value, Expression) and project_arn is not None
                            else None
                        )
                        if (
                            projected is None
                            or projected["$resource"] != symbol["$resource"]
                            or projected["$attribute"] not in allowed
                        ):
                            return ReferenceDecision(None)
                except (Blocked, KeyError, ValueError, TypeError):
                    return ReferenceDecision(None)
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
    rule = REGISTRY.comparison_property_rule(kind, path)
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
        and REFERENCES.context_required_at(prop, context)
    ):
        if not declared:
            return decision(None)
        for symbol in symbols:
            refkind = resource_type(symbol)
            if refkind not in declared or symbol["$attribute"] not in {
                REFERENCES.formal_attribute(refkind, form) for form in declared[refkind]
            }:
                return decision(None)
        if len(symbols) == 2:
            return decision(same(left, right))
        other = right if isinstance(left, ResourceReference) else left
        if not isinstance(other, str) or "{{resolve:" in other or "${" in other:
            return decision(None)
        symbol = symbols[0]
        refkind = resource_type(symbol)
        alternatives = REFERENCES.equivalent_forms(prop, refkind, symbol["$attribute"])
        unknown = False
        for form in declared[refkind]:
            if (
                REFERENCES.formal_attribute(refkind, form) != symbol["$attribute"]
                and form not in alternatives
            ):
                continue
            pattern = REFERENCES.identity_pattern(refkind, form)
            if pattern and not re.fullmatch(pattern, other):
                continue
            candidate = ResourceReference(
                dict(
                    symbol, **{"$attribute": REFERENCES.formal_attribute(refkind, form)}
                )
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
    allowed = (
        REGISTRY.comparison_property_rule(kind, path).forms
        if local_comparison
        else None
    )
    if allowed:
        outcome = REGISTRY.comparison_property_rule(kind, path).form_compare(
            left,
            right,
            allowed,
            resolve_literal=resolve_literal,
            format_of=kms_format,
            project_arn=project_arn,
        )
        result = outcome.equal
        if result is NotImplemented:
            if evidence is not None:
                return evidence(left, right, kind, path)
            result = None
        details = (
            [diagnostic(left, right, kind, path, outcome.message, code=outcome.code)]
            if outcome.code
            else [diagnostic(left, right, kind, path, outcome.message)]
            if outcome.message
            else []
        )
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
        if (
            local_comparison
            and project_arn is not None
            and isinstance(other, ResourceReference)
            and other["$attribute"] == "Arn"
            and (projected := project_arn(expression)) == other
            and resource_type(projected) == "KMS.Key"
        ):
            return decision(True)
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
        REGISTRY.comparison_contract(resource_type(value)).identity_same is not None
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
            and symbols[0]["$attribute"] != REFERENCES.formal_attribute(refkind, "Arn")
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
        REGISTRY.comparison_contract(resource_type(left)).identity_same
        or REGISTRY.comparison_contract(resource_type(right)).identity_same
    )
    forms = forms_for(kind, path)
    forms = (
        {REFERENCES.formal_attribute(resource_type(left), form) for form in forms}
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
