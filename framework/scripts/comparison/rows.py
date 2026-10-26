"""Prepare meaningful grouped settings without changing child/array membership."""

import re

import design.policy_tables as _imports_policy_tables
from model.literal_values import projection_conflicts, value_shape
from utils.comparison_rows import Unresolved, put_row


def grouped_rows(resource, rows):
    grouped = {}
    all_rows = list(rows)
    if (
        resource.get("parentReference")
        and resource.get("parentProperty")
        and not any(
            row["property"] == resource["parentProperty"] for _, row in all_rows
        )
    ):
        all_rows.append(
            (
                "@parent",
                {
                    "property": resource["parentProperty"],
                    "value": resource["parentReference"],
                    "comment": "grouped parent identity",
                },
            )
        )
    for rid, row in all_rows:
        kind = ".".join(row["property"].split(".")[:2])
        grouped.setdefault(kind, []).append((rid, row))
    return grouped


def validated_rows(kind, rows):
    conflicts = projection_conflicts(rows)
    unresolved = {}
    for rid, row in rows:
        short = row["property"].removeprefix(kind + ".")
        setting = re.sub(r"\[(?:\d*)\]", "", short.split(".", 1)[0])
        if setting in conflicts:
            unresolved.setdefault(setting, (rid, conflicts[setting]))
            continue
        if value_shape(row) == "projection":
            continue
        try:
            put_row({}, short, None)
        except Unresolved as error:
            unresolved.setdefault(setting, (rid, str(error)))
    return (
        [
            (rid, row)
            for rid, row in rows
            if re.sub(
                r"\[(?:\d*)\]",
                "",
                row["property"].removeprefix(kind + ".").split(".", 1)[0],
            )
            not in unresolved
        ],
        unresolved,
    )


def name_tag(kind, short, raw, name_tag_kinds):
    if short == "Name" and kind in name_tag_kinds:
        literal = _imports_policy_tables.literal
        return "Tags[]", {"Key": "Name", "Value": literal(raw)}
    return None


def selected_rows(kind, rows, properties):
    return [
        (rid, row)
        for rid, row in rows
        if any(
            row["property"] == kind + "." + prop
            or row["property"].startswith(
                (kind + "." + prop + ".", kind + "." + prop + "[")
            )
            for prop in properties
        )
    ]
