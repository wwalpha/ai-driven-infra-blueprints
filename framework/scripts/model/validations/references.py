"""Model 検証: references。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from validation.findings import Findings

import model.references as _imports_model_references
import model.sources as _imports_model_sources


def _callback_check_model_inputs_references(
    _state_check_model_inputs_337: SimpleNamespace,
    findings: Findings,
    root: Path,
    values: dict[str, str],
    /,
) -> None:
    """Model の参照を診断し、警告とエラーを Findings に追加する。"""
    diagnose = _imports_model_references.diagnose
    scope_for = _imports_model_sources.scope_for
    model_path = (
        root
        / "model"
        / _state_check_model_inputs_337.view.relative_to(root / "docs/designs")
    ).with_suffix(".properties")
    candidate = SimpleNamespace(
        scope=scope_for(model_path), authoritative=values, dependencies={}
    )
    warnings, _ = diagnose(candidate, errors=findings.errors)
    findings.warnings.extend(warnings)
