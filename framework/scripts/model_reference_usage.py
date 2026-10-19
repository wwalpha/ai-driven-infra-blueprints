"""Read-only fixed-identity reference usage, using the existing Model resolver."""
from dataclasses import dataclass
from pathlib import Path
import re
from model_core import entries, LINK
from model_sources import json_read
from model_templates import load_expansion, resolve, template_document, _reference_inputs, model_paths
from model_parameter_inputs import parameter_value, schema, select_reference_target
from validation_cache import input_scope

@dataclass(frozen=True)
class _Reference:
    producer: str
    kind: str
    resource_type: str | None = None
    format: str | None = None
    property_name: str | None = None
    label: str | None = None
    label_policy: str | None = None


def _symbolic(path, expansion, anchors):
    """Use existing bound templates/resolver inputs, replacing typed outputs by records."""
    registered, (definitions, _, _, normalized, bindings, fields) = _reference_inputs(path)
    root, template, _ = registered
    env, target, service = path.parent.parent.name, path.parent.name, path.stem
    tokens, contexts, token_inputs, resolved_tokens = {}, {}, {}, {}

    def token(record, item, name):
        # Markers are local to this comparison; raw inputs cannot impersonate a record.
        marker = '\x00reference' + str(len(tokens)) + '\x00'
        tokens[marker] = record
        token_inputs[marker] = item, name
        return marker

    def producer(item, name, spec):
        rid, kind = select_reference_target(template, item, name, normalized['instances'], definitions, env, {})
        parts = (env, target, spec.get('service', service))
        # Stack identities must never compare equal to a Resource with the same fixed ID.
        return '/'.join((*parts, 'stack', rid) if kind == 'stack' else (*parts, rid))

    def reserved(value):
        if isinstance(value, str):
            return '\x00' in value
        if isinstance(value, dict):
            return any(reserved(item) for item in (*value.keys(), *value.values()))
        if isinstance(value, list):
            return any(reserved(item) for item in value)
        return False

    def symbolize(value):
        if isinstance(value, dict):
            return {k: symbolize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [symbolize(v) for v in value]
        if not isinstance(value, str):
            return value
        if '\x00' in value and not any(marker in value for marker in tokens):
            raise ValueError('invalid reference marker in source')
        pattern = r'\x00reference[0-9]+\x00|\[[^\]]*\]\([^)]*\)'
        pieces, start = [], 0
        for match in re.finditer(pattern, value):
            raw = match[0]
            record = tokens.get(raw)
            nested = []
            resolved_raw = raw
            if record is None:
                for marker in re.findall(r'\x00reference[0-9]+\x00', raw):
                    nested.append(tokens[marker])
                    if marker not in resolved_tokens:
                        item, name = token_inputs[marker]
                        resolved_tokens[marker] = parameter_value(template, item, name, normalized['instances'], bindings, definitions, env, {})
                    resolved_raw = resolved_raw.replace(marker, resolved_tokens[marker])
                link = LINK.fullmatch(resolved_raw)
                if link:
                    filename = link[2].removeprefix('./')
                    target_service = service if not filename else filename[:-3] if filename.endswith('.md') and '/' not in filename else None
                    if target_service is None and filename.endswith('.md') and ':' not in filename:
                        raise ValueError('unsupported internal Model link: ' + raw)
                    fixed = _anchor_reference(path, anchors, target_service, link[3]) if target_service is not None else None
                    if fixed:
                        # Numeric self labels are identity-derived, other literal labels are fixed.
                        label = None if link[1] == fixed.rsplit('/', 1)[1] else link[1]
                        record = _Reference(fixed, 'link', label=label)
            if record is not None or nested:
                pieces.extend((value[start:match.start()], *nested, record if record is not None else resolved_raw))
                start = match.end()
        if not pieces:
            return value
        pieces.append(value[start:])
        return tuple(pieces)

    result = {}
    instances = normalized['instances']
    for output_key, (item, definition, raw) in fields.items():
        if '\x00' in raw or reserved(item['parameters']):
            raise ValueError('reserved control character in reference expression')
        if item['id'] not in contexts:
            context = dict(item['parameters'])
            context.update({'Id_' + key: value for key, value in item['resources'].items()})
            for name in list(item['parameters']):
                spec = schema(definition.parameters[name])
                if spec['type'] == 'reference':
                    context[name] = token(_Reference(producer(item, name, spec), 'typed', spec['resourceType'],
                        spec.get('format'), spec.get('property'), bindings['instances'][item['id']].get('labels', {}).get(name),
                        'explicit' if name in bindings['instances'][item['id']].get('labels', {}) else
                        'scalar' if spec.get('format') else 'service-auto' if 'service' in spec else 'local-auto'), item, name)
                else:
                    context[name] = parameter_value(template, item, name, instances, bindings, definitions, env, {})
            for local in definition.resources:
                context['Anchor_' + local] = expansion.values['desired.resource.' + item['resources'][local] + '.anchor']
            contexts[item['id']] = context
        context = contexts[item['id']]
        local_key = expansion.provenance[output_key]['key']
        structured = output_key.endswith('.document') or any(k == local_key for k, _ in definition.optional_json) or any(k == local_key and pointer is not None for k, pointer, _ in definition.choices)
        source = template_document(output_key, raw) if structured else raw
        if reserved(source):
            raise ValueError('reserved control character in reference expression: ' + output_key)
        value = resolve(source, context, structured=structured)
        result[output_key] = symbolize(value)
    for key, value in expansion.values.items():
        if key not in result:
            result[key] = json_read(value) if key.endswith('.document') else value
    return result


def _walk(value):
    if isinstance(value, _Reference):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _anchor_reference(path, anchors, service, anchor):
    """Resolve only producer anchors when a caller did not expand that service."""
    if (service, anchor) in anchors:
        return anchors[service, anchor]
    from model_templates import reference_values
    producer = path.with_name(service + '.properties')
    _, inputs = _reference_inputs(producer)
    for key, (_, _, kind) in inputs[5].items():
        if not key.startswith('desired.resource.') or not key.endswith('.resourceType'):
            continue
        rid = key.split('.')[2]
        kind = reference_values(producer, rid, None, 'type').values[key]
        value = reference_values(producer, rid, kind, 'anchor').values[key.removesuffix('resourceType') + 'anchor']
        address = '/'.join((path.parent.parent.name, path.parent.name, service, rid))
        previous = anchors.setdefault((service, value), address)
        if previous != address:
            raise ValueError('ambiguous Resource anchor: ' + service + '#' + value)
    if (service, anchor) not in anchors:
        raise ValueError('unresolved internal Model link: ' + service + '#' + anchor)
    return anchors[service, anchor]


def resource_address(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[a-z0-9]+(?:[-_][a-z0-9]+)*/){3}[0-9]{3,}', value):
        raise ValueError('expected environment/target/service/fixed Resource ID: ' + repr(value))
    return tuple(value.split('/'))


def reference_models(root, scopes):
    """Expand each selected service once in the caller's immutable input context."""
    expanded = {}
    for scope in sorted(scopes):
        path = Path(root) / 'model' / scope[0] / scope[1] / (scope[2] + '.properties')
        expansion = load_expansion(path)
        if expansion is None:
            raise ValueError('missing reference Model: ' + '/'.join(scope))
        expanded[scope] = expansion
    anchors = {}
    for scope, expansion in expanded.items():
        for rid, resource in entries(expansion.values, 'desired.resource.'):
            key = (*scope, resource['anchor'])
            if key in anchors:
                raise ValueError('ambiguous Resource anchor: ' + str(key))
            anchors[key] = '/'.join((*scope, rid))
    symbolic = {}
    for scope, expansion in expanded.items():
        path = Path(root) / 'model' / scope[0] / scope[1] / (scope[2] + '.properties')
        index = {(service, anchor): address for (env, target, service, anchor), address in anchors.items()
                 if (env, target) == scope[:2]}
        symbolic[scope] = _symbolic(path, expansion, index)
    return expanded, symbolic


def reference_positions(value, pointer=None):
    if isinstance(value, _Reference):
        yield pointer, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from reference_positions(item, (pointer or '') + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from reference_positions(item, (pointer or '') + '/' + str(index))
    elif isinstance(value, tuple):
        for item in value:
            yield from reference_positions(item, pointer)


def usage_records(root, expanded, symbolic):
    for scope, values in symbolic.items():
        expansion = expanded[scope]
        resources = dict(entries(expansion.values, 'desired.resource.'))
        for key, value in values.items():
            parts = key.split('.')
            rid = parts[2] if parts[1] == 'resource' else parts[2].rpartition('-')[0] if parts[1] == 'row' else None
            consumer = '/'.join((*scope, rid)) if rid in resources else None
            prop = expansion.values.get('.'.join(parts[:3]) + '.property') if parts[1] == 'row' else None
            for pointer, reference in reference_positions(value):
                resolved = expansion.values[key]
                if key.endswith('.document') or isinstance(value, (dict, list)):
                    resolved = json_read(resolved.strip('`'))
                    if pointer is not None:
                        from model_templates import json_pointer
                        parent, leaf = json_pointer(resolved, pointer)
                        resolved = parent[leaf]
                trace = expansion.provenance.get(key, {})
                source = trace.get('sourceLocations', {}).get(pointer, {})
                file = source.get('file', trace.get('template', trace.get('sourceFile')))
                line = source.get('line', trace.get('line'))
                yield {'producer': reference.producer, 'consumer': consumer, 'scope': '/'.join(scope),
                       'key': key, 'property': prop, 'pointer': pointer, 'kind': reference.kind,
                       'format': reference.format, 'resolvedValue': resolved,
                       'role': 'structure' if key.endswith('.parentReference') else
                               'configuration' if parts[0] == 'desired' and parts[1] == 'row' and parts[-1] in {'value', 'document'} else 'display',
                       'sourceLocation': {'file': str(Path(file).relative_to(root)) if file else None, 'line': line},
                       'provenance': trace, 'status': 'resolved'}


@input_scope
def _references(root, address, incoming):
    root = Path(root).resolve()
    env, target, service, rid = resource_address(address)
    from model_sources import publication_lock
    with publication_lock(root, read_only=True):
        # Incoming links can originate in any service of this target, never other environments.
        scopes = ({(*path.relative_to(root / 'model').parts[:2], path.stem)
                   for path in model_paths(root, env, target)} if incoming else {(env, target, service)})
        expanded, symbolic = reference_models(root, scopes)
    selected = expanded.get((env, target, service))
    if selected is None or rid not in dict(entries(selected.values, 'desired.resource.')):
        raise ValueError('unknown Resource: ' + address)
    return [record for record in usage_records(root, expanded, symbolic)
            if record['producer' if incoming else 'consumer'] == address]


def incoming_references(root, resource_address):
    """Return incoming usages, or raise with the unresolved cause; never return false absence."""
    return _references(root, resource_address, True)


def outgoing_references(root, resource_address):
    """Return active outgoing usages, including JSON pointers and source provenance."""
    return _references(root, resource_address, False)


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resource_address')
    parser.add_argument('--repository-root', type=Path, default=Path.cwd())
    parser.add_argument('--direction', choices=('incoming', 'outgoing'), default='incoming')
    args = parser.parse_args()
    try:
        result = _references(args.repository_root, args.resource_address, args.direction == 'incoming')
        print(json.dumps({'status': 'resolved', 'references': result}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'unresolved', 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
