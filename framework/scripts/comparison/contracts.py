"""Explicit optional Resource contracts, separate from property comparison methods."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from types import NotImplementedType
from typing import TYPE_CHECKING, Protocol

from services.registry import REGISTRY
from utils.iac_values import Expression
from utils.type_contracts import JsonValue

if TYPE_CHECKING:
    from comparison.inputs import Inputs

ComparisonValue = JsonValue | Expression
ComparisonResources = Mapping[str, Mapping[str, Mapping[str, JsonValue]]]


@dataclass(frozen=True)
class FormOutcome:
    equal: bool | NotImplementedType | None
    code: str | None = None
    message: str | None = None


class IdentifierFormatHook(Protocol):
    def __call__(
        self,
        value: ComparisonValue,
        resources: ComparisonResources,
        *,
        project_arn: Callable[[ComparisonValue], ComparisonValue] | None = None,
    ) -> str | None: ...


class FormComparisonHook(Protocol):
    def __call__(
        self,
        left: ComparisonValue,
        right: ComparisonValue,
        allowed: Set[str],
        *,
        resolve_literal: Callable[[ComparisonValue], ComparisonValue],
        format_of: Callable[[ComparisonValue], str | None],
        project_arn: Callable[[ComparisonValue], ComparisonValue] | None = None,
    ) -> FormOutcome: ...


class PrepareReferenceHook(Protocol):
    def __call__(
        self,
        inputs: Inputs,
        service: str,
        row_id: str,
        row: Mapping[str, str],
        stack: Mapping[str, JsonValue],
        /,
    ) -> ComparisonValue: ...


@dataclass(frozen=True)
class ResourceContract:
    prepare_rows: object = None
    deferred_rows: str | None = None
    contexts: object = None
    context_properties: dict = field(default_factory=dict)
    design_only: frozenset = frozenset()
    name_tag: bool = False
    identity_same: object = None
    arn_attribute: str | None = None
    ref_attribute: object = None
    ref_property: str | None = None
    imported_arn: object = None
    explicit_name: str | None = None
    identifier_format: IdentifierFormatHook | None = None
    form_compare: FormComparisonHook | None = None
    identifier_evidence: (
        Callable[[ComparisonValue, ComparisonValue, Mapping[str, JsonValue]], bool]
        | None
    ) = None
    defer_reference_arrays: frozenset[str] = frozenset()
    blocked_reference_attributes: Mapping[str, tuple[str, str]] = field(
        default_factory=dict
    )
    export_attributes: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    prepare_reference: Mapping[str, PrepareReferenceHook] = field(default_factory=dict)


def compare_producer_forms(
    producer_type: str,
    left: ComparisonValue,
    right: ComparisonValue,
    allowed: Set[str],
    *,
    resolve_literal: Callable[[ComparisonValue], ComparisonValue],
    format_of: Callable[[ComparisonValue], str | None],
    project_arn: Callable[[ComparisonValue], ComparisonValue] | None = None,
) -> FormOutcome:
    rules = REGISTRY.comparison_rules(producer_type)
    operation = rules.resource.form_compare if rules is not None else None
    if operation is None:
        raise ValueError(f"missing Producer form comparison: {producer_type}")
    return operation(
        left,
        right,
        allowed,
        resolve_literal=resolve_literal,
        format_of=format_of,
        project_arn=project_arn,
    )
