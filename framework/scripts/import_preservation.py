"""Prove automatic reference labels without relaxing ordinary Model comparisons."""
from model_core import LINK, entries, literal, ReferenceResolutionError
from model_parameter_inputs import schema, parameter_value
from model_templates import (_reference_inputs, parse_template, reference_values,
                             service_source)


def automatic_reference(path, expansion, key, warnings=None):
    try:
        return _automatic_reference(path, expansion, key)
    except ReferenceResolutionError as error:
        warning = {**error.diagnostic, "key": key, "source": str(path)}
        if warnings is not None:
            warnings.append(warning)
        else:
            from model_core import report_reference_warnings
            report_reference_warnings([warning])
        return None


def _automatic_reference(path, expansion, key):
    """Return the declared identity and consumed attribute, never just an anchor."""
    from import_scope import selected, create_reference
    from issues_iac import REFERENCE_PROPERTIES
    from model_references import catalog_outputs
    trace = expansion.provenance.get(key, {})
    if not key.startswith('desired.row.') or not key.endswith('.value') or not (trace.get('references') or any(item['type'] == 'reference' for item in trace.get('inputs', {}).values())):
        return None
    root, template, directory = service_source(path)
    definitions = parse_template(template)[0]
    definition = definitions[trace['definition']]
    names = trace['parameters']
    if len(names) != 1 or definition.values[trace['key']] != '<<' + names[0] + '>>':
        return None
    name = names[0]
    spec = schema(definition.parameters[name])
    if spec['type'] != 'reference' or spec.get('source') not in (None, 'template') or spec.get('format') is not None or 'service' not in spec:
        return None
    identity = (path.parent.parent.name, path.parent.name, spec['service'])
    if identity != selected(root):
        return None  # Only this operation's authorized producer can cause a display change.
    import json
    binding = json.loads(expansion.files[directory / 'bindings.json'])['instances'][trace['instance']]
    if name in binding.get('labels', {}):
        return None
    prop = expansion.values.get(key.removesuffix('value') + 'property')
    contract = REFERENCE_PROPERTIES.get(prop)
    if not contract:
        return None
    kinds, attribute = contract
    if spec['resourceType'] not in ((kinds,) if isinstance(kinds, str) else kinds) or attribute is None:
        return None
    producer = path.with_name(spec['service'] + '.properties')
    selector = spec['target'] if spec.get('source') == 'template' else trace['inputs'][name]['value']
    item = {'definition': trace['definition'], 'parameters': {name: selector}, 'id': trace['instance']}
    with create_reference(template, item, name, definitions, identity[0]):
        _, inputs = _reference_inputs(producer)
        _, files, observed, _, bindings, fields = inputs
        rid = selector
        if 'instance' in spec:
            if spec['instance'] not in bindings['instances']:
                raise ReferenceResolutionError('unknown external instance reference')
            bound = bindings['instances'][spec['instance']]
            candidates = [number for number in bound['resources'].values()
                          if fields[f'desired.resource.{number}.resourceType'][2] == spec['resourceType']]
            if len(candidates) != 1:
                raise ReferenceResolutionError('reference producer requires exactly one matching resource')
            rid = candidates[0]
        resolved = reference_values(producer, rid, spec['resourceType'], 'preservation')
        expected = parameter_value(template, item, name, [], {'instances': {trace['instance']: binding}},
                                   definitions, identity[0], {})
        if expansion.values[key] != expected:
            return None
        link = LINK.fullmatch(expansion.values[key])
        anchor = resolved.values.get(f'desired.resource.{rid}.anchor')
        if link is None or link.group(2) != spec['service'] + '.md' or link.group(3) != anchor:
            return None
        # Name/ARN references may consume the changed name. Preserve those literally.
        if attribute.endswith(('Name', 'Arn')) or spec['resourceType'] + '.' + attribute not in catalog_outputs(root, spec['resourceType']):
            return None
        target = reference_values(producer, rid, spec['resourceType'], 'identifier')
        observed_values = [(row_id, row['value']) for row_id, row in entries(target.values, 'observed.row.')
                           if row.get('property') == spec['resourceType'] + '.' + attribute]
        if len(observed_values) > 1:
            return None
        desired_values = [row['value'] for _, row in entries(target.values, 'desired.row.')
                          if row.get('property') == spec['resourceType'] + '.' + attribute]
        if len(desired_values) > 1:
            return None
        desired = desired_values[0] if desired_values else None
        self_link = LINK.fullmatch(desired) if isinstance(desired, str) else None
        if self_link is not None:
            if self_link.group(2) or self_link.group(3) != anchor:
                return None
            desired = {'logical': (rid, attribute, anchor)}
        actual = literal(observed_values[0][1]) if observed_values else desired
        # Unobserved identifiers retain the existing logical reference contract.
        logical = {leaf: resolved.values[f'desired.resource.{rid}.' + leaf]
                   for leaf in ('resourceType', 'anchor', 'logicalId', 'resourceMode', 'cfn-logicalId')
                   if f'desired.resource.{rid}.' + leaf in fields}
        return {'reference': spec, 'selector': selector, 'identity': (*identity, rid), 'attribute': attribute,
                'logical': logical, 'actual': actual, 'desired': desired}


def preserved_values(path, expansion):
    values = dict(expansion.values)
    for key in expansion.provenance:
        if key in values and (reference := automatic_reference(path, expansion, key)) is not None:
            values[key] = reference
    return values
