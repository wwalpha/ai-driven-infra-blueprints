"""lambda_permission design display/restoration helpers."""

import json
from pathlib import Path

from design.common import catalog_property_order
from design.layout_schema import CHILD, CHILD_NAME
from design.services.definitions.lambda_permission import (
    LAMBDA_PERMISSION,
    PERMISSION_METADATA,
)


def permission_rows(rows: list[list[str]]) -> list[list[str]]:
    """Restore hidden permission rows before the shared grouped-child parser."""
    result = []
    index = 0
    order = catalog_property_order(Path(__file__).resolve().parents[4], LAMBDA_PERMISSION)
    while index < len(rows):
        cells = rows[index]
        if not cells[1].startswith(LAMBDA_PERMISSION + "."):
            if "<!-- lambda-permission:" in cells[3]:
                raise ValueError("Lambda Permission metadata must be on Permission.Action")
            result.append(cells)
            index += 1
            continue
        child = CHILD.match(cells[3])
        marker = PERMISSION_METADATA.match(cells[3][child.end():]) if child else None
        if cells[1] != LAMBDA_PERMISSION + ".Action" or not marker:
            raise ValueError("Permission.Action requires complete identity and Lambda Permission metadata")
        try:
            label, hidden = json.loads(marker.group(1))
            if (not isinstance(label, str) or not CHILD_NAME.fullmatch(label + "：") or
                    not isinstance(hidden, list) or len(hidden) != 2 or
                    any(not isinstance(row, list) or len(row) != 3 or
                        any(not isinstance(cell, str) or any(char in cell for char in "|\n\r<>") for cell in row) for row in hidden) or
                    [row[0] for row in hidden] != [LAMBDA_PERMISSION + ".Id", LAMBDA_PERMISSION + ".FunctionName"]):
                raise ValueError("invalid hidden rows")
        except (ValueError, TypeError) as error:
            raise ValueError("invalid Lambda Permission metadata") from error
        block = [[cells[0], *row] for row in hidden]
        block[0][3] = child.group(0) + label + "：" + block[0][3]
        cells = cells.copy()
        cells[3] = cells[3][child.end() + marker.end():]
        while True:
            if cells[1] not in order or cells[1] in {row[1] for row in block}:
                raise ValueError("invalid or duplicate Lambda Permission property")
            if "<!-- lambda-permission:" in cells[3] or "<!-- logical-id:" in cells[3]:
                raise ValueError("Lambda Permission identity must be on its first Action row")
            block.append(cells)
            index += 1
            if index == len(rows) or not rows[index][1].startswith(LAMBDA_PERMISSION + ".") or CHILD.match(rows[index][3]):
                break
            cells = rows[index]
        visible = block[2:]
        if visible != sorted(visible, key=lambda row: order[row[1]]):
            raise ValueError("Lambda Permission rows must follow catalog file order")
        result += sorted(block, key=lambda row: order[row[1]])
    return result
