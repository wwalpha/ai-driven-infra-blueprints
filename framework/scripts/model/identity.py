"""Fixed service-local Resource identities and internal, scope-checked addresses."""
import re
from model.core import LINK, entries, ReferenceResolutionError

COUNTERS = 'desired.service.identity.lastAllocated'



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


def address(scope, resource, *, consumer_scope=None, label=None):
    """Build only explicitly requested new links, using the saved Resource anchor."""
    import posixpath
    destination = '/'.join((scope.environment, scope.target, scope.service + '.md'))
    filename = scope.service + '.md'
    if consumer_scope is not None:
        filename = ('' if scope == consumer_scope else posixpath.relpath(
            destination, '/'.join((consumer_scope.environment, consumer_scope.target))))
    return f"[{label or resource['logicalId']}]({filename}#{resource['anchor']})"


def resource_link(value):
    match = LINK.fullmatch(value) if isinstance(value, str) else None
    if match and ':' not in match[2] and (not match[2] or match[2].endswith('.md')):
        return match
    return None


def parse_reference(value, scope):
    from model.references import link_scope
    match = resource_link(value)
    if not match:
        raise ValueError('invalid Markdown Resource reference: ' + str(value))
    producer = link_scope(scope.environment, scope.target, scope.service, match[2])
    return (*producer.split('/'), match[3])


def reference_tokens(text):
    from model.references import LINKS
    for match in LINKS.finditer(text):
        if resource_link(match[0]):
            yield match


def display_anchor(resource):
    anchor = resource.get('anchor')
    if not anchor:
        raise ReferenceResolutionError('Resource has no saved anchor')
    if not isinstance(anchor, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', anchor) is None:
        raise ValueError('invalid Resource anchor: ' + str(anchor))
    return anchor


def anchor_index(values):
    """Retain ambiguous anchors for semantic diagnostics, without guessing identities."""
    result = {}
    for number, resource in entries(values, 'desired.resource.'):
        anchor = resource.get('anchor')
        if anchor:
            result.setdefault(anchor, []).append((number, resource))
    return result


def select_anchor(index, anchor, reference):
    matches = index.get(anchor, ())
    if len(matches) != 1:
        raise ReferenceResolutionError('Resource anchor is absent or ambiguous', reference=reference)
    return matches[0]


class Resolver:
    """One anchor index per immutable service snapshot, shared across references."""
    def __init__(self, root, reads=None):
        from model.sources import FileReads
        self.root, self.reads, self.models, self.indexes = root, reads or FileReads(), {}, {}

    def resolve(self, value, scope):
        from model.sources import Scope, _source_snapshot, target_for
        environment, target, service, anchor = parse_reference(value, scope)
        producer = Scope(self.root, environment, target, service)
        if producer.path not in self.models:
            target_for(producer, self.reads)
            from model.importing.scope import reference_reader
            if self.reads.kind(producer.path) == 'missing':
                self.reads.read(producer.path)
                raise ReferenceResolutionError('producer Model is absent', reference=value)
            with reference_reader(producer.path):
                snapshot = _source_snapshot(producer, self.reads)
            resource_index(snapshot.authoritative)
            self.models[producer.path] = snapshot
            self.indexes[producer.path] = anchor_index(snapshot.authoritative)
        return self.models[producer.path], *select_anchor(self.indexes[producer.path], anchor, value)

    def operand(self, value, scope, *, attribute=None, field=None):
        """Validate a JSON reference without requiring its physical identifier."""
        from reference_contracts import ARN_FORMS, attributes_for, contract
        snapshot, number, resource = self.resolve(value, scope)
        kind = resource['resourceType']
        declared = contract(field) if field else {}
        if declared and kind not in declared:
            raise ReferenceResolutionError('JSON Resource reference type differs from receiving property', reference=value)
        if attribute is None:
            forms = declared.get(kind, ())
            if len(forms) != 1:
                raise ReferenceResolutionError('JSON Resource reference requires an explicit attribute', reference=value)
            attribute, = forms
        if not isinstance(attribute, str) or not attribute:
            raise ValueError('JSON Resource attribute must be a nonempty string')
        from utils.aws_catalogs import catalogs_for
        if (declared and attribute not in declared[kind] or
                (kind, attribute) not in ARN_FORMS and kind + '.' + attribute not in attributes_for(kind)
                and attribute not in catalogs_for(self.root).selected(kind)):
            raise ReferenceResolutionError('unsupported JSON Resource attribute: ' + kind + '.' + attribute, reference=value)
        return snapshot, number, resource, attribute
