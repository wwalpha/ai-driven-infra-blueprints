"""GuardDuty Features restoration."""

import re

from model.core import literal

from design.services.definitions.guardduty import (
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
