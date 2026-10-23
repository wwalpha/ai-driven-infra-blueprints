"""Desired value preparation and typed equivalence; no file/CLI/AWS acquisition."""
import re
from dataclasses import dataclass
from cloudformation_inputs import Blocked
from iac_values import ResourceReference, Expression, same, selected_same, unordered_same
from model.projection import scalar_reference
from model.identity import resource_link
from reference_contracts import SCALAR_REFERENCE_PROPERTIES
from policy_tables import literal
from utils.json_format import policy_json as strict_json
from . import registry


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


def desired_value(service, row, kind, *, local_comparison, desired_reference, resource_type, property_schema, evaluate, model_path, stack=None, context=None):
    warnings = []
    try:
        value = _desired_value(service, row, kind, local_comparison=local_comparison,
            desired_reference=desired_reference, resource_type=resource_type, property_schema=property_schema,
            evaluate=evaluate, model_path=model_path, stack=stack, context=context, warnings=warnings)
    except (Blocked, KeyError, ValueError, TypeError) as error:
        return PreparedValue(None, warnings, error)
    return PreparedValue(value, warnings)


def _desired_value(service, row, kind, *, local_comparison, desired_reference, resource_type, property_schema, evaluate, model_path, stack=None, context=None, warnings):
    selector = scalar_reference(row)
    if selector is not None:
        prop = re.sub(r'\[\d+\]', '[]', row['property'])
        symbol = desired_reference(service, selector['$resource'], kind,
            prop.removeprefix(kind + '.'), selector['$attribute'], context)
        refservice, identity = symbol['$resource']
        if resource_type(symbol) != SCALAR_REFERENCE_PROPERTIES[prop][0]:
            raise Blocked('scalar Arn reference requires a KMS.Key')
        symbol.explicit_attribute = True
        return symbol
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
    def references(item, field='', operands=False, path='', context=context, pointer=''):
        if isinstance(item, str) and resource_link(item):
            attribute = 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None
            return desired_reference(service, item, kind, path, attribute, context)
        if isinstance(item, list):
            return [references(child, field, operands, path + '[]', context, pointer + '/' + str(index))
                    for index, child in enumerate(item)]
        if isinstance(item, dict):
            if '$resource' in item and not (local_comparison and registry.structured_path(kind, path)):
                if (set(item) - {'$resource', '$attribute'} or not isinstance(item['$resource'], str)
                        or not resource_link(item['$resource'])
                        or ('$attribute' in item and (not isinstance(item['$attribute'], str) or not item['$attribute']))):
                    raise Blocked('invalid structured Model resource reference')
                attribute = item.get('$attribute', 'Arn' if policy and field in {'Resource', 'NotResource', 'AWS'} else None)
                return desired_reference(service, item['$resource'], kind, path, attribute, context)
            if local_comparison:
                if (registry.structured_path(kind, path) and {'$resource', '$attribute'} & item.keys()):
                    link, attribute = registry.hook(kind, 'structured_reference')(item, context)
                    symbol = desired_reference(service, link, kind, path, attribute, context)
                    target_service, identity = symbol['$resource']
                    target_kind = resource_type(symbol)
                    if (target_kind, symbol['$attribute']) not in getattr(registry.rules(target_kind), 'SPECIAL_ATTRIBUTES', set()):
                        registry.hook(kind, 'validate_attribute')(symbol, property_schema(target_kind, symbol['$attribute']))
                    return symbol
                from json_intrinsics import intrinsic, project_document
                if intrinsic(item) and not operands:
                    expression = {key: references(child, field, True, path, context, pointer + '/' + key)
                                  for key, child in item.items()}
                    return project_document(expression,
                        evaluate=(lambda value: evaluate(stack, value)) if stack is not None else None,
                        unresolved=lambda value: Expression('Unverified', [value]),
                        warnings=warnings, property_name=row['property'],
                        model_path=model_path, pointer=pointer)
            if path.endswith(('.Actions[]', '.DataResources[]', '.EnvironmentVariables[]')):
                context = item
            return {key: references(child, field if operands else key, operands, path + '.' + key, context,
                                    pointer + '/' + key.replace('~', '~0').replace('/', '~1')) for key, child in item.items()}
        return item
    path = row['property'].removeprefix(kind + '.')
    decoder = registry.hook(kind, 'decode_selector')
    if local_comparison and decoder:
        value, path = decoder(value, path)
    return references(value, path=path)

def compare_values(desired, actual, key, *, exact=False, unordered=False, reference=None):
    outcomes = []
    def compare(left, right, path):
        outcome = reference(left, right, path)
        outcomes.append(outcome)
        return outcome.equal
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
