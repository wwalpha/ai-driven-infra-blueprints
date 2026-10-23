"""Single-service Import primitives; the LLM supplies selections, Review and consent."""

import argparse
import hashlib
import re
from dataclasses import asdict
from functools import partial as _bind_framework_callback
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import project_targets as _imports_project_targets
import task_contract_core as task_contract
import worktree_state
from aws_mapping_compare import MODEL_ONLY
from aws_mapping_compare import value as mapping_value
from generation_inputs import GenerationInputs
from import_guard import (
    file_hash,
    proof_path,
    require_import_changes,
    workflow,
)
from script_loader import module as load_script
from task_contract_core import contract_read_scope, contract_reads, section, selected_task, task_path
from utils.file_operations import atomic_files
from utils.input_cache import input_context, input_scope, memoized, recording_inputs
from utils.json_format import json_text
from utils.source_reads import FileReads as FileReads
from validation_scope import active_scope

import model.importing.references as _imports_model_importing_references
import model.importing.scope as _exports_model_importing_scope
import model.importing.scope as _imports_model_importing_scope
import model.references as _imports_model_references
import model.sources as _imports_model_sources
from model.core import ReferenceResolutionError
from model.core import entries as entries
from model.importing import approval as import_approval
from model.importing.evidence import (
    acquired,
    acquisition_complete,
    finish_import,
    read_acquisition,
    read_proof,
    record_import,
)
from model.importing.evidence import (
    discard_acquisition as discard_acquisition,
)
from model.importing.inventory import inventory_for
from model.importing.scope import (
    model_path,
    read_consumers,
    restrict,
)
from model.importing.sources import (
    pending_items,
    selection_records,
    verify_values,
)
from model.operations import prepare_edit, publish_edit
from model.render import owned_artifacts, view_plan
from model.sources import (
    SourceWriteContext,
    _publish_transaction,
    candidate_sources,
    json_read,
    load_model,
    publication_lock,
    safe,
)
from model.sources import candidate_base as before_model

# Preserve shared fixtures and compatibility exports under their historical names.
selected = _exports_model_importing_scope.selected



ROOT = Path(__file__).resolve().parents[4]

def comparator():
    return load_script('model/adapters/aws.py', 'model.adapters.aws')


def import_context(root, target, runner=None, service=None):
    profile = target.get('awsProfile')
    if 'awsProfile' in target and (not isinstance(profile, str) or not profile or profile != profile.strip() or profile == 'UNSET' or any(c in profile for c in '\r\n\0')):
        raise ValueError('AWS target has an invalid project.json awsProfile; no fallback')
    region = target.get('awsRegion')
    if not isinstance(region, str) or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*', region):
        raise ValueError('AWS target RegionMismatch; use the project.json awsRegion')
    return comparator().Context(root, target, cli_runner=runner, services=(service,) if service else (), import_mode=True)


def target_for(root, environment, service, selector=None):
    select_target = _imports_project_targets.select_target
    if not environment or not service or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', x) for x in (environment, service)):
        raise ValueError('environment and service are required exact identifiers')
    topology = json_read((root / 'project.json').read_text(encoding='utf-8'))
    choices = [t for t in topology['targets'] if isinstance(t, dict) and t.get('environment') == environment]
    if not choices:
        raise ValueError('environment is not registered')
    if selector is None and len(choices) > 1:
        choices = [t for t in choices if (root / 'model' / environment /
                   t.get('alias', t['awsAccountId']) / (service + '.properties')).is_file()]
    if selector is None:
        if len(choices) != 1:
            raise ValueError('target is required when the environment has multiple targets for this service')
        selector = choices[0].get('alias', choices[0]['awsAccountId'])
    choices = [t for t in choices if t.get('alias', t.get('awsAccountId')) == selector]
    if len(choices) != 1:
        raise ValueError('target must resolve exactly once')
    entry = choices[0]
    target = select_target(topology, environment, alias=entry.get('alias'), account_id=None if 'alias' in entry else selector)
    target.update(environment=environment, directory=selector)
    return target


def inventory(ctx, service, resource_types=None):
    return inventory_for(ctx).discover(service, resource_types)


@contract_read_scope
def contract_scope(root, scope):
    selected = _imports_model_importing_scope.selected
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
    if len(scope) != 1 or selected(root) not in scope or declared is None or not scope <= declared:
        raise ValueError('IMPORT requires one fixed environment/target/service within Validation scope')
    if task_contract.status(text) != 'running':
        raise ValueError('IMPORT requires a running Task Contract')


@contract_read_scope
def record_outputs(root, identity, sources, views, consumers=None):
    """Check the predeclared plan without changing an approved Task/acquisition."""
    allowed_source = _imports_model_importing_scope.allowed_source
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
    declared = active_scope(root)
    if fixed not in section(text, '## Task contract') or not consumers <= declared:
        raise ValueError('IMPORT Task must declare its fixed target and direct consumers before acquisition')
    for heading in ('## Allowed paths', '## Modified files'):
        if not paths <= task_contract.paths_in(text, heading):
            raise ValueError('IMPORT Task must declare exact output paths before acquisition: ' + heading)


def sensitive(resource, prop):
    return resource.module.sensitive(prop or '') or bool(re.search(r'password|credential|accesskey|secretstring|secretbinary|privatekey|token|authorization|username', prop or '', re.I))


def unsafe(value):
    text = json_text(value)
    return ('[REDACTED]' in text or
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


def unchanged(root, checksums):
    safe = _imports_model_sources.safe
    for relative, expected in checksums.items():
        file = root / relative
        safe(root, file)
        if file_hash(file) != expected:
            raise ValueError('Model sources changed during import; concurrent changes were not overwritten: ' + relative)


@input_scope
@contract_read_scope
def resume_acquisition(root, environment, service, evidence, selector=None, dry_run=False):
    """Read the LLM's checkpoint after verifying the original session and live baseline."""
    safe = _imports_model_sources.safe
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    identity = (environment, target['directory'], service)
    evidence = Path(evidence).absolute()
    with publication_lock(root, read_only=True):
        acquisition = read_acquisition(root, evidence, identity, dry_run)
        unchanged(root, acquisition['sources'])
        unchanged_sets(root, acquisition['sourceSets'])
        file = evidence.parent / 'checkpoint.json'
        safe(evidence.parent, file)
        answers = import_approval.verify_checkpoint(acquisition, json_read(file.read_text(encoding='utf-8')))
    return {'status': 'resumed', 'answers': answers, 'model': 'unchanged',
            'markdown': 'not-run', 'designValidation': 'not-run'}





def source_state(root, inputs):
    files = {path.relative_to(root).as_posix(): None if raw is None else hashlib.sha256(raw).hexdigest()
             for path, raw in inputs.contents.items() if path.is_relative_to(root)}
    sets = [{'base': base.relative_to(root).as_posix(), 'pattern': pattern, 'recursive': recursive,
             'kinds': kinds, 'paths': [path.relative_to(root).as_posix() for path in paths]}
            for (base, pattern, recursive, kinds), paths in inputs.selections.items() if base.is_relative_to(root)]
    return dict(sorted(files.items())), sorted(sets, key=json_text)


def unchanged_sets(root, sets):
    for record in sets:
        if not isinstance(record, dict) or set(record) != {'base', 'pattern', 'recursive', 'kinds', 'paths'}:
            raise ValueError('IMPORT invalid input file-set snapshot')
        relative = PurePosixPath(record['base'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) != record['base'] or '\\' in record['base']:
            raise ValueError('IMPORT unsafe input file-set base')
        base = root / relative
        safe(root, base)
        if type(record['recursive']) is not bool or not isinstance(record['pattern'], str) or not isinstance(record['paths'], list):
            raise ValueError('IMPORT invalid input file-set selector')
        pattern = PurePosixPath(record['pattern'])
        if pattern.is_absolute() or '..' in pattern.parts or '\\' in record['pattern']:
            raise ValueError('IMPORT unsafe input file-set pattern')
        live = GenerationInputs.live_select(base, record['pattern'], record['recursive'], record['kinds'])
        if [path.relative_to(root).as_posix() for path in live] != record['paths']:
            raise ValueError('IMPORT source file set changed after acquisition: ' + record['base'])



def replacement_inputs(before, selected_records, reads):

    incoming = _imports_model_references.incoming
    warnings = [{**warning, 'phase': 'before'} for warning in before.warnings]
    for rid, record in selected_records.items():
        if record.get('_action') not in {'replace', 'bind'}:
            continue
        producer = '/'.join((before.scope.environment, before.scope.target, before.scope.service, rid))
        for scope, usage in incoming(before, rid, reads, warnings=warnings):
            owner_id = usage.consumer_key.split('.')[2].rpartition('-')[0] if usage.consumer_key.startswith('desired.row.') else usage.consumer_key.split('.')[2]
            consumer = '/'.join((scope.environment, scope.target, scope.service, owner_id))
            if consumer != producer:
                warnings.append({'code': 'reference.replace_impact',
                    'message': 'replacement or first binding affects an incoming reference',
                    'resource': rid, 'producer': producer, 'consumer': consumer, **asdict(usage)})
    files, sets = source_state(before.scope.root, reads)
    return {'inputs': files, 'fileSets': sets, 'warnings': warnings}


@input_scope
def acquire(root, environment, service, selector=None, dry_run=False, cli_runner=None, no_profile=False, resource_types=None):
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    if no_profile:
        target.pop('awsProfile', None)
    identity = environment, target['directory'], service
    with restrict(identity), read_consumers({identity}), input_context(), publication_lock(root, read_only=True):
        if not dry_run:
            contract_scope(root, {identity})
            if proof_path(root).exists():
                raise ValueError('IMPORT Task already published; recover its display or use a new Task')
            require_import_changes(root, generation=True)
        inputs = GenerationInputs(root)
        try:
            with contract_reads(root), recording_inputs(inputs):
                before = before_model(model_path(root, identity), inputs)
                ctx = import_context(root, target, cli_runner, service)
                ctx.verify()
                records = normalize_records(ctx, service, inventory(ctx, service, resource_types))
            inputs.verify()
            files, sets = source_state(root, inputs)
            evidence, value = acquired(root, identity, ctx, records, files, {identity}, dry_run, source_sets=sets)
            return {'status': 'acquired' if acquisition_complete(value) else 'incomplete',
                'scope': list(identity), 'evidence': str(evidence), 'records': records, 'inventory': value['inventory'],
                'candidates': str(evidence.parent / 'candidates'), 'selection': str(evidence.parent / 'selection.json'),
                'connection': value['connection'], 'sts': value['sts'], 'warnings': list(before.warnings),
                'model': 'unchanged', 'markdown': 'not-run', 'designValidation': 'not-run', 'dryRun': dry_run}
        finally:
            inputs.close()


@contract_read_scope
def review_inputs(root, identity, evidence, acquisition, inputs):
    Resolver = _imports_model_importing_references.Resolver
    unchanged(root, acquisition['sources'])
    unchanged_sets(root, acquisition['sourceSets'])
    before = before_model(model_path(root, identity), inputs)
    output, after = candidate_sources(root, evidence.parent / 'candidates', before)
    selection_file, draft_file = evidence.parent / 'selection.json', evidence.parent / 'review-input.json'
    for file in (selection_file, draft_file):
        safe(evidence.parent, file)
    selection_text, draft_text = selection_file.read_bytes(), draft_file.read_bytes()
    selection, draft = json_read(selection_text), json_read(draft_text)
    if (not isinstance(draft, dict) or 'risks' not in draft or set(draft) - {'risks', 'referenceProvenance'}
            or 'referenceProvenance' in draft and not isinstance(draft['referenceProvenance'], dict)):
        raise ValueError('IMPORT Review requires risks and optional complete referenceProvenance after map; flags grant no approval')
    selected_records = selection_records(selection, acquisition['records'], before.authoritative,
                                         after.authoritative, property_schema)
    proposed_references = draft.get('referenceProvenance', import_approval.reference_provenance(before))
    if proposed_references != import_approval.reference_provenance(after):
        raise ValueError('IMPORT candidate reference map differs from the complete Review after map')
    references = Resolver(root, identity[0], identity[1], local={identity[2]: after}, read_context=inputs)
    changes = verify_values(before, after, selected_records, property_schema, references)
    impact = replacement_inputs(before, selected_records, inputs)
    warnings = [{**warning, 'phase': phase} for phase, items in (
        ('after', after.warnings), ('physical', references.warnings)) for warning in items]
    specs = import_approval.reference_provenance(after)
    warnings = [*impact['warnings'], *warnings]
    for warning in warnings:
        warning.setdefault('phase', 'incoming')
        key = warning.get('consumerKey', warning.get('consumer_key', warning.get('key')))
        if key:
            warning.setdefault('consumerKey', key)
            if key.startswith('desired.row.'):
                warning.setdefault('resource', key.split('.')[2].rpartition('-')[0])
            elif key.startswith('desired.resource.'):
                warning.setdefault('resource', key.split('.')[2])
            matching = sorted(identity for identity, spec in specs.items()
                              if spec['consumerKey'] == key and spec.get('pointer') == warning.get('pointer'))
            if warning['phase'] == 'physical':
                warning['referenceIds'] = matching
    impact['warnings'] = sorted(warnings, key=json_text)
    # Resolve physical and incoming dependencies before binding the final Review.
    for path in after.dependencies:
        if path not in after.files:
            inputs.read(path)
    impact['inputs'], impact['fileSets'] = source_state(root, inputs)
    review = import_approval.build_review(acquisition, selection, before, dict(after.authoritative), draft['risks'],
        property_schema, proposed_references=proposed_references, reference_impact=impact)
    if comparator().redacted(review) != review:
        raise ValueError('IMPORT Review contains sensitive data')
    return before, after, output, selection, review, changes, {selection_file: selection_text, draft_file: draft_text}


@input_scope
def review_acquisition(root, environment, service, evidence, selector=None, dry_run=False):
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target['directory'], service
    with restrict(identity), read_consumers({identity}), input_context(), publication_lock(root, read_only=True):
        acquisition = read_acquisition(root, evidence, identity, dry_run)
        inputs = GenerationInputs(root)
        try:
            with contract_reads(root), recording_inputs(inputs):
                _, _, _, _, review, _, external = review_inputs(root, identity, evidence, acquisition, inputs)
            inputs.verify()
            if any(file.read_bytes() != raw for file, raw in external.items()):
                raise ValueError('IMPORT Review inputs changed during verification')
            destination = evidence.parent / 'review.json'
            safe(evidence.parent, destination)
            atomic_files({destination: json_text(review) + '\n'}, staging_directory=evidence.parent)
            return {'status': 'reviewed', 'review': review, 'reviewFile': str(destination),
                    'model': 'unchanged', 'markdown': 'not-run', 'designValidation': 'not-run'}
        finally:
            inputs.close()


def _callback_publish_acquisition_current(acquisition, before, evidence, expected_task, external, identity, output, review_file, review_raw, root, /, changes):
    with contract_reads(root):
        if task_contract.task_revision(root, selected=expected_task[0]) != expected_task:
            raise ValueError('IMPORT Task changed before publication')
        unchanged(root, acquisition['sources'])
        unchanged_sets(root, acquisition['sourceSets'])
        if (candidate_sources(root, evidence.parent / 'candidates', before)[0] != output
                or any(file.read_bytes() != raw for file, raw in external.items())
                or review_file.read_bytes() != review_raw
                or read_acquisition(root, evidence, identity, False) != acquisition):
            raise ValueError('IMPORT candidate, selection, acquisition or Review changed before publication')
        record_outputs(root, identity, set(changes), set())


def _callback_publish_acquisition_begin_receipt(after, binding, changes, evidence, managed, output, root, selected_records, selection, /):
    record_import(root, output, evidence, {'sources': {p.relative_to(root).as_posix(): text for p, text in output.items()},
        'selection': selection, 'changes': changes, 'ownedArtifacts': [p.relative_to(root).as_posix() for p in managed]},
        complete=not pending_items(selection, selected_records, after.values, property_schema), review_binding=binding)


def _callback_publish_acquisition_finish_model(acquisition, after, before, evidence, external, identity, output, review_file, review_raw, root, /):
    if (read_acquisition(root, evidence, identity, False) != acquisition
            or any(file.read_bytes() != raw for file, raw in external.items())
            or review_file.read_bytes() != review_raw
            or candidate_sources(root, evidence.parent / 'candidates', before)[1].files != after.files):
        raise ValueError('IMPORT candidate, selection, acquisition or Review changed during publication')
    finish_import(root, model='reflected' if output else 'unchanged')


@input_scope
def publish_acquisition(root, environment, service, evidence, selector=None, dry_run=False):
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target['directory'], service
    with restrict(identity), read_consumers({identity}), input_context(), publication_lock(root):
        acquisition = read_acquisition(root, evidence, identity, dry_run)
        review_file = evidence.parent / 'review.json'
        safe(evidence.parent, review_file)
        if not review_file.is_file():
            raise ValueError('IMPORT publication requires review.json containing the complete current Review')
        review_raw = review_file.read_bytes()
        reviewed = json_read(review_raw)
        import_approval.verify_review(reviewed, reviewed)
        inputs = GenerationInputs(root)
        context = None
        try:
            with contract_reads(root), recording_inputs(inputs):
                before, after, output, selection, expected, changes, external = review_inputs(root, identity, evidence, acquisition, inputs)
                import_approval.verify_review(reviewed, expected)
                document = root / 'docs/designs' / identity[0] / identity[1] / (identity[2] + '.md')
                managed = owned_artifacts(document, before.values)
                display_warning = None
                try:
                    views, _ = view_plan(document, after.values, root, managed)
                except ReferenceResolutionError as error:
                    views = {}
                    display_warning = error.diagnostic
                inputs.verify()
            if dry_run:
                return {'status': 'dry-run', 'review': expected, 'model': 'unchanged', 'markdown': 'not-run'}
            binding = import_approval.review_binding(expected, acquisition)
            record_outputs(root, identity, set(output), set(views))
            expected_task = inputs.expected_task
            current = _bind_framework_callback(_callback_publish_acquisition_current, acquisition, before, evidence, expected_task, external, identity, output, review_file, review_raw, root)
            proof = proof_path(root)
            previous = proof.read_bytes() if proof.is_file() else None
            selected_records = selection_records(selection, acquisition['records'], before.authoritative, after.authoritative, property_schema)
            begin_receipt = _bind_framework_callback(_callback_publish_acquisition_begin_receipt, after, binding, changes, evidence, managed, output, root, selected_records, selection)
            finish_model = _bind_framework_callback(_callback_publish_acquisition_finish_model, acquisition, after, before, evidence, external, identity, output, review_file, review_raw, root)
            context = SourceWriteContext._authorized(root, inputs, SimpleNamespace(action='import'), current,
                frozenset(output), start=begin_receipt, receipt=(expected_task[0], previous),
                finish=finish_model)
            plan = prepare_edit(before, output, context)
            publish_edit(plan, context)
            result = {'status': 'saved', 'model': 'reflected' if output else 'unchanged', 'markdown': 'not-run',
                      'designValidation': 'not-run', 'warnings': list(after.warnings), 'changes': changes}
            if display_warning is not None:
                result['warnings'].append(display_warning)
                result.update(status='incomplete', markdown='retained' if document.is_file() else 'not-generated', viewComplete=False)
                return result
            try:
                result.update(recover_display(root, environment, service, selector))
            except (OSError, ValueError) as error:
                result.update(status='display-failed', markdown='failed', displayError=str(error))
                try:
                    finish_import(root, markdown='failed')
                except (OSError, ValueError) as receipt_error:
                    result['displayError'] += '; receipt update failed: ' + str(receipt_error)
            return result
        finally:
            if context is not None:
                context.close()
            else:
                inputs.close()


def _callback_recover_transaction_authorize(acquisition, evidence, expected_task, identity, managed_task_state, name, root, state, /, record):
    with contract_reads(root):
        if record.get('importReceipt', {}).get('task') != name:
            raise ValueError('pending transaction belongs to a different Task or is not an Import transaction')
        if (task_contract.task_revision(root, selected=name) != expected_task or managed_task_state(root, name) != state
                or read_acquisition(root, evidence, identity, False) != acquisition):
            raise ValueError('Import recovery Task/Worktree/acquisition changed')
        paths = {root / relative for relative in record['originals']}
        sources = {path for path in paths if path.is_relative_to(root / 'model')}
        record_outputs(root, identity, sources, paths - sources)


@input_scope
def recover_transaction(root, environment, service, evidence, selector=None, dry_run=False):
    """Restore only this Task's interrupted source/display transaction, with no AWS calls."""
    managed_task_state = worktree_state.managed_task_state
    if dry_run:
        raise ValueError('a dry-run acquisition cannot authorize transaction recovery')
    root, evidence = root.resolve(), Path(evidence).absolute()
    target = target_for(root, environment, service, selector)
    identity = environment, target['directory'], service
    with restrict(identity), read_consumers({identity}), input_context():
        contract_scope(root, {identity})
        acquisition = read_acquisition(root, evidence, identity, False)
        name = workflow(root)
        state = managed_task_state(root, name)
        expected_task = task_contract.task_revision(root, selected=name)
        authorize = _bind_framework_callback(_callback_recover_transaction_authorize, acquisition, evidence, expected_task, identity, managed_task_state, name, root, state)
        with publication_lock(root, recovery_check=authorize):
            pass
        return {'status': 'recovered', 'aws': 'not-contacted', 'scope': list(identity)}


@input_scope
def recover_display(root, environment, service, selector=None):
    root = root.resolve()
    target = target_for(root, environment, service, selector)
    identity = environment, target['directory'], service
    with restrict(identity), read_consumers({identity}), input_context(), publication_lock(root) as journal:
        require_import_changes(root, generation=True)
        proof = read_proof(root)
        if proof['model'] not in {'reflected', 'unchanged'}:
            raise ValueError('IMPORT display recovery requires an already saved Model')
        inputs = GenerationInputs(root)
        try:
            with contract_reads(root), recording_inputs(inputs):
                snapshot = load_model(model_path(root, identity), inputs)
                document = root / 'docs/designs' / environment / identity[1] / (service + '.md')
                managed = {root / relative for relative in proof['ownedArtifacts']}
                managed |= owned_artifacts(document, snapshot.values)
                output, originals = view_plan(document, snapshot.values, root, managed)
            record_outputs(root, identity, set(), set(output))
            inputs.verify()
            if any((file.read_bytes() if file.is_file() else None) != raw for file, raw in originals.items()):
                raise ValueError('IMPORT display inputs changed before publication')
            _publish_transaction(root, {p: text for p, text in output.items() if text is not None},
                {p for p, text in output.items() if text is None}, journal,
                receipt=(proof['task'], proof_path(root).read_bytes()),
                finish=lambda: finish_import(root, markdown='generated' if output else 'unchanged'))
            return {'status': 'complete' if proof['complete'] else 'incomplete', 'markdown': 'generated' if output else 'unchanged'}
        finally:
            inputs.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('acquire', 'review', 'publish', 'resume', 'recover-display', 'recover-transaction'))
    parser.add_argument('--repository-root', type=Path, default=Path.cwd())
    parser.add_argument('--environment', required=True)
    parser.add_argument('--target')
    parser.add_argument('--service', required=True)
    parser.add_argument('--task-file')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-profile', action='store_true')
    parser.add_argument('--resource-type', action='append')
    args = parser.parse_args(argv)
    if args.action != 'acquire' and (args.no_profile or args.resource_type):
        parser.error('--no-profile and --resource-type apply only to acquisition')
    functions = {'acquire': acquire, 'review': review_acquisition, 'publish': publish_acquisition,
                 'resume': resume_acquisition, 'recover-display': recover_display, 'recover-transaction': recover_transaction}
    try:
        with selected_task(args.repository_root, args.task_file):
            kwargs = {'selector': args.target}
            if args.action == 'acquire':
                kwargs.update(dry_run=args.dry_run, no_profile=args.no_profile, resource_types=args.resource_type)
            elif args.action != 'recover-display':
                if args.evidence is None:
                    raise ValueError('IMPORT action requires its original --evidence')
                kwargs.update(evidence=args.evidence, dry_run=args.dry_run)
            result = functions[args.action](args.repository_root, args.environment, args.service, **kwargs)
        print(json_text(result))
        return 3 if result.get('status') == 'display-failed' else 2 if result.get('status') == 'incomplete' else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json_text({'status': 'failed', 'reason': str(error)}))
        return 1
