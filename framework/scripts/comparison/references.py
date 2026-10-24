"""Reference contracts and identity decisions over supplied values and tracked lookups."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback

from cloudformation_inputs import Blocked
from iac_values import Expression, ResourceReference, same
from model.projection import reference_attribute
from reference_contracts import (
    REFERENCE_FORMS,
    REFERENCE_PROPERTIES,
)

from . import registry


@dataclass(frozen=True)
class ReferenceDecision:
    equal: object
    diagnostics: tuple = ()
    equivalent: bool = False


def reference_forms(kind, path, *, local_comparison, property_schema):
    key = kind + '.' + path
    override = registry.kms_forms(kind, path)
    if local_comparison and override is not None:
        return override
    try:
        node = property_schema(kind, path)
    except KeyError:
        node = {}
    contract = REFERENCE_PROPERTIES.get(key)
    forms = REFERENCE_FORMS.get(key)
    if forms is None and contract and contract[1]:
        forms = {contract[1]}
    return ({'Arn'} if node.get('pattern', '').startswith('^arn:') or
            node.get('type') == 'string' and path.removesuffix('[]').lower().endswith(('arn', 'arns')) else forms)

def _callback_reference_diagnostic_format_status(forms, kind, kms_format, local_comparison, path, resource_type, /, value):
    if local_comparison and registry.kms_forms(kind, path) is not None:
        form = kms_format(value)
        return 'unproven' if form is None else 'allowed' if form in forms else 'outside allowed forms'
    if forms is None or not isinstance(value, ResourceReference):
        return 'unproven'
    service, identity = value['$resource']
    refkind = resource_type(value)
    return 'allowed' if value['$attribute'] in {reference_attribute(refkind, form) for form in forms} else 'outside allowed forms'


def reference_diagnostic(left, right, kind, path, reason, *, local_comparison, forms_for, kms_format, resource_type, redact):
    forms = forms_for(kind, path)
    symbols = all(isinstance(value, ResourceReference) for value in (left, right))
    identity = ('same' if left['$resource'] == right['$resource'] else 'different') if symbols else 'unproven'
    format_status = _bind_framework_callback(_callback_reference_diagnostic_format_status, forms, kind, kms_format, local_comparison, path, resource_type)
    return redact(dict(path=kind + '.' + path, model=redact(left, path),
                              iac=redact(right, path), identity=identity,
                              allowed_forms=sorted(forms) if forms is not None else None,
                              format=dict(model=format_status(left), iac=format_status(right)), reason=reason))

def _callback_reference_same_reference(diagnostic, evidence, forms_for, kind, kms_format, local_comparison, nested, resolve_literal, resource_type, /, a, b, p):
    outcome = reference_same(a, b, kind, p, local_comparison=local_comparison,
        forms_for=forms_for, resolve_literal=resolve_literal, resource_type=resource_type,
        kms_format=kms_format, diagnostic=diagnostic, evidence=evidence)
    nested.append(outcome)
    return outcome.equal


def _callback_reference_same_unproven(decision, diagnostic, kind, left, path, right, /, reason):
    return decision(None, [diagnostic(left, right, kind, path, reason)])


def _callback_reference_same_decision(nested, /, equal, diagnostics=(), equivalent=False):
    return ReferenceDecision(equal, tuple(diagnostics) + tuple(d for result in nested for d in result.diagnostics),
                             equivalent or any(result.equivalent for result in nested))


def reference_same(left, right, kind, path, *, local_comparison, forms_for, resolve_literal, resource_type, kms_format, diagnostic, evidence=None):
    if evidence is not None and hasattr(left, "saved_literal"):
        return evidence(left, right, kind, path)
    if any(isinstance(value, Expression) and value.operation == 'Unverified' for value in (left, right)):
        return ReferenceDecision(None)
    nested = []
    reference = _bind_framework_callback(_callback_reference_same_reference, diagnostic, evidence, forms_for, kind, kms_format, local_comparison, nested, resolve_literal, resource_type)
    decision = _bind_framework_callback(_callback_reference_same_decision, nested)
    hook = registry.hook(kind, 'reference_compare')
    if hook is not None:
        if registry.hook(kind, 'INVERSE_ROLES') is not None:
            result = hook(kind, left, right, path, reference)
        elif local_comparison:
            result = hook(left, right, path, resolve_literal, kms_format, resource_type, reference)
        else:
            result = NotImplemented
        if result is not NotImplemented:
            return decision(result)
    allowed = registry.kms_forms(kind, path) if local_comparison else None
    if allowed:
        result, reason = registry.compare_kms_forms(left, right, allowed, resolve_literal=resolve_literal,
                                                    format_of=kms_format)
        if (result is not None or evidence is None or
                not (isinstance(left, str) and isinstance(right, (ResourceReference, Expression)))):
            return decision(result, [diagnostic(left, right, kind, path, reason)] if reason else ())
    if evidence is not None and isinstance(left, str) and isinstance(right, (ResourceReference, Expression)):
        return evidence(left, right, kind, path)
    unproven = _bind_framework_callback(_callback_reference_same_unproven, decision, diagnostic, kind, left, path, right)

    if isinstance(left, Expression) or isinstance(right, Expression):
        if same(left, right):
            return decision(True)
        expression, other = (left, right) if isinstance(left, Expression) else (right, left)
        if not isinstance(other, str):
            return unproven('unresolved expression; reference identity and format cannot be proven')
        try:
            equal = same(resolve_literal(expression), other)
        except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
            return unproven(str(error))
        return decision(equal, equivalent=bool(equal))
    symbols = [value for value in (left, right) if isinstance(value, ResourceReference)]
    if not symbols:
        return decision(NotImplemented)
    if not any(resource_type(value) in getattr(registry.rules(resource_type(value)), 'IDENTITY_KINDS', set()) for value in symbols):
        if len(symbols) == 2:
            forms = forms_for(kind, path)
            refkind = resource_type(left)
            allowed = {reference_attribute(refkind, form) for form in forms or ()}
            if left['$resource'] == right['$resource'] and left['$attribute'] in allowed and right['$attribute'] in allowed:
                return decision(True, equivalent=left['$attribute'] != right['$attribute'])
            return decision(same(left, right))
        other = right if isinstance(left, ResourceReference) else left
        if not isinstance(other, str):
            return unproven('literal versus reference has no proven string contract')
        forms = forms_for(kind, path)
        refkind = resource_type(symbols[0])
        if forms and 'Arn' in forms and other.startswith('arn:') and symbols[0]['$attribute'] != reference_attribute(refkind, 'Arn'):
            return unproven('literal uses an alternative allowed format; local reference value is unproven')
        try:
            concrete = resolve_literal(symbols[0])
        except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
            return unproven(str(error))
        equal = same(concrete, other)
        return decision(equal, equivalent=bool(equal))
    if len(symbols) != 2:
        # No observed/AWS values: a literal cannot prove this symbolic identity.
        return unproven('literal versus symbolic reference; no observed value proves identity or format')
    provider = (registry.hook(resource_type(left), 'identity_same') or
                registry.hook(resource_type(right), 'identity_same'))
    equal, reason, equivalent = provider(left, right, forms_for(kind, path))
    return decision(equal, [diagnostic(left, right, kind, path, reason)] if reason else (), equivalent)


def _callback_literal_expression_replace(resolve_literal, resource_type, variables, /, match):
    key = match.group(1)
    if key.startswith('!'):
        return '${' + key[1:] + '}'
    child = variables[key]
    if isinstance(child, str):
        return child
    if isinstance(child, ResourceReference):
        service, identity = child['$resource']
        if registry.sub_arn(resource_type(child)) and child['$attribute'] == 'Arn':
            return resolve_literal(child)
    if isinstance(child, Expression):
        resolved = resolve_literal(child)
        if isinstance(resolved, str):
            return resolved
    raise Blocked('Sub variable requires a proven S3 ARN or string')


def literal_expression(value, *, resolve_literal, resource_type):
    if value.operation in {'Split', 'Select'}:
        first, source = value.operands
        if isinstance(source, (ResourceReference, Expression)):
            source = resolve_literal(source)
        if value.operation == 'Split' and isinstance(first, str) and first and isinstance(source, str):
            return source.split(first)
        if value.operation == 'Select' and isinstance(source, list) and re.fullmatch(r'\d+', str(first)) and int(first) < len(source):
            return source[int(first)]
        raise Blocked('Split/Select requires concrete operands and an in-bounds index')
    if value.operation != 'Sub':
        raise Blocked('expression has no local literal comparison contract')
    text, variables = value.operands
    replace = _bind_framework_callback(_callback_literal_expression_replace, resolve_literal, resource_type, variables)
    return re.sub(r'\$\{([^}]+)\}', replace, text)
