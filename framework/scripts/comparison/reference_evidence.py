"""Local reference proof. Recorded observations never claim current AWS state."""
import re

from design.layout import resource_mode
from design.policy_tables import literal
from model.adapters.observed import identifier_source
from model.format import REFERENCE_NAME_SUFFIXES
from model.projection import reference_attribute
from utils.aws_catalogs import catalog_outputs
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference, cfn_resource_identity, same
from utils.reference_contracts import (
    ARN_FORMS,
    ARN_SHAPES,
    REFERENCE_PROPERTIES,
)

from . import registry
from .references import ReferenceDecision, literal_expression, reference_same

# Enable recorded ARN derivation only for resource kinds covered by proof tests.
RECORDED_ARN_KINDS = {'KMS.Key'}


class Evidence:
    def __init__(self, inputs):
        self.inputs = inputs
        self.observed = False
        self.producers = []
        self.properties = {}

    def resolve(self, value):
        inputs = self.inputs
        if isinstance(value, Expression):
            return literal_expression(value, resolve_literal=self.resolve)
        service, identity = value['$resource']
        producer = {'producer': service + '/' + identity, 'attribute': value['$attribute']}
        if not any(item['producer'] == producer['producer'] and item['attribute'] == producer['attribute']
                   for item in self.producers):
            self.producers.append(producer)
        return inputs.reference_literal(value, recorded=self.recorded)

    def recorded(self, value):
        inputs = self.inputs
        service, identity = value['$resource']
        resource = inputs.resources[service][identity]
        kind, attribute = resource['resourceType'], value['$attribute']
        if resource_mode(resource) == 'IMPORT':
            raise Blocked('attribute_format_unproven: IMPORT requires approved handoff')
        if kind in RECORDED_ARN_KINDS and attribute == 'Arn':
            return self.derived_arn(value)
        prop = kind + '.' + attribute
        outputs = catalog_outputs(inputs.root, kind)
        if prop not in outputs:
            stack, logical = cfn_resource_identity(resource['cfn-logicalId'])
            if not same(inputs.symbol(stack, logical), value):
                raise Blocked('attribute_format_unproven: not an identifier output')
            candidates = [candidate for candidate in outputs if identifier_source(inputs.catalog,
                resource, outputs, logical, candidate, {'proof': {'Ref': logical}})[1]]
            if len(candidates) != 1:
                raise Blocked('attribute_format_unproven: Ref identifier output is unproven')
            prop = candidates[0]
        self.properties[(service, identity, attribute)] = prop
        rows = [(rid, row) for rid, row in inputs.rows[service][identity] if row['property'] == prop]
        if len(rows) != 1:
            raise Blocked('identifier_unobserved: missing or ambiguous identifier Property')
        raw = inputs.model(service).authoritative.get(f'observed.row.{rows[0][0]}.value')
        text = literal(raw) if raw is not None else ''
        if not text or text in {'PENDING_DEPLOY', 'UNSET', 'TODO', 'TBD', '未確定'} or '${' in text or '{{resolve:' in text:
            raise Blocked('identifier_unobserved')
        schema = inputs.catalog.property_schema(kind, attribute)
        arn = attribute == reference_attribute(kind, 'Arn') or schema.get('pattern', '').startswith('^arn:')
        if text.startswith('arn:') != arn or (schema.get('pattern') and not re.search(schema['pattern'], text)):
            raise Blocked('attribute_format_unproven: recorded identifier format')
        self.observed = True
        return text

    def derived_arn(self, value):
        inputs = self.inputs
        service, identity = value['$resource']
        resource = inputs.resources[service][identity]
        kind = resource['resourceType']
        identifier, template, patterns = ARN_SHAPES[kind]
        fields = identifier if isinstance(identifier, dict) else {identifier: 'id'}
        parts = {}
        for attribute, group in fields.items():
            source = ResourceReference(dict(value, **{'$attribute': attribute}))
            text = self.recorded(source)
            if re.fullmatch(patterns[group], text) is None:
                raise Blocked('attribute_format_unproven: recorded ARN identifier format')
            parts[group] = text
        stack, _ = cfn_resource_identity(resource['cfn-logicalId'])
        pseudo = inputs.stack_inputs[stack][2]
        context = {name: pseudo.get('AWS::' + field) for name, field in
                   [('partition', 'Partition'), ('region', 'Region'), ('account', 'AccountId')]}
        if any(not isinstance(text, str) or not text for text in context.values()):
            raise Blocked('attribute_format_unproven: Producer ARN context is unresolved')
        arn = template.format(**context, **parts)
        if re.fullmatch(ARN_FORMS[kind, 'Arn'][1], arn) is None:
            raise Blocked('attribute_format_unproven: Producer ARN context is invalid')
        for producer in self.producers:
            if producer['producer'] == service + '/' + identity and producer['attribute'] == 'Arn':
                producer.update(source_property=','.join(kind + '.' + field for field in fields),
                                evidence_type='recorded_observed', derived_format=inputs.kms_format(arn),
                                current_aws_verified=False)
        return arn


def validate_declaration(inputs, reference):
    service, identity = reference['$resource']
    prop = reference.saved_property
    rows = [(rid, row) for rid, row in inputs.rows[service][identity] if row['property'] == prop]
    if len(rows) != 1:
        raise Blocked('attribute_format_unproven: declared Property absent or ambiguous')
    rid, row = rows[0]
    if reference.declared_format == 'name':
        if not prop.endswith(REFERENCE_NAME_SUFFIXES):
            raise Blocked('attribute_format_unproven: not a name Property')
        raw = row['value']
    else:
        if prop not in catalog_outputs(inputs.root, inputs.resource_type(reference)):
            raise Blocked('attribute_format_unproven: not a recorded identifier Property')
        raw = inputs.model(service).authoritative.get(f'observed.row.{rid}.value')
    if raw is None or literal(raw) in {'', 'PENDING_DEPLOY', 'UNSET', 'TBD', 'TODO', '未確定'}:
        raise Blocked('identifier_unobserved')
    if literal(raw) != reference.saved_literal:
        raise Blocked('recorded_identifier_mismatch: declaration and Producer Property differ')


def compare(inputs, left, right, kind, path):
    original_left, original_right = left, right
    if (isinstance(right, str) and isinstance(left, (ResourceReference, Expression))
            and not hasattr(left, 'saved_literal')):
        left, right = right, left
    declared = getattr(left, 'saved_literal', None)
    raw = declared if declared is not None else left
    if declared is not None:
        baseline = reference_same(raw, right, kind, path, local_comparison=inputs.local_comparison,
            forms_for=inputs.reference_forms, resolve_literal=inputs.reference_literal,
            resource_type=inputs.resource_type, kms_format=inputs.kms_format, diagnostic=inputs.reference_diagnostic)
        if baseline.equal is False:
            return baseline
    if not isinstance(raw, str) or not isinstance(right, (ResourceReference, Expression)):
        if declared is not None:
            equal = same(raw, right)
            if equal:
                try:
                    validate_declaration(inputs, left)
                except Blocked as error:
                    return ReferenceDecision(None, (inputs.reference_diagnostic(original_left, original_right, kind, path, str(error)),))
            return ReferenceDecision(equal)
        return ReferenceDecision(NotImplemented)
    proof = Evidence(inputs)
    reason, equal = '', None
    try:
        if declared is not None:
            validate_declaration(inputs, left)
            saved = proof.resolve(left)
            if saved != raw or (left.declared_format == 'identifier' and raw.startswith('arn:')):
                raise Blocked('recorded_identifier_mismatch: declaration and saved value differ')
            if isinstance(right, ResourceReference) and left['$resource'] != right['$resource']:
                return ReferenceDecision(False, (inputs.reference_diagnostic(original_left, original_right, kind, path, 'different producer Resources'),))
        if isinstance(right, ResourceReference):
            refkind = inputs.resource_type(right)
            contract = REFERENCE_PROPERTIES.get(kind + '.' + path)
            if contract and refkind not in (contract[0] if isinstance(contract[0], tuple) else (contract[0],)):
                return ReferenceDecision(False, (inputs.reference_diagnostic(original_left, original_right, kind, path, 'resource_type_mismatch'),))
            forms = inputs.reference_forms(kind, path) if registry.kms_forms(kind, path) is None else None
            if forms and right['$attribute'] not in {reference_attribute(refkind, form) for form in forms}:
                return ReferenceDecision(False, (inputs.reference_diagnostic(original_left, original_right, kind, path, 'attribute_format_mismatch'),))
            if forms and 'Arn' in forms and raw.startswith('arn:') and right['$attribute'] != reference_attribute(refkind, 'Arn'):
                raise Blocked('attribute_format_unproven: alternative allowed literal format')
        concrete = proof.resolve(right)
        allowed = registry.kms_forms(kind, path) if inputs.local_comparison else None
        if allowed:
            result, reason = registry.compare_kms_forms(raw, concrete, allowed,
                resolve_literal=inputs.reference_literal, format_of=inputs.kms_format)
            if reason:
                return ReferenceDecision(result, (inputs.reference_diagnostic(original_left, original_right, kind, path, reason),))
        if declared is not None and isinstance(right, ResourceReference) and left['$attribute'] != right['$attribute']:
            left_key = (*left['$resource'], left['$attribute'])
            right_key = (*right['$resource'], right['$attribute'])
            if not proof.properties.get(left_key) or proof.properties[left_key] != proof.properties.get(right_key):
                raise Blocked('attribute_format_unproven: declared attribute differs')
        equal = raw == concrete
        if not equal and proof.observed:
            equal = None
            reason = 'recorded_identifier_mismatch'
        else:
            reason = 'recorded_observed' if proof.observed else 'iac_concrete'
    except Blocked as error:
        reason = str(error)
    detail = inputs.reference_diagnostic(original_left, original_right, kind, path, reason)
    if declared is not None:
        detail['model_literal'] = inputs.redacted(raw, kind + '.' + path)
    detail.update(local_comparison='matched' if equal is True else 'difference' if equal is False else 'uncompared',
                  evidence_type='recorded_observed' if proof.observed else 'local_evaluation',
                  current_aws_verified=False, producers=proof.producers)
    return ReferenceDecision(equal, (inputs.redacted(detail),), equal is True)


def export_origins(value, provenance):
    result = []
    entry = provenance.get(id(value))
    if entry is not None and entry[0] is value:
        result.extend(entry[1])
    children = value.operands if isinstance(value, Expression) else value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for child in children:
        for origin in export_origins(child, provenance):
            if origin not in result:
                result.append(origin)
    return result
