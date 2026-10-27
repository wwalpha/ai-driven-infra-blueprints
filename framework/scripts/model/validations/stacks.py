"""Model 検証: stacks。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model.change_plan import ServiceChange


from validation.diagnostics import InputValidationError

import model.core as _imports_model_core
from model.core import (
    entries,
)


def validate_changed_stacks(values: dict[str, str], change: ServiceChange) -> None:
    """変更された Stack の項目と一意性を検証する。"""
    previous = (
        {}
        if change.before is None
        else dict(entries(change.before.authoritative, "desired.stack."))
    )
    current = dict(entries(values, "desired.stack."))
    for identity, stack in current.items():
        selected = {
            key.rsplit(".", 1)[-1]
            for key in change.keys
            if key.startswith(f"desired.stack.{identity}.")
        }
        if not selected:
            continue
        required = {"name", "template", "parameters", "deployOrder", "placementName"}
        if identity not in previous or any(
            field in required and field not in stack for field in selected
        ):
            if not required <= stack.keys():
                raise InputValidationError("Stack required fields missing: " + identity)
        if "placementName" in selected:
            _imports_model_core.validate_stack_metadata(
                {
                    f"desired.stack.{identity}.{key}": value
                    for key, value in stack.items()
                }
            )
        for field in selected & stack.keys():
            _imports_model_core.validate_stack_field(field, stack[field])
            if field in {"name", "parameters", "placementName"} and any(
                other != identity and spec.get(field) == stack[field]
                for other, spec in current.items()
            ):
                raise InputValidationError(
                    "duplicate Stack " + field + ": " + stack[field]
                )
