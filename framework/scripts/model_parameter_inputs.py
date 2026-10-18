"""Human inputs; normalize into the existing explicit-ID template expansion contract."""
from validation_cache import input_bytes
import copy
import ipaddress
import re

from model_core import entries, literal


def yaml_read(text):
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    # YAML 1.2-like scalars: on/off/yes/no and dates stay strings; no octal surprise.
    Loader.yaml_implicit_resolvers = {
        key: [(tag, regex) for tag, regex in rules if tag not in {
            'tag:yaml.org,2002:bool', 'tag:yaml.org,2002:int', 'tag:yaml.org,2002:timestamp'}]
        for key, rules in Loader.yaml_implicit_resolvers.items()}
    Loader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false)$'), list('tf'))
    Loader.add_implicit_resolver('tag:yaml.org,2002:int', re.compile(r'^[-+]?(?:0|[1-9][0-9]*)$'), list('-+0123456789'))

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str) or key in result:
                raise ValueError(f'non-string/duplicate YAML key: {key}')
            result[key] = loader.construct_object(value_node)
        return result

    Loader.add_constructor('tag:yaml.org,2002:map', mapping)
    try:
        return yaml.load(text, Loader=Loader)
    except yaml.YAMLError as error:
        raise ValueError(f'invalid parameters YAML: {error}') from error


def service_inputs(definitions, bindings, parameters=None):
    from model_templates import exact
    if parameters is not None:
        exact(parameters, {'instances'} | ({'parameters'} if isinstance(parameters, dict) and 'parameters' in parameters else set()), 'human parameters')
        if not isinstance(parameters['instances'], dict):
            raise ValueError('human instances must be an object')
    exact(bindings, {'instances'} | ({'stacks'} if isinstance(bindings, dict) and 'stacks' in bindings else set()), 'internal bindings')
    if 'stacks' in bindings and not isinstance(bindings['stacks'], dict):
        raise ValueError('stack bindings must be an object')
    if not isinstance(bindings['instances'], dict):
        raise ValueError('instance/internal binding mismatch; input instances require an explicit binding')
    used = []
    for identity, binding in bindings['instances'].items():
        exact(binding, {'definition', 'resources', 'rows', 'parameters'} | ({'labels'} if isinstance(binding, dict) and 'labels' in binding else set()), 'internal instance binding')
        name = binding['definition']
        if not isinstance(name, str) or name not in definitions:
            raise ValueError('unknown definition')
        definition = definitions[name]
        if parameters is not None:
            from model_templates import bound_definition
            item = parameters['instances'].get(identity, {'parameters': {}})
            exact(item, {'parameters'}, 'human instance inputs; definition belongs in bindings')
            if not isinstance(item['parameters'], dict) or not isinstance(binding['parameters'], dict):
                raise ValueError('instance parameters must be an object')
            supplied = {**item['parameters'], **binding['parameters']}
            definition = bound_definition(definition, supplied)
        used.append(definition)
    return {name: spec for definition in used for name, spec in definition.parameters.items()
            if isinstance(spec, dict) and spec.get('source') == 'service'}


def parameter_text(value, definitions, bindings):
    """Human serialization only; digest/JSON serialization remains unchanged."""
    import yaml
    shared = service_inputs(definitions, bindings, value)
    ordered = {'parameters': {name: value['parameters'][name] for name in sorted(shared) if name in value.get('parameters', {})}} if shared else {}
    ordered['instances'] = {name: {'parameters': {
        key: item['parameters'][key] for key in definitions[bindings['instances'][name]['definition']].parameters
        if key in item['parameters']}}
        for name, item in value['instances'].items()}
    return yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, default_flow_style=False)


def schema(spec):
    from model_templates import TYPES
    if isinstance(spec, str):
        return {'type': spec, 'required': True}
    allowed = {'type', 'description', 'required', 'default', 'constraints', 'format', 'resourceType', 'service', 'internal', 'source', 'target', 'property', 'instance'}
    if not isinstance(spec, dict) or set(spec) - allowed or not {'type', 'description', 'required'} <= spec.keys():
        raise ValueError('parameter declaration requires type, description and required')
    if spec['type'] not in {*TYPES, 'reference'} or not isinstance(spec['description'], str) or not spec['description'].strip() or type(spec['required']) is not bool:
        raise ValueError('invalid parameter type/description/required')
    if spec.get('source') not in {None, 'service', 'consumer.environment', 'consumer.executionAccountId', 'template'}:
        raise ValueError('invalid parameter source')
    if spec.get('source') in {'consumer.environment', 'consumer.executionAccountId'} and spec['type'] != 'string':
        raise ValueError('consumer context must be a string')
    if 'target' in spec and spec.get('source') != 'template':
        raise ValueError('fixed targets require a template reference')
    if spec.get('source') == 'template' and spec['type'] != 'reference':
        raise ValueError('template source requires a reference')
    if 'instance' in spec:
        from model_templates import NAME
        if spec.get('source') != 'template' or 'service' not in spec or not isinstance(spec['instance'], str) or not NAME.fullmatch(spec['instance']) or spec.get('target') != spec['instance']:
            raise ValueError('external instance requires a fixed template reference')
    if ('format' in spec and not (
            spec['format'] in (None, 'literal') and spec['type'] in TYPES
            or spec['format'] in ('name', 'identifier') and spec['type'] == 'reference'
            and 'service' in spec)):
        raise ValueError('invalid Model parameter format')
    if spec['type'] == 'reference':
        if not isinstance(spec.get('resourceType'), str) or not re.fullmatch(r'[A-Za-z0-9]+\.[A-Za-z0-9]+', spec['resourceType']):
            raise ValueError('reference requires resourceType')
        if 'service' in spec and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', str(spec['service'])):
            raise ValueError('invalid reference service')
    elif {'resourceType', 'service'} & spec.keys():
        raise ValueError('reference metadata on non-reference parameter')
    if spec.get('format') == 'identifier':
        prop = spec.get('property')
        if not isinstance(prop, str) or not prop.startswith(spec['resourceType'] + '.') or prop.endswith('Arn'):
            raise ValueError('identifier reference requires an explicit non-ARN property of its resourceType')
    elif 'property' in spec:
        raise ValueError('property requires identifier reference format')
    constraints = spec.get('constraints', {})
    if not isinstance(constraints, dict) or set(constraints) - {'enum', 'pattern', 'minimum', 'maximum', 'minLength', 'maxLength', 'cidr'}:
        raise ValueError('invalid input constraints')
    for key, value in constraints.items():
        if key == 'enum' and (not isinstance(value, list) or not value):
            raise ValueError('constraint enum requires a nonempty array')
        if key == 'pattern':
            if not isinstance(value, str):
                raise ValueError('pattern must be a string')
            try:
                re.compile(value)
            except re.error as error:
                raise ValueError('invalid constraint pattern') from error
        if key in {'minimum', 'maximum'} and (type(value) not in {int, float} or spec['type'] not in {'integer', 'number'}):
            raise ValueError('numeric constraint requires a numeric parameter/value')
        if key in {'minLength', 'maxLength'} and (type(value) is not int or value < 0):
            raise ValueError('length constraint requires a nonnegative integer')
        if key in {'pattern', 'minLength', 'maxLength', 'cidr'} and spec['type'] not in {'string', 'reference'}:
            raise ValueError('string constraint requires a string parameter')
        if key == 'cidr' and value not in {'ipv4', 'ipv6'}:
            raise ValueError('cidr constraint requires ipv4/ipv6')
    for lo, hi in [('minimum', 'maximum'), ('minLength', 'maxLength')]:
        if lo in constraints and hi in constraints and constraints[lo] > constraints[hi]:
            raise ValueError('inverted input constraints')
    return spec


def reference_schema(value):
    from model_templates import NAME, IDENTITY
    if not isinstance(value, dict) or set(value) - ({'format', 'property'} if value.get('format') == 'identifier' else {'format'}) not in ({'instance', 'resourceType'}, {'service', 'resource', 'resourceType'}, {'service', 'instance', 'resourceType'}):
        raise ValueError('template reference requires instance, service/resource or service/instance')
    target = value.get('instance', value.get('resource'))
    if not isinstance(target, str) or not (NAME if 'instance' in value else IDENTITY).fullmatch(target):
        raise ValueError('invalid template reference target')
    return schema({'type': 'reference', 'description': 'template論理参照', 'required': True,
                   'source': 'template', 'target': target, **{k:v for k,v in value.items() if k in {'service', 'resourceType', 'format', 'property'}},
                   **({'instance': target} if 'service' in value and 'instance' in value else {})})


def check_type(spec, value, label):
    from model_templates import TYPES, json_text
    kind = spec['type']
    expected = str if kind == 'reference' else TYPES[kind]
    if not isinstance(value, expected) or kind in {'integer', 'number'} and isinstance(value, bool):
        raise ValueError(f'parameter type mismatch: {label}: {kind}')
    json_text(value)


def check_value(spec, value, label):
    check_type(spec, value, label)
    for key, bound in spec.get('constraints', {}).items():
        valid = True
        if key == 'enum':
            valid = any(type(value) is type(item) and value == item for item in bound)
        elif key == 'pattern':
            valid = re.fullmatch(bound, value) is not None
        elif key == 'minimum':
            valid = value >= bound
        elif key == 'maximum':
            valid = value <= bound
        elif key == 'minLength':
            valid = len(value) >= bound
        elif key == 'maxLength':
            valid = len(value) <= bound
        elif key == 'cidr':
            try:
                valid = ipaddress.ip_network(value, strict=True).version == (4 if bound == 'ipv4' else 6)
            except ValueError:
                valid = False
        if not valid:
            raise ValueError(f'input constraint {key} failed: {label}')


def values_for(declarations, supplied, label, check=check_value):
    if not isinstance(supplied, dict):
        raise ValueError(f'unknown parameter: {label}; expected an object')
    excess = supplied.keys() - declarations.keys()
    if excess:
        raise ValueError(f'unknown parameter: {label}: {sorted(excess)}')
    result = {}
    for name, declaration in declarations.items():
        spec = schema(declaration)
        if name not in supplied:
            if spec['required'] or 'default' not in spec:
                raise ValueError(f'missing required parameter: {label}/{name}')
            value = copy.deepcopy(spec['default'])
        else:
            value = supplied[name]
        check(spec, value, label+'/'+name)
        result[name] = value
    return result


def consumer_execution_account(template, environment):
    from cloudformation_inputs import load_target
    if environment is None:
        raise ValueError('consumer execution account context required')
    target = load_target(template.parents[3], environment, template.parent.name)
    return target.get('awsExecutionAccountId', target['awsAccountId'])


def human_instances(template, parameters, bindings, definitions, environment=None, *, resolve_references=True):
    for definition in definitions.values():
        for name, declaration in definition.parameters.items():
            spec = schema(declaration)
            if 'default' in spec:
                check_value(spec, spec['default'], 'parameter default: ' + name)
    return bind_instances(template, parameters, bindings, definitions, environment, check_value, resolve_references)


def edit_instances(template, parameters, bindings, definitions, environment=None):
    from model_templates import json_text
    result, files = bind_instances(template, parameters, bindings, definitions, environment,
                                   lambda _spec, value, _label: json_text(value), False)
    for item in result['instances']:
        for name, spec in definitions[item['definition']].parameters.items():
            if spec.get('type') != 'reference':
                continue
            if 'service' in spec:
                item['parameters'][name] = '<<' + name + '>>'
            else:
                item['parameters'][name] = parameter_value(template, item, name, result['instances'], bindings, definitions, environment, files)
    return result, files


def bind_instances(template, parameters, bindings, definitions, environment, check, resolve_references):
    from model_templates import exact, NAME, json_text, bound_definition
    shared = service_inputs(definitions, bindings, parameters)
    bindings = {**bindings, 'instances': {identity: {'labels': {}, **binding}
                for identity, binding in bindings['instances'].items()}}
    exact(parameters, {'instances', 'parameters'} if shared else {'instances'}, 'human parameters')
    if shared:
        common = values_for(shared, parameters['parameters'], 'service', check)
    else:
        common = {}
    humans, maps = parameters['instances'], bindings['instances']
    if not isinstance(humans, dict) or not isinstance(maps, dict) or set(humans) - maps.keys():
        raise ValueError('instance/internal binding mismatch; input instances require an explicit binding')
    files = {}
    execution_account = None
    if any(isinstance(spec, dict) and spec.get('source') == 'consumer.executionAccountId'
           for definition in definitions.values() for spec in definition.parameters.values()):
        project = template.parents[3]/'project.json'
        files[project] = input_bytes(project).decode('utf-8')
        execution_account = consumer_execution_account(template, environment)
    result = []
    for identity, binding in maps.items():
        if not isinstance(identity, str) or not NAME.fullmatch(identity):
            raise ValueError('invalid instance name')
        definition_name = binding['definition']
        definition = definitions[definition_name]
        item = humans.get(identity, {'parameters': {}})
        exact(item, {'parameters'}, 'human instance inputs; definition belongs in bindings')
        if any(isinstance(spec, str) for spec in definition.parameters.values()):
            raise ValueError('human format requires described parameter declarations')
        definition = bound_definition(definition, {**item['parameters'], **binding['parameters']})
        internals = {name for name, spec in definition.parameters.items() if isinstance(spec, dict) and spec.get('internal')}
        automatic = {name: spec for name, spec in definition.parameters.items() if isinstance(spec, dict) and spec.get('source')}
        if not isinstance(item['parameters'], dict) or set(item['parameters']) & internals:
            raise ValueError('internal information is not a public parameter')
        if set(item['parameters']) & automatic.keys():
            raise ValueError('ambiguous parameter source; shared/template values cannot be overridden')
        sources = {}
        for name, spec in automatic.items():
            if spec['source'] == 'consumer.environment':
                if environment is None:
                    raise ValueError('consumer environment context required')
                sources[name] = environment
            elif spec['source'] == 'consumer.executionAccountId':
                sources[name] = execution_account
            elif spec['source'] == 'service':
                sources[name] = common[name]
            else:
                sources[name] = spec['target']
        public = {name for name, spec in definition.parameters.items() if not spec.get('internal') and not spec.get('source')}
        if bool(public) != (identity in humans):
            raise ValueError(f'input-free instances belong in bindings; input-bearing instances require YAML: {identity}')
        internals = {name for name, spec in definition.parameters.items() if spec.get('internal')}
        exact(binding['parameters'], internals, 'internal parameters')
        sources = {name: value for name, value in sources.items() if name in definition.parameters}
        supplied = values_for(definition.parameters, {**item['parameters'], **binding['parameters'], **sources}, identity, check)
        references = {name for name, spec in definition.parameters.items() if schema(spec)['type'] == 'reference'}
        if not isinstance(binding['labels'], dict) or set(binding['labels']) - references:
            raise ValueError('unknown reference label binding')
        result.append({'id': identity, 'definition': definition_name, 'resources': binding['resources'],
                       'rows': binding['rows'], 'parameters': supplied})
    if resolve_references:
        for item in result:
            for name in list(item['parameters']):
                item['parameters'][name] = parameter_value(template, item, name, result, bindings, definitions, environment, files)
    return {'version': 1, 'instances': result}, files


def parameter_value(template, item, name, instances, bindings, definitions, environment, files, context_for=None):
    from model_templates import json_text, REFERENCE_NAME_SUFFIXES, bound_definition
    definition = definitions[item['definition']]
    value = item['parameters'][name]
    maps = bindings['instances']
    labels = maps[item['id']].get('labels', {})
    by_id = {instance['id']: instance for instance in instances}
    spec = schema(definition.parameters[name])
    if spec['type'] == 'reference':
        if 'service' in spec:
            from model_files import resource_row_index
            from model_templates import reference_values
            # Model template layout fixes alias; service_source fixes environment elsewhere.
            if environment is None:
                raise ValueError('external reference requires consumer context')
            from import_scope import create_reference
            with create_reference(template, item, name, definitions, environment):
                root = template.parents[3]
                path = root/'model'/environment/template.parent.name/(spec['service']+'.properties')
                if 'instance' in spec:
                    from model_templates import _reference_inputs
                    _, producer = _reference_inputs(path)
                    _, producer_files, _, _, producer_bindings, fields = producer
                    target = producer_bindings['instances'].get(spec['instance'])
                    if target is None:
                        raise ValueError(f'unknown external instance reference: {spec["service"]}/{spec["instance"]}')
                    candidates = [rid for rid in target['resources'].values()
                                  if fields[f'desired.resource.{rid}.resourceType'][2] == spec['resourceType']]
                    if len(candidates) != 1:
                        raise ValueError(f'ambiguous/type-mismatched external instance reference: {spec["service"]}/{spec["instance"]}: expected exactly one {spec["resourceType"]}, found {len(candidates)}')
                    value = candidates[0]
                    files.update(producer_files)
                mode = spec.get('format')
                if mode is None and name in labels:
                    mode = 'anchor'
                model = reference_values(path, value, spec['resourceType'], mode); files.update(model.files)
            stack_name = f'desired.stack.{value}.name'
            if spec['resourceType'] == 'CloudFormation.Stack' and stack_name in model.values:
                if f'desired.resource.{value}.resourceType' in model.values:
                    raise ValueError(f'ambiguous resource/stack reference: {value}')
                if spec.get('format') != 'name':
                    raise ValueError('stack reference requires format:name')
                if name in labels:
                    raise ValueError('raw name reference cannot override label')
                raw = model.values[stack_name]
                if not raw or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,127}', raw):
                    raise ValueError('reference producer requires a valid stack name')
                return raw
            rows = resource_row_index(model.values)
            candidates = [(rid, resource.get('anchor')) for rid, resource in entries(model.values, 'desired.resource.')
                          if rid == value and resource['resourceType'] == spec['resourceType']]
            prefix = spec['service']+'.md'
        else:
            target = by_id.get(value)
            if target is None:
                raise ValueError(f'unknown instance reference: {item["id"]}/{name}: {value}')
            target_def = bound_definition(definitions[target['definition']], target['parameters'])
            candidates = [(rid, target_def.values[f'desired.resource.{local}.anchor']) for local, rid in target['resources'].items()
                          if target_def.values[f'desired.resource.{local}.resourceType'] == spec['resourceType']]
            from model_templates import resolve
            candidates = [(rid, resolve(anchor, context_for(target, anchor) if context_for else target['parameters'])) for rid, anchor in candidates]
            prefix = ''
        if len(candidates) != 1:
            raise ValueError(f'ambiguous/type-mismatched reference: {item["id"]}/{name}: {value}')
        rid, anchor = candidates[0]
        if spec.get('format') == 'identifier':
            from model_projection import identifier_outputs
            prop = spec['property']
            from design_catalog import design_material_files
            if not any(file.stem.replace('_', '.', 1) == spec['resourceType'] for file in design_material_files(root)):
                raise ValueError('reference catalog material missing: ' + spec['resourceType'])
            if prop not in identifier_outputs(root).get(spec['resourceType'], set()):
                raise ValueError('reference property is not a catalog identifier output')
            selected = [row_id for row_id, row in rows[rid] if row['property'] == prop]
            observed = [(row_id, row) for row_id, row in entries(model.values, 'observed.row.')
                        if row_id.rpartition('-')[0] == rid and row.get('property') == prop]
            if len(selected) != 1 or len(observed) != 1 or observed[0][0] != selected[0]:
                raise ValueError('reference producer requires exactly one matching observed identifier')
            raw = literal(observed[0][1].get('value', ''))
            if not isinstance(raw, str) or not raw or raw.startswith('arn:') or any(c in raw for c in '\r\n'):
                raise ValueError('reference producer requires a nonempty non-ARN string identifier')
            if name in labels:
                raise ValueError('raw identifier reference cannot override label')
            return raw
        default_label = rid
        needs_name = spec.get('format') == 'name' or name not in labels
        if prefix and needs_name and (spec['resourceType'] != 'KMS.Key' or spec.get('format') == 'name'):
            names = [literal(row['value']) for _, row in rows[rid] if row['property'].rsplit('.', 1)[0] == spec['resourceType'] and row['property'].endswith(REFERENCE_NAME_SUFFIXES)]
            if len(names) != 1 or not isinstance(names[0], str) or not names[0]:
                raise ValueError('reference producer requires exactly one name')
            default_label = names[0]
        if spec.get('format') == 'name':
            if name in labels:
                raise ValueError('raw name reference cannot override label')
            return default_label
        label = labels.get(name, default_label)
        if not isinstance(label, str) or not label or any(c in label for c in '[]\r\n'):
            raise ValueError('invalid reference label')
        return f'[{label}]({prefix}#{anchor})'
    elif spec.get('format') == 'literal':
        return '`'+(value if isinstance(value, str) else json_text(value))+'`'
    return value
