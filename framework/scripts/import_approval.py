"""Read-only Import review. Local integrity seals are not Human authorization."""
from datetime import datetime, timedelta
from model_core import LINK, entries
from model_files import resource_row_index
from model_templates import Expansion, REFERENCE_NAME_SUFFIXES
from import_guard import digest, require_fresh_acquisition, validate_inventory
from import_sources import selection_records, verify_values, typed_row, typed_equal, has_reference, pending_items
from import_inventory import type_name


def require_human_approval():
    # No agent-inaccessible approval issuer/verifier is available in this runtime.
    raise ValueError('IMPORT Human approval unavailable: a Human-only trusted interface must bind '
                     'the Review digest, Task, Worktree, scope, acquisition, baseline, selected '
                     'records/changes/risks and expiry; local JSON, flags and HMAC seals cannot authorize publication')


def build_review(acquisition, selection, before, proposed, risks, property_schema):
    """Validate an LLM-authored proposed expanded snapshot; never edit source files."""
    require_fresh_acquisition(acquisition)
    if not isinstance(proposed, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                             for k, v in proposed.items()):
        raise ValueError('IMPORT Review proposedValues must be expanded Model string fields')
    proposed = {**before.values, **proposed}
    records = acquisition['records']
    inventory = validate_inventory(acquisition)
    if any(record['kind'] not in inventory for record in records):
        raise ValueError('IMPORT Review inventory must cover every acquired Resource Type')
    ids = {r['record'] for r in records}
    if len(ids) != len(records) or not isinstance(risks, dict) or set(risks) != ids or any(
            not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items)
            for items in risks.values()):
        raise ValueError('IMPORT Review risks must cover every acquired record exactly once')
    warnings, matching = [], {}
    selected = selection_records(selection, records, before.values, proposed, property_schema,
                                 warnings, matching=matching)
    for key, value in before.values.items():
        if proposed.get(key) == value:
            continue
        parts = key.split('.')
        owner = parts[2].rpartition('-')[0] if len(parts) == 4 and parts[1] == 'row' else parts[2] if len(parts) == 4 and parts[1] == 'resource' else None
        if owner not in selected:
            raise ValueError('IMPORT Review changes an unselected Resource or service field: ' + key)
    after = Expansion(proposed, {}, {})
    verify_values(before, after, selected, property_schema, warnings=warnings)
    pending = pending_items(selection, selected, proposed, property_schema)
    old_resources = dict(entries(before.values, 'desired.resource.'))
    new_resources = dict(entries(proposed, 'desired.resource.'))
    old_rows, new_rows = resource_row_index(before.values), resource_row_index(proposed)
    decisions = {item['record']: item for item in selection['resources']}
    decisions.update({item['record']: {**item, 'action': 'excluded'} for item in selection['excluded']})
    decisions.update({item['record']: {**item, 'action': 'unresolved'}
                      for item in selection['unreflected'] if 'property' not in item})

    def rows(values, indexed, rid, prop):
        result = []
        for row_id, row in indexed.get(rid, []):
            if row['property'] != prop:
                continue
            raw = row.get('document', row['value'])
            value = raw if LINK.fullmatch(raw) or '<<' in raw else typed_row(row, raw, property_schema(prop))
            current = values.get('observed.row.' + row_id + '.value')
            result.append({'row': row_id, 'desired': value,
                           'nativeType': {str: 'string', bool: 'boolean', int: 'integer', float: 'number',
                                          list: 'array', dict: 'object', type(None): 'null'}[type(value)],
                           'observed': None if current is None else typed_row(
                               {'property': prop}, current, property_schema(prop)),
                           'observedPresent': current is not None,
                           'reference': raw if has_reference(raw) or '<<' in raw else None})
        return result

    dispositions = []
    for record in records:
        decision = decisions[record['record']]
        rid = decision.get('resource')
        details = matching[record['record']]
        # Excluded/unresolved records still show their existing exact matches.
        existing = details['existingResources']
        prior = rid if rid in old_resources else existing[0] if len(existing) == 1 else None
        properties = []
        for prop, capture in sorted(record['properties'].items()):
            withheld = capture.get('reason') == 'sensitive Property'
            left = [] if withheld else rows(before.values, old_rows, prior, prop)
            right = left if rid is None else [] if withheld else rows(proposed, new_rows, rid, prop)
            properties.append({'property': prop, 'acquisition': capture,
                               'before': left, 'after': right, 'changed': not typed_equal(left, right)})
        names = {p: c['value'] for p, c in record['properties'].items()
                 if p.endswith(REFERENCE_NAME_SUFFIXES) and c.get('status') == 'captured'}
        tag_keys = record['properties'].get(record['kind'] + '.Tags[].Key', {}).get('value')
        tag_values = record['properties'].get(record['kind'] + '.Tags[].Value', {}).get('value')
        if isinstance(tag_keys, list) and isinstance(tag_values, list) and len(tag_keys) == len(tag_values):
            tagged = [value for key, value in zip(tag_keys, tag_values) if key == 'Name']
            if tagged:
                names['Tags[Name]'] = tagged
        dispositions.append({
            'record': record['record'], 'resourceType': record['kind'], 'awsResourceType': type_name(record['kind']),
            'physicalId': record.get('identityComponents', record['identity']),
            'name': names or {'status': 'not-acquired'}, 'matching': details,
            'operation': decision['action'], 'targetResource': rid, 'reason': decision['reason'],
            'beforeResource': old_resources.get(prior), 'afterResource': new_resources.get(rid),
            'properties': properties,
            'unreflected': [item for item in pending if item['record'] == record['record']],
            'risks': [*risks[record['record']], *[w for w in warnings if w.get('record') == record['record']
                      or rid is not None and w.get('resource') == rid]]})
    review = {'version': 1, 'task': acquisition['task'], 'worktree': acquisition['root'],
              'scope': acquisition['scope'], 'connection': acquisition['connection'],
              'acquiredAt': acquisition['acquiredAt'], 'acquisitionDigest': digest(acquisition),
              'expiresAt': (datetime.fromisoformat(acquisition['acquiredAt']) + timedelta(days=7)).isoformat(),
              'sourceBaselineDigest': digest(acquisition['sources']),
              'inventory': inventory, 'selection': selection,
              'dispositions': dispositions, 'warnings': warnings,
              'proposedValuesDigest': digest(proposed), 'approvalBoundary': 'unavailable'}
    return {**review, 'reviewDigest': digest(review)}


def verify_review(review, expected):
    """Integrity/meaning comparison only; a matching digest never grants approval."""
    content = {key: value for key, value in review.items() if key != 'reviewDigest'}
    if review.get('reviewDigest') != digest(content) or not typed_equal(review, expected):
        raise ValueError('IMPORT Review changed or stale; present the changed records/values/references/risks again')
