"""Model 検証: environment。"""

from __future__ import annotations

from pathlib import Path

import model.core as _imports_model_core
import model.environment_values as environment_values
import model.references as _imports_model_references
import model.sources as _imports_model_sources
from model.core import (
    entries,
)


def validate_environment_settings(
    values: dict[str, str],
    path: Path,
    *,
    warnings: list[dict] | None = None,
    reference_values: dict[str, str] | None = None,
) -> None:
    """環境値の PENDING_DEPLOY 条件を検証し、許可された値を警告する。"""
    root = _imports_model_sources.scope_for(path).root
    authority = values if reference_values is None else dict(reference_values, **values)
    resources = dict(
        _imports_model_core.structural_entries(authority, "desired.resource.")
    )
    rows = entries(values, "desired.row.")
    context_rows = entries(authority, "desired.row.")
    contexts, mappings = {}, {}
    selected_kinds = {
        rid.rpartition("-")[0]: ".".join(row["property"].split(".")[:2])
        for rid, row in rows
    }
    for number, kind in selected_kinds.items():
        mapping = mappings.setdefault(kind, environment_values.mapping_for(root, kind))
        contexts.update(
            environment_values.row_contexts(
                kind,
                [
                    (rid, row)
                    for rid, row in context_rows
                    if rid.rpartition("-")[0] == number
                ],
                mapping,
            )
        )
    for rid, row in rows:
        kind = selected_kinds[rid.rpartition("-")[0]]
        field = "document" if "document" in row else "value"
        value, structured = _imports_model_references._json(
            f"desired.row.{rid}.{field}", row[field]
        )
        if not structured:
            value = _imports_model_core.literal(value)
        invalid = environment_values.pending_errors(
            kind, row["property"], value, mappings[kind], context=contexts.get(rid)
        )
        logical = resources.get(rid.rpartition("-")[0], {}).get("logicalId")
        if invalid:
            raise _imports_model_core.ModelNeedsFixError(
                "PENDING_DEPLOY is permitted only in environment Values, not this desired field",
                code="MODEL_REF_INVALID_PENDING_STATE",
                model=str(path),
                modelKey=f"desired.row.{rid}.{field}",
                property=row["property"],
                pointer=invalid[0],
                resourceLogicalId=logical,
            )
        if warnings is not None:
            for item in environment_values.inspect(
                kind, row["property"], value, mappings[kind], context=contexts.get(rid)
            ):
                if item.value == "PENDING_DEPLOY":
                    warnings.append(
                        dict(
                            category="REFERENCE_PENDING_DEPLOY",
                            code="ENVIRONMENT_VALUE_PENDING",
                            message=item.reason,
                            model=str(path),
                            modelKey=f"desired.row.{rid}.{field}",
                            property=row["property"],
                            pointer=item.pointer,
                            resolutionState=item.status,
                            resourceLogicalId=logical,
                            status="WARNING",
                        )
                    )
