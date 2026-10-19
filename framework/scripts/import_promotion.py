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


def preserve_consumers(path, expansion, output, identities, selected=None):
    """Check changed Properties and direct input users without expanding other Models."""
    from import_scope import read_consumers
    from model_sources import source_paths
    from validation_cache import input_is_file
    root, template, directory = service_source(path) or source_paths(path)
    identity = (path.parent.parent.name, path.parent.name, path.stem)
    before, _ = parse_template(template) if expansion.files or input_is_file(template) else ({}, {})
    after, _ = parse_template(template, output)
    changed = changed_properties(before, after)
    selected_bindings = json_read(expansion.files.get(directory / 'bindings.json', '{"instances":{}}'))
    candidate_bindings = json_read(output.get(directory / 'bindings.json', expansion.files.get(directory / 'bindings.json', '{"instances":{}}')))
    updated = {rid for rid, record in (selected or {}).items() if record.get('_action') in {'refresh', 'replace'}}
    preserve_bindings(selected_bindings, candidate_bindings, updated)
    old_parameters = yaml_read(expansion.files.get(directory / 'parameters.yaml', 'instances: {}'))
    parameters = yaml_read(output.get(directory / 'parameters.yaml', expansion.files.get(directory / 'parameters.yaml', 'instances: {}')))
    if directory / 'parameters.yaml' in expansion.files and not typed_equal(old_parameters.get('parameters', {}), parameters.get('parameters', {})):
        raise ValueError('IMPORT existing common inputs must be preserved')
    for name, binding in selected_bindings['instances'].items():
        if not set(binding['resources'].values()) & updated and not typed_equal(
                old_parameters.get('instances', {}).get(name), parameters.get('instances', {}).get(name)):
            raise ValueError('IMPORT nonselected Instance inputs must be preserved: ' + name)
    verify_input_types(after, parameters, candidate_bindings, (before, old_parameters, selected_bindings))
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


def replacement_inputs(root, identity, selected, warnings=None):
    """Reuse incoming-reference analysis and its input snapshot; never retarget here."""
    warnings = warnings if warnings is not None else []
    replacements = {rid for rid, record in selected.items() if record.get('_action') == 'replace'}
    if not replacements:
        return {}, ()
    from import_scope import read_consumers
    from model_reference_usage import incoming_references
    from model_sources import read_sources
    from validation_cache import input_select
    directories = input_select(root / 'model/parameters' / identity[0] / identity[1], '*')
    scopes = {(*identity[:2], directory.name) for directory in directories}
    inputs = {}
    with read_consumers(scopes):
        for scope in sorted(scopes):
            inputs.update(read_sources(root / 'model' / scope[0] / scope[1] / (scope[2] + '.properties')))
        for rid in sorted(replacements):
            address = '/'.join((*identity, rid))
            diagnosis = incoming_references(root, address)
            warnings.extend(diagnosis['warnings'])
            warnings.extend({'code': 'reference.replace_impact',
                             'message': 'replacement affects an incoming reference', **item}
                            for item in diagnosis['references'] if item['consumer'] != address)
    return inputs, directories


# Compatibility for existing import callers; implementation lives at its final-check boundary.
from model_operation_checks import (operation_rows, operation_values, merged_row,
                                    preserve_input_additions, verify_model_operation)
