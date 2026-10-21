"""Check explicit acquired correspondences and preserve every unselected canonical field."""
import json
from model.core import LINK, entries, literal, resource_row_index
from model.format import owner
from model.identity import resource_link, parse_reference
from utils.json_format import strict_json as json_read

def typed_equal(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def typed_row(row, raw, schema):
    if 'document' in row:
        return json_read(row['document'])
    value = literal(raw)
    types = schema.get('type')
    if '[]' in row['property'] and value.startswith('['):
        parsed = json_read(value)
        if isinstance(parsed, list):
            return parsed
    if types == 'string':
        return value
    if types:
        try:
            value = json_read(value)
        except ValueError:
            if isinstance(types, list) and 'string' in types:
                return value
            raise ValueError('IMPORT candidate Property has an invalid native type: ' + row['property']) from None
    return value


def property_values(values, rid, prop, schema, *, observed=False, rows=None):
    result = []
    for row_id, row in (resource_row_index(values) if rows is None else rows).get(rid, []):
        if row['property'] != prop:
            continue
        raw = values.get('observed.row.' + row_id + '.value') if observed else row['value']
        if raw is None:
            continue
        if observed:
            row = {key: value for key, value in row.items() if key != 'document'}
        elif resource_link(raw) or (
                has_reference(row.get('document', raw)) and 'observed.row.' + row_id + '.value' in values):
            raw = values.get('observed.row.' + row_id + '.value')
            if raw is None:
                continue
            row = {key: value for key, value in row.items() if key != 'document'}
        result.append(typed_row(row, raw, schema))
    if '[]' in prop:
        return result[0] if len(result) == 1 and isinstance(result[0], list) else result
    if len(result) > 1:
        raise ValueError('IMPORT ambiguous candidate Property: ' + prop)
    return result[0] if result else None


def has_reference(raw):
    """Only internal Resource references, including structured leaves, consume observations."""
    from model.identity import resource_link
    if not isinstance(raw, str):
        return False
    if resource_link(raw):
        return True
    try:
        value = json_read(literal(raw))
    except ValueError:
        return False
    def linked(value):
        return (bool(resource_link(value)) if isinstance(value, str) else
                any(linked(item) for item in value.values()) if isinstance(value, dict) else
                any(linked(item) for item in value) if isinstance(value, list) else False)
    return linked(value)


def selection_records(selection, records, old, new, property_schema, warnings=None, *, matching=None):
    """Validate declared correspondences; no Python matching or addition decisions."""
    if set(selection) != {'resources', 'excluded', 'unreflected'} or any(not isinstance(selection[k], list) for k in selection):
        raise ValueError('IMPORT selection requires resources, excluded and unreflected lists')
    acquired = {r['record']: r for r in records}
    old_resources = dict(entries(old, 'desired.resource.'))
    new_resources = dict(entries(new, 'desired.resource.'))
    rows = resource_row_index(old)
    identity_properties = {}
    for record in records:
        identity_properties.setdefault(record['kind'], set()).update(
            prop for prop in record.get('identityProperties', [record['identityProperty']]) if prop)
    component_properties = {}
    for record in records:
        if 'identityComponents' in record:
            props = tuple(item['property'] for item in record['identityComponents'])
            if record['kind'] in component_properties and component_properties[record['kind']] != props:
                raise ValueError('IMPORT inconsistent primary identifier components')
            component_properties[record['kind']] = props
    owners, unknown = {}, {}
    for rid, resource in old_resources.items():
        kind = resource['resourceType']
        if kind in component_properties:
            components = []
            for prop in component_properties[kind]:
                value = property_values(old, rid, prop, property_schema(prop), observed=True, rows=rows)
                if value is None:
                    value = property_values(old, rid, prop, property_schema(prop), rows=rows)
                if value is None or value == '' or value in ('PENDING_DEPLOY', 'UNSET'):
                    break
                components.append({'property': prop, 'value': value})
            if components and len(components) == len(component_properties[kind]):
                owners.setdefault((kind, json.dumps(components, sort_keys=True)), set()).add(rid)
            else:
                unknown.setdefault(kind, []).append(rid)
            continue
        known = False
        for row_id, row in rows.get(rid, []):
            prop = row['property']
            if prop not in identity_properties.get(resource['resourceType'], set()):
                continue
            for raw in (row['value'], old.get('observed.row.' + row_id + '.value')):
                if raw is None or resource_link(raw):
                    continue
                value = typed_row(row, raw, property_schema(prop))
                if isinstance(value, str) and value.strip() and value not in {'PENDING_DEPLOY', 'UNSET'} and not resource_link(value):
                    known = True
                    owners.setdefault((resource['resourceType'], value), set()).add(rid)
        if not known:
            unknown.setdefault(resource['resourceType'], []).append(rid)
    correspondences = {}
    for record in records:
        key = (record['kind'], json.dumps(record['identityComponents'], sort_keys=True)
               if 'identityComponents' in record else record['identity'])
        collisions = owners.get(key, set())
        uncertain = unknown.get(record['kind'], [])
        correspondences[record['record']] = (key, collisions)
        if matching is not None:
            matching[record['record']] = {
                'existingResources': sorted(collisions), 'unknownResources': sorted(uncertain),
                'status': 'possible-duplicate' if len(collisions) > 1 else 'confirmed' if collisions
                          else 'unresolved' if uncertain or record.get('identityStatus', 'known') != 'known' else 'no-match'}
    selected, used, selected_identities = {}, set(), set()
    for item in selection['resources']:
        required = {'record', 'resource', 'action', 'reason', 'basis'} | ({'before'} if item.get('action') in {'replace', 'bind'} else set())
        if set(item) != required or not isinstance(item['reason'], str) or not item['reason'].strip():
            raise ValueError('IMPORT correspondence requires an action, reason and basis')
        record = acquired.get(item['record'])
        rid = item['resource']
        if record is None or item['record'] in used or rid in selected or rid not in new_resources:
            raise ValueError('IMPORT duplicate or unknown resource correspondence')
        if new_resources[rid].get('resourceMode') != 'IMPORT' or record['kind'] != new_resources[rid]['resourceType']:
            raise ValueError('IMPORT correspondence cannot change CREATE or resource type')
        action = item['action']
        if action not in {'add', 'refresh', 'replace', 'bind'} or action == 'add' and rid in old_resources:
            raise ValueError('IMPORT accepts add only with a new Resource ID; use explicit refresh/replace/bind for existing resources')
        if action != 'add' and (rid not in old_resources or old_resources[rid].get('resourceMode') != 'IMPORT'
                                or old_resources[rid]['resourceType'] != record['kind']):
            raise ValueError('IMPORT refresh/replace/bind requires an existing IMPORT Resource of the acquired type; CREATE is protected')
        basis = item['basis']
        if not isinstance(basis, list) or any(not isinstance(p, str) for p in basis) or len(basis) != len(set(basis)):
            raise ValueError('IMPORT correspondence basis must name distinct acquired Properties')
        if 'identityComponents' in record:
            if record.get('identityStatus') != 'known':
                raise ValueError('IMPORT acquired primary identity is unknown')
        if (not isinstance(record['identity'], str) or not record['identity'].strip()
                or record['identity'] in {'PENDING_DEPLOY', 'UNSET'}
                or resource_link(record['identity'])):
            raise ValueError('IMPORT acquired physical identity is invalid')
        identity_key, collisions = correspondences[record['record']]
        if action == 'bind':
            from import_guard import digest
            from model.operations import operation_values
            if rid not in unknown.get(record['kind'], []):
                raise ValueError('IMPORT bind requires an unobserved/unknown existing physical identity')
            if not typed_equal(item['before'], {'identity': None, 'model': digest(operation_values(old, rid))}):
                raise ValueError('IMPORT bind previous Model state differs from the explicit selection')
            if warnings is not None:
                warnings.append({'record': record['record'], 'resource': rid,
                                 'existingResources': unknown[record['kind']],
                                 'reason': 'Physical identity was unknown; Human-selected binding may duplicate another unobserved resource'})
        if action == 'refresh' and collisions != {rid}:
            raise ValueError('IMPORT refresh requires one matching physical identity')
        if action == 'replace':
            from import_guard import digest
            from model.operations import operation_values
            prior = [value for (kind, value), ids in owners.items() if kind == record['kind'] and rid in ids]
            if len(prior) != 1 or owners.get((record['kind'], prior[0])) != {rid}:
                raise ValueError('IMPORT replace requires an unambiguous previous physical identity')
            expected = {'identity': json_read(prior[0]) if record['kind'] in component_properties else prior[0],
                        'model': digest(operation_values(old, rid))}
            if not typed_equal(item['before'], expected):
                raise ValueError('IMPORT replace previous identity/Model state differs from the explicit selection')
            if collisions == {rid}:
                raise ValueError('IMPORT same physical identity requires refresh, not replace')
        if identity_key in selected_identities or collisions - ({rid} if action == 'refresh' else set()):
            raise ValueError('IMPORT acquired record ' + record['record'] + ' for Resource ' + rid
                             + ' has ambiguous or duplicate identity with existing Resource IDs: ' + ','.join(sorted(collisions)))
        if warnings is not None and action == 'add' and unknown.get(record['kind']):
            warnings.append({'record': record['record'], 'resource': rid,
                             'existingResources': unknown[record['kind']],
                             'reason': 'Existing physical IDs are unknown; explicitly managed addition may duplicate an existing resource'})
        selected[rid] = record if action == 'add' else {**record, '_action': action}
        selected_identities.add(identity_key)
        used.add(record['record'])
    for item in selection['excluded']:
        if set(item) != {'record', 'reason'} or item['record'] not in acquired or item['record'] in used or not isinstance(item['reason'], str) or not item['reason'].strip():
            raise ValueError('IMPORT excluded record needs a unique record and reason')
        used.add(item['record'])
    for item in selection['unreflected']:
        if set(item) - {'record', 'property', 'reason'} or item.get('record') not in acquired or not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('IMPORT unreflected item needs a record and reason')
        if not item.get('property'):
            if item['record'] in used:
                raise ValueError('IMPORT resource disposition is ambiguous')
            used.add(item['record'])
        elif item['property'] not in acquired[item['record']]['properties']:
            raise ValueError('IMPORT unreflected Property is unknown')
    if used != acquired.keys():
        raise ValueError('IMPORT every acquired record needs an explicit disposition')
    return selected


def pending_items(selection, selected, values, property_schema):
    """Report absent/unreflected acquired settings for review and publication alike."""
    pending = list(selection['unreflected'])
    known = {(item['record'], item.get('property')) for item in pending}
    rows = resource_row_index(values)
    for rid, record in selected.items():
        for prop, capture in record['properties'].items():
            if (record['record'], prop) in known:
                continue
            represented = any(row['property'] == prop for _, row in rows[rid])
            if capture['status'] == 'missing' and not represented:
                continue
            if capture['status'] == 'captured' and typed_equal(
                    property_values(values, rid, prop, property_schema(prop), rows=rows), capture['value']):
                continue
            pending.append({'record': record['record'], 'property': prop,
                            'reason': capture.get('reason', 'acquired Property not reflected by the candidate')})
    return pending


def reference_value_equal(left, right):
    """Only reference expression spans may differ; structure and other literals stay exact."""
    if isinstance(left, dict) and '$resource' in left and not set(left) - {'$resource', '$attribute'}:
        return reference_value_equal(left['$resource'], right)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(reference_value_equal(v, right[k]) for k, v in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(reference_value_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, str) and isinstance(right, str):
        import re
        from model.identity import reference_tokens
        def matches(expression, value):
            pieces, start = [], 0
            for match in reference_tokens(expression):
                pieces.extend((re.escape(expression[start:match.start()]), '.*?'))
                start = match.end()
            if not pieces:
                return False
            pieces.append(re.escape(expression[start:]))
            return re.fullmatch(''.join(pieces), value, re.DOTALL) is not None
        return left == right or matches(left, right) or matches(right, left)
    return typed_equal(left, right)



def verify_values(before, after, selected, property_schema, references=None, *, warnings=None):
    """Verify acquired values without changing selections or broadening their authority."""
    from model.core import validate_authority
    old, new = before.authoritative, after.authoritative
    validate_authority(new)
    from model.identity import preserve_allocation, COUNTERS
    preserve_allocation(old, new)
    old_resources, new_resources = dict(entries(old, 'desired.resource.')), dict(entries(new, 'desired.resource.'))
    old_rows, new_rows = dict(entries(old, 'desired.row.')), dict(entries(new, 'desired.row.'))
    updated = {rid for rid, record in selected.items() if record.get('_action') in {'refresh', 'replace', 'bind'}}
    if any(old_resources.get(rid, {}).get('resourceMode') != 'IMPORT' for rid in updated):
        raise ValueError('IMPORT updates require existing IMPORT resources; CREATE is protected')
    from model.projection import observed_value
    for key, value in new.items():
        if key.startswith('observed.row.') and old.get(key) != value:
            row_id = key.split('.')[2]
            observed_value(row_id, new_rows[row_id], value, ())
    if old_resources.keys() - new_resources.keys() or old_rows.keys() - new_rows.keys():
        raise ValueError('IMPORT missing inventory never authorizes deleting existing Resource or Row IDs')
    for rid, resource in old_resources.items():
        if resource != new_resources[rid]:
            raise ValueError('IMPORT existing fixed identity, placement, mode and parent relationships must be preserved: ' + rid)
    for row_id, row in old_rows.items():
        if row['property'] != new_rows[row_id]['property']:
            raise ValueError('IMPORT existing Row Property must be preserved: ' + row_id)
    changed_properties = {rid: set() for rid in selected}
    for key in old.keys() | new.keys():
        if old.get(key) == new.get(key) and (key in old) == (key in new):
            continue
        if key == COUNTERS:
            continue  # The shared allocation guard above proved this exact addition.
        owners = {owner(key, values) for values in (old, new) if key in values}
        if any(kind != 'resource' or rid not in selected for kind, rid in owners):
            # Initial service metadata is allowed only in the first explicit service candidate.
            if not old and key.startswith(('desired.service.', 'display.service.')):
                continue
            raise ValueError('IMPORT changes an unselected Resource or service field: ' + key)
        if any(rid in old_resources and rid not in updated for _, rid in owners):
            raise ValueError('IMPORT existing Resource requires an explicitly selected refresh/bind/replace; fields must be preserved: ' + key)
        if key.startswith('desired.reference.'):
            continue
        kind, rid = next(iter(owners))
        if rid not in old_resources:
            continue
        pieces = key.split('.')
        if pieces[0] not in {'desired', 'observed'} or pieces[1] != 'row':
            raise ValueError('IMPORT existing non-acquired field must be preserved: ' + key)
        row_id, field = pieces[2:]
        prop = new_rows[row_id]['property']
        capture = selected[rid]['properties'].get(prop, {})
        fields = ({'value', 'document'} if row_id in old_rows else {'value', 'document', 'property', 'comment'}) if pieces[0] == 'desired' else {'value'}
        if capture.get('status') != 'captured' or key not in new or field not in fields:
            raise ValueError('IMPORT existing unacquired field must be preserved: ' + key)
        changed_properties[rid].add(prop)
    changes = []
    old_index, new_index = resource_row_index(old), resource_row_index(new)
    for rid, record in selected.items():
        if rid in old_resources and rid not in updated:
            continue
        if new_resources[rid].get('resourceMode') != 'IMPORT':
            raise ValueError('IMPORT cannot update CREATE resources')
        if references is not None:
            references.verify_resource(after.values, rid, scope=getattr(after, 'scope', None), identity_properties=record.get('identityProperties', [record['identityProperty']]),
                                       **({'properties': changed_properties[rid]} if rid in old_resources else {}))
        for row_id, row in new_index[rid]:
            prop = row['property']
            if rid in old_resources and prop not in changed_properties[rid]:
                continue
            capture = record['properties'].get(prop, {})
            if capture.get('status') != 'captured':
                raise ValueError('IMPORT candidate uses an unacquired Property: ' + prop)
            schema = property_schema(prop)
            desired = typed_row(row, row['value'], schema)
            actual = property_values(after.values, rid, prop, schema, rows=new_index)
            if not reference_value_equal(desired, capture['value']) or (actual is not None and
                    not typed_equal(actual, capture['value']) and not reference_value_equal(actual, capture['value'])):
                raise ValueError('IMPORT candidate value differs from the acquired Property: ' + prop)
            if warnings is not None and not typed_equal(desired, capture['value']):
                warnings.append({'code': 'reference.import_value', 'message': 'reference representation differs from acquired value',
                                 'property': prop, 'resource': rid, 'reference': desired})
            if rid in old_resources and any(previous['property'] == prop for _, previous in old_index[rid]):
                previous = property_values(before.values, rid, prop, schema, rows=old_index)
                if previous is not None and type(previous) is not type(actual):
                    raise ValueError('IMPORT existing Property native type/array structure must be preserved: ' + prop)
            observed_key = 'observed.row.' + row_id + '.value'
            if observed_key in new and not typed_equal(property_values(after.values, rid, prop, schema,
                    observed=True, rows=new_index), capture['value']):
                raise ValueError('IMPORT observation differs from the acquired Property: ' + prop)
            changes.append({'resource': rid, 'record': record['record'], 'property': prop})
        identities = record.get('identityComponents', [{'property': record['identityProperty'], 'value': record['identity']}])
        for component in identities:
            prop = component['property']
            if prop and not typed_equal(property_values(after.values, rid, prop, property_schema(prop), rows=new_index), component['value']):
                raise ValueError('IMPORT candidate must retain its acquired physical identity')
            if warnings is not None:
                for _, row in new_index[rid]:
                    link = resource_link(row['value'])
                    if row['property'] == prop and link and parse_reference(link[0], after.scope) != (after.scope.environment, after.scope.target, after.scope.service, new_resources[rid].get('anchor')):
                        warnings.append({'code': 'reference.import_identity', 'message': 'identity reference does not refer to its own Resource',
                                         'resource': rid, 'property': prop, 'reference': row['value']})
    return changes
