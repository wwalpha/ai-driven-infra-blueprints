"""Select saved literal declarations from the authoritative snapshot, once per service."""
from cloudformation_inputs import Blocked
from iac_evaluation import RETURN_ATTRIBUTE_PROPERTIES
from iac_values import ResourceReference
from model.references import declarations, usages
from policy_tables import literal


class ModelReferences:
    def __init__(self, inputs, service):
        snapshot = inputs.model(service)
        specs = declarations(snapshot.authoritative)
        self.positions = {}
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
            for usage in usages(snapshot, inputs.model_reads, _cache=cache):
                spec = specs.get(usage.metadata_id)
                if not spec or spec['producerKind'] != 'resource' or spec['format'] == 'link':
                    continue
                self.positions.setdefault(usage.consumer_key, {}).setdefault(usage.pointer, []).append((usage, spec))
        finally:
            inputs.retain_reads()

    def normalize(self, inputs, key, value, pointer=None):
        if key not in self.positions:
            return value
        if isinstance(value, ResourceReference):
            return value
        if isinstance(value, dict):
            return {name: self.normalize(inputs, key, child, (pointer or '') + '/' + name.replace('~', '~0').replace('/', '~1'))
                    for name, child in value.items()}
        if isinstance(value, list):
            return [self.normalize(inputs, key, child, (pointer or '') + '/' + str(index)) for index, child in enumerate(value)]
        records = self.positions[key].get(pointer, ())
        if not records:
            return value
        if len(records) != 1:
            raise Blocked('producer_ambiguous: overlapping reference declarations')
        usage, spec = records[0]
        if not isinstance(value, str) or literal(usage.text) != value:
            raise Blocked('attribute_format_unproven: declaration must cover the complete scalar')
        if spec['producerScope'].split('/')[:2] != [inputs.environment, inputs.directory]:
            raise Blocked('producer_not_found: cross-target reference')
        service = spec['producerScope'].split('/')[2]
        if usage.producer_id is None:
            raise Blocked('producer_not_found: producerLogicalId does not identify one Resource')
        inputs.model(service)
        resource = inputs.resources[service].get(usage.producer_id)
        if not resource or resource['resourceType'] != spec['resourceType']:
            raise Blocked('attribute_format_unproven: producer Resource Type differs')
        prefix = resource['resourceType'] + '.'
        if not spec['property'].startswith(prefix):
            raise Blocked('attribute_format_unproven: producer Property differs')
        attribute = spec['property'][len(prefix):]
        mapped = [returned for (kind, returned), setting in RETURN_ATTRIBUTE_PROPERTIES.items()
                  if kind == resource['resourceType'] and setting == attribute]
        if len(mapped) > 1:
            raise Blocked('attribute_format_unproven: ambiguous returned attribute')
        symbol = ResourceReference({'$resource': [service, usage.producer_id], '$attribute': mapped[0] if mapped else attribute})
        symbol.saved_property = spec['property']
        symbol.saved_literal = value
        symbol.declared_format = spec['format']
        return symbol
