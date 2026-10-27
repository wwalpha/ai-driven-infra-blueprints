"""Model 検証: structure。"""

from __future__ import annotations

from collections.abc import Callable


def _callback_check_model_inputs_structure(
    resource_row_index: Callable[[dict[str, str]], object],
    validate_model_keys: Callable[[dict[str, str]], None],
    values: dict[str, str],
    /,
) -> None:
    """Model の実行時キーと Resource／Row の構造を順に検証する。"""
    validate_model_keys(values)
    resource_row_index(values)
