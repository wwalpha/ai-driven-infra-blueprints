"""Read-only access to the structure of an existing Model value set."""

from copy import deepcopy
from functools import cached_property

from model.configuration import ConfigurationIndex
from model.core import SnapshotValues, entries, resource_row_index, structural_entries
from model.format import owner
from model.sources import ModelSnapshot


class ModelView:
    """A fixed view of authoritative values; accessors return independent values."""

    def __init__(self, source):
        self._values = (
            source.authoritative
            if isinstance(source, ModelSnapshot)
            else source
            if isinstance(source, SnapshotValues)
            else SnapshotValues(source)
        )
        self._locations = (
            dict(source.locations) if isinstance(source, ModelSnapshot) else {}
        )
        self._owned = None

    @cached_property
    def _index(self):
        return ConfigurationIndex(self._values)

    def resources(self):
        return entries(self._values, "desired.resource.")

    def structural_resources(self):
        return structural_entries(self._values, "desired.resource.")

    def all_rows(self):
        return entries(self._values, "desired.row.")

    def row_index(self):
        return resource_row_index(self._values)

    def all_references(self):
        return entries(self._values, "desired.reference.")

    def all_artifacts(self):
        return entries(self._values, "desired.artifact.")

    def rows(self, resource_id):
        return deepcopy(self._index.resource_rows(resource_id))

    def references(self, resource_id):
        return deepcopy(self._index.resource_references(resource_id))

    def observed(self, resource_id):
        return dict(self._index.resource_observed(resource_id))

    def stacks(self):
        return entries(self._values, "desired.stack.")

    def artifacts(self, stack_id):
        stack = dict(self.stacks())[stack_id]
        return [
            (identity, fields)
            for identity, fields in self.all_artifacts()
            if fields.get("stack") == stack.get("name") and "name" in stack
        ]

    def owner(self, key):
        return owner(key, self._values)

    def keys(self, kind, identity):
        if self._owned is None:
            owned = {}
            for key in self._values:
                owned.setdefault(self.owner(key), []).append(key)
            self._owned = owned
        return tuple(self._owned.get((kind, identity), ()))

    def location(self, key):
        return self._locations.get(key)
