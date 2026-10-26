"""Explicit row values and path projections; never infer shape from native types."""

import re
from dataclasses import dataclass

from utils.json_format import strict_json


def value_shape(row):
    shape = row.get("valueShape", "leaf")
    if not isinstance(shape, str) or shape not in {"leaf", "projection"}:
        raise ValueError("valueShape must be leaf or projection")
    return shape


def array_paths(prop):
    """A terminal [] selects items too; an unmarked array Property stays a leaf."""
    return tuple(prop[: match.start()] for match in re.finditer(r"\[\]", prop))


def projection_conflicts(rows):
    """Whole columns cannot establish membership for mixed or repeated row groups."""
    groups = {}
    for _, row in rows:
        prop = row["property"]
        setting = re.sub(r"\[\d*\]", "", prop.split(".", 2)[-1].split(".", 1)[0])
        groups.setdefault(setting, []).append((prop, value_shape(row)))
    return {
        setting: "ambiguous leaf/projection array membership: " + setting
        for setting, members in groups.items()
        if any(shape == "projection" for _, shape in members)
        and (
            any(shape == "leaf" for _, shape in members)
            or len({prop for prop, _ in members}) != len(members)
        )
    }


@dataclass(frozen=True)
class LiteralValues:
    values: tuple
    arrays: tuple


def normalize(prop, value, shape="leaf"):
    value_shape({"valueShape": shape})
    values, arrays = [value], []
    if shape == "projection":
        paths = array_paths(prop)
        if not paths:
            raise ValueError("projection requires an array path: " + prop)
        for path in paths:
            expanded = []
            for current in values:
                if not isinstance(current, list):
                    raise ValueError("projection parent must be array: " + path)
                arrays.append((path, current))
                expanded.extend(current)
            values = expanded
    return LiteralValues(tuple(values), tuple(arrays))


def typed_value(row, raw, schema):
    """Decode by the declared shape/schema, preserving the saved native value."""
    shape = value_shape(row)
    if "document" in row:
        value = strict_json(row["document"])
        if shape == "projection":
            normalize(row["property"], value, shape)
        return value
    value = raw[1:-1] if raw.startswith("`") and raw.endswith("`") else raw
    types = schema.get("type")
    if shape == "projection":
        value = strict_json(value)
        normalize(row["property"], value, shape)
        return value
    if types == "string" or not types:
        return value
    try:
        return strict_json(value)
    except ValueError:
        if isinstance(types, list) and "string" in types:
            return value
        raise ValueError(
            "candidate Property has an invalid native type: " + row["property"]
        ) from None


def projection_value(prop, rows):
    """Put explicit leaf rows on acquisition's projection axes without guessing groups."""
    if not rows:
        return None
    paths = array_paths(prop)
    projected = [value for shape, value in rows if shape == "projection"]
    if projected:
        if len(rows) != 1:
            raise ValueError("ambiguous projection rows: " + prop)
        normalize(prop, projected[0], "projection")
        return projected[0]
    if not paths:
        if len(rows) != 1:
            raise ValueError("ambiguous candidate Property: " + prop)
        return rows[0][1]
    if len(paths) > 1 and len(rows) > 1:
        raise ValueError("ambiguous parent array membership: " + prop)
    result = [value for _, value in rows]
    for _ in paths[1:]:
        result = [result]
    return result


def literal_errors(catalog, kind, field, raw, shape="leaf"):
    """Validate only projected axes and schema leaves, including empty parents."""
    value_shape({"valueShape": shape})
    if shape == "leaf":
        return catalog.literal_errors(kind, field, raw)
    try:
        normalized = normalize(field, strict_json(raw), shape)
    except ValueError as error:
        return [str(error)]
    return validation_errors(catalog, kind, field, normalized)


def validation_errors(catalog, kind, field, normalized):
    # Even an empty parent must resolve the complete schema path.
    catalog.property_schema(kind, field)
    errors = []
    for path, array in normalized.arrays:
        errors.extend(
            f"{path}: {error}" for error in catalog.array_errors(kind, path, array)
        )
    for value in normalized.values:
        errors.extend(catalog.typed_literal_errors(kind, field, value))
    return errors
