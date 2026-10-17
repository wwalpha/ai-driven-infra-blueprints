"""Verify agent-selected shared Property edits against their direct consumers."""
from model_parameter_inputs import check_type, schema, yaml_read
from model_templates import (bound_definition, json_read, json_text, parse_template,
                             resolve, service_source, template_document,
                             template_document_text, variables)
from import_sources import equivalent, preserve_bindings, typed_equal


def changed_properties(before, after):
    """Compute the verification boundary from edited sources, not an edit plan."""
    changed = {}
    for name, definition in before.items():
        if name not in after:
            raise ValueError('IMPORT existing common Definitions must be preserved')
        candidate = after[name]
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


def input_owner(definition, name, instance):
    spec = schema(definition.parameters[name])
    return (('binding', instance, name) if spec.get('internal') else
            ('service', name) if spec.get('source') == 'service' else ('instance', instance, name))


def property_value(definition, key, parameters, binding, instance, environment):
    """Evaluate one Property with only its local inputs and symbolic references."""
    if key not in definition.values:
        return None
    names = property_inputs(definition, key)
    choices = {choice: raw for choice, raw in definition.choices.items() if choice[0] == key}
    context = {}
    def value(name):
        if name.startswith('Anchor_'):
            anchor = definition.values['desired.resource.' + name.removeprefix('Anchor_') + '.anchor']
            return resolve(anchor, {n: value(n) for n in variables(anchor)})
        return input_value(definition, name, parameters, binding, instance, environment)
    context.update({name: value(name) for name in names})
    narrow = definition._replace(values={key: definition.values[key]},
        optional={k: v for k, v in definition.optional.items() if k == key},
        optional_json={k: v for k, v in definition.optional_json.items() if k[0] == key}, choices=choices)
    selected = bound_definition(narrow, context)
    if key not in selected.values:
        return None
    raw = selected.values[key]
    structured = key.endswith('.document') or bool(narrow.optional_json) or any(pointer is not None for _, pointer, _ in choices)
    return (template_document_text(key, resolve(template_document(key, raw), context, structured=True))
            if structured else resolve(raw, context))


def changed_inputs(before, after):
    result = {('service', name) for name in before.get('parameters', {}).keys() | after.get('parameters', {}).keys()
              if name not in before.get('parameters', {}) or name not in after.get('parameters', {})
              or not typed_equal(before['parameters'][name], after['parameters'][name])}
    for instance in before.get('instances', {}).keys() | after.get('instances', {}).keys():
        old = before.get('instances', {}).get(instance, {}).get('parameters', {})
        new = after.get('instances', {}).get(instance, {}).get('parameters', {})
        result |= {('instance', instance, name) for name in old.keys() | new.keys()
                   if name not in old or name not in new or json_text(old[name]) != json_text(new[name])}
    return result


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
    changed_rows = {name: {key.split('.')[2] for key in keys if key.startswith('desired.row.')}
                    for name, keys in changed.items()}
    selected_bindings = json_read(expansion.files[directory / 'bindings.json'])
    candidate_bindings = json_read(output.get(directory / 'bindings.json', expansion.files[directory / 'bindings.json']))
    preserve_bindings(selected_bindings, candidate_bindings, new_instances=True)
    verify_input_types(after, yaml_read(output.get(directory / 'parameters.yaml', expansion.files[directory / 'parameters.yaml'])), candidate_bindings,
                       (before, yaml_read(expansion.files[directory / 'parameters.yaml']), selected_bindings))
    snapshots, used = {}, set()
    with read_consumers(identities):
        for consumer in sorted(set(identities) - {identity}):
            files = root / 'model/parameters' / '/'.join(consumer)
            own_output = {p: text for p, text in output.items() if p.parent == files}
            if not changed:
                if own_output:
                    raise ValueError('IMPORT other-environment inputs require a shared Property change')
                continue
            binding_file, parameter_file = files / 'bindings.json', files / 'parameters.yaml'
            binding_text = binding_file.read_bytes().decode('utf-8')
            bindings = json_read(binding_text)
            instances = {name: binding for name, binding in bindings['instances'].items() if binding['definition'] in changed}
            if not instances:
                if own_output:
                    raise ValueError('IMPORT consumer has no use of the changed shared Property')
                continue
            used.add(consumer)
            parameter_text = parameter_file.read_bytes().decode('utf-8')
            snapshots.update({binding_file: binding_text.encode('utf-8'), parameter_file: parameter_text.encode('utf-8')})
            parameters = yaml_read(parameter_text)
            candidate_parameters = yaml_read(output.get(parameter_file, parameter_text))
            candidate_bindings = json_read(output.get(binding_file, binding_text))
            preserve_bindings(bindings, candidate_bindings, changed_rows=changed_rows)
            allowed_inputs = set()
            inputs = changed_inputs(parameters, candidate_parameters)
            for instance, binding in bindings['instances'].items():
                replacement = candidate_bindings['instances'][instance]
                inputs |= {('binding', instance, n) for n in binding['parameters'].keys() | replacement['parameters'].keys()
                           if n not in binding['parameters'] or n not in replacement['parameters']
                           or not typed_equal(binding['parameters'][n], replacement['parameters'][n])}
            for instance, binding in bindings['instances'].items():
                name = binding['definition']
                replacement = candidate_bindings['instances'][instance]
                keys = set(changed.get(name, set()))
                old_definition, new_definition = before[name], after[name]
                for definition in (old_definition, new_definition):
                    for key in changed.get(name, set()):
                        allowed_inputs |= {input_owner(definition, parameter, instance)
                                           for parameter in property_inputs(definition, key) if parameter in definition.parameters}
                    keys |= {key for key in definition.values
                             if any(input_owner(definition, parameter, instance) in inputs
                                    for parameter in property_inputs(definition, key) if parameter in definition.parameters)}
                def counterpart(key, source, destination):
                    parts = key.split('.')
                    if len(parts) == 4 and parts[1] in {'row', 'resource'}:
                        maps = 'rows' if parts[1] == 'row' else 'resources'
                        number = source[maps].get(parts[2])
                        local = next((local for local, fixed in destination[maps].items() if number is not None and fixed == number), parts[2])
                        parts[2] = local
                    return '.'.join(parts)
                pairs = {(key, counterpart(key, binding, replacement)) for key in keys if key in old_definition.values}
                pairs |= {(counterpart(key, replacement, binding), key) for key in keys if key in new_definition.values}
                for old_key, new_key in pairs:
                    left = property_value(old_definition, old_key, parameters, binding, instance, consumer[0])
                    right = property_value(new_definition, new_key, candidate_parameters, replacement, instance, consumer[0])
                    if not equivalent(left, right):
                        raise ValueError('IMPORT direct consumer Property meaning changed: ' + '/'.join(consumer) + '/' + instance + '/' + name + '/' + old_key)
            if inputs - allowed_inputs:
                raise ValueError('IMPORT unrelated consumer parameter edit: ' + '/'.join(consumer))
            for instance in bindings['instances'].keys() - instances.keys():
                if bindings['instances'][instance] != candidate_bindings['instances'][instance]:
                    raise ValueError('IMPORT unrelated consumer binding edit')
    return snapshots, used, changed
