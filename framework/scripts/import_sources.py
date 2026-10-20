"""Check agent-edited ordinary sources; never choose names, resources or input layout."""
import json
from pathlib import Path

from model_core import LINK, entries, literal
from model_files import resource_row_index
from model_parameter_inputs import yaml_read
from model_templates import json_read
from validation_cache import input_is_file, input_bytes


def parameter_edit(original, wanted):
    """Patch changed YAML nodes, emitting added collections as two-space block YAML."""
    import yaml
    before = yaml_read(original)
    changes = []

    def equal(left, right):
        return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)

    def line_start(index):
        return original.rfind('\n', 0, index) + 1

    def block(value, indent):
        return ''.join(' ' * indent + line for line in yaml.safe_dump(
            value, allow_unicode=True, sort_keys=False, default_flow_style=False, indent=2).splitlines(keepends=True))

    def edit(node, old, new):
        if equal(old, new):
            return
        if isinstance(old, dict) and isinstance(new, dict) and old and new and not node.flow_style:
            nodes = {key.value: (key, value) for key, value in node.value}
            for name, (key, value) in nodes.items():
                if name in new:
                    edit(value, old[name], new[name])
                else:
                    start = line_start(key.start_mark.index)
                    end = value.end_mark.index
                    end = line_start(end) if not original[line_start(end):end].strip() else original.find('\n', end)
                    end = len(original) if end < 0 else end + (original[end:end+1] == '\n')
                    changes.append((start, end, ''))
            added = {name: value for name, value in new.items() if name not in old}
            if added:
                end = node.end_mark.index
                if not original[line_start(end):end].strip():
                    end = line_start(end)
                prefix = '' if end == 0 or original[end-1] == '\n' else '\n'
                changes.append((end, end, prefix + block(added, node.start_mark.column)))
        elif isinstance(new, (dict, list)) and new:
            start = node.start_mark.index
            prefix = original[line_start(start):start]
            indent = len(prefix) - len(prefix.lstrip()) + 2 if prefix.strip() else node.start_mark.column
            text = block(new, indent)
            if prefix.strip():
                text = '\n' + text.rstrip('\n')
            else:
                text = text[indent:]
            changes.append((start, node.end_mark.index, text))
        else:
            text = json.dumps(new, ensure_ascii=False)
            if isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and not node.flow_style:
                text += '\n' + ' ' * node.end_mark.column
            changes.append((node.start_mark.index, node.end_mark.index, text))

    edit(yaml.compose(original), before, wanted)
    result = original
    last = len(original) + 1
    for start, end, text in sorted(changes, reverse=True):
        if end > last:
            raise ValueError('IMPORT input edit has overlapping YAML source spans')
        result = result[:start] + text + result[end:]
        last = start
    if not equal(yaml_read(result), wanted):
        raise ValueError('IMPORT input edit cannot preserve unrelated YAML values')
    return result


def typed_equal(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def candidate_sources(root, directory, identity, *, preservation_consumers=()):
    from import_scope import allowed_source
    from model_templates import safe
    directory = Path(directory).absolute()
    if directory.is_relative_to(root) or directory.is_symlink() or not directory.is_dir():
        raise ValueError('IMPORT candidates must be a temporary directory outside the repository')
    output = {}
    for path in sorted(directory.rglob('*')):
        safe(directory, path)
        if path.is_dir():
            continue
        relative = path.relative_to(directory).as_posix()
        destination = root / relative
        safe(root, destination)
        preservation_input = any(destination == root / 'model/parameters' / '/'.join(item) / 'parameters.yaml'
                                 for item in preservation_consumers)
        if not path.is_file() or not (allowed_source(root, destination, identity) or preservation_input):
            raise ValueError('IMPORT candidate source is outside the selected environment/target/service: ' + relative)
        text = path.read_bytes().decode('utf-8')
        if input_is_file(destination) and input_bytes(destination) == text.encode('utf-8'):
            raise ValueError('IMPORT candidate directory must contain changed sources only: ' + relative)
        if path.name == 'parameters.yaml':
            yaml_read(text)
        elif path.suffix == '.json':
            json_read(text)
        output[destination] = text
    return output


def preserve_bindings(before, after, updated=()):
    """Preserve fixed maps; only selected instances may switch Definition/add rows."""
    if before.keys() != after.keys() or any(not typed_equal(before[k], after[k]) for k in before if k != 'instances'):
        raise ValueError('IMPORT fixed bindings must be preserved')
    for name, binding in before['instances'].items():
        current = after['instances'].get(name)
        if current is not None and set(binding['resources'].values()) & set(updated):
            if current['resources'] != binding['resources'] or any(
                    current['rows'].get(key) != value for key, value in binding['rows'].items()):
                raise ValueError('IMPORT existing fixed bindings must be preserved: ' + name)
            if any(row.rpartition('-')[0] not in updated for key, row in current['rows'].items()
                   if key not in binding['rows']):
                raise ValueError('IMPORT new row binding requires a selected Resource: ' + name)
            continue
        if not typed_equal(after['instances'].get(name), binding):
            raise ValueError('IMPORT existing bindings must be preserved: ' + name)


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
        elif LINK.fullmatch(raw) or '<<' in raw or (
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
    """Only Markdown resource links, including structured leaves, consume observations."""
    if not isinstance(raw, str):
        return False
    if LINK.fullmatch(raw):
        return True
    try:
        value = json_read(literal(raw))
    except ValueError:
        return False
    def linked(value):
        return (bool(LINK.fullmatch(value)) if isinstance(value, str) else
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
                if raw is None or LINK.fullmatch(raw) or '<<' in raw:
                    continue
                value = typed_row(row, raw, property_schema(prop))
                if isinstance(value, str) and value.strip() and value not in {'PENDING_DEPLOY', 'UNSET'} and not LINK.fullmatch(value) and '<<' not in value:
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
        required = {'record', 'resource', 'action', 'reason', 'basis'} | ({'before'} if item.get('action') == 'replace' else set())
        if set(item) != required or not isinstance(item['reason'], str) or not item['reason'].strip():
            raise ValueError('IMPORT correspondence requires an action, reason and basis')
        record = acquired.get(item['record'])
        rid = item['resource']
        if record is None or item['record'] in used or rid in selected or rid not in new_resources:
            raise ValueError('IMPORT duplicate or unknown resource correspondence')
        if new_resources[rid].get('resourceMode') != 'IMPORT' or record['kind'] != new_resources[rid]['resourceType']:
            raise ValueError('IMPORT correspondence cannot change CREATE or resource type')
        action = item['action']
        if action not in {'add', 'refresh', 'replace'} or action == 'add' and rid in old_resources:
            raise ValueError('IMPORT accepts add only with a new Resource ID; use explicit refresh/replace for existing resources')
        if action != 'add' and (rid not in old_resources or old_resources[rid].get('resourceMode') != 'IMPORT'
                                or old_resources[rid]['resourceType'] != record['kind']):
            raise ValueError('IMPORT refresh/replace requires an existing IMPORT Resource of the acquired type; CREATE is protected')
        basis = item['basis']
        if not isinstance(basis, list) or any(not isinstance(p, str) for p in basis) or len(basis) != len(set(basis)):
            raise ValueError('IMPORT correspondence basis must name distinct acquired Properties')
        if 'identityComponents' in record:
            if record.get('identityStatus') != 'known':
                raise ValueError('IMPORT acquired primary identity is unknown')
        identity_key, collisions = correspondences[record['record']]
        if action == 'refresh' and collisions != {rid}:
            raise ValueError('IMPORT refresh requires one matching physical identity')
        if action == 'replace':
            from import_guard import digest
            from model_operation_checks import operation_values
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
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(reference_value_equal(v, right[k]) for k, v in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(reference_value_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, str) and isinstance(right, str):
        import re
        pattern = r'<<[A-Za-z][A-Za-z0-9_-]*>>|\[[^\]]+\]\([^)]*#[^)]+\)'
        def matches(expression, value):
            pieces, start = [], 0
            for match in re.finditer(pattern, expression):
                pieces.extend((re.escape(expression[start:match.start()]), '.*?'))
                start = match.end()
            if not pieces:
                return False
            pieces.append(re.escape(expression[start:]))
            return re.fullmatch(''.join(pieces), value, re.DOTALL) is not None
        return left == right or matches(left, right) or matches(right, left)
    return typed_equal(left, right)


def verify_values(before, after, selected, property_schema, references=None, *, warnings=None):
    """Prove every changed real value against its selected acquired Property."""
    warnings = warnings if warnings is not None else []
    def warn(message, **details):
        warnings.append({"code": "reference.import_impact", "message": message, **details})
    old, new = before.values, after.values
    from model_core import validate_model_keys
    validate_model_keys({key: value for key, value in new.items() if old.get(key) != value})
    old_resources, new_resources = dict(entries(old, 'desired.resource.')), dict(entries(new, 'desired.resource.'))
    if old_resources.keys() - new_resources.keys():
        raise ValueError('IMPORT missing inventory never authorizes deleting an existing resource')
    old_rows, new_rows = dict(entries(old, 'desired.row.')), dict(entries(new, 'desired.row.'))
    from model_references import observed_value
    from model_templates import validate_observed
    changed_observed = {key: value for key, value in new.items()
                        if key.startswith('observed.') and key.endswith('.value') and old.get(key) != value}
    validate_observed(new, changed_observed)
    for key, value in changed_observed.items():
        row_id = key.split('.')[2]
        observed_value(row_id, new_rows[row_id], value, ())
    updated = {rid for rid, record in selected.items() if record.get('_action') in {'refresh', 'replace'}}
    if any(old_resources.get(rid, {}).get('resourceMode') != 'IMPORT' for rid in updated):
        raise ValueError('IMPORT updates require existing IMPORT resources; CREATE is protected')
    changed_properties = {rid: set() for rid in updated}

    def acquired_key(key):
        parts = key.split('.')
        if len(parts) != 4 or parts[0] not in {'desired', 'observed'} or parts[1] != 'row':
            return False
        row_id, field = parts[2:]
        rid = row_id.rpartition('-')[0]
        row = new_rows.get(row_id, {})
        prop = row.get('property')
        if rid not in updated or selected[rid]['properties'].get(prop, {}).get('status') != 'captured':
            return False
        if row_id in old_rows and (row['property'] != old_rows[row_id]['property'] or
                field not in ({'value', 'document', 'artifactSha256'} if parts[0] == 'desired' else {'value', 'property', 'comment'})):
            return False
        if parts[0] == 'observed' and field in {'property', 'comment'} and new.get(key) != row.get(field):
            return False
        changed_properties[rid].add(prop)
        return True
    if old_rows.keys() - new_rows.keys():
        raise ValueError('IMPORT existing Row IDs must be preserved')
    for rid, resource in old_resources.items():
        if {k: v for k, v in resource.items() if k != 'parentReference'} != {k: v for k, v in new_resources[rid].items() if k != 'parentReference'}:
            raise ValueError('IMPORT existing identity, placement, mode and parent references must be preserved: ' + rid)
    for key, value in old.items():
        if new.get(key) != value and not (key in new and acquired_key(key)):
            left, right = (json_read(value), json_read(new[key])) if key.endswith('.document') and key in new else (value, new.get(key))
            if key.startswith('observed.') or not reference_value_equal(left, right):
                raise ValueError('IMPORT existing expanded value must be preserved: ' + key)
            warn('existing reference value changed', key=key, previous_value=value, resolvedValue=new.get(key))
    for key in new.keys() - old.keys():
        if acquired_key(key):
            continue
        parts = key.split('.')
        if len(parts) >= 3 and parts[1] in {'resource', 'row'}:
            owner = parts[2].rpartition('-')[0] if parts[1] == 'row' else parts[2]
            if owner in old_resources:
                raise ValueError('IMPORT cannot add fields, Rows or observations to an existing resource: ' + key)
        elif old or not key.startswith(('desired.service.', 'display.service.')):
            raise ValueError('IMPORT additions must belong to a new resource: ' + key)
    for key, previous in before.provenance.items():
        current = after.provenance.get(key, {})
        reference_state = lambda trace: (trace.get('references', {}), {n: v for n, v in trace.get('inputs', {}).items() if v.get('type') == 'reference'})
        if reference_state(previous) != reference_state(current) and not acquired_key(key):
            warn('reference declaration or selector changed', key=key)
    indexed_old, indexed_new = resource_row_index(old), resource_row_index(new)
    changes = []
    for rid in (new_resources.keys() - old_resources.keys()) | updated:
        if rid not in selected:
            raise ValueError('IMPORT new resource has no selected acquisition: ' + rid)
        record = selected[rid]
        if references is not None:
            identities = record.get('identityProperties', [record['identityProperty']])
            references.verify_resource(new, rid, identity_properties=identities,
                                       **({'properties': changed_properties[rid]} if rid in updated else {}))
        for row_id, row in indexed_new.get(rid, []):
            prop = row['property']
            if rid in updated and prop not in changed_properties[rid]:
                continue
            capture = record['properties'].get(prop, {})
            if capture.get('status') != 'captured':
                raise ValueError('IMPORT candidate uses an unacquired Property: ' + prop)
            schema = property_schema(prop)
            actual = property_values(new, rid, prop, schema, rows=indexed_new)
            desired = typed_row(row, row.get('value', ''), schema)
            if not reference_value_equal(desired, capture['value']):
                raise ValueError('IMPORT candidate value differs from the acquired Property: ' + prop)
            if not typed_equal(desired, capture['value']):
                warn('reference representation differs from acquired value', property=prop, resource=rid, reference=desired)
            if actual is not None and not typed_equal(actual, capture['value']) and not reference_value_equal(actual, capture['value']):
                raise ValueError('IMPORT candidate value differs from the acquired Property: ' + prop)
            if rid in updated and any(r['property'] == prop for _, r in indexed_old.get(rid, [])):
                previous = property_values(old, rid, prop, schema, rows=indexed_old)
                if previous is not None and type(previous) is not type(actual):
                    raise ValueError('IMPORT existing Property native type/array structure must be preserved: ' + prop)
            if 'observed.row.' + row_id + '.value' in new and not typed_equal(
                    property_values(new, rid, prop, schema, observed=True, rows=indexed_new), capture['value']):
                raise ValueError('IMPORT observation differs from the acquired Property: ' + prop)
            changes.append({'resource': rid, 'record': record['record'], 'property': prop})
    anchors = {resource.get('anchor') for resource in old_resources.values()}
    for rid in sorted(new_resources.keys() - old_resources.keys()):
        anchor = new_resources[rid].get('anchor')
        if not anchor:
            raise ValueError('IMPORT new resource requires a fixed anchor: ' + rid)
        if anchor in anchors:
            warn('ambiguous resource anchor', resource=rid, reference=anchor)
        anchors.add(anchor)
    for rid in (new_resources.keys() - old_resources.keys()) | updated:
        record = selected[rid]
        identity_values = (record['identityComponents'] if 'identityComponents' in record else
                           [{'property': record['identityProperty'], 'value': record['identity']}])
        if 'identityComponents' in record and record.get('identityStatus') != 'known':
            raise ValueError('IMPORT acquired primary identity is unknown')
        for component in identity_values:
            prop = component['property']
            if prop and not typed_equal(property_values(new, rid, prop, property_schema(prop), rows=indexed_new), component['value']):
                raise ValueError('IMPORT new resource must retain its acquired physical identity')
            for _, row in indexed_new.get(rid, []):
                link = LINK.fullmatch(row['value'])
                if row['property'] == prop and link and (link[2] or link[3] != new_resources[rid].get('anchor')):
                    warn('identity link does not refer to its own anchor', resource=rid, property=prop, reference=row['value'])
    return changes
