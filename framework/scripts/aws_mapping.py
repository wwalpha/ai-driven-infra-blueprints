"""Catalog-keyed AWS Mapping Registry shared by validation and AWS Compare."""
from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType

from model_parameter_inputs import yaml_read
from validation_cache import memoized


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


class Registry:
    def __init__(self, root: Path, service: str, compile_properties=None):
        self.root, self.service = Path(root), text(service, 'service')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', service):
            raise ValueError('invalid Mapping service')
        path = self.root / 'framework/mappings/aws' / (service + '.yaml')
        document = yaml_read(path.read_text(encoding='utf-8'))
        from aws_mapping_catalog import catalog_properties
        result = (compile_properties or catalog_properties)(self.root, service, document)
        self.resource_types = frozenset(document['resourceTypes'])
        self.adapter_resource_types = frozenset(resource for definition in document['getters'].values()
                                                if definition['kind'] == 'adapter' for resource in definition['resources'])
        self.getters = MappingProxyType({name: MappingProxyType({key: tuple(value) if isinstance(value, list) else value
                                                               for key, value in definition.items()})
                                         for name, definition in document['getters'].items()})
        self.identities = MappingProxyType({resource: Identity(value['identity']['getter'], value['identity']['idPath'],
                                                               value['identity']['arnPath'], value['identity']['nameProperty'])
                                            for resource, value in document['resourceTypes'].items() if 'identity' in value})
        self.properties = MappingProxyType(result)
        self.fields = MappingProxyType({key: prop.field for key, prop in result.items() if prop.include})


@memoized
def registry(root: Path, service: str) -> Registry:
    """Reuse YAML/SDK validation within the existing validation_cache.input_scope."""
    return Registry(root, service)


@memoized
def runtime_registry(root: Path, service: str) -> Registry:
    from aws_mapping_catalog import runtime_properties
    return Registry(root, service, runtime_properties)
