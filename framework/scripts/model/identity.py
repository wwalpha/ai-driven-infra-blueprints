"""Fixed service-local Resource identities and internal, scope-checked addresses."""
import re
from model.core import entries, ReferenceResolutionError

COUNTERS = 'desired.service.identity.lastAllocated'
URI = re.compile(r'resource://([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_]+)')


def prefix(kind):
    if not isinstance(kind, str) or re.fullmatch(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+', kind) is None:
        raise ValueError('invalid ResourceType for logicalId: ' + str(kind))
    return kind.replace('.', '_')


def sequence(kind, logical):
    head = prefix(kind) + '_'
    suffix = logical.removeprefix(head) if isinstance(logical, str) else ''
    if not isinstance(logical, str) or not logical.startswith(head) or not re.fullmatch(r'[0-9]{3,}', suffix) or int(suffix) < 1 or suffix != f'{int(suffix):03d}':
        raise ValueError('logicalId requires ResourceType prefix and fixed sequence: ' + str(logical))
    return int(suffix)


def counters(values):
    from utils.json_format import strict_json
    state = strict_json(values.get(COUNTERS, '{}'))
    if not isinstance(state, dict):
        raise ValueError('lastAllocated must be a ResourceType to integer object')
    prefixes = {}
    for kind, number in state.items():
        if type(number) is not int or number < 0:
            raise ValueError('lastAllocated must contain nonnegative integers')
        head = prefix(kind)
        if head in prefixes and prefixes[head] != kind:
            raise ValueError('ResourceType logicalId prefix collision: ' + head)
        prefixes[head] = kind
    return state


def resource_index(values):
    state, result = counters(values), {}
    prefixes = {prefix(kind): kind for kind in state}
    for number, resource in entries(values, 'desired.resource.'):
        kind, logical = resource['resourceType'], resource.get('logicalId')
        head = prefix(kind)
        if head in prefixes and prefixes[head] != kind:
            raise ValueError('ResourceType logicalId prefix collision: ' + head)
        prefixes[head] = kind
        serial = sequence(kind, logical)
        if logical in result:
            raise ValueError('duplicate logicalId: ' + logical)
        if state.get(kind, -1) < serial:
            raise ValueError('lastAllocated is missing or behind logicalId: ' + logical)
        result[logical] = (number, resource)
    return result


def allocate(values, resource_ids):
    """Prepare explicit additions in caller-selected order; publish the returned map once."""
    import json
    result, state = dict(values), counters(values)
    resources = dict(entries(values, 'desired.resource.'))
    selected = tuple(resource_ids)
    if len(selected) != len(set(selected)):
        raise ValueError('duplicate allocation selection')
    for number in selected:
        resource = resources[number]
        if resource.get('logicalId'):
            raise ValueError('cannot reallocate a saved logicalId: ' + number)
        kind = resource['resourceType']
        state[kind] = state.get(kind, 0) + 1
        result[f'desired.resource.{number}.logicalId'] = f'{prefix(kind)}_{state[kind]:03d}'
    result[COUNTERS] = json.dumps(state, sort_keys=True, separators=(',', ':'))
    resource_index(result)
    return result


def preserve_allocation(before, after):
    old, new = counters(before), counters(after)
    for kind, number in old.items():
        if new.get(kind, -1) < number:
            raise ValueError('lastAllocated cannot decrease or disappear: ' + kind)
    previous = dict(entries(before, 'desired.resource.'))
    current = dict(entries(after, 'desired.resource.'))
    resource_index(after)
    additions = {}
    for number, resource in current.items():
        if number in previous:
            if resource.get('logicalId') != previous[number].get('logicalId'):
                raise ValueError('saved logicalId cannot change: ' + number)
        else:
            kind = resource['resourceType']
            serial = sequence(kind, resource.get('logicalId'))
            if serial <= old.get(kind, 0):
                raise ValueError('logicalId sequence was already allocated: ' + resource['logicalId'])
            additions.setdefault(kind, []).append(serial)
    for kind in old.keys() | new.keys():
        expected = old.get(kind, 0) + len(additions.get(kind, ()))
        if new.get(kind, 0) != expected or sorted(additions.get(kind, ())) != list(range(old.get(kind, 0) + 1, expected + 1)):
            raise ValueError('allocation state does not match Resource additions: ' + kind)


def address(scope, logical):
    value = f'resource://{scope.environment}/{scope.target}/{scope.service}/{logical}'
    parse_reference(value)
    return value


def parse_reference(value):
    match = URI.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError('invalid internal Resource URI: ' + str(value))
    environment, target, service, logical = match.groups()
    if any(part in {'.', '..'} for part in (environment, target, service)):
        raise ValueError('invalid Resource URI scope')
    if not re.fullmatch(r'[A-Za-z0-9_]+_[A-Za-z0-9_]+_[0-9]{3,}', logical) or int(logical.rsplit('_', 1)[1]) < 1 or logical.rsplit('_', 1)[1] != f"{int(logical.rsplit('_', 1)[1]):03d}":
        raise ValueError('invalid Resource logicalId in URI: ' + logical)
    return environment, target, service, logical


def reference_tokens(text):
    """Reject malformed internal addresses instead of accepting a valid-looking prefix."""
    for token in re.finditer(r"resource://[^\s`\"'<>\[\](){} ,]+", text):
        parse_reference(token[0])
        yield token


def display_anchor(logical):
    return 'resource-' + logical


class Resolver:
    """One index per immutable service snapshot, shared by all references in a run."""
    def __init__(self, root, reads=None):
        from model.sources import FileReads
        self.root, self.reads, self.models, self.indexes = root, reads or FileReads(), {}, {}

    def resolve(self, value):
        from model.sources import Scope, _source_snapshot, target_for
        environment, target, service, logical = parse_reference(value)
        scope = Scope(self.root, environment, target, service)
        if scope.path not in self.models:
            target_for(scope, self.reads)
            from model.importing.scope import reference_reader
            if self.reads.kind(scope.path) == 'missing':
                self.reads.read(scope.path)
                raise ReferenceResolutionError('producer Model is absent', reference=value)
            with reference_reader(scope.path):
                snapshot = _source_snapshot(scope, self.reads)
            self.models[scope.path] = snapshot
            self.indexes[scope.path] = resource_index(snapshot.authoritative)
        match = self.indexes[scope.path].get(logical)
        if match is None:
            raise ReferenceResolutionError('Resource logicalId is absent', reference=value)
        return self.models[scope.path], *match
