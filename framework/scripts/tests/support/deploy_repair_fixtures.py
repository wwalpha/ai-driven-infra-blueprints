"""Controller repair diagnosis, signed receipts and resumption; delivery is an adapter."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from deploy import handoff, inputs
from deploy.contracts import accepted_changes, sha, validation_snapshot
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    git,
    invoke,
    recover_owned_lock,
)
from task_contract_core import selected_task
from utils.sealed_evidence import write_sealed


def external_round_trip(tmp_path, monkeypatch, boundary, *, seed, deliver, validate_parent=None,
                        before_resume=None, controller_helper='deploy_controller_fixtures.py'):
    assert boundary in {'normal', 'merge', 'cleanup'}
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    parent = seed(tmp_path / 'project', session, 'repair')
    monkeypatch.chdir(parent)
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/deploy.md')
    aws_state(aws, repair=True)
    original = {p: p.read_bytes() for p in (parent / 'infra').rglob('*') if p.is_file()}
    assert invoke(parent, session, aws) == 2
    assert all(p.read_bytes() == raw for p, raw in original.items())
    saved = json.loads(session.read_text())
    handoff.restore(parent, session, saved)
    first, second = 'cfn-stack-app-dev-first', 'cfn-stack-app-dev-second'
    successful = saved['states'][first]
    failed_evidence = saved['states'][second]['executionEvidence']
    assert saved['states'][second]['status'] == 'FAILED' and successful['observedSynced']
    observation = next(o for o in saved['failureObservations'] if o['observationId'] in saved['workflow']['latestObservations'])
    relative = 'infra/cloudformation/templates/second.yaml'
    model = f'model/dev/{ACCOUNT}/ec2.properties'
    diagnosis = {'revision': saved['inputRevision'], 'problems': [{
        'observationId': observation['observationId'], 'eventIndices': [0], 'resourcePath': 'Vpc',
        'resourceType': 'AWS::EC2::VPC', 'operation': 'CREATE', 'property': 'CidrBlock',
        'constraint': 'approved-CidrBlock', 'cause': 'IAC_PROPERTY',
        'relation': 'NEW', 'relatedProblemIds': [],
        'reason': 'The CidrBlock input disagrees with its approved Model row and the failed Vpc operation.',
        'evidenceRefs': [{'observationId': observation['observationId'], 'revision': saved['inputRevision'], 'eventIndices': [0]}],
        'inputRefs': [{'path': relative, 'sha256': saved['infraManifest'][relative], 'pointer': '/Resources/Vpc/Properties/CidrBlock'}],
        'modelRefs': [{'path': model, 'sha256': saved['modelInputManifest'][model], 'key': 'desired.row.001-002.value'}]}]}
    assert handoff.diagnose(parent, saved, diagnosis) == 'REPAIR_ALLOWED'
    problems = saved['workflow']['currentProblemIds']
    handoff.save(session, saved)
    expectation = [{'stack': second, 'resourcePath': 'Vpc', 'operation': 'CREATE', 'status': 'CREATE_COMPLETE'}]
    pending = handoff.issue_request(parent, session, saved, problems, [relative], expectation)
    assert handoff.issue_request(parent, session, saved, problems, [relative], expectation) == pending
    assert saved['workflow']['reserved'] == 1
    handoff.save(session, saved)
    request, result_path = deliver(parent, session, pending, relative, model, boundary, tmp_path)
    context = {'parent': parent, 'session': session, 'aws': aws, 'relative': relative, 'model': model,
               'result': result_path, 'request': request, 'tmp_path': tmp_path}
    if before_resume:
        before_resume(context)
    if boundary == 'cleanup':
        state = json.loads(aws.read_text())
        state['knobs']['crash_cleanup'] = True
        aws.write_text(json.dumps(state))
        helper = Path(__file__).with_name(controller_helper)
        command = [sys.executable, '-B', str(helper), str(parent), str(session), str(aws), '--resume', '--repair-result', str(result_path)]
        stopped = subprocess.run(command, cwd=parent, env=child_environment(), capture_output=True, text=True, timeout=90)
        assert stopped.returncode == 74, stopped.stdout + stopped.stderr
        intent = json.loads(session.read_text())
        assert intent['inputRevision'] == 1 and intent['workflow']['reserved'] == 1
        assert intent['states'][first] == successful
        failed = intent['states'][second]
        assert failed['cleanupStatus'] == 'DELETE_INTENT' and failed['recoveryPending']
        assert failed['cleanupStackId'] == failed_evidence['StackId']
        assert failed['executionEvidence'] == failed_evidence
        assert failed['clientToken'] == failed_evidence['clientToken']
        assert intent['workflow']['attempts'][pending['attemptId']]['acceptedRevision'] == 1
        recover_owned_lock(parent, stopped)
        resumed = subprocess.run(command, cwd=parent, env=child_environment(), capture_output=True, text=True, timeout=90)
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    else:
        assert invoke(parent, session, aws, ['--resume', '--repair-result', str(result_path)]) == 0
    after = json.loads(session.read_text())
    assert after['inputRevision'] == 1 and after['workflow']['reserved'] == 1
    if boundary == 'cleanup':
        assert {key: after[key] for key in ('infraManifest', 'unitDigests', 'effectiveDigests')} == {
            key: intent[key] for key in ('infraManifest', 'unitDigests', 'effectiveDigests')}
        assert after['states'][second]['cleanupStackId'] == failed_evidence['StackId']
        assert after['states'][second]['cleanupStatus'] == 'DELETE_COMPLETE'
    assert after['states'][first] == successful
    assert all(state['status'] == 'SUCCESS' and state['observedSynced'] for state in after['states'].values())
    assert failed_evidence in [entry.get('executionEvidence') for entry in after['states'][second]['failureArchive']]
    assert accepted_changes(parent, (parent / 'tasks/deploy.md').read_text(), {relative}) == {relative}
    assert after['workflow']['problems'][problems[0]].get('resolvedByExecution')
    calls = json.loads(aws.read_text())['calls']
    assert sum(op == 'delete_stack' and args['StackName'] == failed_evidence['StackId'] for _, op, args in calls) == 1
    assert sum(op == 'execute_change_set' and args['StackName'] == successful['executionEvidence']['StackId'] for _, op, args in calls) == 1
    if boundary == 'normal':
        validate_parent(parent)
    return context


def assert_receipt_rejections(context):
    parent, session, aws, result = (context[key] for key in ('parent', 'session', 'aws', 'result'))
    forged = context['tmp_path'] / 'unsigned-result.json'
    forged.write_text(json.dumps({'result': 'PASS', 'requestId': context['request']['requestId']}))
    assert invoke(parent, session, aws, ['--resume', '--repair-result', str(forged)]) == 2
    model_path = parent / context['model']
    raw = model_path.read_bytes()
    model_path.write_bytes(raw + b'\n# dependency changed after static validation\n')
    assert invoke(parent, session, aws, ['--resume', '--repair-result', str(result)]) == 2
    model_path.write_bytes(raw)


def assert_same_result_reapplication(context):
    parent, session, aws, result = (context[key] for key in ('parent', 'session', 'aws', 'result'))
    before = json.loads(aws.read_text())['calls']
    saved = json.loads(session.read_text())
    assert invoke(parent, session, aws, ['--resume', '--repair-result', str(result)]) == 0
    after = json.loads(session.read_text())
    assert after['inputRevision'] == saved['inputRevision'] and after['states'] == saved['states']
    assert after['workflow']['reserved'] == saved['workflow']['reserved']
    assert after['workflow']['accepted'] == saved['workflow']['accepted']
    assert not [call for call in json.loads(aws.read_text())['calls'][len(before):]
                if call[1] in {'create_change_set', 'execute_change_set', 'delete_stack'}]


def assert_worktree_receipt_extras(context):
    parent, session, aws, result = (context[key] for key in ('parent', 'session', 'aws', 'result'))
    copied = context['tmp_path'] / 'same-result-copy.json'
    copied.write_bytes(result.read_bytes())
    before = json.loads(aws.read_text())['calls']
    assert invoke(parent, session, aws, ['--resume', '--repair-result', str(copied)]) == 0
    assert_same_result_reapplication(context)
    assert not [call for call in json.loads(aws.read_text())['calls'][len(before):] if call[1] == 'execute_change_set']
    relative = context['relative']
    (parent / relative).write_text((parent / relative).read_text() + '# unrecorded parent edit\n')
    with pytest.raises(ValueError, match='unrecorded'):
        accepted_changes(parent, (parent / 'tasks/deploy.md').read_text(), {relative})


def ordinary_delivery(parent, session_path, pending, relative, model, boundary, tmp_path):
    """Supply a trusted external validation result using real ordinary Git bytes.

    The Worktree delivery adapter is tested separately; no lifecycle is simulated.
    """
    session = json.loads(session_path.read_text())
    handoff.restore(parent, session_path, session)
    git(parent, 'add', '.')
    if git(parent, 'status', '--porcelain').strip():
        git(parent, 'commit', '-qm', 'Observed publication checkpoint')
    request = session['pendingRequest']
    request['parentTip'] = git(parent, 'rev-parse', 'HEAD').strip()
    directory = session_path.with_name(session_path.name + '.files') / ('repair-' + request['requestId'])
    directory.mkdir(parents=True, exist_ok=True)
    request['requestPath'] = str(directory / 'request.json')
    handoff.save(session_path, session)
    write_sealed(parent, Path(request['requestPath']), request)
    path = parent / relative
    original = sha(path)
    path.write_text(path.read_text().replace('10.2.0.0/16', '10.0.0.0/16'))
    git(parent, 'add', relative)
    git(parent, 'commit', '-qm', 'External approved repair')
    commit = git(parent, 'rev-parse', 'HEAD').strip()
    with selected_task(parent, session['taskFile']):
        _, units = inputs.load_units(parent, session['environment'], session['directory'], list(session['states']))
    effective = handoff.effective(parent, units,
        lambda unit: inputs.paths(parent, session['environment'], session['directory'], session['target'], unit),
        lambda selected: inputs.deployment_input_paths(parent, session['environment'], session['directory'], session['target'], selected))
    result = {**request, 'result': 'VALIDATED_CANDIDATE', 'commit': commit,
        'changes': {relative: {'before': original, 'after': sha(path),
            'beforeBlob': git(parent, 'rev-parse', request['parentTip'] + ':' + relative).strip(),
            'afterBlob': git(parent, 'rev-parse', commit + ':' + relative).strip()}},
        'validation': {'snapshot': validation_snapshot(parent), 'result': 'PASS'},
        'effectiveInputs': {'before': session['effectiveDigests'], 'after': effective}}
    session['workflow']['attempts'][pending['attemptId']]['stage'] = 'STATIC_PASSED'
    handoff.save(session_path, session)
    destination = directory / 'result.json'
    write_sealed(parent, destination, result)
    return request, destination
