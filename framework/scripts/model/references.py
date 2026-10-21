"""Reference metadata describes saved text; reads never regenerate consumer values."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from model.core import entries, literal
from model.format import owner, json_field
from utils.json_format import strict_json
from model.sources import Scope, load_model, _source_snapshot, list_models, target_for, FileReads

LINKS = re.compile(r'\[([^\]]+)\]\(([^)]*?)#([^)]+)\)')
FIELDS = {'consumerKey', 'pointer', 'text', 'occurrence', 'producerKind', 'producerScope',
          'producerId', 'resourceType', 'format', 'property', 'labelPolicy', 'contextProperty'}
BASE = {'consumerKey', 'text', 'occurrence', 'producerKind', 'producerScope', 'format', 'labelPolicy'}


def pointer_leaf(value, pointer):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])', pointer):
        raise ValueError('reference requires an RFC 6901 pointer')
    for token in pointer.split('/')[1:] if pointer else ():
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValueError('reference pointer must select an existing string leaf')
    if not isinstance(value, str):
        raise ValueError('reference pointer must select an existing string leaf')
    return value


def _json(key, raw):
    body, ticked = json_field(key, raw)
    if body is None:
        return raw, False
    if ticked:
        if not body.endswith('`'):
            raise ValueError('missing closing JSON backtick: ' + key)
        body = body[:-1]
    return strict_json(body), True


def string_leaves(value, pointer=''):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from string_leaves(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from string_leaves(child, pointer + '/' + str(index))



def occurrence_positions(text, fragment):
    if not fragment:
        raise ValueError('reference text must be nonempty')
    positions, start = [], -1
    while (start := text.find(fragment, start + 1)) >= 0:
        positions.append(start)
    return positions


def declarations(values):
    result = dict(entries(values, 'desired.reference.'))
    for identity, spec in result.items():
        if not BASE <= spec.keys() or spec.keys() - FIELDS:
            raise ValueError('invalid reference fields: ' + identity)
        key = spec['consumerKey']
        if key not in values or key.startswith(('observed.', 'desired.reference.')):
            raise ValueError('reference consumerKey does not identify an authoritative consumer: ' + identity)
        kind, block = owner(key, values)
        if (kind == 'resource' and f'desired.resource.{block}.resourceType' not in values or
                kind == 'stack' and f'desired.stack.{block}.name' not in values):
            raise ValueError('reference consumer owner is absent: ' + identity)
        if not spec['text'] or re.fullmatch(r'[1-9][0-9]*', spec['occurrence']) is None:
            raise ValueError('reference text/occurrence is invalid: ' + identity)
        scope = PurePosixPath(spec['producerScope'])
        if scope.is_absolute() or '..' in scope.parts or '\\' in spec['producerScope'] or str(scope) != spec['producerScope']:
            raise ValueError('unsafe reference producerScope: ' + identity)
        kind, mode = spec['producerKind'], spec['format']
        required, forbidden = set(), set()
        if kind == 'resource':
            required = {'producerId', 'resourceType'}
            forbidden = {'contextProperty'}
            if mode not in {'link', 'name', 'identifier'} or len(scope.parts) != 3:
                raise ValueError('invalid resource reference format/scope: ' + identity)
            if mode == 'link':
                forbidden.add('property')
            else:
                required.add('property')
        elif kind == 'stack':
            required = {'producerId', 'property'}
            forbidden = {'resourceType', 'contextProperty'}
            if mode != 'name' or spec.get('property') != 'name' or len(scope.parts) != 3:
                raise ValueError('invalid stack reference: ' + identity)
        elif kind == 'context':
            required = {'contextProperty'}
            forbidden = {'producerId', 'resourceType', 'property'}
            if mode != 'literal' or len(scope.parts) != 2 or spec.get('contextProperty') != 'executionAccountId':
                raise ValueError('invalid context reference (contextProperty must be executionAccountId): ' + identity)
        else:
            raise ValueError('unknown reference producerKind: ' + identity)
        if not required <= spec.keys() or forbidden & spec.keys() or any(not spec[field] for field in required):
            raise ValueError('missing or forbidden reference fields: ' + identity)
        if spec['labelPolicy'] not in {'fixed', 'resource-id', 'display-name', 'none'}:
            raise ValueError('invalid reference labelPolicy: ' + identity)
        if mode != 'link' and spec['labelPolicy'] != 'none':
            raise ValueError('non-link reference requires labelPolicy none: ' + identity)
        value, structured = _json(key, values[key])
        if structured != ('pointer' in spec):
            raise ValueError('JSON references require a pointer; scalar references forbid one: ' + identity)
        leaf = pointer_leaf(value, spec['pointer']) if structured else value
        if len(occurrence_positions(leaf, spec['text'])) < int(spec['occurrence']):
            raise ValueError('reference occurrence does not identify saved text: ' + identity)
    return result


@dataclass(frozen=True)
class Usage:
    consumer_key: str
    pointer: str | None
    start: int
    end: int
    text: str
    producer_scope: str | None
    producer_kind: str
    producer_id: str | None
    metadata_id: str | None = None
    anchor: str | None = None


def _producer(snapshot, address, reads, cache):
    env, target, service = address.split('/')
    scope = Scope(snapshot.scope.root, env, target, service)
    if scope.path not in cache:
        target_for(scope, reads)
        from model.importing.scope import reference_reader
        with reference_reader(scope.path):
            cache[scope.path] = None if reads.kind(scope.path) == 'missing' else _source_snapshot(scope, reads)
    return cache[scope.path]


def link_scope(environment, target, service, filename):
    """Resolve a saved Markdown address lexically inside the registered Model tree."""
    import posixpath
    if not filename:
        return '/'.join((environment, target, service))
    if filename.startswith('/') or '\\' in filename:
        raise ValueError('direct Model reference is outside the Model tree: ' + filename)
    relative = PurePosixPath(posixpath.normpath('/'.join((environment, target, filename))))
    if len(relative.parts) != 3 or '..' in relative.parts or relative.suffix != '.md':
        raise ValueError('direct Model reference is outside the Model tree: ' + filename)
    return '/'.join((*relative.parts[:2], relative.stem))


def _link_scope(snapshot, filename):
    scope = snapshot.scope
    return link_scope(scope.environment, scope.target, scope.service, filename)


def usages(snapshot, read_context=None, *, _cache=None, _producer_scope=None, _coalesce=True):
    """Keep conflicting declarations and links; identical locations/meaning coalesce."""
    values = snapshot.authoritative
    result = []
    reads = read_context or FileReads()
    cache = {snapshot.scope.path: snapshot} if _cache is None else _cache
    declared_specs = declarations(values)
    for identity, spec in declared_specs.items():
        if _producer_scope is not None and spec['producerScope'] != _producer_scope:
            continue
        value, structured = _json(spec['consumerKey'], values[spec['consumerKey']])
        leaf = pointer_leaf(value, spec['pointer']) if structured else value
        offset = occurrence_positions(leaf, spec['text'])[int(spec['occurrence']) - 1]
        result.append(Usage(spec['consumerKey'], spec.get('pointer'), offset, offset + len(spec['text']),
                            spec['text'], spec['producerScope'], spec['producerKind'], spec.get('producerId'), identity))
    declared_by_position = {}
    if _coalesce:
        for usage in result:
            position = (usage.consumer_key, usage.pointer, usage.start, usage.end)
            declared_by_position.setdefault((position, usage.producer_scope), []).append(usage)
    for key, raw in values.items():
        if key.startswith(('observed.', 'desired.reference.')):
            continue
        value, structured = _json(key, raw)
        for pointer, leaf in string_leaves(value):
            for link in LINKS.finditer(leaf):
                filename = link[2].removeprefix('./')
                if re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', filename):
                    continue
                producer_scope = _link_scope(snapshot, filename)
                if _producer_scope is not None and producer_scope != _producer_scope:
                    continue
                position = (key, pointer if structured else None, link.start(), link.end())
                duplicate = False
                for usage in declared_by_position.get((position, producer_scope), ()):
                    if ((usage.consumer_key, usage.pointer, usage.start, usage.end) != position
                            or not usage.metadata_id or usage.producer_scope != producer_scope
                            or usage.producer_kind != 'resource'):
                        continue
                    spec = declared_specs[usage.metadata_id]
                    if spec['format'] != 'link':
                        continue
                    producer = _producer(snapshot, producer_scope, reads, cache)
                    matches = [] if producer is None else [identity for identity, resource in
                        entries(producer.authoritative, 'desired.resource.') if resource.get('anchor') == link[3]]
                    if matches == [usage.producer_id]:
                        duplicate = True
                        break
                if not duplicate:
                    result.append(Usage(*position, link[0], producer_scope, 'resource', None, anchor=link[3]))
    return tuple(result)


def diagnose(snapshot, read_context=None, *, _producer_scope=None):
    """Only semantic producer failures become warnings; syntax, scope and I/O propagate."""
    reads = read_context or FileReads()
    warnings, dependencies, cache = [], dict(snapshot.dependencies), {snapshot.scope.path: snapshot}
    # The producer cache retains snapshots, so their IDs stay unique for this diagnosis.
    parsed = {}

    def producer_entries(producer, prefix):
        key = (id(producer), prefix)
        if key not in parsed:
            result = entries(producer.authoritative, prefix)
            parsed[key] = dict(result) if prefix == 'desired.resource.' else result
        return parsed[key]

    specs = declarations(snapshot.authoritative)
    for usage in usages(snapshot, reads, _cache=cache, _producer_scope=_producer_scope):
        spec = specs.get(usage.metadata_id, {})
        def warn(message):
            warnings.append({'code': 'reference.mismatch', 'message': message,
                             'consumerKey': usage.consumer_key, 'pointer': usage.pointer,
                             'reference': usage.metadata_id, 'text': usage.text})
        if usage.producer_kind == 'context':
            env, target = usage.producer_scope.split('/')
            selected = Scope(snapshot.scope.root, env, target, snapshot.scope.service)
            context, project = target_for(selected, reads)
            expected = context.get('awsExecutionAccountId', context['awsAccountId'])
            if usage.text != expected:
                warn('context value differs from saved text')
            continue
        producer = _producer(snapshot, usage.producer_scope, reads, cache)
        if producer is None:
            warn('producer Model is absent')
            continue
        dependencies.update(producer.dependencies)
        values = producer.authoritative
        if usage.producer_kind == 'stack':
            expected = values.get(f'desired.stack.{usage.producer_id}.name')
            if expected is None:
                warn('producer Stack is absent')
            elif literal(usage.text) != literal(expected):
                warn('Stack name differs from saved text')
            continue
        resources = producer_entries(producer, 'desired.resource.')
        matches = ([usage.producer_id] if usage.producer_id in resources else []) if usage.metadata_id else [
            identity for identity, resource in resources.items() if resource.get('anchor') == usage.anchor]
        if len(matches) != 1:
            warn('producer Resource is absent or ambiguous')
            continue
        identity = matches[0]
        resource = resources[identity]
        if spec and resource['resourceType'] != spec['resourceType']:
            warn('producer Resource Type differs')
        if spec.get('format') in {'name', 'identifier'}:
            from model.projection import REFERENCE_NAME_SUFFIXES
            prop = spec['property']
            if prop.rsplit('.', 1)[0] != spec['resourceType']:
                warn('producer Property does not belong to the expected Resource Type')
                continue
            if spec['format'] == 'name' and not prop.endswith(REFERENCE_NAME_SUFFIXES):
                warn('producer Property is not a raw name Property')
                continue
            rows = [(rid, row) for rid, row in producer_entries(producer, 'desired.row.')
                    if rid.rpartition('-')[0] == identity and row.get('property') == spec['property']]
            if len(rows) != 1:
                warn('producer Property is absent or ambiguous')
                continue
            rid, row = rows[0]
            expected = row.get('value') if spec['format'] == 'name' else values.get(f'observed.row.{rid}.value')
            if expected is None or literal(expected) == 'PENDING_DEPLOY':
                warn('producer Property is unobserved or pending')
            elif spec['format'] == 'identifier' and (not literal(expected) or literal(expected).startswith('arn:')):
                warn('producer identifier is not a nonempty non-ARN string')
            elif literal(usage.text) != literal(expected):
                warn('producer name/identifier differs from saved text')
        elif spec:
            link = LINKS.fullmatch(usage.text)
            linked_scope = (_link_scope(snapshot, link[2]) if link and not re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', link[2]) else None)
            if link is None or link[3] != resource.get('anchor') or linked_scope != usage.producer_scope:
                warn('declared producer differs from the saved link; both meanings are retained')
                continue
            if spec['labelPolicy'] == 'resource-id' and link[1] != identity:
                warn('resource-id label differs')
            elif spec['labelPolicy'] == 'display-name':
                from model.render import display_name
                from model.projection import resource_display_rows
                display_rows = resource_display_rows(values, identity, resource, producer.scope.root)
                try:
                    # This pure function raises only name/display semantic failures.
                    expected, _ = display_name(values, identity, resource, display_rows, producer.scope.root)
                except ValueError as error:
                    warn('producer display name unavailable: ' + str(error))
                else:
                    if expected is None or link[1] != expected:
                        warn('display-name label differs')
    for path, producer in cache.items():
        if producer is None:
            dependencies[path] = None
        else:
            dependencies.update(producer.dependencies)
    return tuple(warnings), dependencies


def incoming(snapshot, producer_id, read_context=None, *, warnings=None):
    """Read-only discovery has no dependency on a mutation/CREATE save guard."""
    result = []
    address = '/'.join((snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service))
    anchor = snapshot.authoritative.get(f'desired.resource.{producer_id}.anchor')
    from model.importing.scope import read_consumers
    reads = read_context or FileReads()
    scopes = list_models(snapshot.scope.root, reads)
    with read_consumers({(scope.environment, scope.target, scope.service) for scope in scopes}):
        for scope in scopes:
            consumer = _source_snapshot(scope, reads)
            relevant_warnings, _ = diagnose(consumer, reads, _producer_scope=address)
            if warnings is not None:
                warnings.extend({'scope': '/'.join((scope.environment, scope.target, scope.service)), **warning}
                                for warning in relevant_warnings)
            for usage in usages(consumer, reads, _producer_scope=address):
                if usage.producer_scope == address and (usage.producer_id == producer_id or
                                                        anchor is not None and usage.anchor == anchor):
                    result.append((scope, usage))
    return tuple(result)


@dataclass(frozen=True)
class Reference:
    """Comparison identity for an existing saved fragment, never a value generator."""
    producer: str | None
    kind: str
    resource_type: str | None = None
    format: str | None = None
    property_name: str | None = None
    label: str | None = None
    label_policy: str | None = None
    selector: str | None = None


def resource_address(value):
    parts = tuple(value.split('/')) if isinstance(value, str) else ()
    if len(parts) != 4 or any(not part or part in {'.', '..'} or '\\' in part for part in parts):
        raise ValueError('resource address requires environment/target/service/fixed-ID')
    return parts


def symbolic(snapshot, read_context=None):
    """Retain JSON/native structure and every literal affix around saved references."""
    values = snapshot.authoritative
    specs = declarations(values)
    grouped = {}
    reads = read_context or FileReads()
    cache = {snapshot.scope.path: snapshot}
    for usage in usages(snapshot, reads, _cache=cache):
        spec = specs.get(usage.metadata_id, {})
        producer_id = usage.producer_id
        if producer_id is None and usage.producer_kind == 'resource':
            producer = _producer(snapshot, usage.producer_scope, reads, cache)
            matches = [] if producer is None else [identity for identity, resource in entries(producer.authoritative, 'desired.resource.')
                                                   if resource.get('anchor') == usage.anchor]
            if len(matches) == 1:
                producer_id = matches[0]
        address = usage.producer_scope
        if usage.producer_kind != 'context':
            address = None if producer_id is None else '/'.join((address, *(['stack'] if usage.producer_kind == 'stack' else []), producer_id))
        link = LINKS.fullmatch(usage.text)
        record = Reference(address, usage.producer_kind, spec.get('resourceType'), spec.get('format', 'link'),
            spec.get('property'), link[1] if link else None, spec.get('labelPolicy'),
            spec.get('contextProperty') if usage.producer_kind == 'context' else usage.anchor if producer_id is None else None)
        grouped.setdefault((usage.consumer_key, usage.pointer), []).append((usage.start, usage.end, record))

    def leaf(key, pointer, value):
        spans = sorted(grouped.get((key, pointer), []), key=lambda item: (item[0], item[1]))
        if not spans:
            return value
        merged = []
        for start, end, record in spans:
            if merged and start < merged[-1][1]:
                previous = merged[-1]
                merged[-1] = previous[0], max(previous[1], end), (*previous[2], record)
            else:
                merged.append((start, end, (record,)))
        result, cursor = [], 0
        for start, end, records in merged:
            result.append(value[cursor:start])
            result.append(records[0] if len(records) == 1 else Reference(None, 'ambiguous', selector=repr(records)))
            cursor = end
        result.append(value[cursor:])
        return tuple(result)

    def tree(key, value, pointer=''):
        if isinstance(value, str):
            return leaf(key, pointer, value)
        if isinstance(value, dict):
            return {name: tree(key, child, pointer + '/' + name.replace('~', '~0').replace('/', '~1')) for name, child in value.items()}
        if isinstance(value, list):
            return [tree(key, child, pointer + '/' + str(index)) for index, child in enumerate(value)]
        return value

    result = {}
    for key, raw in values.items():
        if key.startswith('desired.reference.'):
            continue
        value, structured = _json(key, raw)
        result[key] = tree(key, value) if structured else leaf(key, None, value)
    return result


def walk_references(value):
    if isinstance(value, Reference):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk_references(child)


def reference_positions(value, pointer=''):
    if isinstance(value, Reference):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from reference_positions(child, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from reference_positions(child, pointer + '/' + str(index))
    elif isinstance(value, tuple):
        for child in value:
            yield from reference_positions(child, pointer)
