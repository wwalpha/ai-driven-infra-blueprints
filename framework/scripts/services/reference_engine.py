"""Evaluate service-owned reference declarations without engine or AWS dependencies."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection, Mapping, Set
from functools import cached_property
from typing import TYPE_CHECKING

from .contracts import (
    ArnExtension,
    ArnForm,
    ArnShape,
    ConfigurationContext,
    ProducerReference,
    ReceiverReference,
    ReferenceForms,
    ReferenceMode,
    ReferencePolicy,
    ReferenceTarget,
)
from .reference_data import document_requires_context, supports_getatt
from .registry import REGISTRY, ServiceRegistry, normalize_property_path

if TYPE_CHECKING:
    from utils.type_contracts import JsonValue


class ReferenceEngine:
    def __init__(self, registry: ServiceRegistry = REGISTRY) -> None:
        self.registry = registry

    def ref_attribute(self, resource_type: str) -> str | None:
        producer = self._producer(resource_type)
        return producer.ref_attribute if producer is not None else None

    def getatt_attributes(self, resource_type: str) -> frozenset[str] | None:
        producer = self._producer(resource_type)
        return producer.getatt_attributes if producer is not None else None

    def has_getatt(
        self, resource_type: str, attribute: str, readable: Collection[str] = ()
    ) -> bool:
        extensions = self.getatt_attributes(resource_type)
        return supports_getatt(attribute, extensions or (), readable)

    def arn_attribute(self, resource_type: str) -> str | None:
        producer = self._producer(resource_type)
        return producer.arn_attribute if producer is not None else None

    def model_attribute(self, resource_type: str, form: str) -> str | None:
        producer = self._producer(resource_type)
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
        if mode is ReferenceMode.IMPORT:
            return self._resolve_import(receiver, path, context)
        if receiver.contextual is not None:
            override = receiver.contextual(path, context, mode)
            if override is not None:
                return self.registry.validate_reference_forms(override)
        return receiver.comparison_properties.get(path)

    def policy(
        self,
        resource_type: str,
        path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> ReferencePolicy:
        receiver = self.registry.receiver(resource_type)
        hook = receiver.reference_policy if receiver is not None else None
        return (
            hook(normalize_property_path(resource_type, path), context)
            if hook
            else ReferencePolicy()
        )

    def reference_error(
        self,
        resource_type: str,
        path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> str | None:
        return self.policy(resource_type, path, context).error

    def requires_context(
        self,
        resource_type: str,
        path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> bool:
        """Identify document paths whose reference semantics require evidence."""
        receiver = self.registry.receiver(resource_type)
        if receiver is None:
            return False
        path = normalize_property_path(resource_type, path)
        policy = self.policy(resource_type, path, context)
        if policy.requires_context is not None:
            return policy.requires_context
        return document_requires_context(path, receiver.unproven_paths)

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

    def _producer(self, kind: str) -> ProducerReference | None:
        return self.registry.producer(kind) if kind in self.registry else None

    def formal_attribute(self, kind: str, attribute: str) -> str:
        """Use the formal provider name when a Model attribute has an alias."""
        return self.model_attribute(kind, attribute) or attribute

    def return_property(
        self, kind: str, attribute: str, default: str | None = None
    ) -> str | None:
        producer = self._producer(kind)
        return (
            producer.return_properties.get(attribute, default) if producer else default
        )

    def return_type(self, kind: str, attribute: str) -> str | None:
        producer = self._producer(kind)
        return producer.return_types.get(attribute) if producer else None

    def identity_pattern(self, kind: str, attribute: str) -> str | None:
        producer = self._producer(kind)
        return producer.value_identities.get(attribute) if producer else None

    def attribute_suffix(self, kind: str, attribute: str) -> tuple[str, str] | None:
        producer = self._producer(kind)
        return producer.attribute_suffixes.get(attribute) if producer else None

    def identifier_forms(self, kind: str) -> Set[str]:
        producer = self._producer(kind)
        return producer.type_forms if producer else frozenset()

    def arn(self, kind: str) -> ArnExtension | None:
        return self.registry.arn(kind) if kind in self.registry else None

    def arn_shape(self, kind: str) -> ArnShape | None:
        definition = self.arn(kind)
        return definition.shape if definition else None

    def arn_form(self, kind: str, attribute: str) -> ArnForm | None:
        definition = self.arn(kind)
        return definition.forms.get(attribute) if definition else None

    def _receiving_path(
        self, property_path: str, *, normalize_indices: bool = True
    ) -> tuple[ReceiverReference | None, str]:
        namespace, _, rest = property_path.partition(".")
        resource, _, path = rest.partition(".")
        kind = (
            namespace if namespace.startswith("AWS::") else namespace + "." + resource
        )
        path = rest if namespace.startswith("AWS::") else path
        receiver = self.registry.receiver(kind) if kind in self.registry else None
        if normalize_indices:
            path = re.sub(r"\[[0-9]+\]", "[]", path)
        return receiver, path

    def import_targets(
        self,
        property_path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> ReferenceForms | None:
        receiver, path = self._receiving_path(property_path)
        if receiver is None or not path:
            return None
        return self._resolve_import(receiver, path, context)

    def _resolve_import(
        self,
        receiver: ReceiverReference,
        path: str,
        context: Mapping[str, JsonValue] | None,
    ) -> ReferenceForms | None:
        if path in receiver.exact_properties:
            return receiver.exact_properties[path]
        if receiver.contextual is not None and not receiver.selectors:
            dynamic = receiver.contextual(path, context, ReferenceMode.IMPORT)
            if dynamic is not None:
                return self.registry.validate_reference_forms(dynamic)
        for candidate in (path, path + "[]", path.removesuffix("[]")):
            if candidate in receiver.import_properties:
                return receiver.import_properties[candidate]
            if candidate in receiver.selectors and receiver.contextual is not None:
                dynamic = receiver.contextual(candidate, context, ReferenceMode.IMPORT)
                return (
                    None
                    if dynamic is None
                    else self.registry.validate_reference_forms(dynamic)
                )
        return None

    def comparison_targets(
        self,
        property_path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> ReferenceForms | None:
        receiver, path = self._receiving_path(property_path)
        if receiver is not None and path in receiver.local_comparison:
            return receiver.local_comparison[path]
        return self.import_targets(property_path, context)

    def direct_reference(self, property_path: str) -> ReferenceTarget | None:
        receiver, path = self._receiving_path(property_path)
        return receiver.direct_properties.get(path) if receiver else None

    def declared_consumer_forms(self, property_path: str) -> Set[str] | None:
        receiver, path = self._receiving_path(property_path)
        return receiver.declared_forms.get(path) if receiver else None

    def equivalent_forms(
        self, property_path: str, kind: str, attribute: str
    ) -> Set[str]:
        receiver, path = self._receiving_path(property_path)
        return (
            receiver.equivalent_forms.get((path, kind, attribute), frozenset())
            if receiver
            else frozenset()
        )

    def linked_list_kind(self, property_path: str) -> str | None:
        receiver, path = self._receiving_path(property_path, normalize_indices=False)
        return receiver.linked_lists.get(path) if receiver else None

    def is_context_selector(self, property_path: str) -> bool:
        receiver, path = self._receiving_path(property_path)
        return receiver is not None and path in receiver.selectors

    def defaults_context_form(self, property_path: str) -> bool:
        receiver, path = self._receiving_path(property_path)
        return receiver is not None and path in receiver.default_on_mismatch

    def configuration_at(self, property_path: str) -> ConfigurationContext | None:
        receiver, _ = self._receiving_path(property_path)
        config = receiver.configuration if receiver else None
        return config if config and config.property_prefix == property_path else None

    def collect_row_contexts(
        self,
        kind: str,
        rows: list[tuple[str, Mapping[str, str]]],
    ) -> dict[str, Mapping[str, str]]:
        receiver = self.registry.receiver(kind) if kind in self.registry else None
        return (
            dict(receiver.row_contexts(rows))
            if receiver and receiver.row_contexts
            else {}
        )

    def bind_context(
        self, path: str, value: JsonValue, current: JsonValue
    ) -> JsonValue:
        return value if self.registry.binds_reference_context(path) else current

    def policy_condition(self, property_path: str) -> bool:
        receiver, path = self._receiving_path(property_path)
        return receiver is not None and document_requires_context(
            path, receiver.policy_paths
        )

    def unproven_document_reference(self, property_path: str) -> bool:
        receiver, path = self._receiving_path(property_path)
        return receiver is not None and document_requires_context(
            path, receiver.document_paths
        )

    def context_required_at(
        self,
        property_path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> bool:
        receiver, path = self._receiving_path(property_path)
        if receiver is None or not path:
            return False
        if receiver.reference_policy is not None:
            policy = receiver.reference_policy(path, context)
            if policy.requires_context is not None:
                return policy.requires_context
        return document_requires_context(path, receiver.unproven_paths)

    def error_at(
        self,
        property_path: str,
        context: Mapping[str, JsonValue] | None = None,
    ) -> str | None:
        receiver, path = self._receiving_path(property_path)
        if receiver and path and receiver.reference_policy:
            return receiver.reference_policy(path, context).error
        return None

    @cached_property
    def _import_attributes(self) -> dict[str, tuple[str, ...]]:
        forms = defaultdict(set)
        for kind in self.registry:
            arn = self.registry.arn(kind)
            if arn:
                for identity, _ in arn.forms.values():
                    forms[kind].update(
                        (identity,) if isinstance(identity, str) else identity
                    )
            receiver = self.registry.receiver(kind)
            if receiver is None:
                continue
            for alternatives in receiver.import_properties.values():
                for target, attributes in alternatives.items():
                    forms[target].update(attributes)
            for path, (selector, choices) in receiver.selectors.items():
                for value in choices:
                    alternatives = self.import_targets(
                        kind + "." + path, {selector: value}
                    )
                    for target, attributes in (alternatives or {}).items():
                        forms[target].update(attributes)
            if receiver.configuration:
                for target, form in receiver.configuration.import_choices.values():
                    attribute = self.return_property(target, form, form)
                    if attribute is not None:
                        forms[target].add(attribute)
        return {
            kind: tuple(sorted(kind + "." + form for form in attributes))
            for kind, attributes in forms.items()
        }

    def attributes_for(self, kind: str) -> tuple[str, ...]:
        """Producer attributes usable as physical-identity evidence during IMPORT."""
        return self._import_attributes.get(kind, ())


REFERENCES = ReferenceEngine()
