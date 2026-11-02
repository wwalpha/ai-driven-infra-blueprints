"""Read-only access to the structure of an existing Model value set."""

from copy import deepcopy
from functools import cached_property

from contracts.model import RESOURCE_LOGICAL_ID_KEY, RESOURCE_TYPE_KEY

from model.configuration import ConfigurationIndex
from model.core import SnapshotValues, entries, resource_row_index, structural_entries
from model.format import owner
from model.identity import display_anchor, resource_index
from model.reference_nodes import parse
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

    def resource_groups(self, grouped_types):
        """Resolve parent ownership for the caller-selected grouped Resource types."""
        resource_index(self._values)
        self.row_index()
        resources = dict(self.resources())
        if not resources:
            raise ValueError("Resource ownership unavailable")
        anchors = {}
        for identity, resource in resources.items():
            anchor = display_anchor(resource)
            if anchor in anchors:
                raise ValueError("duplicate Model Resource anchor: " + anchor)
            anchors[anchor] = identity
        parents = {}
        for identity, resource in resources.items():
            if resource[RESOURCE_TYPE_KEY] not in grouped_types:
                continue
            parent = parse(resource.get("parentReference"))
            candidates = [
                rid
                for rid, item in resources.items()
                if item[RESOURCE_LOGICAL_ID_KEY] == parent.logical_id
            ]
            if len(candidates) != 1:
                raise ValueError("grouped parent ownership unavailable: " + identity)
            parents[identity] = candidates[0]
        groups = {}
        for identity in resources:
            parent = identity
            seen = set()
            while parent in parents:
                if parent in seen:
                    raise ValueError("cyclic grouped parent ownership: " + identity)
                seen.add(parent)
                parent = parents[parent]
            groups.setdefault(parent, set()).add(identity)
        return resources, groups

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
