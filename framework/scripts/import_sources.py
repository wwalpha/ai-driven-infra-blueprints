"""Check agent-edited ordinary sources; never choose names, resources or input layout."""
import json
from pathlib import Path

from model_core import LINK, entries, literal
from model_files import resource_row_index
from model_parameter_inputs import yaml_read
from model_templates import json_read


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


def candidate_sources(root, directory, identity):
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
        if not path.is_file() or not allowed_source(root, destination, identity):
            raise ValueError('IMPORT candidate source is outside the selected environment/target/service: ' + relative)
        text = path.read_bytes().decode('utf-8')
        if destination.is_file() and destination.read_bytes() == text.encode('utf-8'):
            raise ValueError('IMPORT candidate directory must contain changed sources only: ' + relative)
        if path.name == 'parameters.yaml':
            yaml_read(text)
        elif path.suffix == '.json':
            json_read(text)
        output[destination] = text
    return output


def preserve_bindings(before, after):
    """Append instances without changing any existing fixed binding."""
    if before.keys() != after.keys() or any(not typed_equal(before[k], after[k]) for k in before if k != 'instances'):
        raise ValueError('IMPORT fixed bindings must be preserved')
    for name, binding in before['instances'].items():
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
        elif LINK.fullmatch(raw) or '<<' in raw:
            raw = values.get('observed.row.' + row_id + '.value')
            if raw is None:
                continue
        result.append(typed_row(row, raw, schema))
    if '[]' in prop:
        return result[0] if len(result) == 1 and isinstance(result[0], list) else result
    if len(result) > 1:
        raise ValueError('IMPORT ambiguous candidate Property: ' + prop)
    return result[0] if result else None


def selection_records(selection, records, old, new, property_schema, warnings=None):
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
    owners, unknown = {}, {}
    for rid, resource in old_resources.items():
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
    selected, used, selected_identities = {}, set(), set()
    for item in selection['resources']:
        if set(item) != {'record', 'resource', 'action', 'reason', 'basis'} or not isinstance(item['reason'], str) or not item['reason'].strip():
            raise ValueError('IMPORT correspondence requires an action, reason and basis')
        record = acquired.get(item['record'])
        rid = item['resource']
        if record is None or item['record'] in used or rid in selected or rid not in new_resources:
            raise ValueError('IMPORT duplicate or unknown resource correspondence')
        if new_resources[rid].get('resourceMode') != 'IMPORT' or record['kind'] != new_resources[rid]['resourceType']:
            raise ValueError('IMPORT correspondence cannot change CREATE or resource type')
        if item['action'] != 'add' or rid in old_resources:
            raise ValueError('IMPORT accepts add only with a new Resource ID; existing resources cannot be updated')
        basis = item['basis']
        if not isinstance(basis, list) or any(not isinstance(p, str) for p in basis) or len(basis) != len(set(basis)):
            raise ValueError('IMPORT correspondence basis must name distinct acquired Properties')
        identity_key = record['kind'], record['identity']
        collisions = owners.get(identity_key, set())
        if identity_key in selected_identities or collisions:
            raise ValueError('IMPORT acquired record ' + record['record'] + ' for Resource ' + rid
                             + ' has ambiguous or duplicate identity with existing Resource IDs: ' + ','.join(sorted(collisions)))
        if warnings is not None and unknown.get(record['kind']):
            warnings.append({'record': record['record'], 'resource': rid,
                             'existingResources': unknown[record['kind']],
                             'reason': 'Existing physical IDs are unknown; explicitly managed addition may duplicate an existing resource'})
        selected[rid] = record
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


def verify_values(before, after, selected, property_schema):
    """Prove every changed real value against its selected acquired Property."""
    old, new = before.values, after.values
    old_resources, new_resources = dict(entries(old, 'desired.resource.')), dict(entries(new, 'desired.resource.'))
    if old_resources.keys() - new_resources.keys():
        raise ValueError('IMPORT missing inventory never authorizes deleting an existing resource')
    old_rows, new_rows = dict(entries(old, 'desired.row.')), dict(entries(new, 'desired.row.'))
    if old_rows.keys() - new_rows.keys():
        raise ValueError('IMPORT existing Row IDs must be preserved')
    for rid, resource in old_resources.items():
        if resource != new_resources[rid]:
            raise ValueError('IMPORT existing identity, placement, mode and parent references must be preserved: ' + rid)
    for key, value in old.items():
        if new.get(key) != value:
            raise ValueError('IMPORT existing expanded value must be preserved: ' + key)
    for key in new.keys() - old.keys():
        parts = key.split('.')
        if len(parts) >= 3 and parts[1] in {'resource', 'row'}:
            owner = parts[2].split('-')[0] if parts[1] == 'row' else parts[2]
            if owner in old_resources:
                raise ValueError('IMPORT cannot add fields, Rows or observations to an existing resource: ' + key)
        else:
            raise ValueError('IMPORT additions must belong to a new resource: ' + key)
    for key, previous in before.provenance.items():
        current = after.provenance.get(key, {})
        references = lambda trace: (trace.get('references', {}), {n: v for n, v in trace.get('inputs', {}).items() if v.get('type') == 'reference'})
        if references(previous) != references(current):
            raise ValueError('IMPORT reference declaration or selector changed: ' + key)
    indexed_new = resource_row_index(new)
    changes = []
    for rid in new_resources.keys() - old_resources.keys():
        if rid not in selected:
            raise ValueError('IMPORT new resource has no selected acquisition: ' + rid)
        record = selected[rid]
        for row_id, row in indexed_new.get(rid, []):
            prop = row['property']
            capture = record['properties'].get(prop, {})
            if capture.get('status') != 'captured':
                raise ValueError('IMPORT candidate uses an unacquired Property: ' + prop)
            schema = property_schema(prop)
            actual = property_values(new, rid, prop, schema, rows=indexed_new)
            if not typed_equal(actual, capture['value']):
                raise ValueError('IMPORT candidate value differs from the acquired Property: ' + prop)
            if 'observed.row.' + row_id + '.value' in new and not typed_equal(
                    property_values(new, rid, prop, schema, observed=True, rows=indexed_new), capture['value']):
                raise ValueError('IMPORT observation differs from the acquired Property: ' + prop)
            changes.append({'resource': rid, 'record': record['record'], 'property': prop})
    anchors = {resource.get('anchor') for resource in old_resources.values()}
    for rid in sorted(new_resources.keys() - old_resources.keys()):
        anchor = new_resources[rid].get('anchor')
        if not anchor or anchor in anchors:
            raise ValueError('IMPORT new resource requires a new fixed anchor: ' + rid)
        anchors.add(anchor)
        record = selected[rid]
        prop = record['identityProperty']
        if prop and property_values(new, rid, prop, property_schema(prop), rows=indexed_new) != record['identity']:
            raise ValueError('IMPORT new resource must retain its acquired physical identity')
        for _, row in indexed_new.get(rid, []):
            link = LINK.fullmatch(row['value'])
            if row['property'] == prop and link and (link[2] or link[3] != new_resources[rid].get('anchor')):
                raise ValueError('IMPORT new resource identity link must refer to its own anchor')
    return changes
