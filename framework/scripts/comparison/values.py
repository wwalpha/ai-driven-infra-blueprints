"""Desired value preparation and typed equivalence; no file/CLI/AWS acquisition."""

import re
from dataclasses import dataclass
from functools import partial as _bind_framework_callback

import json_intrinsics as _imports_json_intrinsics
from model.identity import resource_link
from policy_tables import literal
from utils.cloudformation.inputs import Blocked
from utils.iac_values import (
    Expression,
    same,
    selected_same,
    unordered_same,
)
from utils.json_format import policy_json as strict_json

from . import registry

_CALLBACK_DEFAULT = object()



@dataclass(frozen=True)
class PreparedValue:
    value: object
    warnings: list
    error: Exception | None = None

    def require_value(self):
        if self.error is not None:
            raise self.error
        return self.value


@dataclass(frozen=True)
class ValueDecision:
    equal: object
    diagnostics: tuple
    equivalent: bool


def desired_value(service, row, kind, *, local_comparison, desired_reference, property_schema, evaluate, model_path, stack=None, context=None, normalize=None):
    warnings = []
    try:
        value = _desired_value(service, row, kind, local_comparison=local_comparison,
            desired_reference=desired_reference, property_schema=property_schema,
            evaluate=evaluate, model_path=model_path, stack=stack, context=context, warnings=warnings)
        if normalize is not None:
            value = normalize(value)
    except (Blocked, KeyError, ValueError, TypeError) as error:
        return PreparedValue(None, warnings, error)
    return PreparedValue(value, warnings)


def _callback__desired_value_references_86(desired_reference, evaluate, kind, local_comparison, model_path, policy, row, service, stack, warnings, _default_field, _default_operands, _default_path, _default_context, _default_pointer, /, item, field=_CALLBACK_DEFAULT, operands=_CALLBACK_DEFAULT, path=_CALLBACK_DEFAULT, context=_CALLBACK_DEFAULT, pointer=_CALLBACK_DEFAULT):
    if field is _CALLBACK_DEFAULT:
        field = _default_field
    if operands is _CALLBACK_DEFAULT:
        operands = _default_operands
    if path is _CALLBACK_DEFAULT:
        path = _default_path
    if context is _CALLBACK_DEFAULT:
        context = _default_context
    if pointer is _CALLBACK_DEFAULT:
        pointer = _default_pointer
    if isinstance(item, str) and resource_link(item):
        attribute = 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None
        return desired_reference(service, item, kind, path, attribute, context)
    if isinstance(item, list):
        return [_callback__desired_value_references_86(desired_reference, evaluate, kind, local_comparison, model_path, policy, row, service, stack, warnings, _default_field, _default_operands, _default_path, _default_context, _default_pointer, child, field, operands, path + '[]', context, pointer + '/' + str(index))
                for index, child in enumerate(item)]
    if isinstance(item, dict):
        if local_comparison:
            intrinsic = _imports_json_intrinsics.intrinsic
            project_document = _imports_json_intrinsics.project_document
            if intrinsic(item) and not operands:
                expression = {key: _callback__desired_value_references_86(desired_reference, evaluate, kind, local_comparison, model_path, policy, row, service, stack, warnings, _default_field, _default_operands, _default_path, _default_context, _default_pointer, child, field, True, path, context, pointer + '/' + key)
                              for key, child in item.items()}
                return project_document(expression,
                    evaluate=(lambda value: evaluate(stack, value)) if stack is not None else None,
                    unresolved=lambda value: Expression('Unverified', [value]),
                    warnings=warnings, property_name=row['property'],
                    model_path=model_path, pointer=pointer)
        if path.endswith(('.Actions[]', '.DataResources[]', '.EnvironmentVariables[]')):
            context = item
        return {key: _callback__desired_value_references_86(desired_reference, evaluate, kind, local_comparison, model_path, policy, row, service, stack, warnings, _default_field, _default_operands, _default_path, _default_context, _default_pointer, child, field if operands else key, operands, path + '.' + key, context,
                                pointer + '/' + key.replace('~', '~0').replace('/', '~1')) for key, child in item.items()}
    return item


def _desired_value(service, row, kind, *, local_comparison, desired_reference, property_schema, evaluate, model_path, stack=None, context=None, warnings):
    raw = row.get('document', row['value'])
    if 'document' in row:
        value = strict_json(raw)
    elif resource_link(raw):
        prop = re.sub(r'\[\d+\]', '[]', row['property'].removeprefix(kind + '.'))
        # A schema-typed ARN property selects the referenced Arn, never a current ARN.
        attribute = getattr(registry.rules(kind), 'DIRECT_ATTRIBUTES', {}).get(row['property'])
        node = property_schema(kind, prop)
        symbol = desired_reference(service, raw, kind, prop + ('[]' if node.get('type') == 'array' else ''), attribute, context)
        return [symbol] if node.get('type') == 'array' else symbol
    else:
        value = literal(raw)
        if value in {'UNSET', 'PENDING_DEPLOY', 'TBD', 'TODO', '未確定'}:
            raise Blocked('desired value is unresolved')
        node = property_schema(kind, re.sub(r'\[\d+\]', '[]', row['property'].removeprefix(kind + '.')))
        schema_type = node.get('type')
        if schema_type != 'string':
            if schema_type is None:
                raise Blocked('property type is not uniquely determined')
            value = strict_json(value)
    policy = row['property'].rsplit('.', 1)[-1] in {'PolicyDocument', 'AssumeRolePolicyDocument', 'KeyPolicy', 'Policy'}
    references = _bind_framework_callback(_callback__desired_value_references_86, desired_reference, evaluate, kind, local_comparison, model_path, policy, row, service, stack, warnings, '', False, '', context, '')
    path = row['property'].removeprefix(kind + '.')
    return references(value, path=path)

def _callback_compare_values_compare(outcomes, reference, /, left, right, path):
    outcome = reference(left, right, path)
    outcomes.append(outcome)
    return outcome.equal


def compare_values(desired, actual, key, *, exact=False, unordered=False, reference=None):
    outcomes = []
    compare = _bind_framework_callback(_callback_compare_values_compare, outcomes, reference)
    callback = compare if reference else None
    equal = (unordered_same(desired, actual, reference=callback, path=key) if unordered else
             same(desired, actual, reference=callback, path=key) if exact else
             selected_same(desired, actual, key, reference=callback, path=key))
    return ValueDecision(equal, tuple(d for outcome in outcomes for d in outcome.diagnostics),
                         any(outcome.equivalent for outcome in outcomes))


def unverified(value, pointer=''):
    if isinstance(value, Expression) and value.operation == 'Unverified':
        yield pointer
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from unverified(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from unverified(child, pointer + '/' + str(index))
