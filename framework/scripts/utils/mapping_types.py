"""Immutable Mapping data and lexical SDK paths without registry initialization."""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

from utils.yaml_format import yaml_read as yaml_read

NORMALIZATIONS = frozenset({'typed', 'set', 'name', 'id', 'arn', 'policy', 'kms', 'iam_role',
                            'dns', 'log_group_arn', 'boolean', 'number', 'string', 'protocol', 'json'})


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or re.search(
            r'\b(?:TODO|unimplemented)\b', value, re.I):
        raise ValueError(f'{label}: concrete nonempty text required')
    return value


def response_shape(shape, path):
    """Validate exact SDK casing and explicit [] traversal, without AWS access."""
    for part in text(path, 'AWS path').split('.'):
        array = part.endswith('[]')
        name = part[:-2] if array else part
        if shape.type_name != 'structure' or name not in shape.members:
            raise ValueError(f'unknown SDK response path: {path}')
        shape = shape.members[name]
        if array:
            if shape.type_name != 'list':
                raise ValueError(f'SDK path is not an array: {path}')
            shape = shape.member
    return shape


@dataclass(frozen=True)
class Identity:
    getter: str
    id_path: str
    arn_path: str | None
    name_property: str | None


@dataclass(frozen=True)
class Property:
    field: object
    include: bool
    show: bool
    name: str
    source: str
    constraint: str = ''
    transform: str = 'identity'


def readonly(value):
    if isinstance(value, dict):
        return MappingProxyType({key: readonly(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(readonly(item) for item in value)
    return value


@dataclass(frozen=True, init=False)
class Registry:
    root: Path
    service: str
    resource_types: frozenset
    adapter_resource_types: frozenset
    getters: object
    identities: object
    properties: object
    fields: object

    def __init__(self, root, service, document, properties):
        result = {key: replace(prop, field=replace(prop.field, default=readonly(prop.field.default)))
                  for key, prop in properties.items()}
        values = {
            'root': Path(root), 'service': service,
            'resource_types': frozenset(document['resourceTypes']),
            'adapter_resource_types': frozenset(resource for definition in document['getters'].values()
                                                if definition['kind'] == 'adapter' for resource in definition['resources']),
            'getters': readonly(document['getters']),
            'identities': MappingProxyType({resource: Identity(value['identity']['getter'], value['identity']['idPath'],
                                                              value['identity']['arnPath'], value['identity']['nameProperty'])
                                           for resource, value in document['resourceTypes'].items() if 'identity' in value}),
            'properties': MappingProxyType(result),
            'fields': MappingProxyType({key: prop.field for key, prop in result.items() if prop.include}),
        }
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def at_root(self, root):
        """Bind caller context without copying or revalidating static definitions."""
        result = object.__new__(Registry)
        for key, value in vars(self).items():
            object.__setattr__(result, key, Path(root) if key == 'root' else value)
        return result


def mapping_path(root, service):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', text(service, 'service')):
        raise ValueError('invalid Mapping service')
    return Path(root) / 'framework/mappings/aws' / (service + '.yaml')
