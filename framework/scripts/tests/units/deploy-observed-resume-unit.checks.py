"""Pure classification/authorization checks for durable observed publication plans."""

import sys
import json
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cloudformation_inputs import Blocked
from deploy import observed, handoff
from deploy import observed_resume as M
from deploy import session as controller
from task_contract_core import selected_task

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.mark.parametrize('current,mixed,expected', [
    ({'a': 'old', 'b': 'old'}, False, 'PREPARED'),
    ({'a': 'new', 'b': 'new'}, False, 'MODEL_PUBLISHED'),
    ({'a': 'new', 'b': 'old'}, True, 'PARTIAL'),
    ({'a': 'new', 'b': 'old'}, False, None),
    ({'a': 'third', 'b': 'old'}, True, None),
    ({'a': 'new'}, True, None),
    ({'a': 'new', 'b': 'new', 'dependency': None}, True, None),
    ({'a': 'new', 'b': None}, True, None)])
def check_classification(current, mixed, expected):
    before, after = {'a': 'old', 'b': 'old'}, {'a': 'new', 'b': 'new'}
    if expected:
        assert M.classify(current, before, after, mixed=mixed) == expected
    else:
        with pytest.raises(Blocked, match='cannot explain'):
            M.classify(current, before, after, mixed=mixed)
    assert M.classify(before, before, before) == 'MODEL_PUBLISHED'  # An exact no-op needs only generation.


@pytest.mark.parametrize('field', ['StackId', 'ChangeSetId', 'changeDigest', 'clientToken', 'status'])
def check_execution_identity(field):
    state = {'status': 'SUCCESS', 'stackId': 'stack', 'changeSetId': 'change', 'changeDigest': 'digest', 'clientToken': 'token',
             'executionEvidence': {'StackId': 'stack', 'ChangeSetId': 'change', 'changeDigest': 'digest', 'clientToken': 'token'}}
    saved = M.evidence({'A': state}, ['A'])
    if field == 'status':
        state[field] = 'RUNNING'
    else:
        state['executionEvidence'][field] = 'other'
    with pytest.raises(Blocked):
        M.evidence({'A': state}, ['A'])
    assert saved['A']['executionEvidence']['StackId'] == 'stack'


@pytest.mark.parametrize('problem', ['none', 'foreign', 'original', 'third', 'missing', 'incomplete', 'receipt'])
def check_journal_ownership(problem):
    plan = {'beforeManifest': {'a': 'old', 'b': 'old'}, 'afterManifest': {'a': 'new', 'b': 'new'},
            'originals': {'a': 'raw-a', 'b': 'raw-b'}}
    record, current = {'originals': dict(plan['originals'])}, {'a': 'new', 'b': 'old'}
    if problem == 'foreign':
        record['originals']['other'] = 'raw'
    if problem == 'original':
        record['originals']['a'] = 'foreign'
    if problem == 'third':
        current['a'] = 'external'
    if problem == 'missing':
        current.pop('b')
    if problem == 'incomplete':
        record['originals'].pop('a')
    if problem == 'receipt':
        record['importReceipt'] = {}
    if problem == 'none':
        M.verify_journal(plan, record, current)
    else:
        with pytest.raises(Blocked):
            M.verify_journal(plan, record, current)


@pytest.fixture
def proposal(tmp_path):
    source = tmp_path / 'model/dev/team/service.properties'
    source.parent.mkdir(parents=True)
    old = '# model-format: 2\ndesired.row.001-001.value=`desired`\nobserved.row.001-001.value=`old`\n'
    new = old.replace('value=`old`', 'value=`new`')
    source.write_text(old)
    task = tmp_path / 'tasks/deploy.md'
    task.parent.mkdir()
    relative = source.relative_to(tmp_path).as_posix()
    listed = '- `tasks/deploy.md`\n- `' + relative + '`\n'
    task.write_text('## Task contract\n- Task status: `running`\n## Modified files\n' + listed + '## Allowed paths\n' + listed)
    before, after = M.manifest({relative: old.encode()}), M.manifest({relative: new.encode()})
    session = {'modelInputManifest': before, 'states': {'A': {'status': 'SUCCESS'}}, 'pendingObserved': {
        'identity': {'target': 'pinned'}, 'evidence': M.evidence({'A': {'status': 'SUCCESS'}}, ['A']),
        'beforeManifest': before, 'afterManifest': after, 'outputs': {relative: new},
        'originals': {relative: base64.b64encode(old.encode()).decode()}, 'directories': ['model/dev/team'],
        'inventory': [relative], 'stage': 'PREPARED'}}
    with selected_task(tmp_path, 'tasks/deploy.md'):
        yield tmp_path, session, source, old, new


@pytest.mark.parametrize('problem', ['none', 'legacy', 'legacy-other', 'task', 'evidence', 'manifest', 'candidate', 'desired', 'bytes', 'file-set', 'allowed', 'stage', 'original-set', 'manifest-set'])
def check_plan_validation(proposal, problem):
    root, session, source, old, new = proposal
    plan = session['pendingObserved']
    relative = source.relative_to(root).as_posix()
    if problem in {'legacy', 'legacy-other'}:
        plan['identity']['managedTask'] = {'merged': 'changed-since-plan', 'other': 'old metadata'}
    if problem == 'legacy-other':
        plan['identity']['unexpected'] = True
    if problem == 'task':
        plan['identity'] = {'target': 'changed'}
    if problem == 'evidence':
        session['states']['A']['stackId'] = 'other'
    if problem == 'manifest':
        session['modelInputManifest'] = {}
    if problem == 'candidate':
        plan['outputs'][relative] = new.replace('`new`', '`other`')
    if problem == 'desired':
        plan['outputs'][relative] = new.replace('`desired`', '`other`')
    if problem == 'bytes':
        plan['outputs'][relative] = '# unrelated\n' + new
    if problem == 'file-set':
        source.with_name('extra.properties').write_text(old)
    if problem == 'allowed':
        (root / 'tasks/deploy.md').write_text('## Modified files\n## Allowed paths\n')
    if problem == 'stage':
        plan['stage'] = 'UNKNOWN'
    if problem == 'original-set':
        plan['originals']['project.json'] = base64.b64encode(b'foreign').decode()
    if problem == 'manifest-set':
        plan['afterManifest']['extra'] = None
    with patch.object(M, '_identity', return_value={'target': 'pinned'}):
        if problem in {'none', 'legacy'}:
            assert M.validate_plan(root, session, {}, 'dev', 'team') is plan
        else:
            with pytest.raises((ValueError, Blocked)):
                M.validate_plan(root, session, {}, 'dev', 'team')


def check_signed_legacy_plan(proposal):
    root, session, _, _, _ = proposal
    session.update(repository=str(root), taskFile='tasks/deploy.md')
    plan = session['pendingObserved']
    plan['identity']['managedTask'] = {'merged': 'legacy state', 'tip': 'old'}
    path = root / 'session.json'
    handoff.bind(root, path, session)
    handoff.save(path, session)
    restored = json.loads(path.read_text(encoding='utf-8'))
    handoff.restore(root, path, restored)
    with patch.object(M, '_identity', return_value={'target': 'pinned'}):
        assert M.validate_plan(root, restored, {}, 'dev', 'team') == plan
    # Even the ignored metadata cannot be tampered with outside the signed Session.
    restored['pendingObserved']['identity']['managedTask'] = {}
    with pytest.raises(Blocked, match='ledger'):
        handoff.restore(root, path, restored)


def check_intent_save_failure(proposal):
    root, session, source, old, new = proposal
    session.pop('pendingObserved')
    backend = SimpleNamespace(root=root, session=session, environment='dev', directory='team', target={},
                              save=lambda: (_ for _ in ()).throw(OSError('intent write failed')))
    with patch.object(M, '_identity', return_value={}), patch.object(M, 'authority_snapshot', return_value={source: old.encode()}), \
         patch.object(M, 'generated_plan', return_value={}):
        with pytest.raises(OSError, match='intent write failed'):
            M.prepare(backend, [{'name': 'A'}], {source: new}, ['service'], set())
    assert source.read_text() == old


def check_direct_writer_keeps_noop_source_snapshot(tmp_path):
    source = tmp_path / 'model/dev/team/changed.properties'
    noop = source.with_name('unchanged.properties')
    backend = SimpleNamespace(root=tmp_path, environment='dev', directory='team')
    states = {'A': {'status': 'SUCCESS'}}
    sync = SimpleNamespace(sync=lambda *args, **kwargs: 0)
    with patch.object(observed, 'collect_successful', return_value=({source: 'candidate'}, ['changed', 'unchanged'], sync)), \
         patch.object(observed, 'input_snapshot', side_effect=lambda path: {path: b'original'}) as snapshot, \
         patch.object(observed, 'publish_observed') as publish:
        observed.sync_successful(backend, [{'name': 'A'}], states)
    assert {call.args[0] for call in snapshot.call_args_list} == {source, noop}
    assert publish.call_args.args[2] == {source: b'original', noop: b'original'}
    assert states['A']['observedSynced']


def check_exact_task_bytes_bound(proposal):
    root, session, _, _, _ = proposal
    task = root / 'tasks/deploy.md'
    task.write_text(task.read_text().replace('## Task contract', '## Task contract\n- Authorized delete/replacement: `none`'))
    session.update(repository=str(root), taskFile='tasks/deploy.md', taskDigest=M.task_digest(task.read_text()),
                   inputDigest='inputs', executionDigest='execution', infraManifest={})
    original = M._identity(root, session, {}, 'dev', 'team')
    task.write_text(task.read_text().replace('Authorized delete/replacement: `none`', 'Authorized delete/replacement: `all`'))
    changed = M._identity(root, session, {}, 'dev', 'team')
    assert original['taskDigest'] == changed['taskDigest']
    assert original['taskBytes'] != changed['taskBytes']


def _callback_check_pending_plan_drained_peer_barrier_sync(calls, session, /, backend, units, states):
    pending = session.get('pendingObserved')
    names = list(pending['evidence']) if pending else [u['name'] for u in units]
    calls.append(names)
    for name in names:
        states[name]['observedSynced'] = True


def _callback_check_pending_plan_drained_peer_barrier_save(saves, session, /):
    saves.append([name for name, state in session['states'].items() if state.get('observedSynced')])


def check_pending_plan_drained_peer_barrier():
    units = [{'name': name, 'deployOrder': 10} for name in ('A', 'B')]
    session = {'states': {name: {'status': 'SUCCESS'} for name in ('A', 'B')},
               'pendingObserved': {'evidence': {'A': {}}}, 'metrics': {'observedSyncSeconds': 0}}
    calls, saves = [], []
    sync = _bind_framework_callback(_callback_check_pending_plan_drained_peer_barrier_sync, calls, session)
    save = _bind_framework_callback(_callback_check_pending_plan_drained_peer_barrier_save, saves, session)
    with patch.object(controller, 'sync_successful', sync), patch.object(controller, 'run_group', return_value='COMPLETE'):
        assert controller.run_session(units, 2, session, SimpleNamespace(), save) == 'COMPLETE'
    assert calls == [['A'], ['B']] and saves == [['A'], ['A', 'B']]


def check_original_failure_retained():
    units = [{'name': 'A', 'deployOrder': 10}]
    session = {'states': {'A': {'status': 'SUCCESS'}}, 'metrics': {'observedSyncSeconds': 0},
               'observedError': 'original design I/O failure',
               'observedFailures': [{'stage': 'MODEL_PUBLISHED', 'cause': 'original design I/O failure'}]}
    with patch.object(controller, 'sync_successful', side_effect=Blocked('later guard refusal')):
        assert controller.run_session(units, 1, session, SimpleNamespace(), lambda: None) == 'STOPPED'
    assert session['observedError'] == 'original design I/O failure'
    assert session['observedRecoveryError'] == 'later guard refusal'
    assert session['observedFailures'][0]['stage'] == 'MODEL_PUBLISHED'


@pytest.mark.parametrize('state', ['before', 'after', 'append', 'value', 'empty', 'missing', 'add', 'partial', 'no-proof', 'candidate'])
def check_generated_classification(tmp_path, state):
    view = 'docs/designs/dev/team/service.md'
    artifact = 'docs/designs/dev/team/service/policy.json'
    paths = [view, artifact]
    before, after = {view: b'old\n', artifact: None}, {view: 'new\n', artifact: '{}\n'}
    generated = {'groups': {view: paths}, 'originals': {p: None if raw is None else base64.b64encode(raw).decode()
                 for p, raw in before.items()}, 'outputs': after, 'stage': 'CANDIDATE'}
    plan = {'generated': generated}
    for p, raw in (before if state == 'before' else {p: s.encode() for p, s in after.items()}).items():
        file = tmp_path / p
        file.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            file.write_bytes(raw)
    task = tmp_path / 'tasks/deploy.md'
    task.parent.mkdir()
    listed = ''.join('- `' + p + '`\n' for p in ['tasks/deploy.md', *paths])
    task.write_text('## Task contract\n- Task status: `running`\n## Modified files\n' + listed + '## Allowed paths\n' + listed)
    if state == 'append':
        (tmp_path / view).write_bytes(b'new\nexternal\n')
    if state == 'value':
        (tmp_path / artifact).write_bytes(b'{"external":true}')
    if state == 'empty':
        (tmp_path / artifact).write_bytes(b'')
    if state == 'missing':
        (tmp_path / view).unlink()
    if state == 'add':
        (tmp_path / artifact).with_name('extra.json').write_bytes(b'{}')
    if state == 'partial':
        (tmp_path / view).write_bytes(before[view])
    if state == 'no-proof':
        plan.clear()
    if state == 'candidate':
        generated['outputs'][artifact] = '{"other":true}'
    retained = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with selected_task(tmp_path, 'tasks/deploy.md'):
        if state in {'before', 'after'}:
            current = M.check_generated(tmp_path, plan)
            assert current == M.generated_manifests(tmp_path, plan)[state == 'after']
        else:
            with pytest.raises(Blocked):
                M.check_generated(tmp_path, plan)
    assert {p: p.read_bytes() for p in retained} == retained


@pytest.mark.parametrize('problem', ['none', 'third', 'foreign', 'incomplete', 'empty-original', 'receipt'])
def check_generated_journal(tmp_path, problem):
    view, artifact = 'docs/designs/dev/team/service.md', 'docs/designs/dev/team/service/policy.json'
    files = {view: b'old', artifact: None}
    generated = {'groups': {view: list(files)}, 'originals': {p: None if raw is None else base64.b64encode(raw).decode()
                 for p, raw in files.items()}, 'outputs': {view: 'new', artifact: '{}'}, 'stage': 'CANDIDATE'}
    plan = {'generated': generated}
    (tmp_path / view).parent.mkdir(parents=True)
    (tmp_path / view).write_bytes(b'new')
    record = {'originals': dict(generated['originals'])}
    if problem == 'third':
        (tmp_path / view).write_bytes(b'external')
    if problem == 'foreign':
        record['originals']['other'] = None
    if problem == 'incomplete':
        record['originals'].pop(view)
    if problem == 'empty-original':
        record['originals'][artifact] = ''
    if problem == 'receipt':
        record['importReceipt'] = {}
    task = tmp_path / 'tasks/deploy.md'
    task.parent.mkdir()
    listed = ''.join('- `' + p + '`\n' for p in ['tasks/deploy.md', *files])
    task.write_text('## Task contract\n- Task status: `running`\n## Modified files\n' + listed + '## Allowed paths\n' + listed)
    with selected_task(tmp_path, 'tasks/deploy.md'):
        if problem == 'none':
            M.verify_generated_journal(tmp_path, plan, record)
        else:
            with pytest.raises(Blocked):
                M.verify_generated_journal(tmp_path, plan, record)


def check_generated_plan_snapshot(proposal):
    root, _, _, _, _ = proposal
    view = root / 'docs/designs/dev/team/service.md'
    view.parent.mkdir(parents=True)
    view.write_bytes(b'')
    artifact = view.with_suffix('') / 'policy.json'
    artifact.parent.mkdir()
    extra = artifact.with_name('extra.json')
    extra.write_bytes(b'{}\n')
    plan = M.generated_plan(root, {view, artifact})
    assert plan['outputs'] is None and plan['stage'] == 'PREPARED'
    assert plan['originals'] == {view.relative_to(root).as_posix(): '', artifact.relative_to(root).as_posix(): None,
                                extra.relative_to(root).as_posix(): base64.b64encode(b'{}\n').decode()}
    assert plan['groups'] == {view.relative_to(root).as_posix(): sorted(plan['originals'])}


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
