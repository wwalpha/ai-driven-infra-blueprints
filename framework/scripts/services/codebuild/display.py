"""design/services/codebuild.py display and restoration."""

import re

from contracts.model import RESOURCE_MODE_CREATE, RESOURCE_MODE_IMPORT
from model.core import LINK, ReferenceResolutionError, literal

from ..contracts import (
    DisplayExtension,
    DisplayReferenceError,
    DisplayRowError,
    DisplayRowGroup,
    RestoredRowGroup,
)
from .design import (
    ARRAY_VARIABLE,
    CODEBUILD_FORMAL_VARIABLE,
    CODEBUILD_SECURITY_GROUPS,
    CODEBUILD_SUBNETS,
    CODEBUILD_VARIABLE,
    CODEBUILD_VARIABLE_TYPE,
    COMPACT_ARRAY,
)
from .references import reference_policy


class PlaintextReferenceError(DisplayReferenceError):
    """A prohibited CodeBuild reference."""


def adjust_display_order(kind, order):
    """Adjust only the caller's catalog-order copy."""
    if kind == "CodeBuild.Project":
        order[CODEBUILD_SUBNETS], order[CODEBUILD_SECURITY_GROUPS] = (
            order[CODEBUILD_SECURITY_GROUPS],
            order[CODEBUILD_SUBNETS],
        )


def array_template(template):
    return ARRAY_VARIABLE.sub(r"\g<0>[]", template)


def compact_array(template):
    return bool(COMPACT_ARRAY.search(template))


def codebuild_display_row(
    rows, index, comment, *, mode=RESOURCE_MODE_CREATE, typed=False
):
    block = rows[index : index + 3]
    if [row[1] for row in block] != [
        CODEBUILD_FORMAL_VARIABLE + field for field in ("Name", "Type", "Value")
    ]:
        raise ValueError("CodeBuild variables require contiguous Name/Type/Value rows")
    name, variable_type, value = [literal(row[2]) for row in block]
    if variable_type not in {"PLAINTEXT", "PARAMETER_STORE", "SECRETS_MANAGER"}:
        raise ValueError(
            "invalid CodeBuild environment variable Type: " + variable_type
        )
    prop = CODEBUILD_VARIABLE + name
    if (typed or LINK.fullmatch(block[2][2])) and (
        error := reference_policy(
            CODEBUILD_FORMAL_VARIABLE.removeprefix("CodeBuild.Project.") + "Value",
            {"Type": variable_type},
        ).error
    ):
        raise ValueError(
            f"{prop}: Name={name}, Type={variable_type}, Property={CODEBUILD_FORMAL_VARIABLE}Value: {error}"
        )
    if LINK.fullmatch(block[2][2]):
        value = block[2][2]
        comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
    elif variable_type == "PLAINTEXT":
        value = block[2][2]
    elif (typed or mode == RESOURCE_MODE_IMPORT) and variable_type in {
        "PARAMETER_STORE",
        "SECRETS_MANAGER",
    }:
        value = block[2][2]
        comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
    else:
        raise ReferenceResolutionError(
            "CodeBuild non-PLAINTEXT variables require a resource link"
        )
    return [rows[index][0], prop, value, comment]


def codebuild_formal_rows(cells, names, *, mode=RESOURCE_MODE_CREATE, typed=False):
    prop = cells[1]
    prefix = CODEBUILD_VARIABLE.removesuffix(".")
    if prop.startswith(prefix + "["):
        indexed = re.fullmatch(re.escape(prefix) + r"\[([1-9]\d*)\]\.(.+)", prop)
        if indexed is None or int(indexed[1]) != len(names) + 1:
            raise ValueError(
                "CodeBuild variable indexes must start at 1 and be sequential"
            )
        name = indexed[2]
    else:
        name = prop.removeprefix(CODEBUILD_VARIABLE)
    if not re.fullmatch(r"[^.\s|]+", name) or name in names:
        raise ValueError(
            f"invalid or duplicate CodeBuild environment variable name: {name}"
        )
    names.add(name)
    raw = cells[2]
    if len(raw) >= 2 and raw[0] == raw[-1] == "`":
        raw = raw[1:-1]
    marker = CODEBUILD_VARIABLE_TYPE.match(cells[3])
    linked = re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2])
    if cells[2].startswith("[") and "](" in cells[2] and not linked:
        raise ReferenceResolutionError(
            f"CodeBuild resource variable must use a single resource anchor link: {name}"
        )
    if "<!-- codebuild-variable-type:" in cells[3] and not marker:
        raise ValueError(f"invalid CodeBuild environment variable Type marker: {name}")
    variable_type = marker.group(1) if marker else "PLAINTEXT"
    if linked and (
        error := reference_policy(
            CODEBUILD_FORMAL_VARIABLE.removeprefix("CodeBuild.Project.") + "Value",
            {"Type": variable_type},
        ).error
    ):
        raise PlaintextReferenceError(
            f"Name={name}, Type={variable_type}, Property={CODEBUILD_FORMAL_VARIABLE}Value: {error}",
            positions=(
                {"name": name, "property": CODEBUILD_FORMAL_VARIABLE + "Value"},
            ),
        )
    if marker and not linked and mode != RESOURCE_MODE_IMPORT and not typed:
        raise ReferenceResolutionError(
            f"CodeBuild resource variable requires a link and Type marker: {name}"
        )
    if re.match(r"^(PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER):", raw):
        raise ValueError(
            f"CodeBuild environment variable must omit the Type prefix: {name}"
        )
    comment = cells[3][marker.end() :] if marker else cells[3]
    value = cells[2] if linked else f"`{raw}`"
    return [
        [cells[0], CODEBUILD_FORMAL_VARIABLE + field, field_value, comment]
        for field, field_value in (
            ("Name", f"`{name}`"),
            ("Type", f"`{variable_type}`"),
            ("Value", value),
        )
    ]


def render_group(rows, index, /, *, mode, counts, references):
    prop = rows[index][1]
    if prop == CODEBUILD_FORMAL_VARIABLE + "Name":
        block = rows[index : index + 3]
        typed = len(block) == 3 and block[2][0] in references
        row = codebuild_display_row(rows, index, rows[index][3], mode=mode, typed=typed)
        return DisplayRowGroup(row, tuple(item[0] for item in block))
    if prop.startswith(CODEBUILD_FORMAL_VARIABLE):
        raise ValueError(f"incomplete compact display group: {prop}")
    return None


def restore_group(row, display_property, /, *, mode, counts, names, verified):
    prop = row[1]
    if prop.startswith(CODEBUILD_FORMAL_VARIABLE):
        raise ValueError(
            "CodeBuild environment variables must use Variables.<Name> display rows"
        )
    if prop.startswith(
        (CODEBUILD_VARIABLE, CODEBUILD_VARIABLE.removesuffix(".") + "[")
    ):
        try:
            rows = codebuild_formal_rows(row, names, mode=mode, typed=verified)
        except (ReferenceResolutionError, PlaintextReferenceError):
            raise
        except ValueError as error:
            raise DisplayRowError(str(error)) from error
        return RestoredRowGroup(rows, "CodeBuild environment variable")
    return None


def linked_list_error(row, mode, references):
    if (
        mode != RESOURCE_MODE_IMPORT
        and row[1] in {CODEBUILD_SUBNETS, CODEBUILD_SECURITY_GROUPS}
        and row[0] not in references
    ):
        return "CodeBuild VpcConfig value must be a resource link"
    return None


def compact_group(prop):
    return (
        CODEBUILD_FORMAL_VARIABLE
        if prop.startswith(CODEBUILD_FORMAL_VARIABLE)
        else None
    )


EXTENSIONS = {
    "CodeBuild.Project": DisplayExtension(
        array_template=array_template,
        compact_array=compact_array,
        compact_group=compact_group,
        adjust_order=adjust_display_order,
        validate_adjusted_order=True,
        render_group=render_group,
        restore_group=restore_group,
        validate_linked_list=linked_list_error,
    )
}
