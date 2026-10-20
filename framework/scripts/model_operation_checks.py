"""Read-only final Model-only difference checks against versioned authoritative inputs."""
from dataclasses import replace
import re
from pathlib import Path
from model_core import entries, LINK
from model_sources import json_read, json_text, consumers, source_paths
from model_templates import load_for_analysis as load_expansion, parse_template, variables, _reference_inputs
from model_parameter_inputs import yaml_read, schema
from validation_cache import input_scope
from import_sources import typed_equal

def operation_rows(values, number):
    """Formal Property and array position identify rows, never matching row numbers."""
    from array_display import ROOT, array_template, numbered_property
    from model_files import resource_row_index
    result, states = {}, {}
    for rid, row in resource_row_index(values)[number]:
        key = numbered_property(array_template(row['property'], values['desired.resource.' + number + '.resourceType'], ROOT), states)
        if key in result:
            raise ValueError('IMPORT ambiguous Property correspondence: ' + key)
        result[key] = rid, row
    return result


def operation_values(values, number):
    from model_files import resource_row_index
    rows = {rid for rid, _ in resource_row_index(values)[number]}
    return {key: value for key, value in values.items()
            if key.startswith(('desired.resource.' + number + '.', 'display.resource.' + number + '.'))
            or key.startswith(('desired.row.', 'observed.row.')) and key.split('.')[2] in rows}


def merged_row(values, number, rid, row):
    """Self links keep the destination identity; JSON content and observations move intact."""
    from model_core import LINK
    anchor = values['desired.resource.' + number + '.anchor']
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        match = LINK.fullmatch(value) if isinstance(value, str) else None
        return {'self': True} if match and not match[2] and match[3] == anchor else value
    payload = {key: normalize(json_read(value) if key == 'document' else value)
               for key, value in row.items() if key not in {'comment', 'artifactSha256'}
               and not (key == 'value' and 'document' in row)}
    observed = 'observed.row.' + rid + '.value'
    if observed in values:
        payload['observed'] = values[observed]
    return payload


def preserve_input_additions(before, after, old_definitions, definitions, bindings, exempt=()):
    """Only newly needed public inputs may be added to preserved instances."""
    from import_promotion import changed_properties, property_inputs
    for instance, binding in bindings['instances'].items():
        if instance in exempt:
            continue
        old = before.get('instances', {}).get(instance, {}).get('parameters', {})
        new = after.get('instances', {}).get(instance, {}).get('parameters', {})
        reference_inputs = {key for key, spec in old_definitions[binding['definition']].parameters.items()
                            if schema(spec)['type'] == 'reference'}
        if any(key not in new or not typed_equal(value, new[key]) for key, value in old.items() if key not in reference_inputs):
            raise ValueError('IMPORT preserved instance inputs changed: ' + instance)
        name = binding['definition']
        changed = changed_properties({name: old_definitions[name]}, {name: definitions[name]}).get(name, set())
        needed = set().union(*(property_inputs(definitions[name], key) for key in changed))
        if set(new) - set(old) - needed:
            raise ValueError('IMPORT unrelated preservation input addition: ' + instance)



from model_reference_usage import _Reference, _symbolic, _walk


def reference_equal(left, right):
    """Compare every non-reference leaf, including literal string affixes."""
    if isinstance(left, _Reference) or isinstance(right, _Reference):
        return isinstance(left, _Reference) and isinstance(right, _Reference)
    if isinstance(left, tuple) and isinstance(right, str):
        return re.fullmatch(''.join('.*?' if isinstance(p, _Reference) else re.escape(p) for p in left), right, re.DOTALL) is not None
    if isinstance(right, tuple) and isinstance(left, str):
        return reference_equal(right, left)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(reference_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(reference_equal(a, b) for a, b in zip(left, right))
    return left == right


def operation_warning(warnings, message, **details):
    warnings.append({'code': 'reference.operation_impact', 'message': message, **details})


def _retarget(value, source, destination):
    if isinstance(value, _Reference):
        return replace(value, producer=destination) if value.producer == source else value
    if isinstance(value, dict):
        return {key: _retarget(item, source, destination) for key, item in value.items()}
    if isinstance(value, list):
        return [_retarget(item, source, destination) for item in value]
    if isinstance(value, tuple):
        return tuple(_retarget(item, source, destination) for item in value)
    return value


def _pointer(document, pointer):
    from model_templates import json_pointer
    return json_pointer(document, pointer)


@input_scope
def verify_model_operation(before: Path, after: Path, operation, sources) -> None:
    """Verify all pairs/references together; never write, generate or complete a Task.

    Literal/identity/observed values and structural producer records are compared
    before accepting any evaluated candidate reference result. Existing expansion
    diagnoses unresolved, cyclic or ambiguous references without blocking the operation.
    """
    if operation.action == 'import-retarget':
        return verify_model_retarget(before, after, operation, sources)
    from import_promotion import changed_properties, property_value
    from import_scope import allowed_source, model_path
    from model_templates import model_paths, validate_local
    warnings = []
    identity = operation.scope
    pairs = {pair.source.rsplit('/', 1)[1]: pair.destination.rsplit('/', 1)[1] for pair in operation.pairs}
    deletion_scopes = {}
    for source in operation.delete_sources:
        deletion_scopes.setdefault(tuple(source.split('/')[:3]), set()).add(source.rsplit('/', 1)[1])
    if pairs:
        deletion_scopes[identity] = set(pairs)
    deleted_addresses = {'/'.join((*scope, rid)) for scope, ids in deletion_scopes.items() for rid in ids}
    destinations = set(pairs.values())
    reverse = {right: left for left, right in pairs.items()}
    direct = set()
    selected_scopes = operation.source_scopes
    if operation.action == 'import-delete':
        selected_scopes = operation.scopes
    for selected in selected_scopes:
        previous = consumers(before, selected[1], selected[2])
        if consumers(after, selected[1], selected[2]) != previous:
            raise ValueError('IMPORT operation cannot add/remove service consumers')
        direct.update(previous)
    reference_scopes = {tuple(ref.consumer.split('/')[:3]) for ref in operation.references} | {
        tuple(detach.consumer.split('/')[:3]) for detach in operation.detaches}
    models = {(*path.relative_to(before / 'model').parts[:2], path.stem) for path in model_paths(before, *identity[:2])} | direct
    old_expanded, new_expanded = {}, {}
    for scope in sorted(models):
        old_expanded[scope] = load_expansion(model_path(before, scope))
        new_expanded[scope] = load_expansion(model_path(after, scope))
        if old_expanded[scope] is None or new_expanded[scope] is None:
            raise ValueError('IMPORT operation source does not exist')
        warnings.extend(old_expanded[scope].warnings)
        warnings.extend(new_expanded[scope].warnings)
    resources = dict(entries(old_expanded[identity].values, 'desired.resource.'))
    for selected, deleted in deletion_scopes.items():
        selected_resources = dict(entries(old_expanded[selected].values, 'desired.resource.'))
        required = set(deleted)
        if selected == identity:
            required.update(destinations)
        for rid in required:
            if selected_resources.get(rid, {}).get('resourceMode') != 'IMPORT':
                raise ValueError('IMPORT operation requires existing IMPORT resources: ' + '/'.join((*selected, rid)))
    for left, right in pairs.items():
        if resources[left]['resourceType'] != resources[right]['resourceType']:
            raise ValueError('IMPORT merge resource types differ')
    for relative in sources:
        file = after / relative
        preserved_input = any(file == after / 'model/parameters' / '/'.join(scope) / 'parameters.yaml' for scope in direct)
        reference_input = any(file in read_paths for scope in reference_scopes for read_paths in [
            {p for p in new_expanded[scope].files if p.is_relative_to(after / 'model/templates') or
             p == after / 'model/parameters' / '/'.join(scope) / 'parameters.yaml' or
             operation.action == 'import-delete' and p == after / 'model/parameters' / '/'.join(scope) / 'bindings.json'}])
        if not any(allowed_source(after, file, selected) for selected in operation.source_scopes) and not preserved_input and not reference_input:
            raise ValueError('IMPORT operation source is outside its exact scope: ' + relative)
    editable_definitions = {}
    for selected_scope in operation.source_scopes | reference_scopes:
        selected_path = model_path(before, selected_scope)
        _, template, directory = source_paths(selected_path)
        bindings = json_read(old_expanded[selected_scope].files[directory / 'bindings.json'])
        editable_ids = destinations if selected_scope == identity else set()
        editable_ids = editable_ids | {ref.consumer.rsplit('/', 1)[1] for ref in operation.references if tuple(ref.consumer.split('/')[:3]) == selected_scope}
        editable_ids |= {d.consumer.rsplit('/', 1)[1] for d in operation.detaches if tuple(d.consumer.split('/')[:3]) == selected_scope}
        editable_definitions.setdefault(template.relative_to(before), set()).update(
            binding['definition'] for binding in bindings['instances'].values() if editable_ids & set(binding['resources'].values()))
    anchors = []
    for collection in (old_expanded, new_expanded):
        index = {}
        for scope, expansion in collection.items():
            for rid, resource in entries(expansion.values, 'desired.resource.'):
                key = (scope[0], scope[1], scope[2], resource['anchor'])
                if key in index:
                    index[key] = None
                else:
                    index[key] = '/'.join((*scope, rid))
        anchors.append(index)
    symbolic = []
    for root, collection, index in zip((before, after), (old_expanded, new_expanded), anchors):
        symbolic.append({scope: _symbolic(model_path(root, scope), expansion,
                           {(service, anchor): address for (env, target, service, anchor), address in index.items() if (env, target) == scope[:2]}, warnings)
                         for scope, expansion in collection.items()})
    from model_reference_usage import usage_records, reference_diagnostics
    previous_records = list(usage_records(before, old_expanded, symbolic[0]))
    current_records = list(usage_records(after, new_expanded, symbolic[1]))
    warnings.extend(reference_diagnostics(current_records, previous_records))
    for record in previous_records:
        if record['producer'] in deleted_addresses and record['consumer'] != record['producer']:
            warnings.append({'code': 'reference.target_removed', 'message': 'operation removes a referenced Resource',
                             **record, **({'previous_value': record['resolvedValue']} if 'resolvedValue' in record else {})})
    declarations = {(ref.consumer, ref.field, ref.property_name, ref.pointer): ref for ref in operation.references}
    used = set()

    def compare(left, right, address, field, prop=None, self_pair=None, evaluated=None, origin=None):
        expected = left
        matching = [ref for position, ref in declarations.items() if position[:3] == (address, field, prop)]
        detaches = []
        if origin:
            detaches = [d for d in operation.detaches if d.consumer == address and d.key == origin[1]]
        if operation.action == 'import-delete' and origin and left != right and not matching and not detaches:
            selected_scope, old_key, new_key = origin
            def expression(root, key):
                fields = _reference_inputs(model_path(root, selected_scope))[1][5]
                if key not in fields:
                    return None
                instance, definition, raw = fields[key]
                return raw, {name: (schema(definition.parameters[name]), instance['parameters'][name])
                             for name in variables(raw) if name in definition.parameters}
            if expression(before, old_key) != expression(after, new_key):
                raise ValueError('IMPORT deletion changed an undeclared Property/reference: ' + address + '/' + str(prop or field))
        refs = list(_walk(left))
        if evaluated is not None and evaluated[0] != evaluated[1] and refs and not matching and not (self_pair and all(ref.producer == self_pair[0] for ref in refs)):
            operation_warning(warnings, 'derived reference value changed', consumer=address, property=prop, previous_value=evaluated[0], resolvedValue=evaluated[1])
        if not self_pair and origin and any(ref.source == ref.destination for ref in matching):
            scope, old_key, new_key = origin
            old_field = _reference_inputs(model_path(before, scope))[1][5][old_key]
            new_field = _reference_inputs(model_path(after, scope))[1][5][new_key]
            def expression(item):
                instance, definition, raw = item
                names = variables(raw)
                return (raw, {name: (schema(definition.parameters[name]), instance['parameters'][name])
                              for name in names if name in definition.parameters})
            if expression(old_field) != expression(new_field):
                operation_warning(warnings, 'destination reevaluation changed reference expression', consumer=address, property=prop)
        if self_pair:
            expected = _retarget(expected, *self_pair)
        for position, ref in declarations.items():
            if position[:3] != (address, field, prop):
                continue
            target = expected
            parent = key = None
            if ref.pointer is not None:
                # Existing pointer parser supplies the parent/key and enforces reachability.
                parent, key = _pointer(target, ref.pointer)
                target = parent[key]
                if isinstance(target, (dict, list)):
                    raise ValueError('reference document pointer must select a scalar leaf')
            refs = list(_walk(target))
            if not isinstance(target, tuple) or len(target) != 3 or target[0] != '' or target[-1] != '' or len(refs) != 1 or refs[0].producer != ref.source:
                operation_warning(warnings, 'reference before target does not match declaration', consumer=address, property=prop)
                continue
            updated = _retarget(target, ref.source, ref.destination)
            if parent is not None:
                parent[key] = updated
            else:
                expected = updated
            used.add(position)
        if operation.action == 'import-delete' and (matching or detaches):
            from model_reference_usage import reference_positions
            from collections import Counter
            permitted = {ref.pointer for ref in matching} | {d.pointer for d in detaches if d.pointer is not None}
            previous_positions = Counter(reference_positions(left))
            current_positions = Counter(reference_positions(right))
            permitted.update(position for position, ref in previous_positions
                             if any(d.pointer is None and ref.producer == d.producer for d in detaches))
            if Counter({key: count for key, count in previous_positions.items() if key[0] not in permitted}) != Counter(
                    {key: count for key, count in current_positions.items() if key[0] not in permitted}):
                raise ValueError('IMPORT deletion changed an undeclared reference position: ' + address)
            for detach in detaches:
                if field not in {'value', 'document'} or not origin[1].startswith('desired.row.'):
                    raise ValueError('IMPORT deletion cannot detach structural metadata')
                selected = [ref for position, ref in reference_positions(left)
                            if (detach.pointer is None or position == detach.pointer) and ref.producer == detach.producer]
                if not selected:
                    operation_warning(warnings, 'deletion detach before target does not match declaration', consumer=address, key=detach.key)
        if not reference_equal(expected, right):
            raise ValueError('IMPORT source Property not transferred or unspecified value/reference change: ' + address + '/' + str(prop or field))
        if expected != right:
            operation_warning(warnings, 'reference changed', consumer=address, property=prop, key=field)

    for scope in sorted(models):
        deleted = deletion_scopes.get(scope, set())
        old, new = old_expanded[scope], new_expanded[scope]
        old_values, new_values = symbolic[0][scope], symbolic[1][scope]
        old_resources, new_resources = dict(entries(old.values, 'desired.resource.')), dict(entries(new.values, 'desired.resource.'))
        if set(new_resources) != set(old_resources) - deleted:
            raise ValueError('IMPORT operation must delete only the specified source')
        old_path, new_path = model_path(before, scope), model_path(after, scope)
        old_directory, new_directory = source_paths(old_path)[2], source_paths(new_path)[2]
        old_bindings, bindings = [json_read(exp.files[directory / 'bindings.json']) for exp, directory in ((old, old_directory), (new, new_directory))]
        if operation.action == 'import-delete' and old_bindings.get('stacks') != bindings.get('stacks'):
            raise ValueError('IMPORT operation fixed stack composition changed')
        old_inputs, inputs = [yaml_read(exp.files[directory / 'parameters.yaml']) for exp, directory in ((old, old_directory), (new, new_directory))]
        old_definitions, _ = parse_template(source_paths(old_path)[1])
        definitions, _ = parse_template(source_paths(new_path)[1])
        added_definitions = definitions.keys() - old_definitions.keys()
        if operation.action == 'import-delete':
            repair_ids = {r.consumer.rsplit('/', 1)[1] for r in (*operation.references, *operation.detaches)
                          if tuple(r.consumer.split('/')[:3]) == scope}
            # A new repair Definition may be shared but cannot change other consumers.
            all_repair_definitions = set()
            for selected in reference_scopes:
                if source_paths(model_path(before, selected))[1] == source_paths(old_path)[1]:
                    selected_directory = source_paths(model_path(after, selected))[2]
                    selected_bindings = json_read(new_expanded[selected].files[selected_directory / 'bindings.json'])
                    selected_ids = {r.consumer.rsplit('/', 1)[1] for r in (*operation.references, *operation.detaches)
                                    if tuple(r.consumer.split('/')[:3]) == selected}
                    all_repair_definitions.update(binding['definition'] for binding in selected_bindings['instances'].values()
                                                 if selected_ids & set(binding['resources'].values()))
            if old_definitions.keys() - definitions.keys() or added_definitions - all_repair_definitions:
                raise ValueError('IMPORT deletion changed unrelated Definitions')
        else:
            repair_ids = set()
            if definitions.keys() != old_definitions.keys():
                raise ValueError('IMPORT operation must reuse existing Definitions')
        changed_definitions = changed_properties(old_definitions, definitions)
        if changed_definitions.keys() - added_definitions - editable_definitions.get(source_paths(old_path)[1].relative_to(before), set()):
            raise ValueError('IMPORT operation changed an unrelated Definition')
        removed_instances, edited_instances = set(), set()
        if deleted:
            for rid in deleted:
                owners = [name for name, binding in old_bindings['instances'].items() if rid in binding['resources'].values()]
                if len(owners) != 1 or len(old_bindings['instances'][owners[0]]['resources']) != 1:
                    raise ValueError('IMPORT source cannot safely be separated from its multi-resource Instance')
                removed_instances.add(owners[0])
            edited_instances = {name for name, binding in old_bindings['instances'].items() if destinations & set(binding['resources'].values())}
        if set(bindings['instances']) != set(old_bindings['instances']) - removed_instances or removed_instances & inputs['instances'].keys():
            raise ValueError('IMPORT source Instance/bindings/inputs were not removed exactly')
        for name, binding in bindings['instances'].items():
            previous = old_bindings['instances'][name]
            if name in edited_instances:
                if any(previous[field] != binding[field] for field in ('definition', 'resources')):
                    raise ValueError('IMPORT destination fixed identity changed')
                for field in ('parameters', 'labels'):
                    if any(key not in binding.get(field, {}) or binding[field][key] != value for key, value in previous.get(field, {}).items()):
                        raise ValueError('IMPORT destination internal identity changed')
            elif repair_ids & set(previous['resources'].values()):
                if {k: v for k, v in previous.items() if k not in {'definition', 'parameters', 'labels'}} != {
                        k: v for k, v in binding.items() if k not in {'definition', 'parameters', 'labels'}}:
                    raise ValueError('IMPORT repair fixed identity changed')
            elif previous != binding:
                raise ValueError('IMPORT unrelated bindings changed')
        reference_instances = {name for name, binding in bindings['instances'].items()
                               if any(ref.consumer == '/'.join((*scope, rid)) for rid in binding['resources'].values()
                                      for ref in (*operation.references, *operation.detaches))}

        preserve_input_additions(old_inputs, inputs, old_definitions, definitions, old_bindings,
                                 removed_instances | edited_instances | reference_instances)
        if scope not in operation.source_scopes and scope not in reference_scopes and not typed_equal(old_inputs.get('parameters', {}), inputs.get('parameters', {})):
            raise ValueError('IMPORT other-environment shared inputs changed')
        handled_old, handled_new = set(), set()
        for rid in sorted(new_resources):
            source = reverse.get(rid, rid) if scope == identity else rid
            moved = source != rid
            old_set, new_set = operation_values(old.values, source), operation_values(new.values, rid)
            handled_old.update(old_set); handled_new.update(new_set)
            address = '/'.join((*scope, rid))
            self_pair = ('/'.join((*scope, source)), address) if moved else None
            fixed = {'resourceMode', 'resourceType', 'anchor', 'logicalId', 'cfn-logicalId'}
            if moved and any(old_resources[rid].get(field) != new_resources[rid].get(field) for field in fixed):
                raise ValueError('IMPORT destination identity/mode changed')
            left_resource = {k: old_values.get('desired.resource.' + source + '.' + k, old_resources[source][k]) for k in old_resources[source] if not moved or k not in fixed}
            right_resource = {k: new_values.get('desired.resource.' + rid + '.' + k, new_resources[rid][k]) for k in new_resources[rid] if not moved or k not in fixed}
            if left_resource.keys() != right_resource.keys():
                raise ValueError('IMPORT source Resource settings were not fully transferred')
            for field in left_resource:
                compare(left_resource[field], right_resource[field], address, field, self_pair=self_pair,
                        evaluated=(old_resources[source][field], new_resources[rid][field]),
                        origin=(scope, 'desired.resource.' + source + '.' + field, 'desired.resource.' + rid + '.' + field))
            incoming, existing, transferred = operation_rows(old.values, source), operation_rows(old.values, rid), operation_rows(new.values, rid)
            if incoming.keys() != transferred.keys():
                raise ValueError('IMPORT source Properties were not fully transferred')
            all_old_rows = {key.split('.')[2] for key in old.values if key.startswith('desired.row.')}
            for prop, (row_id, row) in transferred.items():
                old_row_id, old_row = incoming[prop]
                if (prop in existing and row_id != existing[prop][0] or prop not in existing and row_id in all_old_rows):
                    raise ValueError('IMPORT destination Row ID was changed or reused: ' + prop)
                ignored = {'comment', 'artifactSha256'} if moved else {'artifactSha256'} if 'document' in row else set()
                if 'document' in old_row:
                    ignored.add('value')
                if old_row.keys() - ignored != row.keys() - ignored:
                    raise ValueError('IMPORT source Property/observation was not transferred: ' + prop)
                for field in old_row.keys() - ignored:
                    compare(old_values['desired.row.' + old_row_id + '.' + field], new_values['desired.row.' + row_id + '.' + field], address, field, prop, self_pair, (old_row[field], row[field]), (scope, 'desired.row.' + old_row_id + '.' + field, 'desired.row.' + row_id + '.' + field))
                left_observed = {k.removeprefix('observed.row.' + old_row_id + '.'): v for k, v in old.values.items() if k.startswith('observed.row.' + old_row_id + '.')}
                right_observed = {k.removeprefix('observed.row.' + row_id + '.'): v for k, v in new.values.items() if k.startswith('observed.row.' + row_id + '.')}
                if moved:
                    left_observed.pop('comment', None); right_observed.pop('comment', None)
                if left_observed != right_observed:
                    raise ValueError('IMPORT source Property/observation was not transferred: ' + prop)
            # Display metadata for the retained destination is not supplied by the source.
            for key, value in operation_values(old.values, rid).items():
                if key.startswith('display.') and new.values.get(key) != value:
                    raise ValueError('IMPORT destination display changed')
        if deleted:
            for rid in deleted | destinations:
                handled_old.update(operation_values(old.values, rid))
        remaining_old = {k: v for k, v in old_values.items() if k not in handled_old}
        remaining_new = {k: v for k, v in new_values.items() if k not in handled_new}
        if not reference_equal(remaining_old, remaining_new):
            raise ValueError('IMPORT operation changed an unspecified resource or service field')
        if operation.action == 'import-delete':
            for key, value in remaining_old.items():
                compare(value, remaining_new[key], '/'.join(scope), key, origin=(scope, key, key))
        for value in new_values.values():
            if any(ref.producer in deleted_addresses for ref in _walk(value)):
                operation_warning(warnings, 'removed resource still has an incoming reference', scope='/'.join(scope))
        # Before anchors also detect links whose producer no longer exists in after.
        for key, value in new.values.items():
            for link in re.finditer(r'\[[^\]]*\]\(([^)]*)\)', value):
                filename, separator, anchor = link[1].partition('#')
                for selected, removed in deletion_scopes.items():
                    selected_resources = dict(entries(old_expanded[selected].values, 'desired.resource.'))
                    if scope[:2] == selected[:2] and separator and anchor in {selected_resources[rid]['anchor'] for rid in removed} and (filename.removeprefix('./') == selected[2] + '.md' or not filename and scope[2] == selected[2]):
                        operation_warning(warnings, 'removed resource still has an incoming reference', scope='/'.join(scope), key=key, reference=link[0])

    if used != declarations.keys():
        operation_warning(warnings, 'unused Model reference declaration')
    return warnings


@input_scope
def verify_model_refactor(before: Path, after: Path, detaches, sources, validation_scope):
    """Prove an explicit IMPORT detach without editing Models or relaxing other Tasks."""
    from collections import Counter
    from import_guard import resource_config
    from model_reference_usage import reference_models, reference_positions, resource_address
    from model_templates import model_paths
    from policy_tables import literal

    direct = {tuple(resource_address(d.consumer)[:3]) for d in detaches}
    for relative in sources:
        parts = Path(relative).parts
        if parts[:2] == ('model', 'templates') and (len(parts) == 4 and parts[3].endswith('.properties.tpl')
                or len(parts) == 5 and parts[3].endswith('.properties') and parts[4].endswith('.properties')):
            alias, service = parts[2], parts[3].removesuffix('.tpl').removesuffix('.properties')
            old_consumers, new_consumers = consumers(before, alias, service), consumers(after, alias, service)
            if old_consumers != new_consumers:
                raise ValueError('Model refactor cannot add/remove shared consumers: ' + relative)
            direct.update(old_consumers)
        elif parts[:2] == ('model', 'parameters') and len(parts) == 6 and parts[5] in {'parameters.yaml', 'bindings.json', 'observed.json'}:
            direct.add(tuple(parts[2:5]))
        else:
            raise ValueError('Model refactor source outside Model authority: ' + relative)
    if validation_scope is None or not direct <= validation_scope:
        raise ValueError('Model refactor requires all direct consumers in Validation scope: ' + repr(sorted(direct)))
    scopes = set()
    for env, target in {scope[:2] for scope in direct}:
        def registered(root):
            return {(env, target, path.stem) for path in model_paths(root, env, target)}
        old, new = registered(before), registered(after)
        if old != new:
            raise ValueError('Model refactor cannot add/remove services: ' + env + '/' + target)
        scopes.update(old)
    old_expanded, old_symbols = reference_models(before, scopes)
    new_expanded, new_symbols = reference_models(after, scopes)
    warnings = [w for group in (old_expanded, new_expanded) for exp in group.values() for w in exp.warnings]
    used = set()
    for declaration in detaches:
        for address in (declaration.consumer, declaration.producer):
            env, target, service, rid = resource_address(address)
            expanded = old_expanded.get((env, target, service))
            if expanded is None or 'desired.resource.' + rid + '.resourceType' not in expanded.values:
                raise ValueError('Model refactor unknown Resource: ' + address)

    def fail(scope, key, left, right, reason):
        trace = old_expanded[scope].provenance.get(key, {})
        source = trace.get('template', trace.get('sourceFile'))
        parts = key.split('.')
        rid = parts[2].rpartition('-')[0] if len(parts) > 2 and parts[1] == 'row' else parts[2] if len(parts) > 2 and parts[1] == 'resource' else None
        raise ValueError('Model refactor ' + reason + ': ' + json_text({
            'scope': '/'.join(scope), 'resource': '/'.join((*scope, rid)) if rid else None, 'key': key,
            'property': old_expanded[scope].values.get(key.rsplit('.', 1)[0] + '.property'),
            'sourceLocation': {'file': str(Path(source).relative_to(before)) if source else None, 'line': trace.get('line')},
            'before': left, 'after': right}))

    for scope in sorted(scopes):
        old, new = old_expanded[scope], new_expanded[scope]
        bindings_path = Path('model/parameters') / '/'.join(scope) / 'bindings.json'
        old_bindings = json_read(old.files[before / bindings_path])
        new_bindings = json_read(new.files[after / bindings_path])
        if old_bindings['instances'].keys() != new_bindings['instances'].keys() or old_bindings.get('stacks') != new_bindings.get('stacks'):
            raise ValueError('Model refactor fixed Instance/stack composition changed: ' + '/'.join(scope))
        for name, binding in old_bindings['instances'].items():
            if any(binding[field] != new_bindings['instances'][name][field] for field in ('resources', 'rows')):
                raise ValueError('Model refactor fixed Resource/Row mappings changed: ' + '/'.join(scope) + '/' + name)
        old_resources, new_resources = dict(entries(old.values, 'desired.resource.')), dict(entries(new.values, 'desired.resource.'))
        if old_resources.keys() != new_resources.keys():
            fail(scope, 'desired.resource', sorted(old_resources), sorted(new_resources), 'Resource composition changed')
        if old.values.keys() != new.values.keys():
            fail(scope, 'Model keys', sorted(old.values), sorted(new.values), 'structure changed')
        for key, value in old.values.items():
            other = new.values[key]
            if key.endswith('.artifactSha256'):
                continue  # Derived hash; the typed JSON document itself is compared below.
            if key.endswith('.document'):
                value, other = json_read(value), json_read(other)
            elif key.startswith('desired.row.') and key.endswith('.value'):
                value, other = literal(value), literal(other)
            left, right = old_symbols[scope][key], new_symbols[scope][key]
            if not reference_equal(left, right):
                fail(scope, key, value, other, 'value/type changed')
            if not typed_equal(value, other):
                operation_warning(warnings, 'reference effective value changed', key=key, previous_value=value, resolvedValue=other)
            declared = [d for d in detaches if tuple(d.consumer.split('/')[:3]) == scope and d.key == key]
            if not declared:
                if left != right:
                    operation_warning(warnings, 'undeclared reference/expression change', scope='/'.join(scope), key=key)
                continue
            rid = declared[0].consumer.rsplit('/', 1)[1]
            if old_resources[rid].get('resourceMode', 'CREATE') != 'IMPORT':
                raise ValueError('Model refactor cannot detach CREATE dependencies: ' + declared[0].consumer)
            if not key.startswith('desired.row.') or not key.endswith(('.value', '.document')):
                raise ValueError('Model refactor cannot detach structural metadata: ' + key)
            remaining = Counter(reference_positions(left))
            current = Counter(reference_positions(right))
            for declaration in declared:
                selected = [position for position in remaining if position[1].producer == declaration.producer
                            and (declaration.pointer is None or position[0] == declaration.pointer)]
                if not selected or any(position[1].producer == declaration.producer
                                       and (declaration.pointer is None or position[0] == declaration.pointer) for position in current):
                    operation_warning(warnings, 'declared dependency missing before or still present after', scope='/'.join(scope), key=key)
                for position in selected:
                    del remaining[position]
                used.add(declaration)
            if remaining != current:
                operation_warning(warnings, 'undeclared dependency change', scope='/'.join(scope), key=key)
        # Per-leaf symbolic comparisons above retain configuration and observation checks.
    if used != set(detaches):
        operation_warning(warnings, 'unused Model dependency detach declaration: ' + repr(set(detaches) - used))
    return warnings


@input_scope
def verify_model_retarget(before: Path, after: Path, operation, sources):
    """Only declared fixed-identity configuration references may differ; no transfer/delete."""
    import copy
    from model_reference_usage import reference_models, resource_address
    from model_templates import validate_local, template_document
    from validation_cache import input_select, input_bytes

    def files(root):
        return {p.relative_to(root): input_bytes(p) for p in input_select(root / 'model', '*', recursive=True, kinds=('file',))}
    old_files, new_files = files(before), files(after)
    if old_files.keys() != new_files.keys() or input_bytes(before / 'project.json') != input_bytes(after / 'project.json'):
        raise ValueError('retarget cannot change authority file sets or project configuration')
    changed = {p for p in old_files if old_files[p] != new_files[p]}
    if {p.as_posix() for p in changed} - set(sources):
        raise ValueError('retarget undeclared source changes')
    for relative in changed:
        parts = relative.parts
        if parts[:2] == ('model', 'templates'):
            alias, service = parts[2], parts[3].removesuffix('.tpl').removesuffix('.properties')
            old, new = consumers(before, alias, service), consumers(after, alias, service)
            if old != new:
                raise ValueError('retarget shared consumers changed')
        elif parts[:2] == ('model', 'parameters') and len(parts) == 6 and parts[-1] == 'parameters.yaml':
            pass
        else:
            raise ValueError('retarget cannot change bindings, observations or non-configuration sources: ' + str(relative))
    scopes = set()
    for relative in old_files:
        parts = relative.parts
        if parts[:2] == ('model', 'parameters') and len(parts) == 6 and parts[-1] == 'bindings.json':
            scopes.add(tuple(parts[2:5]))
    old_expanded, old_symbols = reference_models(before, scopes)
    new_expanded, new_symbols = reference_models(after, scopes)
    # Producers and consumers must exist independently of their display/name/physical values.
    for ref in operation.references:
        for address in (ref.consumer, ref.source, ref.destination):
            env, target, service, rid = resource_address(address)
            values = old_expanded.get((env, target, service))
            if values is None or 'desired.resource.' + rid + '.resourceType' not in values.values:
                raise ValueError('retarget unknown Resource: ' + address)
        left = resource_address(ref.source); right = resource_address(ref.destination)
        a, b = old_expanded[left[:3]].values, old_expanded[right[:3]].values
        if any(values.get('desired.resource.' + rid + '.resourceMode', 'CREATE') != 'IMPORT'
               for values, rid in ((a, left[3]), (b, right[3]))):
            raise ValueError('retarget requires existing IMPORT producers')
        if a['desired.resource.' + left[3] + '.resourceType'] != b['desired.resource.' + right[3] + '.resourceType']:
            pass  # Reference type mismatch is diagnosed by the selected consumer resolver.

    warnings = [w for group in (old_expanded, new_expanded) for exp in group.values() for w in exp.warnings]
    used, editable_fields, editable_inputs = set(), {}, {}
    for scope in sorted(scopes):
        old, new = old_expanded[scope], new_expanded[scope]
        validate_local(new.values)
        if old.values.keys() != new.values.keys():
            raise ValueError('retarget cannot change Model structure')
        expected = copy.deepcopy(old_symbols[scope])
        current = copy.deepcopy(new_symbols[scope])
        structured_keys = set()
        for ref in operation.references:
            if tuple(ref.consumer.split('/')[:3]) != scope:
                continue
            rid = ref.consumer.rsplit('/', 1)[1]
            kind = old.values['desired.resource.' + rid + '.resourceType']
            if 'Subnet' in kind or 'Association' in kind or 'Subnet' in ref.property_name:
                raise ValueError('retarget cannot change Subnet associations')
            rows = operation_rows(old.values, rid)
            if ref.property_name not in rows:
                raise ValueError('retarget missing or ambiguous formal Property: ' + ref.property_name)
            row_id, _ = rows[ref.property_name]
            key = 'desired.row.' + row_id + '.' + ref.field
            if key not in expected:
                raise ValueError('retarget missing reference field')
            if ref.field == 'value' and ref.pointer is not None and key not in structured_keys:
                expected[key], current[key] = _retarget_document(expected[key]), _retarget_document(current[key])
                structured_keys.add(key)
            target = expected[key]
            parent = leaf = None
            if ref.pointer is not None:
                parent, leaf = _pointer(target, ref.pointer)
                target = parent[leaf]
            if not isinstance(target, tuple) or len(target) != 3 or target[0] != '' or target[2] != '' or not isinstance(target[1], _Reference):
                raise ValueError('retarget pointer must select a scalar reference leaf')
            if target[1].producer != ref.source:
                operation_warning(warnings, 'retarget before reference mismatch', consumer=ref.consumer, key=key, pointer=ref.pointer)
            updated = _retarget(target, ref.source, ref.destination)
            if parent is None:
                expected[key] = updated
            else:
                parent[leaf] = updated
            used.add(ref)
            trace = old.provenance[key]
            editable_fields.setdefault((scope[1], scope[2], trace['definition']), set()).add(trace['key'])
            # Only public reference selectors feeding this exact field may change.
            path = before / 'model' / scope[0] / scope[1] / (scope[2] + '.properties')
            _, (_, _, _, _, _, fields) = _reference_inputs(path)
            item, definition, raw = fields[key]
            selected_raw = raw
            if ref.pointer is not None:
                document = template_document(key, raw) if ref.field == 'document' else json_read(raw.strip('`'))
                raw_parent, raw_leaf = _pointer(document, ref.pointer)
                selected_raw = raw_parent[raw_leaf]
            for name in variables(selected_raw):
                if name in definition.parameters:
                    spec = schema(definition.parameters[name])
                    if spec['type'] == 'reference' and not spec.get('internal'):
                        location = ('parameters', name) if spec.get('source') == 'service' else ('instances', item['id'], 'parameters', name)
                        editable_inputs.setdefault(scope, set()).add(location)
        for key, value in expected.items():
            if key.endswith('.artifactSha256') or key.endswith('.value') and key.removesuffix('.value') + '.document' in expected:
                continue  # Generated document link/hash; compare its authoritative document below.
            if not _retarget_equal(value, current[key]):
                raise ValueError('retarget undeclared value/type/reference/structure change: ' + '/'.join(scope) + '/' + key)
            if value != current[key]:
                operation_warning(warnings, 'retarget reference differs from declaration', scope='/'.join(scope), key=key)
        # Preserve raw inputs too, including unused parameters and definition metadata.
        relative = Path('model/parameters') / '/'.join(scope) / 'parameters.yaml'
        a, b = yaml_read(old_files[relative].decode()), yaml_read(new_files[relative].decode())
        for location in editable_inputs.get(scope, ()):
            x, y = a, b
            for part in location[:-1]:
                x, y = x.get(part, {}), y.get(part, {})
            name = location[-1]
            if (name in x) != (name in y):
                raise ValueError('retarget cannot add/remove selector inputs')
            if name in x:
                x[name] = y[name]
        if not _retarget_equal(a, b):
            raise ValueError('retarget changed unrelated/unused input settings')
    if used != set(operation.references):
        operation_warning(warnings, 'retarget unused declarations')
    template_files = set()
    for alias, service in {scope[1:] for scope in scopes}:
        path = Path('model/templates') / alias / (service + '.properties.tpl')
        a, raw_files = parse_template(before / path); b, _ = parse_template(after / path)
        definition_name = None
        for file, text in raw_files.items():
            relative = file.relative_to(before)
            template_files.add(relative)
            previous, candidate = text.splitlines(), new_files[relative].decode().splitlines()
            if len(previous) != len(candidate):
                raise ValueError('retarget cannot change template structure')
            for left_line, right_line in zip(previous, candidate):
                if left_line.startswith('# definition: '):
                    definition_name = left_line.removeprefix('# definition: ')
                if left_line != right_line:
                    key = left_line.partition('=')[0]
                    if (key not in editable_fields.get((alias, service, definition_name), ()) or
                            right_line.partition('=')[0] != key):
                        raise ValueError('retarget changed undeclared raw template field')
        if a.keys() != b.keys():
            raise ValueError('retarget cannot add/remove Definitions')
        for name, definition in a.items():
            other = b[name]
            left, right = definition._asdict(), other._asdict()
            left.pop('locations'); right.pop('locations')
            left['values'] = dict(left['values'])
            for key in editable_fields.get((alias, service, name), ()):
                if key in left['values'] and key in right['values']:
                    left['values'][key] = right['values'][key]
            if not _retarget_equal(left, right):
                raise ValueError('retarget changed unrelated Definition or reference schema')
    if any(p.parts[:2] == ('model', 'templates') and p not in template_files for p in changed):
        raise ValueError('retarget changed an unused template source')
    return warnings


def _retarget_equal(left, right):
    if isinstance(left, _Reference) and isinstance(right, _Reference):
        return True
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_retarget_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(_retarget_equal(a, b) for a, b in zip(left, right))
    return left == right


def _retarget_document(value):
    """Parse a JSON value with symbolic tokens, retaining references as typed records."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, tuple):
        raise ValueError('retarget pointer requires a JSON reference container')
    tokens = {}
    pieces = []
    for item in value:
        if isinstance(item, _Reference):
            marker = '__retarget_reference_' + str(len(tokens)) + '__'
            if any(isinstance(part, str) and marker in part for part in value):
                raise ValueError('reserved retarget reference marker')
            tokens[marker] = ('', item, '')
            pieces.append(marker)
        elif isinstance(item, str):
            pieces.append(item)
        else:
            raise ValueError('retarget unsupported reference expression')
    document = json_read(''.join(pieces).strip('`'))
    def restore(item):
        if isinstance(item, dict):
            return {key: restore(raw) for key, raw in item.items()}
        if isinstance(item, list):
            return [restore(raw) for raw in item]
        return tokens.get(item, item) if isinstance(item, str) else item
    return restore(document)
