#!/usr/bin/env python3
"""Acquire AWS facts, then verify/publish ordinary Model sources edited by the agent."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import re

import task_contract
from import_guard import (workflow, require_import_changes, record_import, finish_import,
                          acquired, read_acquisition, discard_acquisition, file_hash, text_hash, write_sealed, acquisition_complete)
from model_core import ReferenceResolutionError, entries
from model_files import resource_row_index
from model_parameter_inputs import yaml_read
from model_templates import publication_lock, json_read, json_text, publish, service_source, load_for_edit
from task_contract import task_path, section
from validation_scope import active_scope
from validation_cache import input_scope, memo_table, memoized
from script_loader import module as load_script
from sync_files import atomic_files
from aws_mapping_compare import MODEL_ONLY, value as mapping_value
from import_sources import candidate_sources, selection_records, verify_values, typed_equal
from import_promotion import preserve_consumers, replacement_inputs

ROOT = Path(__file__).resolve().parents[2]


def comparator():
    return load_script('check-model-aws.py', 'model_aws_compare')


from import_inventory import inventory_for


def import_context(root, target, runner=None, service=None):
    profile = target.get('awsProfile')
    if 'awsProfile' in target and (not isinstance(profile, str) or not profile or profile != profile.strip() or profile == 'UNSET' or any(c in profile for c in '\r\n\0')):
        raise ValueError('AWS target has an invalid project.json awsProfile; no fallback')
    region = target.get('awsRegion')
    if not isinstance(region, str) or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*', region):
        raise ValueError('AWS target RegionMismatch; use the project.json awsRegion')
    return comparator().Context(root, target, cli_runner=runner, services=(service,) if service else (), import_mode=True)


def target_for(root, environment, service, selector=None):
    if not environment or not service or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', x) for x in (environment, service)):
        raise ValueError('environment and service are required exact identifiers')
    topology = json_read((root / 'project.json').read_text(encoding='utf-8'))
    choices = [t for t in topology['targets'] if isinstance(t, dict) and t.get('environment') == environment]
    if not choices:
        raise ValueError('environment is not registered')
    if selector is None and len(choices) > 1:
        choices = [t for t in choices if (root / 'model/parameters' / environment /
                   t.get('alias', t['awsAccountId']) / service).is_dir()]
    if selector is None:
        if len(choices) != 1:
            raise ValueError('target is required when the environment has multiple targets for this service')
        selector = choices[0].get('alias', choices[0]['awsAccountId'])
    choices = [t for t in choices if t.get('alias', t.get('awsAccountId')) == selector]
    if len(choices) != 1:
        raise ValueError('target must resolve exactly once')
    entry = choices[0]
    resolver = load_script('check-deploy-context.py', 'import_target')
    target = resolver.load_target(root, environment, alias=entry.get('alias'),
                                  account_id=None if 'alias' in entry else selector)
    target.update(environment=environment, directory=selector)
    return target


def inventory(ctx, service, resource_types=None):
    return inventory_for(ctx).discover(service, resource_types)



def contract_scope(root, scope):
    workflow(root)
    text = task_path(root).read_text(encoding='utf-8')
    if '- Task type: `design`' not in section(text, '## Task contract'):
        raise ValueError('normal import requires a registered design Task Contract')
    declared = active_scope(root)
    pins = [line for line in section(text, '## Task contract') if line.startswith('- IMPORT target:')]
    if pins:
        expected = '- IMPORT target: `' + '/'.join(next(iter(scope))) + '`' if len(scope) == 1 else None
        if pins != [expected]:
            raise ValueError('IMPORT acquisition must match the fixed Task target')
    elif declared != scope:
        raise ValueError('IMPORT initially requires exactly one acquisition target in Validation scope')
    from import_scope import selected
    if len(scope) != 1 or selected(root) not in scope or declared is None or not scope <= declared:
        raise ValueError('IMPORT requires one fixed environment/target/service within Validation scope')
    if task_contract.status(text, task_path(root).name == 'active.md') != 'running':
        raise ValueError('IMPORT requires a running Task Contract')


def record_outputs(root, identity, sources, views, consumers=None):
    """Record selected IMPORT outputs and direct consumers in the task plan."""
    from import_scope import allowed_source
    consumers = set(consumers or {identity})
    environment, target, service = identity
    document = root / 'docs/designs' / environment / target / (service + '.md')
    for file in sources:
        if not allowed_source(root, file, identity):
            raise ValueError('IMPORT output is outside selected environment/target/service')
    if any(file != document and not (file.parent == document.with_suffix('') and file.suffix == '.json') for file in views):
        raise ValueError('IMPORT view is outside selected environment/target/service')
    paths = {file.relative_to(root).as_posix() for file in sources | views}
    for relative in paths:
        task_contract.safe_path(root, relative)
    contract_scope(root, {identity})
    records = task_contract.contracts(root)
    selected = task_path(root)
    name = selected.relative_to(root).as_posix()
    text = task_contract.selected_text(root, records, name)
    fixed = '- IMPORT target: `' + '/'.join(identity) + '`'
    if not re.search(r'^- IMPORT target:', text, re.M):
        text = text.replace('- Workflow: `import`', '- Workflow: `import`\n' + fixed)
    declared = active_scope(root)
    body = '## Validation scope\n\n' + ''.join('- `' + '/'.join(item) + '`\n' for item in sorted(declared | consumers)) + '\n'
    text = re.sub(r'^## Validation scope\n.*?(?=^## |\Z)', lambda _: body, text, flags=re.M | re.S)
    for heading in ('## Allowed paths', '## Modified files'):
        existing = task_contract.paths_in(text, heading)
        if paths - existing:
            body = heading + '\n\n' + ''.join('- `' + path + '`\n' for path in sorted(existing | paths)) + '\n'
            text = re.sub(r'^' + heading + r'\n.*?(?=^## |\Z)', lambda _: body, text, flags=re.M | re.S)
    if text != records[name]:
        atomic_files({selected: text}, staging_directory=root)




def sensitive(resource, prop):
    return resource.module.sensitive(prop or '') or bool(re.search(r'password|credential|accesskey|secretstring|secretbinary|privatekey|token|authorization|username', prop or '', re.I))


def unsafe(value):
    text = json_text(value)
    return ('[REDACTED]' in text or '<<' in text or
            any(x in text for x in ('PENDING_DEPLOY', 'UNSET')) or comparator().redacted(value) != value)


def model_literal(value):
    text = value if isinstance(value, str) else json_text(value)
    if any(c in text for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029`'):
        raise ValueError('AWS value cannot be represented losslessly as a Model scalar')
    return '`' + text + '`'


def schema_property(kind, prop):
    if kind in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'} and prop == kind + '.Name':
        return 'Tags[].Value'
    return prop.removeprefix(kind + '.')


@memoized
def property_catalog():
    return comparator().DesignSchemaCatalog(ROOT)


@memoized
def property_schema(prop):
    kind = '.'.join(prop.split('.')[:2])
    return property_catalog().property_schema(kind, schema_property(kind, prop))


def normalize_records(ctx, service, records):
    return [inventory_for(ctx).normalize(service, record, _normalize_records) for record in records]


def _normalize_records(ctx, service, records):
    """Reuse Mapping and adapter getters without constructing any public Model source."""
    m = comparator()
    mapping, mapped = inventory_for(ctx).mapping(service)
    ctx.comparisons[service] = mapping, mapped
    model = SimpleNamespace(ctx=ctx, path=ctx.root / 'model' / ctx.target['environment'] / ctx.target['directory'] / (service + '.properties'),
                            service=service, values={}, resources=[])
    normalized = []
    for record in records:
        kind = record['kind']
        record_id = hashlib.sha256((kind + '\0' + record['identity']).encode('utf-8')).hexdigest()
        seed = next(iter(record['getters'].values()), {})
        seed_rows = []
        proxy = m.Resource(model, record_id, {'resourceType': kind, 'resourceMode': 'IMPORT'}, seed_rows)
        for prop, item in mapped.items():
            field = item.field
            if prop.startswith(kind + '.') and field.getter in record['getters']:
                raw = m.select(record['getters'][field.getter], field.path)
                if raw not in (m.MISSING, None) and not sensitive(proxy, prop) and not unsafe(raw):
                    try:
                        seed_rows.append((record_id + '-' + str(len(seed_rows) + 1).zfill(3), {'property': prop, 'value': model_literal(raw)}))
                    except ValueError:
                        pass  # A non-scalar seed cannot be an adapter selector.
        for prop, raw in record.get('seedProperties', {}).items():
            if not any(row['property'] == prop for _, row in seed_rows) and not unsafe(raw):
                try:
                    seed_rows.append((record_id + '-' + str(len(seed_rows) + 1).zfill(3), {'property': prop, 'value': model_literal(raw)}))
                except ValueError:
                    pass  # Unrepresentable data cannot be an adapter selector.
        for getter, payload in record['getters'].items():
            ctx.fetch_cache[model.path, record_id, getter] = payload
            ctx.fetch_trace[model.path, record_id, getter] = []
        properties = {p: item for p, item in mapped.items() if p.startswith(kind + '.') and item.include}
        fields = {p: item.field for p, item in properties.items()}
        fields.update({p: item.field for p, item in mapped.items() if p in MODEL_ONLY and p.startswith(kind + '.')})
        if kind == 'EC2.Subnet' and 'association' in record['getters']:
            fields.update({p: item.field for p, item in mapped.items() if p == 'EC2.SubnetRouteTableAssociation.RouteTableId' and item.include})
        if kind == 'EC2.FlowLog':
            resource_type = next((name for prefix, name in [('vpc-', 'VPC'), ('subnet-', 'Subnet'), ('eni-', 'NetworkInterface')]
                                  if seed.get('ResourceId', '').startswith(prefix)), None)
            if resource_type:
                ctx.fetch_cache[model.path, record_id, 'resource_type'] = {'ResourceType': resource_type}
                ctx.fetch_trace[model.path, record_id, 'resource_type'] = []
        if {kind + '.Tags[].Key', kind + '.Tags[].Value'} <= fields.keys() and seed.get('Tags'):
            tags = [tag for tag in seed['Tags'] if tag.get('Key') != 'Name' or kind not in {'EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'}]
            ctx.fetch_cache[model.path, record_id, 'tags'] = {'Tags': sorted(tags, key=lambda tag: tag['Key'])}
            ctx.fetch_trace[model.path, record_id, 'tags'] = []
            fields.update({kind + '.Tags[].' + leaf: m.Field('tags', 'Tags[].' + leaf) for leaf in ('Key', 'Value')})
        captured = {}
        for prop, field in fields.items():
            try:
                if sensitive(proxy, prop):
                    raise ValueError('sensitive Property')
                if field.classification != 'supported':
                    raise ValueError(field.classification + ': ' + field.reason)
                if prop in properties and field.getter != 'tags':
                    _, value = mapping_value(ctx, proxy, mapping, properties[prop], prop)
                else:
                    value = m.select(ctx.fetch(proxy, field.getter), field.path)
                if value == m.MISSING:
                    captured[prop] = {'status': 'missing', 'reason': 'AWS optional value not retrieved'}
                    continue
                expected = inventory_for(ctx).property_schema(prop).get('type')
                types = {'string': (str,), 'integer': (int,), 'number': (int, float), 'boolean': (bool,), 'object': (dict,), 'array': (list,), 'null': (type(None),)}
                allowed = expected if isinstance(expected, list) else [expected] if expected else []
                extracted = [value]
                for _ in range(prop.count('[]')):
                    if any(not isinstance(item, list) for item in extracted):
                        raise ValueError('AWS array projection does not match the Property path')
                    extracted = [leaf for item in extracted for leaf in item]
                for item in extracted:
                    if item == m.MISSING or unsafe(item):
                        raise ValueError('sensitive or unresolved AWS value')
                    if allowed and not any(type(item) in types.get(name, ()) for name in allowed):
                        raise ValueError('AWS value type does not match the registered schema')
                captured[prop] = {'status': 'captured', 'value': value, 'source': properties[prop].source if prop in properties else 'aws'}
            except (ValueError, KeyError, TypeError, m.AcquisitionError, m.Unresolved) as error:
                reason = error.code if isinstance(error, m.AcquisitionError) else 'sensitive Property' if sensitive(proxy, prop) else type(error).__name__
                captured[prop] = {'status': 'unavailable', 'reason': reason}
        identity = inventory_for(ctx).identity(kind, record)
        normalized.append({'record': record_id, 'kind': kind, 'identity': record['identity'],
                           **identity, 'properties': captured})
    return normalized


def source_snapshot(root, path, expansion, identities):
    """Hash direct inputs once; never expand another environment or a Git Model."""
    from model_templates import safe, source_paths, parse_template
    _, template, directory = source_paths(path)
    files = set(expansion.files) | {root / 'project.json', root / 'framework/mappings/aws' / (path.stem + '.yaml'),
                                   template, directory / 'parameters.yaml', directory / 'bindings.json', directory / 'observed.json'}
    if not expansion.values and template.is_file():
        files.update(parse_template(template)[1])
    for identity in identities:
        directory = root / 'model/parameters' / '/'.join(identity)
        files.update(directory / name for name in ('parameters.yaml', 'bindings.json'))
    result = {}
    for file in files:
        safe(root, file)
        result[file.relative_to(root).as_posix()] = file_hash(file)
    return result


def unchanged(root, checksums):
    from model_templates import safe
    for relative, expected in checksums.items():
        file = root / relative
        safe(root, file)
        if file_hash(file) != expected:
            raise ValueError('Model sources changed during import; concurrent changes were not overwritten: ' + relative)


@input_scope
def acquire(root, environment, service, selector=None, dry_run=False, cli_runner=None, no_profile=False, resource_types=None):
    from import_scope import restrict, read_consumers
    from model_templates import consumers
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    if no_profile:
        target.pop('awsProfile', None)
    identity = (environment, target['directory'], service)
    with restrict(identity), read_consumers({identity}):
        if not dry_run:
            contract_scope(root, {identity})
            require_import_changes(root, generation=True)
        path = root / 'model' / identity[0] / identity[1] / (service + '.properties')
        from model_templates import Expansion
        expansion = load_for_edit(path) or Expansion({}, {}, {})
        direct = consumers(root, identity[1], service)
        snapshots = source_snapshot(root, path, expansion, direct)
        contract = None if dry_run else task_path(root)
        if contract:
            snapshots[contract.relative_to(root).as_posix()] = file_hash(contract)
        ctx = import_context(root, target, cli_runner, service)
        ctx.verify()
        records = normalize_records(ctx, service, inventory(ctx, service, resource_types))
        unchanged(root, snapshots)
        evidence, value = acquired(root, identity, ctx, records, snapshots, direct, dry_run)
        return {'status': 'acquired' if acquisition_complete(value) else 'incomplete', 'inventory': value['inventory'], 'metrics': dict(ctx.metrics), 'scope': list(identity), 'evidence': str(evidence),
                'candidates': str(evidence.parent / 'candidates'), 'selection': str(evidence.parent / 'selection.json'),
                'records': records, 'connection': value['connection'], 'sts': value['sts'],
                'warnings': list(expansion.warnings), 'model': 'unchanged', 'markdown': 'not-run', 'designValidation': 'not-run', 'dryRun': dry_run}


def pending_items(selection, selected, values):
    """Report absent/unreflected acquired settings independently from saved sources."""
    pending = list(selection['unreflected'])
    known = {(item['record'], item.get('property')) for item in pending}
    for rid, record in selected.items():
        for prop, capture in record['properties'].items():
            if (record['record'], prop) in known:
                continue
            represented = any(row['property'] == prop for _, row in resource_row_index(values)[rid])
            if capture['status'] == 'missing' and not represented:
                continue
            if capture['status'] == 'captured':
                from import_sources import property_values
                if typed_equal(property_values(values, rid, prop, property_schema(prop)), capture['value']):
                    continue
            pending.append({'record': record['record'], 'property': prop,
                            'reason': capture.get('reason', 'acquired Property not reflected by the candidate')})
    return pending


@input_scope
def publish_acquisition(root, environment, service, evidence, selector=None, dry_run=False):
    from import_scope import restrict, read_consumers
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    identity = (environment, target['directory'], service)
    evidence = Path(evidence).absolute()
    with restrict(identity), read_consumers({identity}):
        try:
            acquisition = read_acquisition(root, evidence, identity, dry_run)
            result = publish_selected(root, identity, evidence, acquisition, dry_run)
        finally:
            if dry_run:
                discard_acquisition(root, evidence)
        if not dry_run:
            discard_acquisition(root, evidence)
        return result


def publish_selected(root, identity, evidence, acquisition, dry_run):
    from model_templates import consumers
    from sync_runtime import owned_artifacts, view_plan
    path = root / 'model' / identity[0] / identity[1] / (identity[2] + '.properties')
    direct = {tuple(item) for item in acquisition['consumers']}
    foreign = {str(Path('model/parameters') / '/'.join(item) / name)
               for item in direct - {identity} for name in ('parameters.yaml', 'bindings.json')}
    checksums = {name: checksum for name, checksum in acquisition['sources'].items() if name not in foreign}
    unchanged(root, checksums)
    if not dry_run:
        contract_scope(root, {identity})
        require_import_changes(root, generation=True)
    output = candidate_sources(root, evidence.parent / 'candidates', identity)
    for file in output:
        relative = file.relative_to(root).as_posix()
        checksums.setdefault(relative, acquisition['sources'].get(relative))
    unchanged(root, checksums)
    from model_templates import Expansion
    before = load_for_edit(path) or Expansion({}, {}, {})
    after = load_for_edit(path, output)
    if after is None:
        raise ValueError('IMPORT missing service requires explicit template, parameters and bindings candidates')
    if not before.values and (set(dict(entries(after.values, 'desired.service.'))) != {identity[2]} or
                             after.values.get('desired.service.' + identity[2] + '.serviceId') != identity[2]):
        raise ValueError('IMPORT new service metadata must match the selected service')
    selection = json_read((evidence.parent / 'selection.json').read_text(encoding='utf-8'))
    warnings = [*before.warnings, *after.warnings]
    selected = selection_records(selection, acquisition['records'], before.values, after.values, property_schema, warnings)
    consumer_inputs, preserved, shared = preserve_consumers(path, before, output, direct, selected)
    for file in consumer_inputs:
        relative = file.relative_to(root).as_posix()
        checksums[relative] = acquisition['sources'].get(relative)
    if shared:
        checksums.update({name: acquisition['sources'][name] for name in foreign if name.endswith('/bindings.json')})
    unchanged(root, checksums)
    if shared and consumers(root, identity[1], identity[2]) != direct:
        raise ValueError('IMPORT registered direct consumers changed after acquisition')
    from import_scope import new_references, preserved_reference_view
    from import_references import Resolver
    if any(key.startswith('desired.row.') and key.split('.')[2].rpartition('-')[0] in selected
           and '<<' in after.values.get(key, '') and (trace.get('references') or
                any(item.get('type') == 'reference' for item in trace.get('inputs', {}).values()))
           for key, trace in after.provenance.items()):
        with new_references(before, selected):
            before = load_for_edit(path) or before
            after = load_for_edit(path, after.files)
    references = Resolver(root, identity[0], identity[1], local={identity[2]: after})
    changes = verify_values(before, after, selected, property_schema, references, warnings=warnings)
    warnings.extend(references.warnings)
    incoming_inputs, incoming_services = replacement_inputs(root, identity, selected, warnings)
    for file, text in incoming_inputs.items():
        checksums.setdefault(file.relative_to(root).as_posix(), text_hash(text))
    # Producers are read dependencies, never candidate writes or display targets.
    for file, text in {**after.files, **references.files}.items():
        if file not in output:
            checksums.setdefault(file.relative_to(root).as_posix(), text_hash(text))
    pending = pending_items(selection, selected, after.values)
    complete = not pending and acquisition_complete(acquisition)
    result = {'status': 'incomplete' if not complete else 'dry-run' if dry_run else 'complete',
              'scope': ['/'.join(identity)], 'model': 'unchanged', 'markdown': 'not-run',
              'designValidation': 'not-run', 'dryRun': dry_run,
              'resources': {'added': sum(item['action'] == 'add' for item in selection['resources']),
                            'refreshed': sum(item['action'] == 'refresh' for item in selection['resources']),
                            'replaced': sum(item['action'] == 'replace' for item in selection['resources']),
                            'excluded': len(selection['excluded']), 'unresolved': sum('property' not in item for item in pending)},
              'unreflected': pending, 'inventory': acquisition.get('inventory', {}), 'warnings': warnings, 'changes': changes, 'files': sorted(p.relative_to(root).as_posix() for p in output),
              'preservedConsumers': sorted('/'.join(item) for item in preserved)}
    result['referenceMetrics'] = references.metrics
    unchanged(root, checksums)
    if dry_run:
        result['diff'] = '\n'.join(''.join(difflib.unified_diff(
            (file.read_text(encoding='utf-8') if file.is_file() else '').splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile=file.relative_to(root).as_posix(), tofile=file.relative_to(root).as_posix())) for file, text in output.items())
        return result
    document = root / 'docs/designs' / identity[0] / identity[1] / (identity[2] + '.md')
    managed = owned_artifacts(document, before.values)
    write_sealed(root, evidence.parent / 'publication.json', {
        'acquisition': acquisition, 'selection': selection,
        'sources': {file.relative_to(root).as_posix(): {'before': file.read_text(encoding='utf-8') if file.is_file() else None, 'after': text}
                    for file, text in output.items()}})
    record_outputs(root, identity, set(output), set(), preserved)
    task_relative = task_path(root).relative_to(root).as_posix()
    checksums[task_relative] = file_hash(task_path(root))
    acquisition['sources'][task_relative] = checksums[task_relative]
    write_sealed(root, evidence, acquisition)
    snapshot = {root / name: (root / name).read_bytes() if checksum is not None else None for name, checksum in checksums.items()}
    from inspect import unwrap
    from model_templates import _reference_inputs, reference_values
    memo = memo_table()
    readers = {unwrap(_reference_inputs), unwrap(reference_values)}
    producers = {key: value for key, value in memo.items()
                 if key[0] in readers and key[1][0] in references.model_paths}
    with publication_lock(root):
        contract_scope(root, {identity})
        unchanged(root, checksums)
        if incoming_services and tuple(sorted((root / 'model/parameters' / identity[0] / identity[1]).glob('*'))) != incoming_services:
            raise ValueError('IMPORT reference consumer services changed before publication')
        if shared and consumers(root, identity[1], identity[2]) != direct:
            raise ValueError('IMPORT registered direct consumers changed before publication')
        from import_guard import proof_path
        proof = proof_path(root)
        previous = proof.read_text(encoding='utf-8') if proof.is_file() else None
        record_import(root, output, evidence, {'sources': {p.relative_to(root).as_posix(): text for p, text in output.items()},
                      'selection': selection, 'changes': changes,
                      'ownedArtifacts': sorted(p.relative_to(root).as_posix() for p in managed)}, complete=complete)
        try:
            publish(root, output, inputs=snapshot, verify=lambda: finish_import(root, 'reflected' if output else 'unchanged'))
        except (OSError, ValueError):
            atomic_files({proof: previous}, staging_directory=proof.parent)
            raise
    result['model'] = 'reflected' if output else 'unchanged'
    snapshot.update({p: text.encode('utf-8') for p, text in output.items()})
    memo.clear()
    memo.update(producers)  # Producer bytes remain guarded by both publication snapshots.
    try:
        with publication_lock(root):
            with new_references(before, selected), preserved_reference_view(before):
                saved = load_for_edit(path, display=True)
            publication, view_inputs = view_plan(document, saved.values, root, managed)
            view_inputs.update({file: snapshot.get(file, text.encode('utf-8')) for file, text in saved.files.items()})
            for file in saved.files:
                if file.name == 'parameters.yaml':
                    view_inputs.setdefault(file.parent / 'observed.json', None)
        record_outputs(root, identity, set(), set(publication), preserved)
        snapshot[task_path(root)] = task_path(root).read_bytes()
        with publication_lock(root):
            contract_scope(root, {identity})
            publish(root, publication, inputs={**snapshot, **view_inputs})
            finish_import(root, markdown='generated' if publication else 'unchanged')
        result['markdown'] = 'generated' if publication else 'unchanged'
        result['files'] = sorted(set(result['files']) | {p.relative_to(root).as_posix() for p in publication})
    except ReferenceResolutionError as error:
        result['markdown'] = 'retained' if document.is_file() else 'not-generated'
        result['warnings'].append({**error.diagnostic, 'scope': '/'.join(identity),
                                   'retainedView': str(document) if document.is_file() else None})
        result['viewComplete'] = False
    except Exception as error:
        result['markdown'] = 'failed'
        result['displayError'] = str(error)
        try:
            finish_import(root, markdown='failed')
        except (OSError, ValueError):
            result['displayError'] += '; evidence update failed'
    result['status'] = 'incomplete' if not complete else 'display-failed' if result['markdown'] == 'failed' else 'complete'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, default=ROOT)
    parser.add_argument('--environment', required=True)
    parser.add_argument('--service', required=True)
    parser.add_argument('--target')
    parser.add_argument('--resource-type', action='append', dest='resource_types')
    parser.add_argument('--phase', choices=('acquire', 'publish'), required=True)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-profile', action='store_true', help='Acquire with the default credential chain, retaining Region and STS account verification')
    args = parser.parse_args()
    if (args.phase == 'acquire' and args.evidence is not None or
            args.phase == 'publish' and (args.evidence is None or args.no_profile or args.resource_types)):
        parser.error('acquire accepts --no-profile; publish requires --evidence and never accesses AWS')
    try:
        result = (acquire(args.repository_root, args.environment, args.service, args.target, args.dry_run, no_profile=args.no_profile, resource_types=args.resource_types)
                  if args.phase == 'acquire' else publish_acquisition(args.repository_root, args.environment, args.service,
                                                                    args.evidence, args.target, args.dry_run))
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result['status'] == 'incomplete' else 3 if result['markdown'] == 'failed' else 0
    except Exception as error:
        controlled = ('environment ', 'target ', 'AWS ', 'IMPORT ', 'import ', 'Model sources changed',
                      'normal import requires', 'include every affected consumer')
        reason = (error.code if isinstance(error, comparator().AcquisitionError) else
                  str(error) if type(error) is ValueError and str(error).startswith(controlled) else type(error).__name__)
        print(json.dumps({'status': 'failed', 'model': 'failed', 'markdown': 'not-run', 'designValidation': 'not-run', 'reason': reason}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
