"""Catalog ordering and common display tables, separate from document assembly."""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import aws_mapping_display as _display_aws_mapping_display
import design.common as _display_common
import design.compact_rows
import design.layout_schema as _display_design_layout
from contracts.model import (
    RESOURCE_LOGICAL_ID_KEY,
    RESOURCE_MODE_CREATE,
    RESOURCE_MODE_IMPORT,
    RESOURCE_TYPE_KEY,
)
from design.common import row_table as row_table
from services.reference_engine import REFERENCES
from services.registry import REGISTRY
from utils.input_cache import input_scope

import model.files as _display_model_files
from model.core import LINK, ReferenceResolutionError, entries, literal
from model.reference_nodes import (
    ReferenceNode,
    nodes,
)

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ReferenceRows:
    """Original Model rows, captured before display projection for one Resource."""

    logical_id: str
    kind: str
    mode: str
    rows: tuple[tuple[str, ...], ...]
    references: tuple[tuple[str, tuple[ReferenceNode, ...]], ...]

    @property
    def reference_ids(self):
        return frozenset(rid for rid, _ in self.references)


@dataclass(frozen=True)
class ReferenceTable:
    """A generated expectation and semantic rows; never serialized to Markdown."""

    anchor: str
    resources: tuple[ReferenceRows, ...]
    expected: tuple[str, ...]
    semantic: tuple[str, ...]
    baseline: tuple[str, ...]


def reference_rows(values):
    result = {}
    rows_by_resource = _display_model_files.resource_row_index(values)
    for identity, resource in entries(values, "desired.resource."):
        for rid, row in rows_by_resource[identity]:
            if not {"property", "value"} <= row.keys():
                raise ValueError("invalid resource row: " + rid)
        rows = tuple(
            (rid, row["property"], row["value"], row.get("comment", ""))
            for rid, row in rows_by_resource[identity]
        )
        result[resource[RESOURCE_LOGICAL_ID_KEY]] = ReferenceRows(
            resource[RESOURCE_LOGICAL_ID_KEY],
            resource[RESOURCE_TYPE_KEY],
            resource.get("resourceMode", RESOURCE_MODE_CREATE),
            rows,
            tuple(
                (rid, references)
                for rid, source in rows_by_resource[identity]
                if (
                    references := tuple(
                        node
                        for field in ("value", "document")
                        if field in source
                        for node in nodes(literal(source[field]))
                    )
                )
            ),
        )
    return result


def catalog_display_rows(
    rows: list[list[str]], kind: str, root: Path
) -> list[list[str]]:
    """Sort property blocks without separating contiguous array elements."""
    extension = REGISTRY.presentation(kind)
    if (
        extension.horizontal_tables
        or _display_design_layout.GROUPED.get(kind, {}).get("display") == "rule-table"
    ):
        return rows
    order = dict(_display_common.catalog_property_order(root, kind) or {})
    if extension.adjust_order is not None:
        extension.adjust_order(kind, order)
    blocks = []
    previous_array = ""
    array_order = {}
    for prop, rank in order.items():
        if "[]" in prop:
            array = prop.split("[]", 1)[0] + "[]"
            array_order.setdefault(array, rank)
    for row in rows:
        array = row[1].split("[]", 1)[0] + "[]" if "[]" in row[1] else ""
        if array and array == previous_array:
            blocks[-1].append(row)
        else:
            blocks.append([row])
        previous_array = array
    return [
        row
        for block in sorted(
            blocks,
            key=lambda block: array_order.get(
                block[0][1].split("[]", 1)[0] + "[]", order.get(block[0][1], len(order))
            ),
        )
        for row in block
    ]


@input_scope
def display_rows(
    kind: str,
    rows: list[list[str]],
    root: Path = ROOT,
    *,
    mode=RESOURCE_MODE_CREATE,
    _counts=None,
    consumed: list[str] | None = None,
    references=None,
) -> list[list[str]]:
    rows = _display_aws_mapping_display.selected_rows(rows, root)
    if any(any(nodes(literal(row[2]))) for row in rows):
        # Preserve symbolic rows before compact displays require physical strings.
        if consumed is not None:
            consumed.extend(row[0] for row in rows)
        return [
            [identity, prop.removeprefix(kind + "."), value, comment]
            for identity, prop, value, comment in rows
        ]
    return _display_rows(
        kind,
        rows,
        root,
        mode=mode,
        _counts=_counts,
        consumed=consumed,
        references=set(references or ()),
    )


def _display_rows(kind, rows, root, *, mode, _counts, consumed, references):
    """Apply the existing service displays without changing formal model values."""
    rows = _display_aws_mapping_display.selected_rows(rows, root)
    extension = REGISTRY.presentation(kind)
    source_ids = tuple(row[0] for row in rows)
    processed = []
    formal_properties = {row[1] for row in rows}
    result = []
    index = 0
    counts = {} if _counts is None else _counts
    while index < len(rows):
        start = index
        identity, prop, value, comment = rows[index]
        packed = (
            design.compact_rows.packed_compact_rows(rows, index)
            if mode == RESOURCE_MODE_IMPORT
            else None
        )
        if packed is not None:
            block, expanded = packed
            rendered = display_rows(
                kind, expanded, root, mode=mode, _counts=counts, references=references
            )
            source = json.dumps(
                [[row[1:] for row in block], len(rendered)], ensure_ascii=True
            )
            for char in "|<>":
                source = source.replace(char, f"\\u{ord(char):04x}")
            rendered[0][3] = "<!-- compact-source: " + source + " --> " + rendered[0][3]
            result.extend(rendered)
            processed.extend(row[0] for row in block)
            index += len(block)
            continue
        group = (
            extension.render_group(
                rows, index, mode=mode, counts=counts, references=references
            )
            if extension.render_group is not None
            else None
        )
        if group is not None:
            size = len(group.consumed)
            expected = source_ids[index : index + size]
            if (
                not size
                or expected != group.consumed
                or len(set(expected)) != size
                or len(group.row) != 4
                or group.row[0] != identity
            ):
                raise ValueError(
                    "selected display rows were omitted or consumed more than once"
                )
            identity, prop, value, comment = group.row
            index += size - 1
        elif REFERENCES.linked_list_kind(prop) is not None:
            linked = LINK.fullmatch(value)
            error = (
                extension.validate_linked_list(rows[index], mode, references)
                if extension.validate_linked_list is not None
                else None
            )
            if not linked and error:
                raw = literal(value).lstrip()
                items = (
                    _display_common.subnet_list_items(prop, value)
                    if raw.startswith(("[", "{"))
                    else None
                )
                if items is None or items:
                    raise ReferenceResolutionError(
                        error,
                        property=prop,
                        reference=value,
                    )
            else:
                items = (
                    [value]
                    if linked
                    else _display_common.subnet_list_items(prop, value)
                )
            field = prop.removesuffix("[]").removeprefix(kind + ".")
            for item in items or [value]:
                if items:
                    counts[prop] = counts.get(prop, 0) + 1
                result.append(
                    [
                        identity,
                        f"{field}[{counts[prop]}]" if items else field,
                        item,
                        comment,
                    ]
                )
            processed.extend(row[0] for row in rows[start : index + 1])
            index += 1
            continue
        # Compact producers own their dynamic names; ordinary rows use Mapping names.
        item = (
            _display_aws_mapping_display.rule(prop, root)
            if not _display_aws_mapping_display.compact_group(prop)
            and prop in formal_properties
            else None
        )
        alias = (
            extension.literal_link_label(prop, value)
            if mode == RESOURCE_MODE_IMPORT and extension.literal_link_label
            else None
        )
        prop = alias or (
            _display_aws_mapping_display.display_name(prop, kind, root)
            if item
            else prop.removeprefix(kind + ".")
        )
        result.append([identity, prop, value, comment])
        processed.extend(row[0] for row in rows[start : index + 1])
        index += 1
    if tuple(row[0] for row in rows) != source_ids or Counter(processed) != Counter(
        source_ids
    ):
        raise ValueError(
            "selected display rows were omitted or consumed more than once"
        )
    if extension.display is not None:
        result = extension.display(result, kind, mode=mode)
    if consumed is not None:
        consumed.extend(processed)
    return result
