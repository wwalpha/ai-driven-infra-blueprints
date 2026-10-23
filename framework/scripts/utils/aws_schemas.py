"""Lazy CFn/API JSON definitions, shared read-only by contract per source root."""

import json
from collections.abc import Mapping
from copy import deepcopy
from threading import Lock

import utils.aws_mappings as _imports_utils_aws_mappings
from utils.input_cache import input_select, input_text
from utils.lazy_definitions import load_once

_lock = Lock()
_instances = {}


class Schemas:
    def __init__(self, root):
        definition_root = _imports_utils_aws_mappings.definition_root
        self.root = definition_root(root)
        self.directory = self.root / 'framework/materials/cloudformation-schema/ap-northeast-1'
        self._lock = Lock()
        self._cache = {}

    @property
    def resource_types(self):
        return load_once(self._lock, self._cache, ('index',), lambda: json.loads(
            input_text(self.directory / 'index.json', encoding='utf-8'))['resourceTypes'])

    @property
    def api_paths(self):
        return load_once(self._lock, self._cache, ('api-index',), lambda: {
            path.stem.replace('_', '.', 1): path
            for path in input_select(self.root / 'framework/materials/api', '*.json')})

    def cloudformation(self, resource_type):
        return load_once(self._lock, self._cache, ('cfn', resource_type), lambda: json.loads(
            input_text(self.directory / self.resource_types[resource_type], encoding='utf-8')))

    def api(self, resource_type):
        return load_once(self._lock, self._cache, ('api', resource_type), lambda: json.loads(
            input_text(self.api_paths[resource_type], encoding='utf-8')))


class ApiSchemas(Mapping):
    """Compatibility view: membership/iteration never parse schema bodies."""
    def __init__(self, definitions):
        self.definitions = definitions
        self._values = {}
        self._lock = Lock()

    def __iter__(self):
        return iter(self.definitions.api_paths)

    def __len__(self):
        return len(self.definitions.api_paths)

    def __contains__(self, key):
        return key in self.definitions.api_paths

    def __getitem__(self, key):
        return load_once(self._lock, self._values, key,
                         lambda: deepcopy(self.definitions.api(key)))


def schemas_for(root):
    definition_root = _imports_utils_aws_mappings.definition_root
    root = definition_root(root)
    return load_once(_lock, _instances, root, lambda: Schemas(root))
