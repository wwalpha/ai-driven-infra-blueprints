"""GuardDuty Features restoration."""

import re

from model.core import literal

from ..contracts import DisplayExtension, DisplayRowGroup, RestoredRowGroup
from .design import (
    ARRAY_FEATURE,
    COMPACT_ARRAY,
    GUARDDUTY_FEATURE,
    GUARDDUTY_FORMAL_FEATURE,
)


def array_template(template):
    return ARRAY_FEATURE.sub(r"\g<0>[]", template)


def compact_array(template):
    return bool(COMPACT_ARRAY.search(template))


def formal_rows(cells, names):
    prop = cells[1]
    guardduty_names = names
    result = []
    name = prop.removeprefix(GUARDDUTY_FEATURE)
    if not re.fullmatch(r"[^.\s|]+", name) or name in guardduty_names:
        raise ValueError(f"invalid or duplicate GuardDuty Feature name: {name}")
    guardduty_names.add(name)
    status = cells[2]
    if len(status) >= 2 and status[0] == status[-1] == "`":
        status = status[1:-1]
    for field, field_value in (("Name", name), ("Status", status)):
        result.append(
            [cells[0], GUARDDUTY_FORMAL_FEATURE + field, f"`{field_value}`", cells[3]]
        )
    return result


def display_row(rows, index):
    value = rows[index][2]
    if (
        index + 1 >= len(rows)
        or rows[index + 1][1] != GUARDDUTY_FORMAL_FEATURE + "Status"
    ):
        raise ValueError("GuardDuty features require contiguous Name/Status rows")
    prop = GUARDDUTY_FEATURE + literal(value)
    value = rows[index + 1][2]

    return prop, value


def incomplete_feature(prop: str) -> bool:
    return prop.startswith(GUARDDUTY_FORMAL_FEATURE) and not prop.startswith(
        GUARDDUTY_FORMAL_FEATURE + "AdditionalConfiguration"
    )


def render_group(rows, index, /, *, mode, counts, references):
    identity, prop, _, comment = rows[index]
    if prop == GUARDDUTY_FORMAL_FEATURE + "Name":
        name, value = display_row(rows, index)
        return DisplayRowGroup(
            [identity, name, value, comment], (identity, rows[index + 1][0])
        )
    if incomplete_feature(prop):
        raise ValueError(f"incomplete compact display group: {prop}")
    return None


def restore_group(row, display_property, /, *, mode, counts, names, verified):
    validate_display_property(row[1])
    if row[1].startswith(GUARDDUTY_FEATURE):
        return RestoredRowGroup(formal_rows(row, names), "GuardDuty Feature")
    return None


def validate_display_property(prop: str) -> None:
    if prop in {GUARDDUTY_FORMAL_FEATURE + "Name", GUARDDUTY_FORMAL_FEATURE + "Status"}:
        raise ValueError(
            "GuardDuty Features Name/Status must use Features.<Name> display rows"
        )


def compact_group(prop):
    return (
        GUARDDUTY_FORMAL_FEATURE if prop.startswith(GUARDDUTY_FORMAL_FEATURE) else None
    )


EXTENSION = DisplayExtension(
    render_group=render_group,
    restore_group=restore_group,
    array_template=array_template,
    compact_array=compact_array,
    compact_group=compact_group,
)
