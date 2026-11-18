"""Optional capabilities declared by the owner of each ResourceType."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

from utils.type_contracts import JsonObject, JsonValue

if TYPE_CHECKING:
    from comparison.methods import RuleSet
    from model.identity import Resolver
    from model.reference_nodes import ReferenceNode
    from model.reference_presentation import Position, Reference
    from model.sources import ModelSnapshot
    from model.sources import Scope as ModelScope
    from utils.iac_values import Expression
    from validation.findings import Findings


class ReferenceMode(Enum):
    IMPORT = "import"
    COMPARISON = "comparison"


# Producer ResourceType -> accepted Model attribute forms. An empty map forbids links.
ReferenceForms = Mapping[str, tuple[str, ...]]
ReferenceTarget = tuple[str | tuple[str, ...], str | tuple[str, ...] | None]
ContextSelector = tuple[str, Mapping[str, ReferenceTarget]]


@dataclass(frozen=True)
class ProducerReference:
    ref_attribute: str | None = None
    getatt_attributes: frozenset[str] = frozenset()
    arn_attribute: str | None = None
    model_attributes: Mapping[str, str] = field(default_factory=dict)

    return_properties: Mapping[str, str] = field(default_factory=dict)
    return_types: Mapping[str, str] = field(default_factory=dict)
    type_forms: Set[str] = frozenset()
    format_names: Mapping[str, str] = field(default_factory=dict)
    value_identities: Mapping[str, str] = field(default_factory=dict)
    attribute_suffixes: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    def attribute_for(self, form: str) -> str | None:
        """Resolve a Model form to a Producer attribute. GetAtt uses formal names."""
        if form in self.model_attributes:
            return self.model_attributes[form]
        if form == "Arn" and self.arn_attribute is not None:
            return self.arn_attribute
        if (
            form in self.getatt_attributes
            or form in self.return_properties
            or form
            in (
                self.ref_attribute,
                self.arn_attribute,
            )
        ):
            return form
        return None


@dataclass(frozen=True)
class ReferencePolicy:
    error: str | None = None
    requires_context: bool | None = None
    unproven_reason: str | None = None


class ReferencePolicyHook(Protocol):
    def __call__(
        self, path: str, context: Mapping[str, JsonValue] | None, /
    ) -> ReferencePolicy: ...


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


class RowContextHook(Protocol):
    def __call__(
        self, rows: list[tuple[str, Mapping[str, str]]], /
    ) -> Mapping[str, Mapping[str, str]]: ...


class ConfigurationRowsHook(Protocol):
    def __call__(
        self,
        rows: list[tuple[str, Mapping[str, str]]],
        root: Path,
        *,
        index_rows: Callable[[list[list[str]], str, Path], list[list[str]]],
    ) -> dict[str, Mapping[str, JsonValue]]: ...


@dataclass(frozen=True)
class ConfigurationContext:
    property_prefix: str
    collect: ConfigurationRowsHook
    signature: Callable[
        [Iterable[tuple[str, Mapping[str, str]]]], list[tuple[str | None, str | None]]
    ]
    import_selector: str | None = None
    import_choices: Mapping[tuple[str, str], tuple[str, str]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ReceiverReference:
    import_properties: Mapping[str, ReferenceForms] = field(default_factory=dict)
    comparison_properties: Mapping[str, ReferenceForms] = field(default_factory=dict)
    exact_properties: Mapping[str, ReferenceForms] = field(default_factory=dict)
    local_comparison: Mapping[str, ReferenceForms] = field(default_factory=dict)
    direct_properties: Mapping[str, ReferenceTarget] = field(default_factory=dict)
    declared_forms: Mapping[str, Set[str]] = field(default_factory=dict)
    format_limits: Mapping[str, Set[str]] = field(default_factory=dict)
    selectors: Mapping[str, ContextSelector] = field(default_factory=dict)
    default_on_mismatch: Set[str] = frozenset()
    linked_lists: Mapping[str, str] = field(default_factory=dict)
    policy_paths: tuple[str, ...] = ()
    document_paths: tuple[str, ...] = ()
    contextual: ContextReferenceHook | None = None
    unproven_paths: tuple[str, ...] = ()
    row_contexts: RowContextHook | None = None
    context_producers: frozenset[str] = frozenset()
    reference_policy: ReferencePolicyHook | None = None
    context_paths: tuple[str, ...] = ()
    context_suffixes: tuple[str, ...] = ()
    equivalent_forms: Mapping[tuple[str, str, str], Set[str]] = field(
        default_factory=dict
    )
    configuration: ConfigurationContext | None = None
    split_reference_operands: Mapping[str, tuple[str, str, str]] = field(
        default_factory=dict
    )


class ArnComponentHook(Protocol):
    def __call__(
        self,
        properties: Mapping[str, JsonValue | Expression],
        evaluate: Callable[[JsonValue | Expression], JsonValue | Expression],
        /,
    ) -> dict[str, str]: ...


ArnIdentity = str | Mapping[str, str]
ArnForm = tuple[ArnIdentity, str]
ArnShape = tuple[ArnIdentity, str, Mapping[str, str]]


@dataclass(frozen=True)
class ArnExtension:
    """Additional ARN components and the property paths they depend on."""

    components: ArnComponentHook | None = None
    depends_on: tuple[str, ...] = ()
    shape: ArnShape | None = None
    forms: Mapping[str, ArnForm] = field(default_factory=dict)
    defaults: Mapping[str, str] = field(default_factory=dict)
    verified_symbolic_attributes: Set[str] = frozenset()


class DisplayHook(Protocol):
    def __call__(
        self, rows: list[list[str]], resource_type: str, /, *, mode: str
    ) -> list[list[str]]: ...


class RestoreHook(Protocol):
    def __call__(
        self, rows: list[list[str]], resource_type: str, /, *, mode: str
    ) -> list[list[str]]: ...


class DocumentDisplayHook(Protocol):
    def __call__(
        self, document: JsonObject, name: str, anchor: str, /
    ) -> list[str]: ...


class DocumentRestoreHook(Protocol):
    def __call__(
        self, path: Path, /, *, require_artifact: bool = True
    ) -> dict[str, tuple[Path | None, list[JsonObject]]]: ...


@dataclass(frozen=True)
class DisplayRowGroup:
    row: list[str]
    consumed: tuple[str, ...]


class RenderGroupHook(Protocol):
    def __call__(
        self,
        rows: list[list[str]],
        index: int,
        /,
        *,
        mode: str,
        counts: dict[str, int],
        references: Set[str],
    ) -> DisplayRowGroup | None: ...


@dataclass(frozen=True)
class RestoredRowGroup:
    rows: list[list[str]]
    label: str


class RestoreGroupHook(Protocol):
    def __call__(
        self,
        row: list[str],
        display_property: str,
        /,
        *,
        mode: str,
        counts: dict[str, int],
        names: set[str],
        verified: bool,
    ) -> RestoredRowGroup | None: ...


class DisplayRowError(ValueError):
    """A row error that requires the table's Resource identity in its diagnostic."""


class DisplayReferenceError(ValueError):
    """A classified reference error with recovered Markdown rows and positions."""

    def __init__(
        self,
        message: str,
        *,
        lines: list[str] | None = None,
        positions: tuple[Mapping[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        self.lines = lines
        self.positions = positions


class ReferenceLabelHook(Protocol):
    def __call__(
        self,
        property_path: str | None,
        producer_type: str,
        attribute: str,
        name: str,
        displayed: JsonValue,
        /,
    ) -> str: ...


class RenderDocumentTablesHook(Protocol):
    def __call__(
        self,
        rows: list[list[str]],
        children: list[tuple[dict[str, str], list[list[str]]]],
        root: Path,
        *,
        consumed: list[str] | None = None,
    ) -> list[str]: ...


class ValidateRowsHook(Protocol):
    def __call__(
        self, path: Path, logical_id: str, rows: list[list[str]], *, findings: Findings
    ) -> None: ...


@dataclass(frozen=True)
class DocumentReferenceRules:
    validate: Callable[
        [str, str, JsonValue, list[ReferenceNode], list[JsonObject]], None
    ]
    require_links: Callable[
        [str, str, list[ReferenceNode], list[str | None], list[JsonObject]], None
    ]
    label: Callable[
        [str | None, str, str | None, JsonValue, ModelSnapshot, str], str | None
    ]


class ReferenceDocumentHook(Protocol):
    def __call__(
        self,
        values: Mapping[str, str],
        row_id: str,
        field: str,
        raw: JsonValue,
        marked: JsonValue,
        selected: list[Reference],
        markers: Mapping[Position, str],
        scope: ModelScope,
        resolver: Resolver,
    ) -> JsonValue: ...


class ContextualLabelHook(Protocol):
    def __call__(
        self,
        values: Mapping[str, str],
        position: Position,
        node: ReferenceNode,
        scope: ModelScope,
        resolver: Resolver,
        resource: Mapping[str, str],
        attribute: str,
        name: str,
        displayed: JsonValue,
    ) -> str: ...


@dataclass(frozen=True)
class NamedChildDisplay:
    prepare: Callable[[str, list[list[str]], list[list[str]]], list[list[str]]]
    render_in_parent: bool = False
    label_in_display: bool = False
    require_restored_parent: bool = False


@dataclass(frozen=True)
class DisplayExtension:
    display: DisplayHook | None = None
    restore: RestoreHook | None = None
    display_document: DocumentDisplayHook | None = None
    restore_document: DocumentRestoreHook | None = None
    array_template: Callable[[str], str] | None = None
    compact_array: Callable[[str], bool] | None = None
    compact_group: Callable[[str], str | None] | None = None
    reference_label: ReferenceLabelHook | None = None
    parse_linked_list: Callable[[str, str], list[str] | None] | None = None
    render_group: RenderGroupHook | None = None
    restore_group: RestoreGroupHook | None = None
    validate_linked_list: Callable[[list[str], str, Set[str]], str | None] | None = None
    adjust_order: Callable[[str, dict[str, int | float]], None] | None = None
    validate_selection: Callable[[list[list[str]], list[list[str]]], None] | None = None
    name_tag: (
        Callable[[str, list[list[str]], dict[str, str], str], str | None] | None
    ) = None
    restore_raw: RestoreHook | None = None
    restore_formal: RestoreHook | None = None
    indexed_packed: bool = False
    horizontal_tables: bool = False
    restore_label: str | None = None
    validate_adjusted_order: bool = False
    validate_order: (
        Callable[[str, list[list[str]], dict[str, int | float]], list[str]] | None
    ) = None
    render_document_tables: RenderDocumentTablesHook | None = None
    validate_rows: ValidateRowsHook | None = None
    reference_document: ReferenceDocumentHook | None = None
    document_reference_rules: DocumentReferenceRules | None = None
    contextual_reference_label: ContextualLabelHook | None = None
    restore_document_tables: Callable[[list[str], Path], list[str]] | None = None
    selected_name: Callable[[list[list[str]], str | None], str | None] | None = None
    literal_link_label: Callable[[str, str], str | None] | None = None
    import_link_required: Set[str] = frozenset()
    literal_link_alias_error: str | None = None
    literal_link_mode_error: str | None = None
    child_property_prefixes: tuple[str, ...] = ()
    validate_display_property: Callable[[str], None] | None = None
    restore_children: Callable[[list[list[str]]], list[list[str]] | None] | None = None
    named_child: NamedChildDisplay | None = None


class DesignDefinition(TypedDict, total=False):
    """References to the existing fixed design tables for a ResourceType."""

    POLICY_FORMATS: Mapping[str, Literal["statement", "wrapped-statement", "settings"]]
    RESOURCE_REFERENCE_PROPERTIES: Mapping[str, tuple[str, str]]
    HIDDEN_PROPERTIES: Set[str]
    COLLAPSED_POLICY_DOCUMENTS: Set[str]
    REQUIRED_NAME_TAG_TYPES: Set[str]
    COMPACT_FIELDS: Mapping[str, tuple[tuple[str, ...], str | None]]
    PACKED_ARRAY_PREFIXES: tuple[str, ...]
    IMPORT_PENDING_PROPERTIES: Set[str]
    RESOURCE_ANCHOR_KINDS: Mapping[str, str]
    RESOURCE_NAME_FIELDS: Mapping[str, tuple[str, ...]]
    ADDITIONAL_RESOURCE_NAME_FIELDS: Mapping[str, tuple[str, ...]]
    REQUIRED_CREATE_NAME_TYPES: Set[str]
    REQUIRED_IMPORT_NAME_TYPES: Set[str]
    RULE_TABLE_LAYOUTS: Mapping[str, JsonObject]
    REQUIRED_DISPLAY_LINKS: Mapping[str, str]
    NAMING_EXEMPT_PROPERTIES: Set[str]
    FIFO_PROPERTIES: Mapping[str, tuple[str, str]]
    PROVIDER_NAME_CHECKS: Mapping[str, Callable[[str, str, str], list[str]]]
    CONFIRMED_NAME_FIELDS: Mapping[str, str]
    CATALOG_EXEMPT_NAMES: Set[str]
    NAMING_SUFFIX_CHECKS: Mapping[str, Callable[[str, str | None], list[str]]]
    JSON_LINK_IN_COMMENT: Set[str]
    REVIEW_POLICY_JSON: Set[str]


AccountPolicyCheck = Callable[[dict[str, str], dict[str, JsonValue]], None]


@dataclass(frozen=True)
class ResourceDefinition:
    resource_type: str
    producer: ProducerReference | None = None
    receiver: ReceiverReference | None = None
    comparison: Callable[[], RuleSet] | None = None
    design: DesignDefinition | None = None
    display: Callable[[], DisplayExtension] | None = None
    arn: ArnExtension | None = None
    account_policy: Callable[[], AccountPolicyCheck] | None = None


@dataclass(frozen=True)
class AwsAdapter:
    module: str

    @property
    def source(self) -> Path:
        return Path(*self.module.split(".")).with_suffix(".py")

    @property
    def evidence_module(self) -> str:
        return self.module + "_contracts"


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    resources: tuple[ResourceDefinition, ...]
    aws_adapters: Mapping[str, AwsAdapter] = field(default_factory=dict)
