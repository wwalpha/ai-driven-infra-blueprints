"""Exact, session-owned observation plans around the existing Model transaction."""
import base64
import copy
import hashlib

from cloudformation_inputs import Blocked
from deploy.contracts import task_digest
from model.sources import authority_snapshot, publication_lock, safe
from model.observed import verify_observed_outputs
from task_contract import task_path, validate_contract, paths_in, matches


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
    raise Blocked('observed plan cannot explain current Model bytes or dependency file set')


def _identity(root, session, target, environment, directory):
    from import_guard import managed_task_state
    task = task_path(root)
    text = task.read_text(encoding='utf-8')
    validate_contract(root, task.relative_to(root).as_posix(), text)
    if (session['repository'] != str(root) or session['taskFile'] != task.relative_to(root).as_posix()
            or session['taskDigest'] != task_digest(text)):
        raise Blocked('observed plan Task/repository changed')
    return {'repository': str(root), 'taskFile': session['taskFile'], 'taskDigest': task_digest(text),
            'taskBytes': hashlib.sha256(task.read_bytes()).hexdigest(),
            'managedTask': managed_task_state(root, session['taskFile']),
            'environment': environment, 'directory': directory, 'target': target,
            **{key: session[key] for key in ('inputDigest', 'executionDigest', 'infraManifest')}}


def prepare(backend, units, outputs, services):
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
        session['pendingObserved'] = {
            'identity': _identity(root, session, backend.target, backend.environment, backend.directory),
            'evidence': evidence(session['states'], [unit['name'] for unit in units]),
            'beforeManifest': before_manifest, 'afterManifest': manifest(after),
            'originals': {path.relative_to(root).as_posix(): base64.b64encode(before[path]).decode('ascii') for path in outputs},
            'outputs': {path.relative_to(root).as_posix(): text for path, text in outputs.items()},
            'directories': sorted(directories), 'inventory': inventory(root, directories),
            'services': services, 'stage': 'PREPARED'}
        backend.save()  # A failed intent save must never reach Model publication.


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
    declared = paths_in(task_path(root).read_text(encoding='utf-8'), '## Modified files')
    allowed = paths_in(task_path(root).read_text(encoding='utf-8'), '## Allowed paths')
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


def reconcile(root, session, target, environment, directory):
    """Validate recovery before any read-only Model load can encounter a journal."""
    def recovery(record):
        # Never let an unrelated transaction or third-party bytes be rolled back.
        plan = validate_plan(root, session, target, environment, directory)
        current = {relative: (root / relative).read_bytes() if (root / relative).is_file() else None
                   for relative in plan['beforeManifest']}
        verify_journal(plan, record, manifest(current))

    with publication_lock(root, recovery_check=recovery):
        plan = validate_plan(root, session, target, environment, directory)
        current = {path.relative_to(root).as_posix(): raw
                   for path, raw in authority_snapshot(root, environment, directory).items()}
        stage = classify(manifest(current), plan['beforeManifest'], plan['afterManifest'])
        plan['stage'] = stage
        session['modelInputManifest'] = plan['beforeManifest'] if stage == 'PREPARED' else plan['afterManifest']
    return stage


def finish(backend, units):
    from model.adapters.observed import publish_observed
    from deploy.observed import collect_successful
    import sync_runtime
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
    if sync_runtime.sync(root, True, backend.environment, backend.directory, services=plan['services']):
        raise ValueError('observed model sync/validation failed; resume same session after resolving blocker')
    if reconcile(root, session, backend.target, backend.environment, backend.directory) != 'MODEL_PUBLISHED':
        raise Blocked('Model changed during observed design generation')
    backend.guard()
    return outputs
