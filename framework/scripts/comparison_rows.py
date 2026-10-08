"""Catalog row construction and path selection; no input acquisition."""
import re

MISSING = {"absent": True}


class Unresolved(ValueError):
    pass


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
    """Catalog-ordered repeated rows: a repeated scalar starts a new array element."""
    part, _, rest = path.partition(".")
    indexed = re.fullmatch(r"(.+)\[(\d+)\]", part)
    if indexed:
        name, number = indexed.group(1), int(indexed.group(2)) - 1
        array = tree.setdefault(name, [])
        while len(array) <= number:
            array.append({})
        put_row(array[number], rest, value)
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


