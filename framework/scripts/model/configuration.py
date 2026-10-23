"""Read-only Resource configuration indexes, independent of publication and rendering."""
from types import SimpleNamespace

from utils.aws_catalogs import catalog_outputs
from utils.aws_schemas import schemas_for

import model.core as _imports_model_core
import model.references as _dependency_model_references
import model.sources as _imports_model_sources
from model.format import owner
from model.references import declarations


def _field_value(key, value):
    return _dependency_model_references._json(key, value)[0]


def foreign_observation(snapshot, row, *, outputs=catalog_outputs):
    """Prove a Row observes only foreign Resources and is not a native physical ID."""

    entries = _imports_model_core.entries
    usages = _dependency_model_references.usages
    resource_id = row.rpartition('-')[0]
    resource = dict(entries(snapshot.authoritative, 'desired.resource.'))[resource_id]
    key = f'desired.row.{row}.value'
    own_scope = '/'.join((snapshot.scope.environment, snapshot.scope.target, snapshot.scope.service))
    uses = [use for use in usages(snapshot, _coalesce=False) if use.consumer_key == key]
    if not uses or any(use.producer_kind != 'resource' or use.producer_scope == own_scope and
                       use.producer_id == resource_id for use in uses):
        return False

    kind = resource['resourceType']
    try:
        schema = schemas_for(snapshot.scope.root).cloudformation('AWS::' + kind.replace('.', '::', 1))
    except KeyError:
        raise ValueError('IMPORT physical identity cannot be proven without its schema: ' + kind) from None
    identities = outputs(snapshot.scope.root, kind) | {
        kind + '.' + pointer.removeprefix('/properties/').replace('/', '.')
        for pointer in schema.get('primaryIdentifier', ())}
    return bool(schema.get('primaryIdentifier')) and snapshot.authoritative[f'desired.row.{row}.property'] not in identities

def _observed_index(values):
    result = {}
    for key, value in values.items():
        if key.startswith('observed.row.'):
            identity = key.removeprefix('observed.row.')
            for offset, char in enumerate(identity):
                if char == '-':
                    result.setdefault(identity[:offset], {})[key] = value
    return result

class ConfigurationIndex:
    """Lazy indexes owned by one comparison; retain the source authority itself."""
    def __init__(self, values):
        self.values = values
        self.resources = {}
        for key, value in values.items():
            if key.startswith('desired.resource.'):
                number, _, field = key.removeprefix('desired.resource.').partition('.')
                self.resources.setdefault(number, {})[field] = value
        self.rows = self.references = self.observed = None

    def resource_rows(self, number):
        if self.rows is None:
            resource_row_index = _imports_model_core.resource_row_index
            self.rows = resource_row_index(self.values)
        return self.rows[number]

    def resource_references(self, number):
        if self.references is None:
            references = {}
            for identity, spec in declarations(self.values).items():
                kind, rid = owner(spec['consumerKey'], self.values)
                if kind == 'resource':
                    references.setdefault(rid, {})[identity] = spec
            self.references = references
        return self.references.get(number, {})

    def resource_observed(self, number):
        if self.observed is None:
            self.observed = _observed_index(self.values)
        return self.observed.get(number, {})

def _recursive_resource_configuration_native(value):
    if isinstance(value, dict):
        return {'object': {key: _recursive_resource_configuration_native(child) for key, child in value.items()}}
    if isinstance(value, list):
        return {'array': [_recursive_resource_configuration_native(child) for child in value]}
    if not isinstance(value, str):
        return {type(value).__name__: value}
    return {'string': value}

def resource_configuration(values, number, path=None, expansion=None, *, index=None):
    """Compare configuration/native values and fixed reference meaning, excluding display labels."""
    native = _recursive_resource_configuration_native
    index = index if index is not None else ConfigurationIndex(values)
    resource = {key: native(value) for key, value in index.resources.get(number, {}).items()}
    rows = []
    for row_id, row in index.resource_rows(number):
        key = f'desired.row.{row_id}.' + ('document' if 'document' in row else 'value')
        rows.append([row_id, row['property'], native(_field_value(key, values[key]))])
    references = {}
    for identity, spec in index.resource_references(number).items():
        consumer = spec['consumerKey']
        if owner(consumer, values) != ('resource', number) or not (consumer.startswith('desired.resource.') or
                consumer.startswith('desired.row.') and consumer.endswith(('.value', '.document'))):
            continue
        references[identity] = {field: native(value) if field == 'text' and spec['format'] == 'link' else value
                                for field, value in spec.items()}
    observed = index.resource_observed(number)
    if observed and path is not None and values.get(f'desired.resource.{number}.resourceMode') == 'IMPORT':

        scope_for = _imports_model_sources.scope_for
        snapshot = SimpleNamespace(scope=scope_for(path), authoritative=values)
        observed = {key: value for key, value in observed.items() if not foreign_observation(
            snapshot, key.removeprefix('observed.row.').removesuffix('.value'))}
    return {'resource': resource, 'rows': rows, 'references': references,
            'observed': observed if values.get(f'desired.resource.{number}.resourceMode', 'CREATE') == 'IMPORT' else {}}
