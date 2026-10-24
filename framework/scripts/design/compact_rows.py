"""design/compact_rows.py display and restoration."""

import json
from functools import partial as _bind_framework_callback

from model.core import LINK, literal

from design.services.definitions.registry import COMPACT_FIELDS, PACKED_ARRAY_PREFIXES


def _recursive_packed_compact_rows_expand(block, values, prefix):
    if any(not isinstance(value, list) or len(value) != len(values[0]) for value in values):
        raise ValueError('packed array dimensions differ')
    result = []
    for children in zip(*values, strict=False):
        cursor = 0
        while cursor < len(block):
            row, value = block[cursor], children[cursor]
            end = row[1].find('[]', len(prefix))
            if end == -1:
                raw = value if isinstance(value, str) and LINK.fullmatch(value) else '`' + (value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))) + '`'
                result.append([row[0], row[1], raw, row[3]])
                cursor += 1
                continue
            child_prefix = row[1][:end + 2]
            stop = cursor + 1
            while stop < len(block) and block[stop][1].startswith(child_prefix):
                stop += 1
            result.extend(_recursive_packed_compact_rows_expand(block[cursor:stop], children[cursor:stop], child_prefix))
            cursor = stop
    return result


def _recursive_packed_compact_rows_unpack(block, fields, result, vector, /, values):
    if isinstance(values[0], list):
        if any(not isinstance(value, list) or len(value) != len(values[0]) for value in values):
            raise ValueError('packed compact array dimensions differ')
        for children in zip(*values, strict=False):
            _recursive_packed_compact_rows_unpack(block, fields, result, vector, children)
        return
    groups = [values]
    if vector and isinstance(values[fields.index(vector)], list):
        groups = [[value if field != vector else item for field, value in zip(fields, values, strict=False)]
                  for item in values[fields.index(vector)]]
    for group in groups:
        if any(not isinstance(value, str) for value in group):
            raise ValueError('compact fields require string leaves')
        result.extend([[row[0], row[1], value if LINK.fullmatch(value) else '`' + value + '`', row[3]]
                       for row, value in zip(block, group, strict=False)])


def packed_compact_rows(rows, index):
    """Unpack acquired array dimensions before the existing compact renderers."""
    for prefix in PACKED_ARRAY_PREFIXES:
        if rows[index][1].startswith(prefix + '.'):
            try:
                value = json.loads(literal(rows[index][2]))
            except ValueError:
                return None
            if not isinstance(value, list):
                return None
            stop = index
            while stop < len(rows) and rows[stop][1].startswith(prefix + '.'):
                stop += 1
            block = rows[index:stop]
            values = [json.loads(literal(row[2])) for row in block]
            expand = _recursive_packed_compact_rows_expand
            expanded = expand(block, values, prefix)
            if not expanded:
                raise ValueError('empty packed array display group')
            return block, expanded
    if rows[index][1] not in COMPACT_FIELDS:
        return None
    fields, vector = COMPACT_FIELDS[rows[index][1]]
    try:
        shape = json.loads(literal(rows[index][2]))
    except ValueError:
        return None
    if not isinstance(shape, list):
        return None
    block = rows[index:index + len(fields)]
    prefix = rows[index][1].rsplit('.', 1)[0] + '.'
    if [row[1] for row in block] != [prefix + field for field in fields]:
        raise ValueError('packed compact fields must be contiguous')
    values = [json.loads(literal(row[2])) for row in block]
    result = []
    unpack = _bind_framework_callback(_recursive_packed_compact_rows_unpack, block, fields, result, vector)
    unpack(values)
    if not result:
        raise ValueError('empty packed compact display group')
    return block, result
