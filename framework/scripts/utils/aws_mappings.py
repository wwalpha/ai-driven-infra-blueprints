"""Process-local static Mapping definitions, shared by exact source/stage roots."""
from utils.json_format import policy_json
from validation_cache import input_text
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
import re
from threading import Lock
from types import MappingProxyType


_lock = Lock()
_instances = {}
_aliases = {}


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
            raise
        else:
            future.set_result(result)
    return future.result()


class Mappings:
    def __init__(self, root):
        self._root = Path(root)
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
        def load():
            import aws_mapping
            document = aws_mapping.yaml_read(input_text(aws_mapping.mapping_path(self._root, service), encoding='utf-8'))
            expected = {kind for kind, owner in self._owners.items() if owner == service}
            if (not isinstance(document, dict) or document.get('service') != service
                    or not isinstance(document.get('resourceTypes'), dict)
                    or document['resourceTypes'].keys() != expected):
                raise ValueError('Mapping ownership index mismatch: ' + service)
            return document
        return _once(self._documents, service, load)

    def get(self, service):
        self._require_service(service)
        def build():
            from aws_mapping import Registry
            from aws_mapping_catalog import runtime_properties
            document = self._document(service)
            return Registry(self._root, service, document, runtime_properties(self._root, service, document))
        return _once(self._runtime, service, build)

    def validated(self, service, sdk, schemas, catalogs, validator):
        """A provider lifetime fixes Mapping/adapter code; dependencies fix definitions.

        Definition, validation or adapter edits require a new provider/dependency set
        (or a new process), never extending input/diagnostic cache lifetimes.
        """
        self._require_service(service)
        def build():
            from aws_mapping import Registry
            document = self._document(service)
            properties = validator(self._root, service, document, sdk=sdk, schemas=schemas, catalogs=catalogs)
            return Registry(self._root, service, document, properties)
        return _once(self._validated, (service, sdk, schemas, catalogs, validator), build)


def definition_root(root):
    """Resolve an explicitly aliased stage to its surviving source, without loading it."""
    root = Path(root).absolute()
    with _lock:
        provider = _aliases.get(root)
        return provider._root if provider is not None else root


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
