"""Optional capabilities declared by the owner of each ResourceType."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

if TYPE_CHECKING:
    from comparison.methods import RuleSet
    from utils.iac_values import Expression
    from utils.type_contracts import JsonValue


class ReferenceMode(Enum):
    IMPORT = "import"
    COMPARISON = "comparison"


# Producer ResourceType -> accepted Model attribute forms. An empty map forbids links.
ReferenceForms = Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class ProducerReference:
    ref_attribute: str | None = None
    getatt_attributes: frozenset[str] = frozenset()
    arn_attribute: str | None = None
    model_attributes: Mapping[str, str] = field(default_factory=dict)

    def attribute_for(self, form: str) -> str | None:
        """Resolve a Model form to a Producer attribute. GetAtt uses formal names."""
        if form in self.model_attributes:
            return self.model_attributes[form]
        if form == "Arn" and self.arn_attribute is not None:
            return self.arn_attribute
        if form in self.getatt_attributes or form in (
            self.ref_attribute,
            self.arn_attribute,
        ):
            return form
        return None


class ContextReferenceHook(Protocol):
    def __call__(
        self,
        path: str,
        context: Mapping[str, JsonValue] | None,
        mode: ReferenceMode,
        /,
    ) -> ReferenceForms | None:
        """Return an override for the relative path, or None to use its static rule."""
        ...


@dataclass(frozen=True)
class ReceiverReference:
    import_properties: Mapping[str, ReferenceForms] = field(default_factory=dict)
    comparison_properties: Mapping[str, ReferenceForms] = field(default_factory=dict)
    contextual: ContextReferenceHook | None = None


class ArnComponentHook(Protocol):
    def __call__(
        self,
        properties: Mapping[str, JsonValue | Expression],
        evaluate: Callable[[JsonValue | Expression], JsonValue | Expression],
        /,
    ) -> dict[str, str]: ...


@dataclass(frozen=True)
class ArnExtension:
    """Additional ARN components and the property paths they depend on."""

    components: ArnComponentHook
    depends_on: tuple[str, ...] = ()


class DisplayHook(Protocol):
    def __call__(
        self, rows: list[list[str]], resource_type: str, /, *, mode: str
    ) -> list[list[str]]: ...


class RestoreHook(Protocol):
    def __call__(
        self, rows: list[list[str]], resource_type: str, /, *, mode: str
    ) -> list[list[str]]: ...


@dataclass(frozen=True)
class DisplayExtension:
    display: DisplayHook | None = None
    restore: RestoreHook | None = None


class DesignDefinition(TypedDict, total=False):
    """References to the existing fixed design tables for a ResourceType."""

    POLICY_FORMATS: Mapping[str, Literal["statement", "wrapped-statement", "settings"]]
    RESOURCE_REFERENCE_PROPERTIES: Mapping[str, tuple[str, str]]
    HIDDEN_PROPERTIES: Set[str]
    REQUIRED_NAME_TAG_TYPES: Set[str]
    COMPACT_FIELDS: Mapping[str, tuple[tuple[str, ...], str | None]]
    PACKED_ARRAY_PREFIXES: tuple[str, ...]
    IMPORT_PENDING_PROPERTIES: Set[str]


@dataclass(frozen=True)
class ResourceDefinition:
    resource_type: str
    producer: ProducerReference | None = None
    receiver: ReceiverReference | None = None
    comparison: Callable[[], RuleSet] | None = None
    design: DesignDefinition | None = None
    display: Callable[[], DisplayExtension] | None = None
    arn: ArnExtension | None = None


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    resources: tuple[ResourceDefinition, ...]
