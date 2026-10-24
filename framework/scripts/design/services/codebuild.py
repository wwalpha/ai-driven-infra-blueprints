"""design/services/codebuild.py display and restoration."""

import re

from model.core import LINK, ReferenceResolutionError, literal

from design.services.definitions.codebuild import (
    ARRAY_VARIABLE,
    CODEBUILD_FORMAL_VARIABLE,
    CODEBUILD_SECURITY_GROUPS,
    CODEBUILD_SUBNETS,
    CODEBUILD_VARIABLE,
    CODEBUILD_VARIABLE_TYPE,
    COMPACT_ARRAY,
)


def adjust_display_order(kind, order):
    """Adjust only the caller's catalog-order copy."""
    if kind == "CodeBuild.Project":
        order[CODEBUILD_SUBNETS], order[CODEBUILD_SECURITY_GROUPS] = order[CODEBUILD_SECURITY_GROUPS], order[CODEBUILD_SUBNETS]


def array_template(template):
    return ARRAY_VARIABLE.sub(r"\g<0>[]", template)


def compact_array(template):
    return bool(COMPACT_ARRAY.search(template))


def codebuild_display_row(rows, index, comment, *, mode="CREATE"):
    block = rows[index:index + 3]
    if [row[1] for row in block] != [CODEBUILD_FORMAL_VARIABLE + field for field in ("Name", "Type", "Value")]:
        raise ValueError("CodeBuild variables require contiguous Name/Type/Value rows")
    name, variable_type, value = [literal(row[2]) for row in block]
    if variable_type not in {"PLAINTEXT", "PARAMETER_STORE", "SECRETS_MANAGER"}:
        raise ValueError("invalid CodeBuild environment variable Type: " + variable_type)
    prop = CODEBUILD_VARIABLE + name
    if LINK.fullmatch(block[2][2]):
        value = block[2][2]
        comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
    elif variable_type == "PLAINTEXT":
        value = block[2][2]
    elif mode == "IMPORT" and variable_type in {"PARAMETER_STORE", "SECRETS_MANAGER"}:
        value = block[2][2]
        comment = f"<!-- codebuild-variable-type: {variable_type} --> {comment}"
    else:
        raise ReferenceResolutionError("CodeBuild non-PLAINTEXT variables require a resource link")
    return [rows[index][0], prop, value, comment]


def codebuild_formal_rows(cells, names, *, mode="CREATE"):
    name = cells[1].removeprefix(CODEBUILD_VARIABLE)
    if not re.fullmatch(r"[^.\s|]+", name) or name in names:
        raise ValueError(f"invalid or duplicate CodeBuild environment variable name: {name}")
    names.add(name)
    raw = cells[2]
    if len(raw) >= 2 and raw[0] == raw[-1] == "`":
        raw = raw[1:-1]
    marker = CODEBUILD_VARIABLE_TYPE.match(cells[3])
    linked = re.fullmatch(r"\[[^\]]+\]\([^)]*#[^)]+\)", cells[2])
    if cells[2].startswith("[") and "](" in cells[2] and not linked:
        raise ReferenceResolutionError(f"CodeBuild resource variable must use a single resource anchor link: {name}")
    if "<!-- codebuild-variable-type:" in cells[3] and not marker:
        raise ValueError(f"invalid CodeBuild environment variable Type marker: {name}")
    if linked and not marker:
        raise ValueError(f"CodeBuild resource variable requires a link and Type marker: {name}")
    if marker and not linked and mode != "IMPORT":
        raise ReferenceResolutionError(f"CodeBuild resource variable requires a link and Type marker: {name}")
    if re.match(r"^(PLAINTEXT|PARAMETER_STORE|SECRETS_MANAGER):", raw):
        raise ValueError(f"CodeBuild environment variable must omit the Type prefix: {name}")
    variable_type = marker.group(1) if marker else "PLAINTEXT"
    comment = cells[3][marker.end():] if marker else cells[3]
    value = cells[2] if linked else f"`{raw}`"
    return [[cells[0], CODEBUILD_FORMAL_VARIABLE + field, field_value, comment]
            for field, field_value in (("Name", f"`{name}`"), ("Type", f"`{variable_type}`"), ("Value", value))]
