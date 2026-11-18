"""Validate service ownership and look up capabilities by ResourceType."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Set
from dataclasses import replace
from functools import cached_property
from importlib import import_module
from types import MappingProxyType
from typing import TYPE_CHECKING

from .contracts import (
    AccountPolicyCheck,
    ArnExtension,
    AwsAdapter,
    DesignDefinition,
    DisplayExtension,
    ProducerReference,
    ReceiverReference,
    ReferenceForms,
    ResourceDefinition,
    ServiceDefinition,
)
from .manifest import SERVICES

if TYPE_CHECKING:
    from comparison.contracts import ResourceContract
    from comparison.methods import Rule, RuleSet


def normalize_resource_type(resource_type: str) -> str:
    """Convert AWS::Service::Resource and Service.Resource to the Model spelling."""
    if isinstance(resource_type, str):
        token = r"[A-Za-z][A-Za-z0-9]*"
        if re.fullmatch(rf"AWS::{token}::{token}", resource_type):
            return resource_type.removeprefix("AWS::").replace("::", ".")
        if re.fullmatch(rf"{token}\.{token}", resource_type):
            return resource_type
    raise ValueError(f"invalid ResourceType: {resource_type!r}")


def normalize_property_path(resource_type: str, path: str) -> str:
    """Return a relative property path with list offsets replaced by []."""
    kind = normalize_resource_type(resource_type)
    if isinstance(path, str):
        qualified = "AWS::" + kind.replace(".", "::")
        if path.startswith("AWS::"):
            if not path.startswith(qualified + "."):
                raise ValueError(f"property path must belong to {kind}: {path!r}")
            prop = path.removeprefix(qualified + ".")
        else:
            prop = path.removeprefix(kind + ".")
        prop = re.sub(r"\[[0-9]+\]", "[]", prop)
        segment = r"[^.\s\[\]]+(?:\[\])*"
        if re.fullmatch(segment + r"(?:\." + segment + ")*", prop):
            return prop
    raise ValueError(f"invalid property path for {kind}: {path!r}")


def _attribute(value: str) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", value)
    )


def _producer(kind: str, contract: ProducerReference) -> ProducerReference:
    if (
        not isinstance(contract, ProducerReference)
        or not isinstance(contract.getatt_attributes, frozenset)
        or not isinstance(contract.model_attributes, Mapping)
        or any(
            attr is not None and not _attribute(attr)
            for attr in (contract.ref_attribute, contract.arn_attribute)
        )
        or any(not _attribute(attr) for attr in contract.getatt_attributes)
        or any(
            not _attribute(form) or not _attribute(attr)
            for form, attr in contract.model_attributes.items()
        )
        or (
            contract.arn_attribute is not None
            and contract.model_attributes.get("Arn", contract.arn_attribute)
            != contract.arn_attribute
        )
    ):
        raise ValueError(f"invalid Producer reference contract for {kind}")
    return replace(
        contract, model_attributes=MappingProxyType(dict(contract.model_attributes))
    )


def _design(kind: str, definitions: DesignDefinition) -> None:
    if (
        not isinstance(definitions, dict)
        or definitions.keys() - DesignDefinition.__optional_keys__
    ):
        raise ValueError(f"invalid Design definition for {kind}")
    for name, values in definitions.items():
        collection_type = {
            "POLICY_FORMATS": Mapping,
            "RESOURCE_REFERENCE_PROPERTIES": Mapping,
            "COMPACT_FIELDS": Mapping,
            "RESOURCE_ANCHOR_KINDS": Mapping,
            "RESOURCE_NAME_FIELDS": Mapping,
            "ADDITIONAL_RESOURCE_NAME_FIELDS": Mapping,
            "RULE_TABLE_LAYOUTS": Mapping,
            "REQUIRED_DISPLAY_LINKS": Mapping,
            "FIFO_PROPERTIES": Mapping,
            "PROVIDER_NAME_CHECKS": Mapping,
            "CONFIRMED_NAME_FIELDS": Mapping,
            "NAMING_SUFFIX_CHECKS": Mapping,
            "PACKED_ARRAY_PREFIXES": tuple,
        }.get(name, Set)
        if not isinstance(values, collection_type):
            raise ValueError(f"invalid Design table {name} for {kind}")
        for path in values:
            if name in {
                "REQUIRED_NAME_TAG_TYPES",
                "RESOURCE_ANCHOR_KINDS",
                "RESOURCE_NAME_FIELDS",
                "ADDITIONAL_RESOURCE_NAME_FIELDS",
                "REQUIRED_CREATE_NAME_TYPES",
                "REQUIRED_IMPORT_NAME_TYPES",
                "RULE_TABLE_LAYOUTS",
                "FIFO_PROPERTIES",
                "PROVIDER_NAME_CHECKS",
                "CONFIRMED_NAME_FIELDS",
                "NAMING_SUFFIX_CHECKS",
            }:
                owned = path == kind
            else:
                owned = isinstance(path, str) and path.startswith(kind + ".")
                if owned:
                    normalize_property_path(kind, path)
            if not owned:
                raise ValueError(
                    f"Design table {name} for {kind} contains foreign key: {path!r}"
                )


class ServiceRegistry:
    """Explicit registrations. Unknown ResourceTypes raise KeyError."""

    def __init__(self, services: Iterable[ServiceDefinition]) -> None:
        self._resources: dict[str, ResourceDefinition] = {}
        self._owners: dict[str, str] = {}
        registered = set()
        adapters = {}
        for service in services:
            if (
                not isinstance(service, ServiceDefinition)
                or not isinstance(service.name, str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", service.name)
                or not isinstance(service.resources, tuple)
                or not service.resources
            ):
                raise ValueError(f"invalid service definition: {service!r}")
            if service.name in registered:
                raise ValueError(f"duplicate service: {service.name}")
            registered.add(service.name)
            for alias, adapter in service.aws_adapters.items():
                if (
                    not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias)
                    or not isinstance(adapter, AwsAdapter)
                    or not adapter.module.startswith("services.")
                ):
                    raise ValueError(f"invalid AWS adapter: {alias}")
                if alias in adapters:
                    raise ValueError(f"duplicate AWS adapter: {alias}")
                adapters[alias] = adapter
            for definition in service.resources:
                self._register(service.name, definition)

        self.aws_adapters: Mapping[str, AwsAdapter] = MappingProxyType(adapters)
        for kind, definition in self._resources.items():
            receiver = definition.receiver
            if receiver is not None:
                receiver = replace(
                    receiver,
                    import_properties=self._receiver_paths(
                        kind, receiver.import_properties
                    ),
                    comparison_properties=self._receiver_paths(
                        kind, receiver.comparison_properties
                    ),
                    exact_properties=self._receiver_paths(
                        kind, receiver.exact_properties
                    ),
                    local_comparison=self._receiver_paths(
                        kind, receiver.local_comparison
                    ),
                )
                self._resources[kind] = replace(definition, receiver=receiver)

        receivers = [
            item.receiver
            for item in self._resources.values()
            if item.receiver is not None
        ]
        self._context_paths = frozenset(
            path for receiver in receivers for path in receiver.context_paths
        )
        self._context_suffixes = tuple(
            dict.fromkeys(
                suffix for receiver in receivers for suffix in receiver.context_suffixes
            )
        )

    def _register(self, owner: str, definition: ResourceDefinition) -> None:
        if not isinstance(definition, ResourceDefinition):
            raise ValueError(f"invalid Resource definition for {owner}")
        kind = normalize_resource_type(definition.resource_type)
        if kind in self._resources:
            raise ValueError(
                f"duplicate ResourceType: {kind} ({self._owners[kind]}, {owner})"
            )
        producer, receiver, arn = (
            definition.producer,
            definition.receiver,
            definition.arn,
        )
        if receiver is not None and (
            not isinstance(receiver, ReceiverReference)
            or (receiver.contextual is not None and not callable(receiver.contextual))
            or (
                receiver.row_contexts is not None
                and not callable(receiver.row_contexts)
            )
        ):
            raise ValueError(f"invalid Receiver reference contract for {kind}")
        if arn is not None:
            if (
                not isinstance(arn, ArnExtension)
                or (arn.components is not None and not callable(arn.components))
                or (arn.shape is None and arn.components is None)
                or not isinstance(arn.depends_on, tuple)
            ):
                raise ValueError(f"invalid ARN extension for {kind}")
            arn = replace(
                arn,
                depends_on=tuple(
                    normalize_property_path(kind, path) for path in arn.depends_on
                ),
            )
        for feature, load in (
            ("Comparison", definition.comparison),
            ("Display", definition.display),
            ("Account policy", definition.account_policy),
        ):
            if load is not None and not callable(load):
                raise ValueError(f"invalid {feature} loader for {kind}")
        if definition.design is not None:
            _design(kind, definition.design)
        self._resources[kind] = replace(
            definition,
            resource_type=kind,
            producer=_producer(kind, producer) if producer is not None else None,
            arn=arn,
        )
        self._owners[kind] = owner

    def _receiver_paths(
        self, kind: str, properties: Mapping[str, ReferenceForms]
    ) -> Mapping[str, ReferenceForms]:
        if not isinstance(properties, Mapping):
            raise ValueError(f"invalid receiving properties for {kind}")
        normalized = {}
        for path, forms in properties.items():
            relative = normalize_property_path(kind, path)
            if relative in normalized:
                raise ValueError(f"duplicate receiving property: {kind}.{relative}")
            normalized[relative] = self.validate_reference_forms(forms)
        return MappingProxyType(normalized)

    def validate_reference_forms(self, forms: ReferenceForms) -> ReferenceForms:
        """Validate static declarations and contextual overrides against their Producers."""
        if not isinstance(forms, Mapping):
            raise ValueError("invalid reference forms: expected a mapping")
        normalized = {}
        for resource_type, attributes in forms.items():
            kind = normalize_resource_type(resource_type)
            if kind in normalized:
                raise ValueError(f"duplicate Producer ResourceType: {kind}")
            definition = self._resources.get(kind)
            producer = definition.producer if definition is not None else None
            if (
                not isinstance(attributes, tuple)
                or not attributes
                or any(
                    not _attribute(form)
                    or (
                        definition is not None
                        and (producer is None or producer.attribute_for(form) is None)
                    )
                    for form in attributes
                )
                or len(set(attributes)) != len(attributes)
            ):
                raise ValueError(f"invalid Producer forms for {kind}: {attributes!r}")
            normalized[kind] = attributes
        return MappingProxyType(normalized)

    def binds_reference_context(self, path: str) -> bool:
        normalized = re.sub(r"\[\d+\]", "[]", path)
        return normalized in self._context_paths or normalized.endswith(
            self._context_suffixes
        )

    def missing_producers(self) -> frozenset[str]:
        """Report unresolved inter-service declarations in this registry."""
        receivers = (
            item.receiver
            for item in self._resources.values()
            if item.receiver is not None
        )
        missing = set()
        for receiver in receivers:
            missing.update(receiver.context_producers)
            for properties in (
                receiver.import_properties,
                receiver.comparison_properties,
                receiver.exact_properties,
                receiver.local_comparison,
            ):
                for forms in properties.values():
                    missing.update(forms)
        return frozenset(missing - self._resources.keys())

    def check_coverage(self, expected_owners: Mapping[str, str]) -> None:
        """Require each ResourceType in a caller-selected ownership inventory."""
        for resource_type, expected in expected_owners.items():
            kind = normalize_resource_type(resource_type)
            owner = self._owners.get(kind)
            if owner is None:
                raise ValueError(f"missing ResourceType registration: {kind}")
            if owner != expected:
                raise ValueError(
                    f"wrong owner for {kind}: expected {expected}, got {owner}"
                )

    def __contains__(self, resource_type: str) -> bool:
        return resource_type in self._resources or (
            resource_type.startswith("AWS::")
            and resource_type.removeprefix("AWS::").replace("::", ".")
            in self._resources
        )

    def __iter__(self) -> Iterator[str]:
        return iter(self._resources)

    def owner(self, resource_type: str) -> str:
        return self._owners[normalize_resource_type(resource_type)]

    def resource(self, resource_type: str) -> ResourceDefinition:
        return self._resources[normalize_resource_type(resource_type)]

    def producer(self, resource_type: str) -> ProducerReference | None:
        return self.resource(resource_type).producer

    def receiver(self, resource_type: str) -> ReceiverReference | None:
        return self.resource(resource_type).receiver

    def arn(self, resource_type: str) -> ArnExtension | None:
        return self.resource(resource_type).arn

    def design(self, resource_type: str) -> DesignDefinition | None:
        return self.resource(resource_type).design

    @cached_property
    def design_tables(self) -> DesignDefinition:
        """Collect cross-resource Design views in document precedence order."""
        entries = {}
        for item in self._resources.values():
            for name, values in (item.design or {}).items():
                table = entries.setdefault(name, {})
                for key in values:
                    if key in table:
                        raise ValueError(f"duplicate {name} definition: {key}")
                    table[key] = values[key] if isinstance(values, Mapping) else None
        for name, table in entries.items():
            if name == "POLICY_FORMATS":
                entries[name] = MappingProxyType(
                    dict(
                        sorted(
                            table.items(),
                            key=lambda item: (item[1] == "settings", item[0]),
                        )
                    )
                )
            elif name == "PACKED_ARRAY_PREFIXES":
                entries[name] = tuple(table)
            elif any(value is not None for value in table.values()):
                entries[name] = MappingProxyType(table)
            else:
                entries[name] = frozenset(table)
        return entries

    def presentation(self, resource_type: str) -> DisplayExtension:
        return (
            self.display(resource_type) or _DEFAULT_DISPLAY
            if resource_type in self
            else _DEFAULT_DISPLAY
        )

    def display(self, resource_type: str) -> DisplayExtension | None:
        definition = self.resource(resource_type)
        if definition.display is None:
            return None
        extension = definition.display()
        if not isinstance(extension, DisplayExtension) or any(
            hook is not None and not callable(hook)
            for hook in (
                extension.display,
                extension.restore,
                extension.display_document,
                extension.restore_document,
                extension.array_template,
                extension.compact_array,
                extension.compact_group,
                extension.reference_label,
                extension.parse_linked_list,
                extension.render_group,
                extension.restore_group,
                extension.validate_linked_list,
                extension.adjust_order,
                extension.validate_selection,
                extension.name_tag,
                extension.restore_raw,
                extension.restore_formal,
                extension.restore_document_tables,
                extension.validate_order,
                extension.render_document_tables,
                extension.validate_rows,
                extension.reference_document,
                extension.contextual_reference_label,
                extension.selected_name,
                extension.literal_link_label,
                extension.validate_display_property,
                extension.restore_children,
                extension.named_child.prepare if extension.named_child else None,
            )
        ):
            raise ValueError(
                f"invalid Display extension for {definition.resource_type}"
            )
        return extension

    def account_policy_checks(self) -> Iterator[AccountPolicyCheck]:
        for definition in self._resources.values():
            if definition.account_policy is not None:
                yield definition.account_policy()

    def comparison_rules(self, resource_type: str) -> RuleSet | None:
        """Return the original RuleSet, including its ResourceContract."""
        definition = self.resource(resource_type)
        if definition.comparison is None:
            return None
        rules = definition.comparison()
        methods = import_module("comparison.methods")
        if not isinstance(rules, methods.RuleSet) or not isinstance(
            rules.resource, methods.ResourceContract
        ):
            raise ValueError(f"invalid Comparison rules for {definition.resource_type}")
        return rules

    def require_comparison(self, resource_type: str) -> RuleSet:
        rules = self.comparison_rules(resource_type) if resource_type in self else None
        if rules is None:
            raise ValueError(f"Framework comparison rule missing: {resource_type}")
        return rules

    def require_comparison_property(self, resource_type: str, path: str) -> Rule:
        path = re.sub(r"\[\d+\]", "[]", path)
        rules = self.require_comparison(resource_type)
        try:
            return rules[path]
        except KeyError as error:
            raise ValueError(
                f"Framework comparison rule missing: {resource_type}.{path}"
            ) from error

    def comparison_contract(self, resource_type: str) -> ResourceContract:
        rules = self.comparison_rules(resource_type) if resource_type in self else None
        return rules.resource if rules is not None else self._empty_comparison

    @cached_property
    def _empty_comparison(self) -> ResourceContract:
        return import_module("comparison.contracts").ResourceContract()

    def comparison_property_rule(self, resource_type: str, path: str) -> Rule:
        """Use OBJECT for paths visited by reference traversal without an override."""
        rules = self.comparison_rules(resource_type) if resource_type in self else None
        path = re.sub(r"\[\d+\]", "[]", path)
        default = import_module("comparison.methods").OBJECT
        return default if rules is None else rules.get(path, default)


_DEFAULT_DISPLAY = DisplayExtension()
REGISTRY = ServiceRegistry(SERVICES)
