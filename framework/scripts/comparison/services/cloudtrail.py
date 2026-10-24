"""cloudtrail comparison contracts and projections."""

import re

import model.display as _imports_model_display
from design.policy_tables import literal
from utils.cloudformation.inputs import Blocked
from utils.comparison_rows import Unresolved, put_row


def cloudtrail_rows(rows, *, index_rows):
    """Project fixed Model row identities through the lossless indexed display."""
    display_rows = _imports_model_display.display_rows

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
        displayed = index_rows(display_rows(kind, [[rid, row['property'], row['value'], row.get('comment', '')]
                                                    for rid, row in canonical]), kind)
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

prepare_rows = cloudtrail_rows

def contexts(rows):
    contexts = {}
    for _, row in rows:
        prop = row['property'].removeprefix('CloudTrail.Trail.')
        data = re.fullmatch(r'(.*\.DataResources\[\d+\])\.Type', prop)
        if data:
            put_row(contexts.setdefault(data[1], {}), 'Type', literal(row['value']))
    return contexts


def reference_contract(path, attribute, context):
    if path != 'EventSelectors[].DataResources[].Values[]':
        return NotImplemented
    if context.get('Type', 'AWS::Lambda::Function') != 'AWS::Lambda::Function':
        raise Blocked('CloudTrail DataResource link requires a confirmed Lambda ARN; other resource/prefix contracts are unproven')
    return 'Lambda.Function', 'Arn'

DEFERRED_ROWS = 'EventSelectors'
