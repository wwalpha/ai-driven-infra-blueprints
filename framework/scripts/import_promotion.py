"""Lossless Property promotion; all candidates stay in memory until import publication."""
import copy
import hashlib
from pathlib import Path

from import_scope import model_path, read_consumers
from import_sources import equivalent, input_plan, parameter_edit
from model_core import LINK, literal
from model_files import model_file_contents, model_parts
from model_references import catalog_outputs
from model_parameter_inputs import check_type, schema, yaml_read
from model_templates import (bound_definition, json_read, json_text, parse_template,
                             remap_key, service_source, variables)


def conflict(path, trace, prop, reason):
    root = path.parents[3]
    template = Path(trace['template'])
    return ValueError('IMPORT conflict:\n' + '\n'.join(label + ': ' + str(value) for label, value in (
        ('Environment', path.parent.parent.name), ('Target', path.parent.name), ('Service', path.stem),
        ('Instance', trace['instance']), ('Definition', trace['definition']),
        ('Resource ID', next(iter(trace.get('rows', {}).values()), '').rpartition('-')[0]),
        ('Row ID', next(iter(trace.get('rows', {}).values()), '')), ('Property', prop),
        ('Template file', template.relative_to(root)), ('Template line', trace['line']),
        ('Conflict type', 'unsafe Property promotion'), ('Reason', reason))))


def safe_expression(definition, key):
    raw = definition.values[key]
    names = variables(raw)
    if any(name.startswith(('Id_', 'Anchor_')) or schema(definition.parameters[name]).get('internal') or
           schema(definition.parameters[name])['type'] == 'reference' or
           schema(definition.parameters[name]).get('source') == 'consumer.executionAccountId' for name in names):
        raise ValueError('logical reference or internal identifier cannot become a value parameter')
    if any(part == key for part, _ in definition.optional_json) or any(part == key for part, _, _ in definition.choices):
        raise ValueError('conditional JSON/choice branches require an explicit safe shape plan')
    if LINK.fullmatch(raw) or '{{resolve:' in raw or '](' in raw:
        raise ValueError('logical/dynamic reference cannot become a value parameter')


def typed_value(raw, spec, document=False):
    value = json_read(raw) if document else literal(raw)
    if not document and spec['type'] != 'string':
        value = json_read(value)
    check_type(spec, value, 'promoted Property')
    return value


def plan_promotions(path, expansion, values, property_schema, unsafe, sensitive):
    """Reuse proven inverse updates, isolating only destinations with unsafe side effects."""
    _, template, directory = service_source(path)
    definitions, _ = parse_template(template)
    parameters = yaml_read(expansion.files[directory / 'parameters.yaml'])
    bindings = json_read(expansion.files[directory / 'bindings.json'])
    schemas = {}
    for key, trace in expansion.provenance.items():
        if not key.startswith('desired.row.') or not key.endswith(('.value', '.document')) or key not in values or 'definition' not in trace or equivalent(expansion.values[key], values[key]):
            continue
        prop = values.get(key.rpartition('.')[0] + '.property', '')
        kind = '.'.join(prop.split('.')[:2])
        try:
            schemas[key] = property_schema(prop)
        except (ValueError, KeyError, TypeError) as error:
            raise conflict(path, trace, prop, 'registered Property schema could not be resolved') from error
        declared = schemas[key].get('type')
        if isinstance(declared, list) and len(set(declared)) > 1 and not key.endswith('.document'):
            raise conflict(path, trace, prop, 'union-typed scalar has no unambiguous native parameter type')
        if prop in catalog_outputs(Path(__file__).resolve().parents[2], kind):
            raise conflict(path, trace, prop, 'identifier output cannot become a value parameter')
        if sensitive(prop) or unsafe(values[key]) or '{{resolve:' in values[key]:
            raise conflict(path, trace, prop, 'sensitive, unresolved or reference value is not promotable')
    pending = set()
    parameters, _ = input_plan(template, definitions, parameters, bindings['instances'], expansion,
                               values, path.parent.parent.name, promotions=pending)
    plans = {}
    names_used = {name: set(definition.parameters) for name, definition in definitions.items()}
    for key in sorted(pending):
        trace = expansion.provenance[key]
        owner = key.split('.')[2].rpartition('-')[0]
        prop = values.get(key.rpartition('.')[0] + '.property')
        # Removed resources/rows and reference retargeting remain snapshot responsibilities.
        if values.get('desired.resource.' + owner + '.resourceMode') != 'IMPORT' or not prop:
            continue
        definition = definitions[trace['definition']]
        try:
            safe_expression(definition, trace['key'])
            if sensitive(prop) or unsafe(values[key]) or '](' in values[key] or '{{resolve:' in values[key]:
                raise ValueError('sensitive, unresolved or reference value is not promotable')
            registered = schemas[key]
            kinds = registered.get('type')
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not kinds or set(kinds) - {'string', 'integer', 'number', 'boolean', 'object', 'array', 'null'}:
                raise ValueError('Property schema has no supported lossless type')
            document = key.endswith('.document')
            decoded = json_read(values[key]) if document else literal(values[key])
            if document or kinds != ['string']:
                decoded = json_read(decoded) if isinstance(decoded, str) and not document else decoded
            actual_kind = {str: 'string', int: 'integer', float: 'number', bool: 'boolean',
                           dict: 'object', list: 'array', type(None): 'null'}.get(type(decoded))
            kind = actual_kind if actual_kind in kinds else 'number' if actual_kind == 'integer' and 'number' in kinds else None
            if kind is None:
                raise ValueError('AWS value type does not match registered Property schema')
            spec = {'type': kind, 'description': 'AWS実環境のProperty値', 'required': True}
            if not document and expansion.values[key].startswith('`'):
                spec['format'] = 'literal'
            name = 'Import_' + hashlib.sha256('/'.join((path.stem, trace['definition'], trace['key'])).encode()).hexdigest()[:20]
            previous = plans.get((trace['definition'], trace['key']))
            if previous:
                name = previous['parameter']
            else:
                base, suffix = name, 1
                while name in names_used[trace['definition']]:
                    suffix += 1
                    name = base + '_' + str(suffix)
                names_used[trace['definition']].add(name)
            expression = json_text('<<' + name + '>>') if document else '<<' + name + '>>'
            plan = plans.setdefault((trace['definition'], trace['key']),
                {'definition': trace['definition'], 'key': trace['key'], 'parameter': name, 'spec': spec,
                 'expression': expression, 'trace': trace, 'property': prop, 'targets': {}})
            if plan['spec'] != spec:
                raise ValueError('instances require incompatible Property types or literal formats')
            plan['targets'][trace['instance']] = typed_value(values[key], spec, document)
        except (ValueError, TypeError) as error:
            raise conflict(path, trace, prop, str(error)) from error
    return list(plans.values()), parameters


def preserve_consumers(path, expansion, plans):
    """Read only the promoted Property in direct Definition consumers."""
    root = path.parents[3]
    identity = (path.parent.parent.name, path.parent.name, path.stem)
    from model_templates import consumers
    identities = {identity} | (consumers(root, identity[1], identity[2]) if plans else set())
    preserved = {}
    definitions = parse_template(service_source(path)[1])[0]
    with read_consumers(identities):
        for consumer in sorted(identities):
            _, _, directory = service_source(model_path(root, consumer))
            from model_templates import Expansion
            files = {file: file.read_text(encoding='utf-8') for file in (directory / 'parameters.yaml', directory / 'bindings.json')}
            current = expansion if consumer == identity else Expansion({}, {}, files)
            bindings = json_read(files[directory / 'bindings.json'])
            parameters = yaml_read(files[directory / 'parameters.yaml'])
            uses = {}
            for plan in plans if consumer[1:] == identity[1:] else []:
                definition = definitions[plan['definition']]
                for instance, binding in bindings['instances'].items():
                    if binding['definition'] != plan['definition']:
                        continue
                    local_row = plan['key'].split('.')[2]
                    if local_row not in binding['rows'] and plan['key'] in definition.optional:
                        continue
                    key = remap_key(plan['key'], definition, binding['resources'], binding['rows'])
                    if consumer == identity and key not in current.values:
                        # Whole-field optional selection can safely omit the new input as before.
                        if plan['key'] in definition.optional:
                            continue
                        raise conflict(path, plan['trace'], plan['property'], 'consumer Property is absent without a field selector')
                    try:
                        if consumer == identity:
                            value = current.values[key]
                        else:
                            from model_templates import resolve, template_document, template_document_text
                            raw = definition.values[plan['key']]
                            context = {}
                            for name in variables(raw):
                                declaration = definition.parameters[name]
                                source = declaration.get('source')
                                if source == 'consumer.environment':
                                    context[name] = consumer[0]
                                elif source == 'consumer.executionAccountId':
                                    from model_parameter_inputs import consumer_execution_account
                                    context[name] = consumer_execution_account(service_source(path)[1], consumer[0])
                                    current.files[root / 'project.json'] = (root / 'project.json').read_text(encoding='utf-8')
                                else:
                                    supplied = parameters.get('parameters', {}) if source == 'service' else parameters.get('instances', {}).get(instance, {}).get('parameters', {})
                                    if name not in supplied and 'default' not in declaration:
                                        raise ValueError('preserved Property input is missing: ' + name)
                                    context[name] = supplied.get(name, declaration.get('default'))
                            value = template_document_text(plan['key'], resolve(template_document(plan['key'], raw), context, structured=True)) if key.endswith('.document') else resolve(raw, context)
                        uses[instance, plan['parameter']] = typed_value(value, plan['spec'], key.endswith('.document'))
                    except (ValueError, TypeError) as error:
                        raise conflict(path, plan['trace'], plan['property'], 'consumer value cannot retain its type/format') from error
            preserved[consumer] = (current, parameters, bindings, uses)
    return preserved


def apply_promotions(path, plans, parameters, preserved):
    """Return shared template and YAML candidates using existing split/serialization rules."""
    root, template, directory = service_source(path)
    definitions, files = parse_template(template)
    definitions = copy.deepcopy(definitions)
    for plan in plans:
        definition = definitions[plan['definition']]
        definition.parameters[plan['parameter']] = plan['spec']
        definition.values[plan['key']] = plan['expression']
    removed = {name: set() for name in definitions}
    original = parse_template(template)[0]
    for plan in plans:
        name = plan['definition']
        used = set().union(*(variables(value) for value in definitions[name].values.values()))
        used |= set(definitions[name].optional.values()) | set(definitions[name].optional_json.values())
        used |= {selector for _, _, selector in definitions[name].choices}
        removed[name] |= variables(original[name].values[plan['key']]) - used
    for name, discarded in removed.items():
        for parameter in discarded:
            definitions[name].parameters.pop(parameter, None)
    text = ''.join(files[part] for part in model_parts(template))
    lines, current = [], None
    shared_used = {parameter for definition in definitions.values() for parameter, spec in definition.parameters.items() if spec.get('source')}
    for line in text.splitlines(keepends=True):
        if line.startswith('# input: ') and line.split()[2] not in shared_used:
            continue
        if line.startswith('# definition: '):
            current = line.strip().removeprefix('# definition: ')
            lines.append(line)
            lines.extend('# parameter: ' + plan['parameter'] + ' ' + json_text(plan['spec']) + '\n'
                         for plan in plans if plan['definition'] == current)
            continue
        if line.startswith(('# parameter: ', '# internal: ', '# reference: ')) and line.split()[2] in removed[current]:
            continue
        if current and line.partition('=')[0] in definitions[current].values:
            key = line.partition('=')[0]
            if any(plan['definition'] == current and plan['key'] == key for plan in plans):
                line = key + '=' + definitions[current].values[key] + ('\r\n' if line.endswith('\r\n') else '\n')
        lines.append(line)
        if line.strip() == '# end-definition':
            current = None
    output = model_file_contents(template, ''.join(lines), validate=False) if plans else {}
    if plans:
        output.update({part: None for part in set(model_parts(template)) - output.keys() - {template}})
    identity = (path.parent.parent.name, path.parent.name, path.stem)
    for consumer, (expansion, original, bindings, uses) in preserved.items():
        if consumer[1:] != identity[1:]:
            continue
        candidate = copy.deepcopy(parameters if consumer == identity else original)
        for (instance, name), value in uses.items():
            candidate['instances'].setdefault(instance, {'parameters': {}})['parameters'][name] = value
        for plan in plans:
            if consumer == identity:
                for instance, value in plan['targets'].items():
                    candidate['instances'].setdefault(instance, {'parameters': {}})['parameters'][plan['parameter']] = value
        for instance, item in candidate['instances'].items():
            for name in removed[bindings['instances'][instance]['definition']]:
                item['parameters'].pop(name, None)
        removed_shared = set().union(*removed.values()) - shared_used
        for name in removed_shared:
            candidate.get('parameters', {}).pop(name, None)
        if removed_shared and not candidate.get('parameters'):
            candidate.pop('parameters', None)
        file = root / 'model/parameters' / Path(*consumer) / 'parameters.yaml'
        if candidate != original:
            output[file] = parameter_edit(expansion.files[file], candidate)
    return {file: content for file, content in output.items()
            if (file.read_bytes().decode('utf-8') if file.is_file() else None) != content}
