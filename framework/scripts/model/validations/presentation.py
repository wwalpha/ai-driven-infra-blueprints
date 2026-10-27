"""Model 検証: presentation。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from validation.findings import Findings

import model.sources as _imports_model_sources
from model.projection import bound_resource_anchors


def _callback_check_model_inputs_presentation(
    definitions: Path,
    findings: Findings,
    owned: list[str],
    path: Path,
    resource_details: Callable[..., object],
    resources: list[tuple[str, dict[str, str]]],
    root: Path,
    service: str,
    values: dict[str, str],
    /,
) -> None:
    """Resource の表示情報と保存済みアンカーを検証する。"""
    scope_for = _imports_model_sources.scope_for
    view = (
        (root / "docs/designs" / path.relative_to(root / "model")).with_suffix(".md")
        if path.is_relative_to(root / "model")
        else path
    )
    scope = scope_for(
        (root / "model" / view.relative_to(root / "docs/designs")).with_suffix(
            ".properties"
        )
    )
    resource_details(
        values,
        definitions,
        service,
        owned,
        resources,
        bound_resource_anchors(view),
        findings=findings,
        scope=scope,
    )
