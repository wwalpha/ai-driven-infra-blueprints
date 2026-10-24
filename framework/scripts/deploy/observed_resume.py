"""Exact, session-owned observation plans around the existing Model transaction."""

import base64
import copy
import hashlib
from functools import partial as _bind_framework_callback

import generation_inputs as _imports_generation_inputs
import model.adapters.observed as _imports_model_adapters_observed
import sync_runtime as _imports_sync_runtime
from model.observed import verify_observed_outputs
from model.sources import authority_snapshot, publication_lock, safe
from task_contract_core import (
    matches,
    paths_in,
    task_read_scope,
    task_reads,
    task_snapshot,
    validate_contract,
)
from task_contract_core import task_digest as task_digest
from utils.cloudformation.inputs import Blocked

import deploy.observed as _imports_deploy_observed


def manifest(snapshot):
    return {str(path): None if raw is None else hashlib.sha256(raw).hexdigest()
            for path, raw in snapshot.items()}


def evidence(states, names):
    fields = ('status', 'stackStatus', 'stackId', 'changeSetId', 'changeDigest',
              'clientToken', 'approvedChangeDigest', 'executionEvidence')
    result = {}
    for name in names:
        state = states[name]
        if state['status'] != 'SUCCESS':
            raise Blocked('observed plan requires AWS SUCCESS: ' + name)
        execution = state.get('executionEvidence')
        if execution and any(execution.get(key) != state.get(field) for key, field in (
                ('StackId', 'stackId'), ('ChangeSetId', 'changeSetId'),
                ('changeDigest', 'changeDigest'), ('clientToken', 'clientToken'))):
            raise Blocked('observed execution evidence changed: ' + name)
        result[name] = {key: copy.deepcopy(state.get(key)) for key in fields}
    return result


def inventory(root, directories):
    return sorted(path.relative_to(root).as_posix() for directory in directories
                  for path in (root / directory).rglob('*.properties'))


def classify(current, before, after, *, mixed=False):
    if current == after:
        return 'MODEL_PUBLISHED'
    if current == before:
        return 'PREPARED'
    if mixed and current.keys() == before.keys() == after.keys() and all(
            current[key] in (before[key], after[key]) for key in current):
        return 'PARTIAL'
    raise Blocked('observed plan cannot explain current bytes or dependency file set')


def generated_plan(root, views):
    """Pin observed_destinations before any Model save or fallible generation."""
    GenerationInputs = _imports_generation_inputs.GenerationInputs
    snapshot = GenerationInputs(root)
    try:
        files = set(views)
        for view in (p for p in views if p.suffix == '.md'):
            files.update(snapshot.select(view.with_suffix(''), '*.json', True, ('file', 'symlink')))
        originals = {}
        for path in files:
            safe(root, path)
            raw = snapshot.read(path)
            originals[path.relative_to(root).as_posix()] = None if raw is None else base64.b64encode(raw).decode('ascii')
        groups = {view.relative_to(root).as_posix(): sorted(p.relative_to(root).as_posix() for p in files
                  if p == view or p.is_relative_to(view.with_suffix('')))
                  for view in views if view.suffix == '.md'}
        snapshot.verify()
        return {'groups': groups, 'originals': originals, 'outputs': None, 'stage': 'PREPARED'}
    finally:
        snapshot.close()


def generated_manifests(root, plan):
    generated = plan.get('generated')
    if not isinstance(generated, dict):
        raise Blocked('observed plan has no generated-file evidence; safe resume cannot be proven')
    groups, originals, outputs = (generated[key] for key in ('groups', 'originals', 'outputs'))
    if (not isinstance(groups, dict) or not groups or not isinstance(originals, dict)
            or generated['stage'] not in {'PREPARED', 'CANDIDATE', 'PUBLISHED'}
            or set(originals) != {p for files in groups.values() for p in files}
            or outputs is not None and (not isinstance(outputs, dict) or outputs.keys() != originals.keys())):
        raise Blocked('invalid observed generated-file evidence')
    task = task_snapshot(root).text
    declared, allowed = paths_in(task, '## Modified files'), paths_in(task, '## Allowed paths')
    for view, files in groups.items():
        if (not view.startswith('docs/designs/') or not view.endswith('.md') or view not in files
                or len(files) != len(set(files))):
            raise Blocked('invalid observed generated-file group')
        for relative in files:
            path = root / relative
            safe(root, path)
            if (relative not in declared or not any(matches(relative, p) for p in allowed)
                    or relative != view and (path.suffix != '.json' or path.parent != (root / view).with_suffix(''))):
                raise Blocked('observed generated output outside Task authority')
    before = manifest({p: None if raw is None else base64.b64decode(raw, validate=True) for p, raw in originals.items()})
    after = before if outputs is None else manifest({p: text.encode('utf-8') for p, text in outputs.items()})
    return before, after


def check_generated(root, plan, *, mixed=False):
    before, after = generated_manifests(root, plan)
    current = {}
    for relative in before:
        path = root / relative
        safe(root, path)
        current[relative] = path.read_bytes() if path.is_file() else None
    generated = plan['generated']
    for view in generated['groups']:
        # Generation scans this exact artifact selection, including unexpected JSONs.
        for path in (root / view).with_suffix('').rglob('*.json'):
            if path.relative_to(root).as_posix() not in before:
                raise Blocked('observed generated file set changed: ' + str(path.relative_to(root)))
    current = manifest(current)
    classify(current, before, after, mixed=True)
    if not mixed:
        # Each service is one existing journal transaction; completed services may differ.
        for files in generated['groups'].values():
            classify({p: current[p] for p in files}, {p: before[p] for p in files}, {p: after[p] for p in files})
    return current


def verify_generated_journal(root, plan, record):
    before, after = generated_manifests(root, plan)
    generated = plan['generated']
    if ('importReceipt' in record or generated['outputs'] is None or not record['originals']
            or any(p not in generated['originals'] or raw != generated['originals'][p]
                   for p, raw in record['originals'].items())
            or not any(set(record['originals']) == {p for p in files if before[p] != after[p]}
                       for files in generated['groups'].values())):
        raise Blocked('publication journal is not owned by this observed generated plan')
    current = check_generated(root, plan, mixed=True)
    restored = {**current, **{p: before[p] for p in record['originals']}}
    for files in generated['groups'].values():
        classify({p: restored[p] for p in files}, {p: before[p] for p in files}, {p: after[p] for p in files})


@task_read_scope
def _identity(root, session, target, environment, directory):
    snapshot = task_snapshot(root)
    task, text = snapshot.path, snapshot.text
    validate_contract(root, task.relative_to(root).as_posix(), text)
    if (session['repository'] != str(root) or session['taskFile'] != task.relative_to(root).as_posix()
            or session['taskDigest'] != task_digest(text)):
        raise Blocked('observed plan Task/repository changed')
    return {'repository': str(root), 'taskFile': session['taskFile'], 'taskDigest': task_digest(text),
            'taskBytes': snapshot.raw_digest,
            'environment': environment, 'directory': directory, 'target': target,
            **{key: session[key] for key in ('inputDigest', 'infraManifest')}}


def prepare(backend, units, outputs, services, views):
    root, session = backend.root, backend.session
    with publication_lock(root, read_only=True):
        before = authority_snapshot(root, backend.environment, backend.directory)
        verify_observed_outputs(before, outputs)
        relative = {path.relative_to(root).as_posix(): raw for path, raw in before.items()}
        before_manifest = manifest(relative)
        if before_manifest != session['modelInputManifest']:
            raise Blocked('Model inputs changed before observed plan')
        after = {**relative, **{path.relative_to(root).as_posix(): text.encode('utf-8') for path, text in outputs.items()}}
        directories = {f'model/{backend.environment}/{backend.directory}'}
        directories.update('/'.join(path.split('/')[:3]) for path in relative if path.startswith('model/'))
        generated = generated_plan(root, views)
        if manifest({p.relative_to(root).as_posix(): raw for p, raw in authority_snapshot(
                root, backend.environment, backend.directory).items()}) != before_manifest:
            raise Blocked('Model inputs changed during observed generation planning')
        session['pendingObserved'] = {
            'identity': _identity(root, session, backend.target, backend.environment, backend.directory),
            'evidence': evidence(session['states'], [unit['name'] for unit in units]),
            'beforeManifest': before_manifest, 'afterManifest': manifest(after),
            'originals': {path.relative_to(root).as_posix(): base64.b64encode(before[path]).decode('ascii') for path in outputs},
            'outputs': {path.relative_to(root).as_posix(): text for path, text in outputs.items()},
            'directories': sorted(directories), 'inventory': inventory(root, directories),
            'services': services, 'stage': 'PREPARED', 'generated': generated}
        backend.save()  # A failed intent save must never reach Model publication.


@task_read_scope
def validate_plan(root, session, target, environment, directory):
    plan = session['pendingObserved']
    if not isinstance(plan, dict) or any(not isinstance(plan.get(key), dict) for key in (
            'identity', 'evidence', 'beforeManifest', 'afterManifest', 'originals', 'outputs')):
        raise Blocked('invalid observed plan records')
    if (plan['originals'].keys() != plan['outputs'].keys()
            or plan['beforeManifest'].keys() != plan['afterManifest'].keys()):
        raise Blocked('observed plan file sets differ')
    if plan['identity'] != _identity(root, session, target, environment, directory):
        raise Blocked('observed plan Task/target/session identity changed')
    if plan['evidence'] != evidence(session['states'], plan['evidence']):
        raise Blocked('observed plan execution evidence changed')
    if any(state['executionEvidence'] and state['executionEvidence'].get('inputDigest') != session['unitDigests'][name]
           for name, state in plan['evidence'].items()):
        raise Blocked('observed execution evidence does not match unit inputs')
    if session['modelInputManifest'] not in (plan['beforeManifest'], plan['afterManifest']):
        raise Blocked('observed plan/session manifest mismatch')
    if plan['stage'] not in {'PREPARED', 'MODEL_PUBLISHED'}:
        raise Blocked('unknown observed plan stage')
    before = {}
    outputs = {}
    declared = paths_in(task_snapshot(root).text, '## Modified files')
    allowed = paths_in(task_snapshot(root).text, '## Allowed paths')
    for relative, text in plan['outputs'].items():
        path = root / relative
        safe(root, path)
        if not relative.startswith('model/') or relative not in declared or not any(matches(relative, p) for p in allowed):
            raise Blocked('observed plan output outside Task authority')
        before[path] = base64.b64decode(plan['originals'][relative], validate=True)
        outputs[path] = text
    verify_observed_outputs(before, outputs)
    original_hashes = manifest({p.relative_to(root).as_posix(): raw for p, raw in before.items()})
    if (any(plan['beforeManifest'].get(p) != digest for p, digest in original_hashes.items())
            or {**plan['beforeManifest'], **manifest({p: t.encode('utf-8') for p, t in plan['outputs'].items()})} != plan['afterManifest']):
        raise Blocked('observed plan candidate/manifest mismatch')
    for relative in plan['beforeManifest']:
        safe(root, root / relative)
    directories = {f'model/{environment}/{directory}'} | {
        '/'.join(path.split('/')[:3]) for path in plan['beforeManifest'] if path.startswith('model/')}
    if plan['directories'] != sorted(directories):
        raise Blocked('observed discovery scope changed')
    if inventory(root, plan['directories']) != plan['inventory']:
        raise Blocked('observed Model file set changed')
    return plan


def verify_journal(plan, record, current):
    if ('importReceipt' in record or not record['originals'] or
            any(path not in plan['originals'] or raw != plan['originals'][path]
                for path, raw in record['originals'].items())):
        raise Blocked('publication journal is not owned by this observed plan')
    classify(current, plan['beforeManifest'], plan['afterManifest'], mixed=True)
    restored = {**current, **{path: plan['beforeManifest'][path] for path in record['originals']}}
    if restored != plan['beforeManifest']:
        raise Blocked('journal cannot restore the complete observed input state')


# Never let an unrelated transaction or third-party bytes be rolled back.
def _callback_reconcile_recovery(directory, environment, root, session, target, /, record):
    with task_reads(root, live=True):
        # Never let an unrelated transaction or third-party bytes be rolled back.
        plan = validate_plan(root, session, target, environment, directory)
        current = {relative: (root / relative).read_bytes() if (root / relative).is_file() else None
                   for relative in plan['beforeManifest']}
        if record['originals'] and all(p.startswith('docs/designs/') for p in record['originals']):
            classify(manifest(current), plan['beforeManifest'], plan['afterManifest'])
            verify_generated_journal(root, plan, record)
        else:
            check_generated(root, plan)
            verify_journal(plan, record, manifest(current))


@task_read_scope
def reconcile(root, session, target, environment, directory):
    """Validate recovery before any read-only Model load can encounter a journal."""
    recovery = _bind_framework_callback(_callback_reconcile_recovery, directory, environment, root, session, target)

    with publication_lock(root, recovery_check=recovery):
        plan = validate_plan(root, session, target, environment, directory)
        current = {path.relative_to(root).as_posix(): raw
                   for path, raw in authority_snapshot(root, environment, directory).items()}
        stage = classify(manifest(current), plan['beforeManifest'], plan['afterManifest'])
        check_generated(root, plan)
        plan['stage'] = stage
        session['modelInputManifest'] = plan['beforeManifest'] if stage == 'PREPARED' else plan['afterManifest']
    return stage


def finish(backend, units):

    sync_runtime = _imports_sync_runtime
    publish_observed = _imports_model_adapters_observed.publish_observed

    collect_successful = _imports_deploy_observed.collect_successful
    root, session = backend.root, backend.session
    plan = session['pendingObserved']
    stage = reconcile(root, session, backend.target, backend.environment, backend.directory)
    outputs = {root / path: text for path, text in plan['outputs'].items()}
    fresh, _, _ = collect_successful(backend, [unit for unit in units if unit['name'] in plan['evidence']], session['states'])
    previous = authority_snapshot(root, backend.environment, backend.directory)
    expected = {**previous, **{path: text.encode('utf-8') for path, text in fresh.items()}}
    if manifest({path.relative_to(root).as_posix(): raw for path, raw in expected.items()}) != plan['afterManifest']:
        raise Blocked('fresh AWS observations differ from the saved observed candidate')
    backend.guard()
    if stage == 'PREPARED':
        publish_observed(root, outputs, previous)
        # The journal may be gone while the on-disk session still says PREPARED.
        if reconcile(root, session, backend.target, backend.environment, backend.directory) != 'MODEL_PUBLISHED':
            raise Blocked('observed publication did not produce the exact candidate')
    backend.save()
    backend.guard()
    # Keep journal recovery owned across preparation and the existing atomic publication.
    with publication_lock(root, read_only=True):
        reconcile(root, session, backend.target, backend.environment, backend.directory)
        with sync_runtime.generation_context(root, True) as snapshot:
            generation = sync_runtime.prepare_generation(root, {
                (backend.environment, backend.directory, service) for service in plan['services']}, snapshot=snapshot)
            try:
                sync_runtime.validate_generation(generation)
                if generation.failures or generation.unavailable:
                    raise Blocked('observed generation failed: ' + str(generation.failures or generation.unavailable))
                candidate = {p.relative_to(root).as_posix(): text
                             for files in generation.expected_outputs.values() for p, text in files.items()}
                generated = plan['generated']
                if candidate.keys() != generated['originals'].keys():
                    raise Blocked('observed generated candidate file set changed')
                if generated['outputs'] is not None and candidate != generated['outputs']:
                    raise Blocked('observed generated candidate differs from saved session')
                check_generated(root, plan)
                generated['outputs'], generated['stage'] = candidate, 'CANDIDATE'
                backend.save()  # Persist exact candidates before the first generated-file write.
                backend.guard()
                reconcile(root, session, backend.target, backend.environment, backend.directory)
                sync_runtime.publish_generation(generation)  # Verifies the consumed input/output snapshot under lock.
                sync_runtime.report_generation(generation)
                if check_generated(root, plan) != manifest({p: text.encode('utf-8') for p, text in candidate.items()}):
                    raise Blocked('observed generated publication did not produce the saved candidate')
                generated['stage'] = 'PUBLISHED'
            finally:
                generation.close()
    if reconcile(root, session, backend.target, backend.environment, backend.directory) != 'MODEL_PUBLISHED':
        raise Blocked('Model changed during observed design generation')
    backend.guard()
    return outputs
