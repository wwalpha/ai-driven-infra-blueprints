"""Build one union of old/new saved reference edges and traverse Resource/Stack nodes."""
from collections import defaultdict
from pathlib import Path
from model.core import entries
from model.format import owner
from model.identity import resource_index
from model.references import usages, declarations
from model.sources import FileReads, list_models, raw_model, load_model
from model.impact_changes import node


def models(root, reads, *, previous=False, raw=False, allowed=None):
    result = {}
    try:
        scopes = list_models(root, reads)
    except (OSError, ValueError):
        if not previous:
            raise
        # Discovery must still retain each identifiable old service when topology is broken.
        from model.sources import scope_for
        scopes = [scope_for(path) for path in reads.select(Path(root) / 'model', '*/*/*.properties')]
    for scope in scopes:
        identity = scope.environment, scope.target, scope.service
        if allowed is not None and identity not in allowed:
            continue
        try:
            result[identity] = (raw_model if previous or raw else load_model)(scope, reads)
        except (OSError, ValueError) as error:
            if not previous:
                raise
            result[identity] = error
    return result


def owned(scope, key, values):
    kind, identity = owner(key, values)
    if kind == 'resource':
        logical = values.get(f'desired.resource.{identity}.logicalId')
        if not logical:
            raise ValueError('consumer Resource logicalId is absent')
        return node(scope, kind, logical)
    return node(scope, kind, identity) if kind == 'stack' else node(scope)


class Graph:
    def __init__(self):
        self.edges = defaultdict(set)
        self.members = defaultdict(set)
        self.reasons = []

    def add(self, producer, consumer):
        self.edges[producer].add(consumer)
        for entry in (producer, consumer):
            self.members[entry[:3]].add(entry)

    def include(self, records, reads):
        cache = {}
        for scope, model in records.items():
            if isinstance(model, Exception):
                continue
            try:
                resource_index(model.authoritative)
                cache[model.scope.path] = model
                for _, resource in entries(model.authoritative, 'desired.resource.'):
                    self.members[scope].add(node(scope, 'resource', resource['logicalId']))
                self.members[scope].update(node(scope, 'stack', identity) for identity, _ in entries(model.authoritative, 'desired.stack.'))
            except (ValueError, KeyError, TypeError):
                # usages() retains declared logical IDs and unresolved direct links with an absent producer.
                cache[model.scope.path] = None
        all_scopes = set(records)
        for scope, model in records.items():
            try:
                if isinstance(model, Exception):
                    raise model
                for usage in usages(model, reads, _cache=cache):
                    if usage.producer_kind == 'context':
                        continue  # project.json changes keep the existing conservative context behavior.
                    producer_scope = tuple(usage.producer_scope.split('/'))
                    consumer = owned(scope, usage.consumer_key, model.authoritative)
                    identity = usage.logical_id if usage.producer_kind == 'resource' else usage.producer_id
                    producer = node(producer_scope, usage.producer_kind, identity) if identity else node(producer_scope)
                    producer_model = records.get(producer_scope)
                    missing_stack = usage.producer_kind == 'stack' and (producer_model is None or
                        isinstance(producer_model, Exception) or
                        f'desired.stack.{identity}.name' not in producer_model.authoritative)
                    if usage.producer_id is None or missing_stack:
                        self.reasons.append({'scope': usage.producer_scope, 'reason': 'unresolved producer',
                                             'consumer': '/'.join(scope), 'key': usage.consumer_key})
                        self.add(node(producer_scope), consumer)
                    self.add(producer, consumer)
            except (OSError, ValueError, KeyError, TypeError) as error:
                try:
                    producers = {tuple(spec['producerScope'].split('/')) for spec in declarations(model.authoritative).values()
                                 if spec['producerKind'] != 'context'}
                except (AttributeError, ValueError, KeyError, TypeError):
                    producers = set()
                # An unparseable consumer may hide direct links; retain only that consumer's uncertainty.
                for producer_scope in all_scopes | producers:
                    self.add(node(producer_scope), node(scope))
                self.reasons.append({'scope': '/'.join(scope), 'reason': 'unreadable reference graph: ' + str(error)})

    def traverse(self, seeds):
        visited, pending = set(), set(seeds)
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            scope = current[:3]
            incoming = self.edges[current] | self.edges[node(scope)]
            if current[3] == 'service':
                incoming = incoming | self.members[scope]
            pending.update(incoming - visited)
        return visited
