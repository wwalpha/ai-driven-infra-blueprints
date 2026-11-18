"""config design display/restoration helpers."""

import re

from contracts.model import RESOURCE_MODE_IMPORT
from model.core import literal

from ..contracts import DisplayExtension
from .design import ROLE_ARN


def config_role_arn(prop: str, value: str) -> bool:
    return prop == ROLE_ARN and bool(
        re.fullmatch(
            r"arn:aws(?:-[a-z]+)*:iam::[0-9]{12}:role/(?:[!-~]{1,510}/)?[A-Za-z0-9_+=,.@-]{1,64}",
            literal(value),
        )
    )


def is_import_role_arn(prop: str, value: str, mode: str) -> bool:
    return mode == RESOURCE_MODE_IMPORT and config_role_arn(prop, value)


def display_rows(
    rows: list[list[str]], resource_type: str, /, *, mode: str
) -> list[list[str]]:
    return [
        [
            rid,
            "RoleARN" if is_import_role_arn(prop, value, mode) else prop,
            value,
            comment,
        ]
        for rid, prop, value, comment in rows
    ]


def restore_rows(
    rows: list[list[str]], resource_type: str, /, *, mode: str
) -> list[list[str]]:
    return [
        [rid, ROLE_ARN if prop == "RoleARN" else prop, value, comment]
        for rid, prop, value, comment in rows
    ]


def literal_link_label(prop: str, value: str) -> str | None:
    return "RoleARN" if config_role_arn(prop, value) else None


EXTENSION = DisplayExtension(
    display_rows,
    restore_rows,
    literal_link_label=literal_link_label,
    import_link_required=frozenset({ROLE_ARN}),
    literal_link_alias_error="ConfigurationRecorder RoleARN must use Mapping display name",
    literal_link_mode_error="Config RoleARN literal requires IMPORT",
)
