"""Read-only access to the structure of an existing Model value set."""

from copy import deepcopy

from model.configuration import ConfigurationIndex
from model.core import SnapshotValues, entries
from model.format import owner
from model.sources import ModelSnapshot


class ModelView:
    """A fixed view of authoritative values; accessors return independent values."""

    def __init__(self, source):
        self._values = (
            source.authoritative
            if isinstance(source, ModelSnapshot)
            else SnapshotValues(source)
        )
        self._locations = (
            dict(source.locations) if isinstance(source, ModelSnapshot) else {}
        )
        self._index = ConfigurationIndex(self._values)
        self._owned = None

    def resources(self):
        return entries(self._values, "desired.resource.")

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
            for identity, fields in entries(self._values, "desired.artifact.")
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
