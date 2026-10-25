"""Lazy selection lists and derived indexes; definitions are read-only by contract."""

from functools import partial as _bind_framework_callback
from pathlib import Path
from threading import Lock
from types import MappingProxyType

from design.services.definitions.registry import HIDDEN_PROPERTIES

import utils.aws_mappings as _imports_utils_aws_mappings
from utils.input_cache import input_select, input_text, memoized
from utils.lazy_definitions import load_once

_lock = Lock()
_instances = {}


def _callback_Catalogs_lines_load(resource_type, self, /):
    path = next(
        (p for p in self.paths if p.stem.replace("_", ".", 1) == resource_type), None
    )
    return (
        None if path is None else tuple(input_text(path, encoding="utf-8").splitlines())
    )


def _callback_Catalogs_order_load(resource_type, self, /):
    lines = self.lines(resource_type)
    return (
        None
        if lines is None
        else MappingProxyType(
            {line.partition("=")[0]: n for n, line in enumerate(lines)}
        )
    )


def _callback_Catalogs_design_properties_load(self, /):
    types, owners, outputs = set(), {}, {}
    for path in self.paths:
        kind = path.stem.replace("_", ".", 1)
        types.add(kind)
        for line in self.lines(kind):
            name, separator, marker = line.partition("=")
            if not separator or not name.startswith(kind + "."):
                continue
            owners.setdefault(name[len(kind) + 1 :], set()).add(kind)
            owners.setdefault(name, set()).add(kind)
            if marker == "IDENTIFIER_OUTPUT":
                outputs.setdefault(kind, set()).add(name)
    return (
        frozenset(types),
        MappingProxyType({k: frozenset(v) for k, v in owners.items()}),
        MappingProxyType({k: frozenset(v) for k, v in outputs.items()}),
    )


class Catalogs:
    def __init__(self, root):
        definition_root = _imports_utils_aws_mappings.definition_root
        self.root = definition_root(root)
        self._lock = Lock()
        self._cache = {}

    @property
    def paths(self):
        return load_once(
            self._lock,
            self._cache,
            ("paths",),
            lambda: tuple(
                sorted(
                    [
                        *input_select(
                            self.root / "framework/materials/aws", "*.properties"
                        ),
                        *input_select(
                            self.root / "framework/materials/api", "*.properties"
                        ),
                    ]
                )
            ),
        )

    def lines(self, resource_type):
        load = _bind_framework_callback(
            _callback_Catalogs_lines_load, resource_type, self
        )
        return load_once(self._lock, self._cache, ("lines", resource_type), load)

    def selected(self, resource_type):
        return load_once(
            self._lock,
            self._cache,
            ("selected", resource_type),
            lambda: frozenset(
                line.partition("=")[0].removeprefix(resource_type + ".")
                for line in self.lines(resource_type) or ()
                if "=" in line and not line.startswith("#")
            ),
        )

    def order(self, resource_type):
        load = _bind_framework_callback(
            _callback_Catalogs_order_load, resource_type, self
        )
        return load_once(self._lock, self._cache, ("order", resource_type), load)

    def outputs(self, resource_type):
        return load_once(
            self._lock,
            self._cache,
            ("outputs", resource_type),
            lambda: frozenset(
                line.partition("=")[0]
                for line in self.lines(resource_type) or ()
                if line.endswith("=IDENTIFIER_OUTPUT")
            ),
        )

    def design_properties(self):
        load = _bind_framework_callback(_callback_Catalogs_design_properties_load, self)
        return load_once(self._lock, self._cache, ("design-index",), load)


def catalogs_for(root):
    definition_root = _imports_utils_aws_mappings.definition_root
    root = definition_root(root)
    return load_once(_lock, _instances, root, lambda: Catalogs(root))


@memoized
def catalog_outputs(root: Path, kind: str) -> set[str]:
    return set(catalogs_for(root).outputs(kind)) - HIDDEN_PROPERTIES
