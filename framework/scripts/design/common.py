"""Shared design row/table primitives without document or Model-display dependencies."""

import html
import json
import re
from pathlib import Path

from model.core import LINK
from utils.aws_catalogs import catalogs_for
from utils.input_cache import memoized

from design.layout_schema import ALIGNMENT, DETAILS_HEADING, HEADER
from design.services import secrets_manager
from design.services.definitions.secrets_manager import ROTATION_SUBNETS


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def resource_heading_lines(lines: list[str]) -> list[str]:
    """Normalize type-only detail headings; overview type headings stay unchanged."""
    result = []
    details = False
    for line in lines:
        if line.startswith("## "):
            details = line == DETAILS_HEADING
        if details and re.fullmatch(r"### [A-Za-z0-9]+\.[A-Za-z0-9]+", line):
            line += ": " + line[4:]
        result.append(line)
    return result


@memoized
def catalog_property_order(root: Path, resource_type: str):
    order = catalogs_for(root).order(resource_type)
    return None if order is None else dict(order)


def subnet_list_items(prop: str, value: str) -> list[str]:
    """Split a saved list for display without inferring resource references."""
    raw = value[1:-1] if value.startswith("`") and value.endswith("`") else value
    if prop == ROTATION_SUBNETS:
        items = secrets_manager.subnet_list_items(raw)
    elif prop.endswith("[]") and not raw.lstrip().startswith(("[", "{")):
        items = [raw]
    else:
        items = json.loads(raw)
    if (
        not isinstance(items, list)
        or any(
            not isinstance(item, str)
            or not item.strip()
            or any(char in item for char in "|\n\r`")
            for item in items
        )
    ):
        raise ValueError(f"{prop}: Subnet list must contain non-empty string elements")
    return [
        item if re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", item) else f"`{item}`"
        for item in items
    ]


def code(value: object) -> str:
    if isinstance(value, str) and LINK.fullmatch(value):
        return value
    text = (
        value
        if isinstance(value, str)
        else json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    if text == "":
        return '`""`'
    if any(char in text for char in "`|<>&\n\r"):
        escaped = (
            html.escape(text, quote=False)
            .replace("|", "&#124;")
            .replace("\n", "&#10;")
            .replace("\r", "&#13;")
        )
        return f"<code>{escaped}</code>"
    return f"`{text}`"


def cell(value: object) -> str:
    return (
        "<br>".join(code(item) for item in value)
        if isinstance(value, list) and value
        else code(value)
    )


def table(
    headers: list[str], rows: list[list[str]], numbered: bool = False
) -> list[str]:
    alignment = ["---"] * len(headers)
    if numbered:
        alignment[0] = "---:"
    return ["| " + " | ".join(row) + " |" for row in [headers, alignment, *rows]]


def row_table(rows: list[list[str]]) -> list[str]:
    return [
        HEADER,
        ALIGNMENT,
        *(
            "| " + " | ".join([str(number), *row[1:]]) + " |"
            for number, row in enumerate(rows, 1)
        ),
    ]
