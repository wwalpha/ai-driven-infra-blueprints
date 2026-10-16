"""Catalog row construction and path selection; no input acquisition."""
import re

MISSING = {"absent": True}


class Unresolved(ValueError):
    pass


def cloudtrail_rows(rows, root):
    """Project fixed Model row identities through the lossless indexed display."""
    from array_display import indexed_rows
    from model_display import display_rows

    kind = 'CloudTrail.Trail'
    prefix = kind + '.EventSelectors[]'
    selected = [(rid, row) for rid, row in rows if row['property'].startswith(prefix + '.')]
    if not any('.DataResources[]' in row['property'] for _, row in selected):
        return rows
    # Model entries have fixed IDs; the caller's list order is not membership evidence.
    if len(dict(selected)) != len(selected) or any(not re.fullmatch(r'.+-[0-9]+', rid) for rid, _ in selected):
        raise Unresolved('array membership unresolved: EventSelectors; fixed Model row identities required')
    canonical = sorted(selected)
    if any(row['property'].startswith(kind + '.EventSelectors') and
           not row['property'].startswith(prefix + '.') for _, row in rows):
        raise Unresolved('array membership unresolved: EventSelectors; mixed whole/indexed/wildcard rows')
    try:
        displayed = indexed_rows(display_rows(kind, [[rid, row['property'], row['value'], row.get('comment', '')]
                                                    for rid, row in canonical]), kind, root)
    except ValueError as error:
        raise Unresolved(f'array membership unresolved: EventSelectors; {error}') from error
    partners = {rid: canonical[index + 1][0] for index, (rid, row) in enumerate(canonical)
                if row['property'] == prefix + '.DataResources[].Type'}
    properties = {}
    for rid, prop, _, _ in displayed:
        if rid in properties:
            raise Unresolved('array membership unresolved: EventSelectors; display row maps to multiple elements')
        data = re.fullmatch(r'(EventSelectors\[[1-9]\d*\]\.DataResources\[[1-9]\d*\])\.(S3|Lambda)', prop)
        if data:
            properties[rid] = kind + '.' + data[1] + '.Type'
            properties[partners[rid]] = kind + '.' + data[1] + '.Values'
        else:
            properties[rid] = kind + '.' + prop
    if properties.keys() != dict(canonical).keys():
        raise Unresolved('array membership unresolved: EventSelectors; incomplete display-to-Model mapping')
    return [(rid, dict(row, property=properties[rid]) if rid in properties else row) for rid, row in rows]


def select(value, path):
    if not path:
        return value
    part, _, rest = path.partition(".")
    array = part.endswith("[]")
    child = value.get(part.removesuffix("[]"), MISSING) if isinstance(value, dict) else MISSING
    if array:
        if child == MISSING:
            return MISSING
        if not isinstance(child, list):
            raise Unresolved("SDK response has an invalid array type")
        return [select(item, rest) for item in child] if rest else child
    return select(child, rest) if rest else child


def put_row(tree, path, value):
    """Use explicit membership for nested arrays; retain simple repeated rows."""
    arrays = re.findall(r"[^.]+\[(?:\d+)?\]", path)
    if len(arrays) > 1:
        for part in path.split('.')[:-1]:
            if part.endswith('[]'):
                raise Unresolved(f"array membership unresolved: {path}; {part} has no element index; "
                                 "row order does not identify parent/child membership or omitted fields")
    part, _, rest = path.partition(".")
    indexed = re.fullmatch(r"(.+)\[(\d+)\]", part)
    if indexed:
        name, number = indexed.group(1), int(indexed.group(2)) - 1
        if number < 0:
            raise Unresolved(f"array indexes are one-based: {path}")
        array = tree.setdefault(name, [])
        while len(array) <= number:
            array.append({})
        if rest:
            put_row(array[number], rest, value)
        else:
            array[number] = value
    elif part.endswith("[]"):
        name = part[:-2]
        array = tree.setdefault(name, [])
        if not rest:
            array.extend(value if isinstance(value, list) else [value])
        else:
            if not array or ("[]" not in rest and select(array[-1], rest) != MISSING):
                array.append({})
            put_row(array[-1], rest, value)
    elif rest:
        put_row(tree.setdefault(part, {}), rest, value)
    elif part in tree:
        # Repeated list-valued rows are individual resource references.
        old = tree[part]
        tree[part] = (old if isinstance(old, list) else [old]) + (value if isinstance(value, list) else [value])
    else:
        tree[part] = value


