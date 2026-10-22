"""Lazy selection lists and derived indexes; definitions are read-only by contract."""
from validation_cache import input_select, input_text
from pathlib import Path
from threading import Lock
from types import MappingProxyType

from utils.lazy_definitions import load_once

_lock = Lock()
_instances = {}


class Catalogs:
    def __init__(self, root):
        from utils.aws_mappings import definition_root
        self.root = definition_root(root)
        self._lock = Lock()
        self._cache = {}

    @property
    def paths(self):
        return load_once(self._lock, self._cache, ('paths',), lambda: tuple(sorted([
            *input_select(self.root / 'framework/materials/aws', '*.properties'),
            *input_select(self.root / 'framework/materials/api', '*.properties')])))

    def lines(self, resource_type):
        def load():
            path = next((p for p in self.paths if p.stem.replace('_', '.', 1) == resource_type), None)
            return None if path is None else tuple(input_text(path, encoding='utf-8').splitlines())
        return load_once(self._lock, self._cache, ('lines', resource_type), load)

    def selected(self, resource_type):
        return load_once(self._lock, self._cache, ('selected', resource_type), lambda: frozenset(
            line.partition('=')[0].removeprefix(resource_type + '.')
            for line in self.lines(resource_type) or () if '=' in line and not line.startswith('#')))

    def order(self, resource_type):
        def load():
            lines = self.lines(resource_type)
            return None if lines is None else MappingProxyType({line.partition('=')[0]: n for n, line in enumerate(lines)})
        return load_once(self._lock, self._cache, ('order', resource_type), load)

    def outputs(self, resource_type):
        return load_once(self._lock, self._cache, ('outputs', resource_type), lambda: frozenset(
            line.partition('=')[0] for line in self.lines(resource_type) or ()
            if line.endswith('=IDENTIFIER_OUTPUT')))

    def design_properties(self):
        def load():
            types, owners, outputs = set(), {}, {}
            for path in self.paths:
                kind = path.stem.replace('_', '.', 1)
                types.add(kind)
                for line in self.lines(kind):
                    name, separator, marker = line.partition('=')
                    if not separator or not name.startswith(kind + '.'):
                        continue
                    owners.setdefault(name[len(kind) + 1:], set()).add(kind)
                    owners.setdefault(name, set()).add(kind)
                    if marker == 'IDENTIFIER_OUTPUT':
                        outputs.setdefault(kind, set()).add(name)
            return (frozenset(types), MappingProxyType({k: frozenset(v) for k, v in owners.items()}),
                    MappingProxyType({k: frozenset(v) for k, v in outputs.items()}))
        return load_once(self._lock, self._cache, ('design-index',), load)


def catalogs_for(root):
    from utils.aws_mappings import definition_root
    root = definition_root(root)
    return load_once(_lock, _instances, root, lambda: Catalogs(root))
