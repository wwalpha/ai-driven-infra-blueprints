"""Comparison records and display evidence; predicates run before output redaction."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import partial as _bind_framework_callback

from utils.iac_values import (
    array_presence,
    safe_value,
    same,
    selected_same,
    unknown_value,
)

import comparison.values as _imports_comparison_values

from .deferral import failure_category


def identifier(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]

def safe_text(text):
    value = safe_value(text)
    value = re.sub(r'(?i)((?:password|secretstring|token|credential)\s*[=:]\s*)[^\s,;]+', r'\1<masked>', value)
    return value.replace('\n', ' ').replace('\r', ' ')



def _value_differences_child(value, key):
    return value[key] if isinstance(value, (dict, list)) else value


def _callback_value_differences_formatted(missing, /, value):
    if value is missing:
        return '欠落'
    if isinstance(value, str) and re.fullmatch(r'[A-Za-z_$][\w ./$:-]*', value) and value not in {'null', 'true', 'false'}:
        return value
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _callback_value_differences_add(differences, formatted, property_name, /, path, left, right):
    differences.append({'path': safe_text(path or property_name),
                        'model': formatted(left), 'iac': formatted(right)})


def _recursive_value_differences_walk(add, child, exact, formatted, missing, predicate, property_name, reference, /, left, right, shown_left, shown_right, path, name):
    if left is missing and unknown_value(right):
        return
    if left is missing or right is missing:
        add(path, shown_left, shown_right)
        return
    if reference is None:
        equal = predicate(left, right, name)
    else:
        field = property_name.rsplit('.', 1)[-1]
        typed_path = path if path.startswith(field + '[') else field + ('.' + path if path else '')
        typed_path = re.sub(r'\[\d+\]', '[]', typed_path)
        equal = (same(left, right, reference=reference, path=typed_path) if exact else
                 selected_same(left, right, name, reference=reference, path=typed_path))
    if equal is None or equal:
        return
    if type(left) is not type(right):
        add(path, shown_left, shown_right)
    elif isinstance(left, dict):
        for key in sorted(left.keys() | right.keys() if exact else left.keys()):
            _recursive_value_differences_walk(add, child, exact, formatted, missing, predicate, property_name, reference, left.get(key, missing), right.get(key, missing),
                 child(shown_left, key) if key in left else missing,
                 child(shown_right, key) if key in right else missing,
                 f'{path}.{key}' if path else key, key)
    elif isinstance(left, list):
        if not exact and name in {'Tags', 'HostedZoneTags'} and all(isinstance(item, dict) and 'Key' in item for item in left):
            model_keys, iac_keys = {}, {}
            for i, item in enumerate(left):
                model_keys.setdefault(item['Key'], []).append(i)
            for i, item in enumerate(right):
                if isinstance(item, dict) and not unknown_value(item.get('Key')) and item.get('Key') in model_keys:
                    iac_keys.setdefault(item['Key'], []).append(i)
            unknown = sum(unknown_value(item) or isinstance(item, dict) and unknown_value(item.get('Key')) for item in right)
            if unknown and len(iac_keys) + unknown < len(model_keys):
                add(path + '.要素数', len(model_keys), {'min': len(iac_keys), 'max': len(iac_keys) + unknown})
            for key, model_indexes in model_keys.items():
                iac_indexes = iac_keys.get(key, [])
                field = f'{path}[Key={formatted(safe_value(key))}]'
                if len(model_indexes) != 1 or len(iac_indexes) > 1:
                    add(field + '.要素数（キー重複）', len(model_indexes), len(iac_indexes))
                elif not iac_indexes and unknown:
                    continue
                else:
                    i = model_indexes[0]
                    j = iac_indexes[0] if iac_indexes else None
                    _recursive_value_differences_walk(add, child, exact, formatted, missing, predicate, property_name, reference, left[i], right[j] if j is not None else missing,
                         child(shown_left, i), child(shown_right, j) if j is not None else missing, field, '')
        else:
            known, prefix = array_presence(right)
            if known != len(right) and not known <= len(left) <= len(right):
                add(path + '.要素数', len(left), {'min': known, 'max': len(right)})
            for i in range(max(len(left), len(right)) if known == len(right) else prefix):
                _recursive_value_differences_walk(add, child, exact, formatted, missing, predicate, property_name, reference, left[i] if i < len(left) else missing, right[i] if i < len(right) else missing,
                     child(shown_left, i) if i < len(left) else missing,
                     child(shown_right, i) if i < len(right) else missing, f'{path}[{i}]', name)
    else:
        add(path, shown_left, shown_right)


def value_differences(desired, actual, property_name='', *, exact=False, redact=safe_value, reference=None, missing_actual=False):
    """Display only: use the detector's predicate, then redact the differing leaves."""
    missing = object()
    differences = []
    predicate = (lambda left, right, name: same(left, right)) if exact else selected_same

    formatted = _bind_framework_callback(_callback_value_differences_formatted, missing)

    add = _bind_framework_callback(_callback_value_differences_add, differences, formatted, property_name)

    child = _value_differences_child

    walk = _bind_framework_callback(_recursive_value_differences_walk, add, child, exact, formatted, missing, predicate, property_name, reference)

    name = property_name.rsplit('.', 1)[-1]
    walk(desired, missing if missing_actual else actual, redact(desired, property_name),
         missing if missing_actual else redact(actual, property_name), name if isinstance(desired, list) else '', name)
    return differences

def redacted(value, prop='', *, sensitive_values=()):
    value = safe_value(value, prop)
    if prop in {'id','service','resource','resourceType','resourceMode','property','stack','code','naming_context_id','job_id','diagnostic_id','scope'}:
        return value
    if isinstance(value, str) and any(secret in value for secret in sensitive_values if secret):
        return '<masked sensitive parameter>'
    if isinstance(value, dict):
        return {key: redacted(item, key, sensitive_values=sensitive_values) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(item, prop, sensitive_values=sensitive_values) for item in value]
    return value


def record(category, service, identity, prop, reason, desired=None, actual=None,
           stack=None, source=None, template=None, cause=None, *, redact=safe_value, **details):
    result = dict(category=category, service=service, resource=identity, property=prop,
                  reason=reason, desired=redact(desired, prop), actual=redact(actual, prop),
                  stack=stack, model=source, iac=template)
    if cause:
        result['cause'] = redact(cause)
    result.update(details)
    return result


@dataclass
class RowResult:
    records: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    display_differences: dict = field(default_factory=dict)
    failure: Exception | None = None



def setting_result(service, identity, prop, desired, actual, decision, stack, sources, template, *,
                   exact, actual_error, redact, reference, default_source=None, missing=None, deferred_children=()):
    unverified = _imports_comparison_values.unverified
    source = sources[0] or default_source
    if decision.equal is None:
        item = record(failure_category(actual_error) if actual_error is not None else 'uncompared', service, identity, prop,
            str(actual_error) if actual_error is not None else 'reference identity or property format is unproven',
            stack=None if actual_error is not None else stack, source=source, template=template,
            cause=getattr(actual_error, 'iac_cause', None), redact=redact,
            reference_diagnostics=list(decision.diagnostics))
        return RowResult([item])
    if decision.equal:
        return RowResult([record('matched', service, identity, prop,
            'reference expression equivalent' if decision.equivalent else 'equal', stack=stack,
            source=source, template=template, redact=redact,
            **({"reference_diagnostics": list(decision.diagnostics)} if decision.diagnostics else {}))])
    details = {'model_sources': sources}
    if deferred_children:
        details['deferred_children'] = list(deferred_children)
    reason = missing or 'value mismatch'
    if decision.diagnostics:
        details['reference_diagnostics'] = list(decision.diagnostics)
        errors = [item['reason'] for item in decision.diagnostics if item['reason'].startswith('KMS format')
                  and item['reason'] != 'KMS format is unproven']
        if errors:
            reason = '; '.join(dict.fromkeys(errors))
    # The predicate sees raw values; masking is applied only to emitted evidence.
    differences = value_differences(desired, actual, prop, exact=exact, redact=redact,
        reference=(lambda a, b, path: reference(a, b, path).equal) if reference else None, missing_actual=bool(missing))
    item = record('difference', service, identity, prop, reason, desired, None if missing else actual, stack, source, template,
                  redact=redact, **details)
    records = [item]
    for pointer in sorted(set(unverified(desired)) | (set() if missing else set(unverified(actual)))):
        records.append(record('uncompared', service, identity, prop + '#' + pointer,
            'unresolved/unverified intrinsic; JSON Pointer=' + repr(pointer), stack=stack,
            source=source, template=template, redact=redact))
    return RowResult(records, display_differences={identifier(item): differences})
