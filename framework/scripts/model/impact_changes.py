"""Semantic Model changes keyed by saved logicalId, never by internal numbering."""
import json
from model.core import entries
from model.format import owner
from model.identity import COUNTERS, counters, sequence, reference_tokens
from model.references import _json


def node(scope, kind='service', identity=''):
    return (*scope, kind, identity)


def canonical(value):
    """Keep JSON types/order, but ignore a saved Resource link's display label."""
    if isinstance(value, dict):
        return {key: canonical(child) for key, child in value.items()}
    if isinstance(value, list):
        return [canonical(child) for child in value]
    if isinstance(value, str):
        for match in reversed(tuple(reference_tokens(value))):
            value = value[:match.start()] + '[](' + match[2] + '#' + match[3] + ')' + value[match.end():]
    return value


def frozen(value):
    return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def configurations(model):
    # The operation comparator owns field extraction; only its internal IDs are normalized here.
    from model.operations import ConfigurationIndex, resource_configuration
    values = model.authoritative
    index = ConfigurationIndex(values)
    resources = {}
    for number, resource in entries(values, 'desired.resource.'):
        logical = resource.get('logicalId')
        if not logical or logical in resources:
            raise ValueError('Resource logicalId absent or ambiguous')
        config = resource_configuration(values, number, index=index)
        row_keys = {f'desired.row.{rid}.' + field: (row['property'], field)
                    for rid, row in index.resource_rows(number) for field in ('value', 'document')}
        def consumer_key(key):
            if key in row_keys:
                return row_keys[key]
            prefix = f'desired.resource.{number}.'
            if key.startswith(prefix):
                return 'resource', key.removeprefix(prefix)
            return key
        refs = [{field: consumer_key(value) if field == 'consumerKey' else value
                 for field, value in spec.items()} for spec in index.resource_references(number).values()]
        observed = [(values.get(key.replace('observed.', 'desired.').removesuffix('value') + 'property'),
                     _json(key, value)[0]) for key, value in index.resource_observed(number).items()]
        resources[logical] = frozen({'resource': config['resource'],
            'rows': sorted((frozen([prop, value]) for _, prop, value in config['rows'])),
            'references': sorted(map(frozen, refs)), 'observed': sorted(map(frozen, observed))})
    from model.references import declarations
    specs = declarations(values)
    stack_refs = {}
    for spec in specs.values():
        kind, identity = owner(spec['consumerKey'], values)
        if kind == 'stack':
            stack_refs.setdefault(identity, []).append(frozen(spec))
    stacks = {identity: frozen([fields, sorted(stack_refs.get(identity, ()))])
              for identity, fields in entries(values, 'desired.stack.')}
    common = {}
    for key, value in values.items():
        if not key.startswith('desired.') or key == COUNTERS or key.startswith(('desired.note.', 'desired.reference.')) or key.endswith('.comment'):
            continue
        kind, identity = owner(key, values)
        if kind not in {'resource', 'stack'}:
            common[key] = _json(key, value)[0]
    common['references'] = sorted(frozen(spec) for spec in specs.values()
        if owner(spec['consumerKey'], values)[0] not in {'resource', 'stack'})
    return resources, stacks, frozen(common)


def allocation_only(old, new):
    """A counter advance is local only when explained by actual new fixed identities."""
    previous, current = counters(old), counters(new)
    expected = dict(previous)
    old_ids = {resource.get('logicalId') for _, resource in entries(old, 'desired.resource.')}
    for _, resource in entries(new, 'desired.resource.'):
        if resource.get('logicalId') not in old_ids:
            kind = resource['resourceType']
            expected[kind] = max(expected.get(kind, 0), sequence(kind, resource['logicalId']))
    return current == expected


def changed_nodes(scopes, before, after, reasons):
    seeds = set()
    for scope in scopes:
        old, new = before.get(scope), after.get(scope)
        try:
            if isinstance(old, Exception) or isinstance(new, Exception):
                raise ValueError('Model snapshot could not be parsed')
            old_config = configurations(old) if old is not None else ({}, {}, frozen({'references': []}))
            new_config = configurations(new) if new is not None else ({}, {}, frozen({'references': []}))
            for kind, previous, current in zip(('resource', 'stack'), old_config[:2], new_config[:2]):
                seeds.update(node(scope, kind, identity) for identity in previous.keys() | current.keys()
                             if previous.get(identity) != current.get(identity))
            if old_config[2] != new_config[2]:
                seeds.add(node(scope))
            if old is not None and new is not None and not allocation_only(old.authoritative, new.authoritative):
                seeds.add(node(scope))
                reasons.append({'scope': '/'.join(scope), 'reason': 'unexplained allocation change'})
        except (OSError, ValueError, KeyError, TypeError) as error:
            seeds.add(node(scope))
            reasons.append({'scope': '/'.join(scope), 'reason': 'uncomparable Model: ' + str(error)})
    return seeds
