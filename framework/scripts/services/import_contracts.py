"""Optional IMPORT acquisition contracts owned by each ResourceType."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from utils.type_contracts import JsonObject, JsonValue

if TYPE_CHECKING:
    from model.adapters.aws import Context, Resource
    from utils.mapping_types import Property


Inventory = tuple[str, str, str | None]


@dataclass(frozen=True)
class Detail:
    operation: str
    selector: str
    result: str
    list_returns_selector: bool = False
    mismatch: str | None = None


@dataclass(frozen=True)
class ScopedInventory:
    api: str
    operations: tuple[str, ...]
    payload: tuple[str, str]
    components: tuple[str, ...]
    collect: Callable[..., list[JsonObject]]
    selectors: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()
    filter_error: str | None = None
    group_review: str | None = None
    grouped_identity: str | None = None
    cloudcontrol_fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountFilter:
    selector: str
    discovery_reason: str
    evidence_reason: str
    scope_mismatch: str


@dataclass(frozen=True)
class DerivedInventory:
    parents: tuple[str, ...]
    reason_code: str
    reason: str
    unavailable_reason: str
    identity_code: str
    identity_reason: str
    identity_paths: tuple[str, ...]
    components: tuple[str, ...]
    attach: Callable[[JsonObject, list[JsonObject]], None]


@dataclass(frozen=True)
class ConditionalCapture:
    paths: Mapping[str, str]
    contract: Callable[[Path, str, Property, JsonObject, str], JsonObject | None]
    capture: Callable[[str, JsonValue, JsonValue, JsonObject | None], JsonObject | None]
    valid: Callable[
        [str, JsonObject, JsonObject, Callable[[], JsonObject | None]], bool
    ]
    invalid_contract: str
    unknown_identity: str
    missing_reason: str


@dataclass(frozen=True)
class ImportProfile:
    adapter: Inventory | None = None
    detail: Detail | None = None
    scoped: ScopedInventory | None = None
    derived: DerivedInventory | None = None
    dependencies: tuple[str, ...] = ()
    name_tag: bool = False
    conditional_capture: ConditionalCapture | None = None
    unobservable: Mapping[str, tuple[str, str, str, str]] = field(default_factory=dict)
    addition_issue: (
        Callable[[JsonObject, Callable[[str], JsonValue]], str | None] | None
    ) = None
    account_filter: AccountFilter | None = None
    verify_list_fields: tuple[str, ...] = ()
    verify_list_error: str = ""
    execution_account_input: str | None = None
    batch: Callable[[Context, list[str]], list[JsonObject]] | None = None
    decorate: Callable[[JsonObject], None] | None = None
    additional_getters: (
        Callable[[Context, JsonObject, dict[str, str]], JsonObject] | None
    ) = None
    related_records: Callable[[JsonObject], list[JsonObject]] | None = None
    verify_detail: (
        Callable[[Context, Resource, JsonObject, JsonObject, JsonValue], bool] | None
    ) = None
    allows_missing: (
        Callable[[str, JsonObject, Mapping[str, JsonObject]], bool] | None
    ) = None
    normalize_identity: Callable[[str, str], str] | None = None
    related_fields: tuple[tuple[str, str], ...] = ()
    derived_getters: Callable[[JsonObject], Mapping[str, JsonObject]] | None = None


def _call_inventory_handler(module: str, name: str, /, *args):
    return getattr(import_module(module), name)(*args)


def inventory_handler(module: str, name: str):
    """Defer importing acquisition logic until the profile's handler runs."""
    return partial(_call_inventory_handler, module, name)
