"""Evaluate service-owned reference declarations without engine or AWS dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .contracts import ReferenceForms, ReferenceMode
from .registry import REGISTRY, ServiceRegistry, normalize_property_path

if TYPE_CHECKING:
    from utils.type_contracts import JsonValue


class ReferenceEngine:
    def __init__(self, registry: ServiceRegistry = REGISTRY) -> None:
        self.registry = registry

    def ref_attribute(self, resource_type: str) -> str | None:
        producer = self.registry.producer(resource_type)
        return producer.ref_attribute if producer is not None else None

    def getatt_attributes(self, resource_type: str) -> frozenset[str] | None:
        producer = self.registry.producer(resource_type)
        return producer.getatt_attributes if producer is not None else None

    def arn_attribute(self, resource_type: str) -> str | None:
        producer = self.registry.producer(resource_type)
        return producer.arn_attribute if producer is not None else None

    def model_attribute(self, resource_type: str, form: str) -> str | None:
        producer = self.registry.producer(resource_type)
        return producer.attribute_for(form) if producer is not None else None

    def receiver_forms(
        self,
        resource_type: str,
        path: str,
        *,
        mode: ReferenceMode,
        context: Mapping[str, JsonValue] | None = None,
    ) -> ReferenceForms | None:
        """Return None for an undeclared path and an empty mapping for denial."""
        if not isinstance(mode, ReferenceMode):
            raise ValueError(f"invalid reference mode: {mode!r}")
        receiver = self.registry.receiver(resource_type)
        path = normalize_property_path(resource_type, path)
        if receiver is None:
            return None
        if receiver.contextual is not None:
            override = receiver.contextual(path, context, mode)
            if override is not None:
                return self.registry.validate_reference_forms(override)
        if mode is ReferenceMode.COMPARISON:
            return receiver.comparison_properties.get(path)

        # IMPORT treats terminal list scalars with and without [] as equivalent.
        properties = receiver.import_properties
        if path in properties:
            return properties[path]
        alternate = path.removesuffix("[]") if path.endswith("[]") else path + "[]"
        return properties.get(alternate)

    def allows(
        self,
        receiver_type: str,
        path: str,
        producer_type: str,
        form: str,
        *,
        mode: ReferenceMode,
        context: Mapping[str, JsonValue] | None = None,
    ) -> bool | None:
        """Return None for an undeclared receiver path; require a registered Producer."""
        kind = self.registry.resource(producer_type).resource_type
        forms = self.receiver_forms(receiver_type, path, mode=mode, context=context)
        return None if forms is None else form in forms.get(kind, ())
