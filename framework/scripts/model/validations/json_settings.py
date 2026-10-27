"""Model 検証: json_settings。"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from model.projection import (
    validate_json_documents,
)
from model.validations.environment import validate_environment_settings


def validate_json_settings(
    values: dict[str, str],
    model_path: Path,
    *,
    warnings: list[dict] | None = None,
    excluded_references: Collection[tuple[str, str, str]] = (),
    reference_values: dict[str, str] | None = None,
) -> None:
    """環境値と JSON Document の検証を順に実行する。"""
    path = Path(model_path)
    if path.suffix == ".md" and path.parents[2].name == "designs":
        path = (
            path.parents[4]
            / "model"
            / path.relative_to(path.parents[4] / "docs/designs")
        ).with_suffix(".properties")
    validate_environment_settings(
        values, path, warnings=warnings, reference_values=reference_values
    )
    validate_json_documents(
        values,
        model_path,
        warnings=warnings,
        excluded_references=excluded_references,
        reference_values=reference_values,
    )
