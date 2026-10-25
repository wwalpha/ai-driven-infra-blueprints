"""CNAME Endpoint DNS selection; value evaluation and Export lookup remain shared."""

import re

from model.core import entries, literal
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import select
from utils.iac_values import Expression, ResourceReference, cfn_resource_identity, same

from .. import expressions, reference_evidence, registry


def model_property(inputs, service, identity, field):
    kind = inputs.resources[service][identity]['resourceType']
    rows = [row for rid, row in entries(inputs.model(service).authoritative, 'desired.row.')
            if rid.rpartition('-')[0] == identity and row.get('property') == kind + '.' + field]
    if len(rows) != 1 or 'document' in rows[0]:
        raise Blocked('Endpoint DNS requires one explicit Model ' + field)
    return literal(rows[0]['value'])


def stack_property(inputs, service, identity, field):
    resource = inputs.resources[service][identity]
    stack, logical = cfn_resource_identity(resource['cfn-logicalId'])
    units = [unit for _, unit in inputs.templates() if unit['name'] == stack]
    if len(units) != 1:
        raise Blocked('Endpoint DNS stack correspondence is unproven')
    _, (document, _, pseudo) = inputs.stack(units[0])
    if document.get('Transform') or inputs.symbol(stack, logical)['$resource'] != [service, identity]:
        raise Blocked('Endpoint DNS resource correspondence is unproven')
    scope = tuple(registry.context_value(pseudo, group) for group in ('partition', 'account', 'region'))
    return inputs.evaluate(stack, select(document['Resources'][logical].get('Properties', {}), field)), scope


def selected_reference(inputs, service, key, value, spec, producer_id):
    """Project only a declared saved link; never change the saved row or invent index 0."""
    number = key.split('.')[2].rpartition('-')[0]
    if model_property(inputs, service, number, 'Type') != 'CNAME':
        raise Blocked('Endpoint DNS valueSelector requires Type=CNAME')
    symbol = inputs.reference(service, value, 'DnsEntries')
    producer = spec['producerScope'].split('/')[2]
    expected = ResourceReference({'$resource': [producer, producer_id], '$attribute': 'DnsEntries'})
    if same(symbol, expected) is not True:
        raise Blocked('Endpoint DNS declared Producer differs from saved link')
    if model_property(inputs, producer, producer_id, 'VpcEndpointType') != 'Interface':
        raise Blocked('Endpoint DNS requires an explicit Interface Endpoint')
    match = re.fullmatch(r'dns-entry\[(0|[1-9][0-9]*)\]\.dns-name', spec['valueSelector'])
    if match is None:
        raise Blocked('Endpoint DNS selection index is unproven')
    symbol = ResourceReference(symbol)
    symbol.dns_consumer = (service, number)
    return Expression('Select', [1, Expression('Split', [':', Expression('Select', [int(match[1]), symbol])])])


def dns_expression(value):
    parts = expressions.parts(value)
    if len(parts) != 1:
        raise Blocked('Endpoint DNS extraction has unproven string affixes')
    value = parts[0]
    operands = []
    for operation in ('Select', 'Split', 'Select'):
        if not isinstance(value, Expression) or value.operation != operation or len(value.operands) != 2:
            raise Blocked('Endpoint DNS extraction structure is unproven')
        first, value = value.operands
        operands.append(first)
    field, delimiter, index = operands
    if (type(field) is not int or field != 1 or delimiter != ':'
            or type(index) is not int or index < 0
            or not isinstance(value, ResourceReference) or value['$attribute'] != 'DnsEntries'):
        raise Blocked('Endpoint DNS requires Select(1, Split(":", Select(entry, DnsEntries)))')
    return value, index


def selected_decision(inputs, left, right, path):
    if re.fullmatch(r'ResourceRecords\[(?:[0-9]+)?\]', path) is None:
        return NotImplemented
    consumers = {ref.dns_consumer for ref in expressions.references([left, right]) if hasattr(ref, 'dns_consumer')}
    if not consumers:
        return NotImplemented
    if len(consumers) != 1:
        return None, 'Endpoint DNS consumer correspondence is unproven'
    consumer, = consumers
    try:
        left_ref, left_index = dns_expression(left)
        right_ref, right_index = dns_expression(right)
        record_type, scope = stack_property(inputs, *consumer, 'Type')
        if model_property(inputs, *consumer, 'Type') != 'CNAME' or record_type != 'CNAME':
            raise Blocked('Endpoint DNS requires Model and IaC Type=CNAME')
        origins = reference_evidence.export_origins([left, right], inputs.export_provenance)
        if not origins or any(origin.get('scope') != scope for origin in origins):
            raise Blocked('Endpoint DNS Export provenance/scope is unproven')
        for ref in (left_ref, right_ref):
            if inputs.resource_type(ref) != 'EC2.VPCEndpoint':
                raise Blocked('Endpoint DNS Producer must be EC2.VPCEndpoint')
            service, identity = ref['$resource']
            inputs.reference(service, ref, 'DnsEntries')
            endpoint_type, endpoint_scope = stack_property(inputs, service, identity, 'VpcEndpointType')
            if (model_property(inputs, service, identity, 'VpcEndpointType') != 'Interface'
                    or endpoint_type != 'Interface' or endpoint_scope != scope):
                raise Blocked('Endpoint DNS requires same-scope Model and IaC Interface Endpoint')
        producer = inputs.reference_decision(left_ref, right_ref, 'EC2.VPCEndpoint', 'DnsEntries')
        if producer.equal is False:
            return False, 'Endpoint DNS uses different Producer Resources'
        if producer.equal is not True:
            raise Blocked('Endpoint DNS Producer correspondence is unproven')
        if left_index != right_index:
            return False, 'Endpoint DNS entry selection differs'
        if expressions.symbolic_same(expressions.parts(left), expressions.parts(right)) is not True:
            raise Blocked('Endpoint DNS extraction equivalence is unproven')
        return True, 'structurally equal Endpoint DNS extraction; runtime Select bounds remain unproven'
    except (Blocked, KeyError, ValueError, TypeError, OSError) as error:
        return None, str(error)
