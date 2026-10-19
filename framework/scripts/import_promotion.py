"""Verify agent-selected shared Property edits against their direct consumers."""
from model_parameter_inputs import check_type, schema, yaml_read
from model_templates import (bound_definition, json_read, json_text, parse_template,
                             resolve, service_source, template_document,
                             template_document_text, variables)
from import_sources import preserve_bindings, typed_equal


def changed_properties(before, after):
    """Compute the verification boundary from edited sources, not an edit plan."""
    changed = {}
    for name, definition in before.items():
        if name not in after:
            raise ValueError('IMPORT existing common Definitions must be preserved')
        candidate = after[name]
        if any(candidate.rows.get(row) != owner for row, owner in definition.rows.items()):
            raise ValueError('IMPORT existing Definition row owners must be preserved: ' + name)
        parameters = {key for key in definition.parameters.keys() | candidate.parameters.keys()
                      if key not in definition.parameters or key not in candidate.parameters
                      or not typed_equal(definition.parameters[key], candidate.parameters[key])}
        keys = {key for key in definition.values.keys() | candidate.values.keys()
                if definition.values.get(key) != candidate.values.get(key)
                or (property_inputs(definition, key) | property_inputs(candidate, key)) & parameters}
        keys |= {key for key in definition.optional.keys() | candidate.optional.keys()
                 if definition.optional.get(key) != candidate.optional.get(key)}
        keys |= {key for key, pointer in definition.optional_json.keys() | candidate.optional_json.keys()
                 if definition.optional_json.get((key, pointer)) != candidate.optional_json.get((key, pointer))}
        keys |= {key for key, pointer, selector in definition.choices.keys() | candidate.choices.keys()
                 if definition.choices.get((key, pointer, selector)) != candidate.choices.get((key, pointer, selector))}
        if keys:
            changed[name] = keys
    return changed


def input_value(definition, name, parameters, binding, instance, environment):
    if name.startswith('Id_'):
        return binding['resources'][name.removeprefix('Id_')]
    declaration = schema(definition.parameters[name])
    source = declaration.get('source')
    if declaration['type'] == 'reference':
        selector = declaration.get('target') if source == 'template' else parameters.get('instances', {}).get(instance, {}).get('parameters', {}).get(name)
        if selector is None:
            raise ValueError('IMPORT consumer reference selector is missing')
        # Symbolic identity preserves external references without reading other services.
        return 'REFERENCE:' + json_text({**declaration, 'selector': selector, 'label': binding.get('labels', {}).get(name)})
    if source == 'consumer.environment':
        return environment
    if source == 'consumer.executionAccountId':
        return 'CONTEXT:executionAccountId'  # Topology is pinned; this is not an AWS identifier.
    supplied = (binding['parameters'] if declaration.get('internal') else
                parameters.get('parameters', {}) if source == 'service' else
                parameters.get('instances', {}).get(instance, {}).get('parameters', {}))
    if name not in supplied and 'default' not in declaration:
        raise ValueError('IMPORT preserved Property input is missing: ' + name)
    value = supplied.get(name, declaration.get('default'))
    check_type(declaration, value, name)
    if declaration.get('format') == 'literal':
        return '`' + (value if isinstance(value, str) else json_text(value)) + '`'
    return value


def property_inputs(definition, key):
    """Local dependencies, including selectors, choice values and anchor helpers."""
    names = variables(definition.values.get(key, ''))
    names |= {flag for selected, flag in definition.optional.items() if selected == key}
    names |= {flag for (selected, _), flag in definition.optional_json.items() if selected == key}
    for (selected, _, flag), raw in definition.choices.items():
        if selected == key:
            names.add(flag)
            names |= variables(raw)
    pending = list(names)
    while pending:
        name = pending.pop()
        if name.startswith('Anchor_'):
            dependencies = variables(definition.values.get('desired.resource.' + name.removeprefix('Anchor_') + '.anchor', ''))
            pending.extend(dependencies - names)
            names |= dependencies
    return names


def property_value(definition, key, parameters, binding, instance, environment):
    """Evaluate one Property with only its local inputs and symbolic references."""
    if key not in definition.values:
        return None
    choices = {choice: raw for choice, raw in definition.choices.items() if choice[0] == key}
    context = {}
    def value(name):
        if name.startswith('Anchor_'):
            anchor = definition.values['desired.resource.' + name.removeprefix('Anchor_') + '.anchor']
            return resolve(anchor, {n: value(n) for n in variables(anchor)})
        return input_value(definition, name, parameters, binding, instance, environment)
    narrow = definition._replace(values={key: definition.values[key]},
        optional={k: v for k, v in definition.optional.items() if k == key},
        optional_json={k: v for k, v in definition.optional_json.items() if k[0] == key}, choices=choices)
    selectors = set(narrow.optional.values()) | set(narrow.optional_json.values()) | {flag for _, _, flag in choices}
    context.update({name: value(name) for name in selectors})
    selected = bound_definition(narrow, context)
    if key not in selected.values:
        return None
    raw = selected.values[key]
    context.update({name: value(name) for name in variables(raw)})
    structured = key.endswith('.document') or bool(narrow.optional_json) or any(pointer is not None for _, pointer, _ in choices)
    return (template_document_text(key, resolve(template_document(key, raw), context, structured=True))
            if structured else resolve(raw, context))


def verify_input_types(definitions, parameters, bindings, previous=None):
    """Type checks only; existing unrelated design constraints remain the issues phase."""
    for instance, binding in bindings['instances'].items():
        definition = definitions[binding['definition']]
        for name, declaration in definition.parameters.items():
            spec = schema(declaration)
            if spec.get('source') in {'template', 'consumer.environment', 'consumer.executionAccountId'}:
                continue
            supplied = binding['parameters'] if spec.get('internal') else parameters.get('parameters', {}) if spec.get('source') == 'service' else parameters.get('instances', {}).get(instance, {}).get('parameters', {})
            if name in supplied:
                if previous is not None:
                    old_definitions, old_parameters, old_bindings = previous
                    old_binding = old_bindings['instances'].get(instance, {})
                    old_definition = old_definitions.get(old_binding.get('definition'))
                    old_supplied = (old_binding.get('parameters', {}) if spec.get('internal') else
                                    old_parameters.get('parameters', {}) if spec.get('source') == 'service' else
                                    old_parameters.get('instances', {}).get(instance, {}).get('parameters', {}))
                    if old_definition and old_definition.parameters.get(name) == declaration and name in old_supplied and json_text(old_supplied[name]) == json_text(supplied[name]):
                        continue
                check_type(spec, supplied[name], name)


def preserve_consumers(path, expansion, output, identities):
    """Check changed Properties and direct input users without expanding other Models."""
    from import_scope import read_consumers
    root, template, directory = service_source(path)
    identity = (path.parent.parent.name, path.parent.name, path.stem)
    before, _ = parse_template(template)
    after, _ = parse_template(template, output)
    changed = changed_properties(before, after)
    selected_bindings = json_read(expansion.files[directory / 'bindings.json'])
    candidate_bindings = json_read(output.get(directory / 'bindings.json', expansion.files[directory / 'bindings.json']))
    preserve_bindings(selected_bindings, candidate_bindings)
    verify_input_types(after, yaml_read(output.get(directory / 'parameters.yaml', expansion.files[directory / 'parameters.yaml'])), candidate_bindings,
                       (before, yaml_read(expansion.files[directory / 'parameters.yaml']), selected_bindings))
    snapshots, used = {}, set()
    with read_consumers(identities):
        for consumer in sorted(set(identities) - {identity}):
            files = root / 'model/parameters' / '/'.join(consumer)
            if any(p.parent == files for p in output):
                raise ValueError('IMPORT other-environment inputs are read-only')
            if not changed:
                continue
            binding_file, parameter_file = files / 'bindings.json', files / 'parameters.yaml'
            binding_text = binding_file.read_bytes().decode('utf-8')
            bindings = json_read(binding_text)
            instances = {name: binding for name, binding in bindings['instances'].items() if binding['definition'] in changed}
            if not instances:
                continue
            used.add(consumer)
            parameter_text = parameter_file.read_bytes().decode('utf-8')
            snapshots.update({binding_file: binding_text.encode('utf-8'), parameter_file: parameter_text.encode('utf-8')})
            parameters = yaml_read(parameter_text)
            for instance, binding in instances.items():
                name = binding['definition']
                for key in changed[name]:
                    left = property_value(before[name], key, parameters, binding, instance, consumer[0])
                    right = property_value(after[name], key, parameters, binding, instance, consumer[0])
                    if left != right:
                        raise ValueError('IMPORT direct consumer Property meaning changed: ' + '/'.join(consumer) + '/' + instance + '/' + name + '/' + key)
    return snapshots, used, changed


def operation_rows(values, number):
    """Formal Property and array position identify rows, never matching row numbers."""
    from array_display import numbered_property
    from model_files import resource_row_index
    result, states = {}, {}
    for rid, row in resource_row_index(values)[number]:
        key = numbered_property(row['property'], states)
        if key in result:
            raise ValueError('IMPORT ambiguous Property correspondence: ' + key)
        result[key] = rid, row
    return result


def operation_values(values, number):
    from model_files import resource_row_index
    rows = {rid for rid, _ in resource_row_index(values)[number]}
    return {key: value for key, value in values.items()
            if key.startswith(('desired.resource.' + number + '.', 'display.resource.' + number + '.'))
            or key.startswith(('desired.row.', 'observed.row.')) and key.split('.')[2] in rows}


def merged_row(values, number, rid, row):
    """Self links keep the destination identity; JSON content and observations move intact."""
    from model_core import LINK
    anchor = values['desired.resource.' + number + '.anchor']
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        match = LINK.fullmatch(value) if isinstance(value, str) else None
        return {'self': True} if match and not match[2] and match[3] == anchor else value
    payload = {key: normalize(json_read(value) if key == 'document' else value)
               for key, value in row.items() if key not in {'comment', 'artifactSha256'}
               and not (key == 'value' and 'document' in row)}
    observed = 'observed.row.' + rid + '.value'
    if observed in values:
        payload['observed'] = values[observed]
    return payload


def preserve_input_additions(before, after, old_definitions, definitions, bindings, exempt=()):
    """Only newly needed public inputs may be added to preserved instances."""
    for instance, binding in bindings['instances'].items():
        if instance in exempt:
            continue
        old = before.get('instances', {}).get(instance, {}).get('parameters', {})
        new = after.get('instances', {}).get(instance, {}).get('parameters', {})
        if any(key not in new or not typed_equal(value, new[key]) for key, value in old.items()):
            raise ValueError('IMPORT preserved instance inputs changed: ' + instance)
        name = binding['definition']
        changed = changed_properties({name: old_definitions[name]}, {name: definitions[name]}).get(name, set())
        needed = set().union(*(property_inputs(definitions[name], key) for key in changed))
        if set(new) - set(old) - needed:
            raise ValueError('IMPORT unrelated preservation input addition: ' + instance)


def verify_model_operation(before, after, operation, sources):
    """Prove the exact /update merge/delete against the versioned ordinary Model sources."""
    from model_core import entries
    from model_templates import consumers, load_expansion, model_paths, validate_local
    from model_impact import references
    from import_scope import allowed_source, model_path
    action, identity, source, destination = operation
    path = model_path(before, identity)
    original = load_expansion(path)
    if original is None:
        raise ValueError('IMPORT operation source does not exist')
    resources = dict(entries(original.values, 'desired.resource.'))
    for rid in (source, destination) if destination else (source,):
        if resources.get(rid, {}).get('resourceMode') != 'IMPORT':
            raise ValueError('IMPORT operation requires existing IMPORT resources: ' + rid)
    if destination and resources[source]['resourceType'] != resources[destination]['resourceType']:
        raise ValueError('IMPORT merge resource types differ')
    direct = consumers(before, identity[1], identity[2])
    if consumers(after, identity[1], identity[2]) != direct:
        raise ValueError('IMPORT operation cannot add/remove service consumers')
    for relative in sources:
        file = after / relative
        foreign_parameters = any(file == after / 'model/parameters' / '/'.join(item) / 'parameters.yaml'
                                 for item in direct - {identity})
        if not allowed_source(after, file, identity) and not foreign_parameters:
            raise ValueError('IMPORT operation source is outside its exact scope: ' + relative)
    template = service_source(path)[1]
    old_definitions, _ = parse_template(template)
    definitions, _ = parse_template(after / template.relative_to(before))
    if definitions.keys() != old_definitions.keys():
        raise ValueError('IMPORT operation must reuse existing Definitions')
    changed = changed_properties(old_definitions, definitions)
    selected_bindings = json_read(original.files[service_source(path)[2] / 'bindings.json'])['instances']
    editable = {binding['definition'] for binding in selected_bindings.values()
                if destination and destination in binding['resources'].values()}
    if changed.keys() - editable:
        raise ValueError('IMPORT operation changed an unrelated Definition')
    for consumer in sorted(direct):
        old_path, new_path = model_path(before, consumer), model_path(after, consumer)
        old = original if consumer == identity else load_expansion(old_path)
        new = load_expansion(new_path)
        validate_local(new.values)
        old_dir, new_dir = service_source(old_path)[2], service_source(new_path)[2]
        old_bindings = json_read(old.files[old_dir / 'bindings.json'])
        bindings = json_read(new.files[new_dir / 'bindings.json'])
        old_inputs = yaml_read(old.files[old_dir / 'parameters.yaml'])
        inputs = yaml_read(new.files[new_dir / 'parameters.yaml'])
        if consumer != identity:
            if old.values != new.values or old_bindings != bindings:
                raise ValueError('IMPORT shared consumer values/identities changed: ' + '/'.join(consumer))
            if not typed_equal(old_inputs.get('parameters', {}), inputs.get('parameters', {})):
                raise ValueError('IMPORT other-environment shared inputs changed')
            preserve_input_additions(old_inputs, inputs, old_definitions, definitions, old_bindings)
            for instance, binding in bindings['instances'].items():
                name = binding['definition']
                for key in changed.get(name, ()):
                    left = property_value(old_definitions[name], key, old_inputs, old_bindings['instances'][instance], instance, consumer[0])
                    right = property_value(definitions[name], key, inputs, binding, instance, consumer[0])
                    if left != right:
                        raise ValueError('IMPORT shared consumer reference meaning changed')
            continue
        new_resources = dict(entries(new.values, 'desired.resource.'))
        if set(new_resources) != set(resources) - {source}:
            raise ValueError('IMPORT operation must delete only the specified source')
        owners = [name for name, binding in old_bindings['instances'].items() if source in binding['resources'].values()]
        if len(owners) != 1 or len(old_bindings['instances'][owners[0]]['resources']) != 1:
            raise ValueError('IMPORT source cannot safely be separated from its multi-resource Instance')
        source_instance = owners[0]
        destination_instance = next((name for name, binding in old_bindings['instances'].items()
                                     if destination in binding['resources'].values()), None) if destination else None
        expected_instances = set(old_bindings['instances']) - {source_instance}
        if set(bindings['instances']) != expected_instances or source_instance in inputs['instances']:
            raise ValueError('IMPORT source Instance/bindings/inputs were not removed exactly')
        for name in expected_instances:
            left, right = old_bindings['instances'][name], bindings['instances'][name]
            if name == destination_instance:
                for field in ('definition', 'resources'):
                    if left[field] != right[field]:
                        raise ValueError('IMPORT destination fixed identity changed: ' + field)
                for field in ('parameters', 'labels'):
                    if any(key not in right.get(field, {}) or right[field][key] != value for key, value in left.get(field, {}).items()):
                        raise ValueError('IMPORT destination internal identity changed: ' + field)
            elif left != right:
                raise ValueError('IMPORT unrelated bindings changed: ' + name)
        preserve_input_additions(old_inputs, inputs, old_definitions, definitions, old_bindings,
                                 {source_instance, destination_instance})
        removed = operation_values(old.values, source)
        previous = operation_values(old.values, destination) if destination else {}
        current = operation_values(new.values, destination) if destination else {}
        if ({k: v for k, v in old.values.items() if k not in removed and k not in previous}
                != {k: v for k, v in new.values.items() if k not in current}):
            raise ValueError('IMPORT operation changed an unspecified resource or service field')
        if not destination:
            continue
        for field in ('resourceMode', 'resourceType', 'anchor', 'logicalId', 'cfn-logicalId'):
            if resources[destination].get(field) != new_resources[destination].get(field):
                raise ValueError('IMPORT destination identity/mode changed: ' + field)
        identity_fields = {'resourceMode', 'resourceType', 'anchor', 'logicalId', 'cfn-logicalId'}
        if ({k: v for k, v in resources[source].items() if k not in identity_fields}
                != {k: v for k, v in new_resources[destination].items() if k not in identity_fields}):
            raise ValueError('IMPORT source Resource settings were not fully transferred')
        incoming = operation_rows(old.values, source)
        existing = operation_rows(old.values, destination)
        transferred = operation_rows(new.values, destination)
        if incoming.keys() != transferred.keys():
            raise ValueError('IMPORT source Properties were not fully transferred')
        all_old_rows = {key.split('.')[2] for key in old.values if key.startswith('desired.row.')}
        for prop, (rid, row) in transferred.items():
            if prop in existing and rid != existing[prop][0] or prop not in existing and rid in all_old_rows:
                raise ValueError('IMPORT destination Row ID was changed or reused: ' + prop)
            source_rid, source_row = incoming[prop]
            if merged_row(old.values, source, source_rid, source_row) != merged_row(new.values, destination, rid, row):
                raise ValueError('IMPORT source Property/observation was not transferred: ' + prop)
    # Declared references and literal links to the removed identity both block deletion.
    # Only this environment/target needs incoming-reference inspection.
    import re
    anchor = resources[source]['anchor']
    for consumer_path in model_paths(before, *identity[:2]):
        candidate = after / consumer_path.relative_to(before)
        expanded = load_expansion(candidate)
        for key, value in expanded.values.items():
            for link in re.finditer(r'\[[^\]]*\]\(([^)]*)\)', value):
                target, separator, fragment = link[1].partition('#')
                if separator and fragment == anchor and (target == identity[2] + '.md' or not target and candidate.stem == identity[2]):
                    raise ValueError('IMPORT removed resource still has an incoming reference: ' + str(candidate) + ':' + key)
        # Raw name/identifier references have no rendered link.
        for (_, name), (item, spec) in references(candidate).items():
            if spec.get('service') == identity[2] and (item['parameters'].get(name) == source or spec.get('instance') == source_instance):
                raise ValueError('IMPORT removed resource still has a declared reference')
