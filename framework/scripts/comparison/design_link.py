"""Convert Model resource links under explicit receiving-property contracts."""
import re
from cloudformation_inputs import Blocked
from iac_values import ResourceReference
from model.projection import reference_attribute
from reference_contracts import REFERENCE_PROPERTIES
from . import registry

def desired_reference(service, value, kind, path, attribute=None, context=None, *, local_comparison, reference, resource_type, forms_for):
    path = re.sub(r'\[\d+\]', '[]', path)
    if local_comparison and registry.kms_forms(kind, path) is not None:
        symbol = reference(service, value)
        refservice, identity = symbol['$resource']
        refkind = resource_type(symbol)
        if registry.kms_forms(kind, path) <= {'KeyArn', 'AliasArn'}:
            select = registry.hook(refkind, 'arn_attribute')
            selected = select(refkind, symbol['$attribute']) if select else symbol['$attribute']
            return ResourceReference(dict(symbol, **{'$attribute': selected}))
        return reference(service, value, attribute) if attribute else symbol
    context = context or {}
    expected_kind = None
    contract = REFERENCE_PROPERTIES.get(kind + '.' + path)
    if local_comparison:
        consumer = registry.hook(kind, 'reference_contract')
        override = consumer(path, attribute, context) if consumer else NotImplemented
        if override is not NotImplemented:
            expected_kind, attribute = override
        elif contract:
            expected_kind, default_attribute = contract
            if attribute is None:
                attribute = default_attribute
        elif attribute is None and forms_for(kind, path) == {'Arn'}:
            attribute = 'Arn'
        elif attribute is None and forms_for(kind, path) is None:
            raise Blocked(f'reference property contract unproven: {kind}.{path}')
    symbol = reference(service, value, attribute, consumer_property=kind + '.' + path)
    forms = forms_for(kind, path) if local_comparison else None
    refservice, identity = symbol['$resource']
    refkind = resource_type(symbol)
    validator = registry.hook(kind, 'validate_reference')
    if local_comparison and validator:
        validator(path, attribute, context, refkind)
    if forms and symbol['$attribute'] not in {reference_attribute(refkind, form) for form in forms}:
        error = Blocked(f'reference attribute {symbol["$attribute"]} is outside property contract: {kind}.{path}')
        error.reference_detail = (symbol, path)
        raise error
    if expected_kind:
        if refkind not in ((expected_kind,) if isinstance(expected_kind, str) else expected_kind):
            raise Blocked(f'reference target must be {expected_kind}: {kind}.{path}')
    return symbol
