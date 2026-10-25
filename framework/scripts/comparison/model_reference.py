"""Select saved literal declarations from the authoritative snapshot, once per service."""
from design.policy_tables import literal
from model.identity import Resolver
from model.reference_nodes import (
    is_reference,
    nodes,
    parse,
    receiving_property,
    resolve,
)
from model.references import declarations, usages
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression, ResourceReference
from utils.reference_contracts import reference_attribute, reference_context

from . import registry


class ModelReferences:
    def __init__(self, inputs, service):
        snapshot = inputs.model(service)
        specs = declarations(snapshot.authoritative)
        self.positions = {}
        self.scope = snapshot.scope
        if not hasattr(inputs, 'model_reference_resolver'):
            inputs.model_reference_resolver = Resolver(inputs.root, inputs.model_reads)
        self.resolver = inputs.model_reference_resolver
        self.resolver.models.update({item.scope.path: item for item in inputs.models.values()})
        if not specs:
            return
        cache = {model.scope.path: model for model in inputs.models.values()}
        for spec in specs.values():
            if spec['producerKind'] != 'resource':
                continue
            environment, target, producer = spec['producerScope'].split('/')
            path = inputs.root / 'model' / environment / target / (producer + '.properties')
            if path in cache:
                continue
            if (environment, target) != (inputs.environment, inputs.directory):
                cache[path] = None
            else:
                try:
                    cache[path] = inputs.model(producer)
                except FileNotFoundError:
                    cache[path] = None
        try:
            for usage in usages(snapshot, inputs.model_reads, _cache=cache, _typed=False):
                spec = specs.get(usage.metadata_id)
                if (not spec or spec['producerKind'] != 'resource'
                        or spec['format'] == 'link' and 'valueSelector' not in spec):
                    continue
                self.positions.setdefault(usage.consumer_key, {}).setdefault(usage.pointer, []).append((usage, spec))
        finally:
            inputs.retain_reads()

    def normalize(self, inputs, key, value, pointer=None, context=None):
        if is_reference(value):
            try:
                node = parse(value, pointer or '')
                row = key.rsplit('.', 1)[0]
                prop = inputs.model(self.scope.service).authoritative[row + '.property']
                kind = '.'.join(prop.split('.')[:2])
                field = receiving_property(prop, pointer or '')
                path = field.removeprefix(kind + '.')
                producer, number, resource, attribute = resolve(node, self.scope, self.resolver,
                    field=field, property_name=prop, context=context)
                service = producer.scope.service
                inputs.model(service)
                symbol = ResourceReference({'$resource': [service, number],
                    '$attribute': reference_attribute(resource['resourceType'], attribute)})
                if any(token.startswith('Fn::') for token in (pointer or '').split('/')):
                    return inputs.reference(self.scope.service, symbol, consumer_property=field)
                return inputs.desired_reference(self.scope.service, symbol, kind, path, symbol['$attribute'], context)
            except (Blocked, KeyError, OSError, ValueError, TypeError) as error:
                return Expression('Unverified', [value, f'JSON Pointer={pointer or ""!r}; {key}: {error}'])
            finally:
                inputs.retain_reads()
        if isinstance(value, ResourceReference):
            return value
        if isinstance(value, dict):
            prop = inputs.model(self.scope.service).authoritative.get(key.rsplit('.', 1)[0] + '.property', '')
            context = reference_context(receiving_property(prop, pointer or ''), value, context)
            return {name: self.normalize(inputs, key, child, (pointer or '') + '/' + name.replace('~', '~0').replace('/', '~1'), context)
                    for name, child in value.items()}
        if isinstance(value, list):
            return [self.normalize(inputs, key, child, (pointer or '') + '/' + str(index), context) for index, child in enumerate(value)]
        if isinstance(value, str) and any(nodes(value)):
            return Expression('Unverified', [value, 'encoded JSON reference needs proven expression evaluation'])
        records = self.positions.get(key, {}).get(pointer, ())
        if not records:
            return value
        if not isinstance(value, str):
            raise Blocked('attribute_format_unproven: declaration requires a string leaf')
        ranges = []
        for usage, spec in records:
            # Scalar Usage offsets include saved backticks; JSON leaf offsets do not.
            start, stop, text = usage.start, usage.end, usage.text
            if pointer is None:
                raw = inputs.model(self.scope.service).authoritative[key]
                if raw != value and literal(raw) == value:
                    if (start, stop) == (0, len(raw)):
                        start, stop, text = 0, len(value), value
                    else:
                        start, stop = start - 1, stop - 1
            if start < 0 or stop > len(value) or value[start:stop] != text:
                raise Blocked('attribute_format_unproven: normalized reference occurrence differs')
            ranges.append((start, stop, text, usage, spec))
        parts, end = [], 0
        for start, stop, text, usage, spec in sorted(ranges, key=lambda item: item[:2]):
            if start < end:
                raise Blocked('producer_ambiguous: overlapping reference declarations')
            if start > end:
                parts.append(value[end:start])
            parts.append(self.fragment(inputs, key, value, usage, spec, text))
            end = stop
        if end < len(value):
            parts.append(value[end:])
        return parts[0] if len(parts) == 1 else Expression('Join', ['', parts])

    def fragment(self, inputs, key, value, usage, spec, text):
        if spec['producerScope'].split('/')[:2] != [inputs.environment, inputs.directory]:
            raise Blocked('producer_not_found: cross-target reference')
        service = spec['producerScope'].split('/')[2]
        if usage.producer_id is None:
            raise Blocked('producer_not_found: producerLogicalId does not identify one Resource')
        inputs.model(service)
        resource = inputs.resources[service].get(usage.producer_id)
        if not resource or resource['resourceType'] != spec['resourceType']:
            raise Blocked('attribute_format_unproven: producer Resource Type differs')
        if 'valueSelector' in spec:
            prop = inputs.model(self.scope.service).authoritative[key.rsplit('.', 1)[0] + '.property']
            project = registry.hook('.'.join(prop.split('.')[:2]), 'selected_reference')
            if project is None:
                raise Blocked('reference valueSelector has no receiving property contract')
            return project(inputs, self.scope.service, key, value, spec, usage.producer_id)
        prefix = resource['resourceType'] + '.'
        if not spec['property'].startswith(prefix):
            raise Blocked('attribute_format_unproven: producer Property differs')
        attribute = spec['property'][len(prefix):]
        symbol = ResourceReference({'$resource': [service, usage.producer_id],
                                    '$attribute': reference_attribute(resource['resourceType'], attribute)})
        symbol.saved_property = spec['property']
        symbol.saved_literal = text
        symbol.declared_format = spec['format']
        return symbol
