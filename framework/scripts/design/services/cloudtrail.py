"""CloudTrail DataResources restoration."""

import re

from model.core import ReferenceResolutionError, literal

from design.services.definitions.cloudtrail import (
    ARRAY_DATA_RESOURCE,
    ARRAY_DATA_RESOURCE_PREFIX,
    ARRAY_DATA_RESOURCE_TEMPLATE,
    CLOUDTRAIL_DATA_RESOURCE,
    CLOUDTRAIL_FORMAL_DATA_RESOURCE,
    CLOUDTRAIL_RESOURCE_TYPES,
    COMPACT_ARRAY,
)


def array_template(template):
    if ARRAY_DATA_RESOURCE.search(template):
        return ARRAY_DATA_RESOURCE_PREFIX.sub(ARRAY_DATA_RESOURCE_TEMPLATE, template)
    return template


def compact_array(template):
    return bool(COMPACT_ARRAY.search(template))


def formal_rows(cells, display_property, count, mode):
    prop = cells[1]
    result = []
    match = CLOUDTRAIL_DATA_RESOURCE.fullmatch(display_property)
    if not match or int(match.group(1)) != count + 1:
        raise ValueError(
            "CloudTrail DataResources display indexes must start at 1 and be sequential"
        )
    resource_value = cells[2]
    if (
        match.group(2) == "S3"
        and resource_value == "`All current and future S3 buckets`"
    ):
        resource_value = '`["arn:aws:s3"]`'
    elif mode != "IMPORT" and not re.fullmatch(
        r"\[[^\]]+\]\([^)]*#[^)]+\)", resource_value
    ):
        raise ReferenceResolutionError(
            "CloudTrail DataResources value must be a resource link or, for S3, `All current and future S3 buckets`",
            property=prop,
            reference=cells[2],
        )
    for field, value in (
        ("Type", f"`{CLOUDTRAIL_RESOURCE_TYPES[match.group(2)]}`"),
        ("Values", resource_value),
    ):
        result.append(
            [cells[0], CLOUDTRAIL_FORMAL_DATA_RESOURCE + field, value, cells[3]]
        )
    return result


def display_row(rows, index, counts, mode):
    value = rows[index][2]
    if (
        index + 1 >= len(rows)
        or rows[index + 1][1] != CLOUDTRAIL_FORMAL_DATA_RESOURCE + "Values"
    ):
        raise ValueError(
            "CloudTrail data resources require contiguous Type/Values rows"
        )
    types = {value: key for key, value in CLOUDTRAIL_RESOURCE_TYPES.items()}
    if literal(value) not in types:
        raise ValueError("unsupported CloudTrail data resource type")
    counts["data"] = counts.get("data", 0) + 1
    prop = f"CloudTrail.Trail.EventSelectors.DataResources[{counts['data']}].{types[literal(value)]}"
    value = rows[index + 1][2]
    if (
        literal(value) == '["arn:aws:s3"]'
        or mode == "IMPORT"
        and literal(value) == "arn:aws:s3"
    ):
        value = "`All current and future S3 buckets`"

    return prop, value
