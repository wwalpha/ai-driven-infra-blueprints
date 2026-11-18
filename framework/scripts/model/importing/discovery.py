"""Offline discovery selection shared by acquisition and capability diagnostics."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.registry import REGISTRY
from utils.mapping_types import Property, Registry

SchemaLookup = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class DiscoveryPlan:
    mode: str
    status: str
    reason_code: str
    reason: str
    required_filters: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()


def type_name(kind: str) -> str:
    return "AWS::" + kind.replace(".", "::", 1)


def required_filters(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = (
        schema.get("handlers", {})
        .get("list", {})
        .get("handlerSchema", {})
        .get("required", ())
    )
    if (
        not isinstance(required, (list, tuple))
        or any(not isinstance(name, str) or not name for name in required)
        or len(set(required)) != len(required)
    ):
        raise ValueError("Invalid CloudFormation List required filters")
    return tuple(required)


def filter_parents(
    kinds: Sequence[str], kind: str, required: Sequence[str], schema: SchemaLookup
) -> tuple[str, ...]:
    """Keep the runtime's exact same-owner, ordered primary-identifier rule."""
    return tuple(
        parent
        for parent in kinds
        if parent != kind
        and tuple(schema(parent).get("primaryIdentifier", ()))
        == tuple("/properties/" + name for name in required)
        and not required_filters(schema(parent))
    )


def resolve(
    mapping: Registry,
    properties: Mapping[str, Property],
    kind: str,
    schema: SchemaLookup | None = None,
) -> DiscoveryPlan:
    """Omit schema inspection at runtime: existing execution owns failures/statuses.

    Schema inspection is offline and never changes the selected execution branch.
    Adapter readiness still needs payload/identity checks in Coverage.
    """
    if not any(
        p.include for key, p in properties.items() if key.startswith(kind + ".")
    ):
        return DiscoveryPlan(
            "not_modelled",
            "not_modelled",
            "NO_MODEL_PROPERTIES",
            "No model.include properties",
        )
    profile = REGISTRY.import_profile(kind)
    if profile.scoped is not None:
        return DiscoveryPlan(
            "scoped_sdk",
            "uncertain",
            "SCOPED_SDK_INVENTORY",
            "SDK inventory preserves parent selectors and composite identity",
            parents=profile.scoped.parents,
        )
    if profile.adapter is not None and kind in mapping.identities:
        return DiscoveryPlan(
            "adapter",
            "uncertain",
            "ADAPTER_REGISTERED",
            "SDK inventory selected; payload and identity require inspection",
        )
    if profile.derived and profile.derived.parents[0] in mapping.resource_types:
        return DiscoveryPlan(
            "parent_derived",
            "uncertain",
            profile.derived.reason_code,
            profile.derived.reason,
            parents=profile.derived.parents,
        )
    if schema is None:
        return DiscoveryPlan(
            "cloudcontrol",
            "uncertain",
            "PROVIDER_DISCOVERY",
            "Cloud Control fallback selected; provider capabilities not inspected",
        )
    try:
        definition = schema(kind)
    except KeyError:
        return DiscoveryPlan(
            "unsupported",
            "unsupported",
            "SCHEMA_UNSUPPORTED",
            "No CloudFormation schema and no executable SDK inventory/identity pair",
        )
    if "list" not in definition.get("handlers", {}):
        return DiscoveryPlan(
            "unsupported",
            "unsupported",
            "LIST_UNSUPPORTED",
            "CloudFormation schema has no List handler; SDK inventory/identity pair unavailable",
        )
    handler_schema = definition["handlers"]["list"].get("handlerSchema", {})
    if any(
        key in handler_schema
        for key in (
            "$ref",
            "allOf",
            "anyOf",
            "oneOf",
            "if",
            "dependentRequired",
            "dependencies",
        )
    ):
        return DiscoveryPlan(
            "cloudcontrol",
            "uncertain",
            "LIST_CONDITIONS_UNCONFIRMED",
            "List handler has conditions not resolved by the existing required-filter builder",
        )
    required = required_filters(definition)
    if not required:
        return DiscoveryPlan(
            "cloudcontrol",
            "ready",
            "PROVIDER_LIST",
            "Cloud Control List has no required filters",
        )
    if profile.account_filter and required == (profile.account_filter.selector,):
        return DiscoveryPlan(
            "cloudcontrol",
            "ready",
            "TARGET_ACCOUNT_FILTER",
            profile.account_filter.discovery_reason,
            required,
        )
    try:
        parents = filter_parents(sorted(mapping.resource_types), kind, required, schema)
    except KeyError as error:
        return DiscoveryPlan(
            "cloudcontrol",
            "unsupported",
            "PARENT_SCHEMA_UNSUPPORTED",
            "Runtime parent search encounters an unsupported sibling schema: "
            + str(error),
            required,
        )
    if len(parents) != 1:
        return DiscoveryPlan(
            "cloudcontrol",
            "unsupported",
            "REQUIRED_FILTER_AMBIGUOUS" if parents else "REQUIRED_FILTER_UNRESOLVED",
            "Runtime requires exactly one same-owner parent with matching ordered primary identifiers",
            required,
            parents,
        )
    parent = resolve(mapping, properties, parents[0], schema)
    if parent.mode != "cloudcontrol" or parent.status != "ready":
        return DiscoveryPlan(
            "cloudcontrol",
            "unsupported",
            "PARENT_FILTER_UNAVAILABLE",
            "Parent cannot supply cloudProperties to the existing filter builder: "
            + parents[0]
            + " ("
            + parent.reason_code
            + ")",
            required,
            parents,
        )
    if "read" not in schema(parents[0]).get("handlers", {}):
        return DiscoveryPlan(
            "cloudcontrol",
            "uncertain",
            "PARENT_VALUES_UNCONFIRMED",
            "Parent List may omit identifier properties and no Read handler can fill them",
            required,
            parents,
        )
    return DiscoveryPlan(
        "cloudcontrol",
        "ready",
        "PARENT_FILTER",
        "Required filters derive from parent cloudProperties primary identifiers",
        required,
        parents,
    )
