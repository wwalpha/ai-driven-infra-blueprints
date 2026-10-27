"""Explicit optional Resource contracts, separate from property comparison methods."""

from dataclasses import dataclass, field


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
