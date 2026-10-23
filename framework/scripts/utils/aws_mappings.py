"""Process-local static Mapping definitions, shared by exact source/stage roots."""

import re
from copy import deepcopy
from concurrent.futures import Future
from contextlib import contextmanager
from functools import partial as _bind_framework_callback
from pathlib import Path
from threading import Lock
from types import MappingProxyType

import utils.mapping_runtime as _imports_aws_mapping_catalog
import utils.mapping_types as _imports_aws_mapping
from utils.input_cache import input_text
from utils.json_format import policy_json

_lock = Lock()
_instances = {}
_aliases = {}
_documents = {}


def _once(table, key, load):
    with _lock:
        if table is _instances and key in _aliases:
            return _aliases[key]
        future = table.get(key)
        first = future is None
        if first:
            future = table[key] = Future()
    if first:
        try:
            result = load()
        except BaseException as error:
            # Complete waiters even for cancellation/interrupt, then propagate it.
            future.set_exception(error)
            if table is _documents:
                with _lock:
                    if table.get(key) is future:
                        del table[key]
            raise
        else:
            future.set_result(result)
    return future.result()


def _callback_Mappings__document_load(self, service, /):
    aws_mapping = _imports_aws_mapping
    path = aws_mapping.mapping_path(self._root, service)
    content = input_text(path, encoding='utf-8')
    # Only successful parsing is shared; each provider owns its mutable document.
    document = deepcopy(_once(_documents, (path, content, aws_mapping.yaml_read),
                              lambda: aws_mapping.yaml_read(content)))
    expected = {kind for kind, owner in self._owners.items() if owner == service}
    if (not isinstance(document, dict) or document.get('service') != service
            or not isinstance(document.get('resourceTypes'), dict)
            or document['resourceTypes'].keys() != expected):
        raise ValueError('Mapping ownership index mismatch: ' + service)
    return document


def _callback_Mappings_get_build(self, service, /):
    Registry = _imports_aws_mapping.Registry
    runtime_properties = _imports_aws_mapping_catalog.runtime_properties
    document = self._document(service)
    return Registry(self._root, service, document, runtime_properties(self._root, service, document))


def _callback_Mappings_validated_build(catalogs, schemas, sdk, self, service, validator, /):
    Registry = _imports_aws_mapping.Registry
    document = self._document(service)
    properties = validator(self._root, service, document, sdk=sdk, schemas=schemas, catalogs=catalogs)
    return Registry(self._root, service, document, properties)


class Mappings:
    def __init__(self, root):
        self._root = definition_root(root)
        index = policy_json(input_text(self._root / 'framework/mappings/aws/owners.json', encoding='utf-8'))
        if not isinstance(index, dict) or not index or any(
                not re.fullmatch(r'[A-Za-z0-9]+\.[A-Za-z0-9]+', kind)
                or not isinstance(service, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', service)
                for kind, service in index.items()):
            raise ValueError('invalid Mapping ownership index')
        self._owners = MappingProxyType(index)
        self._services = frozenset(index.values())
        self._documents = {}
        self._runtime = {}
        self._validated = {}

    def _require_service(self, service):
        if not isinstance(service, str) or service not in self._services:
            raise ValueError('unknown Mapping service: ' + str(service))

    def _document(self, service):
        self._require_service(service)
        load = _bind_framework_callback(_callback_Mappings__document_load, self, service)
        return _once(self._documents, service, load)

    def get(self, service):
        self._require_service(service)
        build = _bind_framework_callback(_callback_Mappings_get_build, self, service)
        return _once(self._runtime, service, build)

    def validated(self, service, sdk, schemas, catalogs, validator):
        """A provider lifetime fixes Mapping/adapter code; dependencies fix definitions.

        Definition, validation or adapter edits require a new provider/dependency set
        (or a new process), never extending input/diagnostic cache lifetimes.
        """
        self._require_service(service)
        build = _bind_framework_callback(_callback_Mappings_validated_build, catalogs, schemas, sdk, self, service, validator)
        return _once(self._validated, (service, sdk, schemas, catalogs, validator), build)


def definition_root(root):
    """Resolve shared definitions independently of the mutable Project workspace."""
    root = Path(root).absolute()
    with _lock:
        provider = _aliases.get(root)
        if provider is not None:
            return provider._root
        return root if (root / "framework").is_dir() else Path(__file__).resolve().parents[3]


def mappings_for(root):
    root = Path(root).absolute()
    return _once(_instances, root, lambda: Mappings(root))


def owners(root):
    return mappings_for(root)._owners


@contextmanager
def mapping_alias(source, stage):
    """Share only this sync's temporary definition root, until all workers finish."""
    provider = mappings_for(source)
    stage = Path(stage).absolute()
    with _lock:
        if stage in _aliases or stage in _instances:
            raise ValueError('Mapping stage already has a provider: ' + str(stage))
        _aliases[stage] = provider
    try:
        yield
    finally:
        with _lock:
            del _aliases[stage]
