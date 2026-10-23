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


def external_round_trip(tmp_path, monkeypatch, boundary, *, seed, deliver, validate_parent=None, controller_helper='deploy_controller_fixtures.py'):
    unexecuted = boundary in {'input-decode', 'validate-template', 'create-change-set', 'changeset-review'}
    case = 'shared-success' if boundary == 'shared-success' else 'input-syntax' if boundary == 'input-decode' else 'repair-series' if boundary in {'new-problem', 'regression'} else 'repair'
    parent = seed(tmp_path / 'project', tmp_path / 'session.json', case)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.chdir(parent)
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/deploy.md')
    stage = {'validate-template':'validate_template','create-change-set':'create_change_set','changeset-review':'changeset_review'}.get(boundary)
    aws_state(aws, repair=True, followup_dns=boundary in {'new-problem', 'regression'}, input_stage=stage)
    original = {p: p.read_bytes() for p in (parent / 'infra').rglob('*') if p.is_file()}
    assert invoke(parent, session, aws) == 2
    assert all(p.read_bytes() == raw for p, raw in original.items())
    saved = json.loads(session.read_text())
    handoff.restore(parent, session, saved)
    failed = saved['states']['cfn-stack-app-dev-second']
    if unexecuted:
        assert failed['status'] == 'BLOCKED' and 'stackStatus' not in failed and 'executionEvidence' not in failed
        assert not any(op == 'execute_change_set' and args['StackName'].split(':stack/')[-1].split('/')[0] == 'cfn-stack-app-dev-second'
            for _,op,args in json.loads(aws.read_text())['calls'])
    else:
        assert failed['status'] == 'FAILED' and saved['states']['cfn-stack-app-dev-first']['observedSynced']
    observation = next(o for o in saved['failureObservations'] if o['observationId'] in saved['workflow']['latestObservations'])
    relative = 'infra/cloudformation/templates/' + ('first.yaml' if boundary == 'shared-success' else 'second.yaml')
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
    if unexecuted:
        entry = diagnosis['problems'][0]
        entry['evidenceRefs'][0]['eventIndices'] = []
        entry.update(eventIndices=[], operation='create_change_set' if boundary == 'changeset-review' else stage or 'decode_input')
        if boundary == 'input-decode':
            model = f'model/dev/{ACCOUNT}/cloudformation-stacks.properties'
            entry.update(resourcePath='Template', resourceType='AWS::CloudFormation::Stack', property='Template',
                constraint='parseable-template', cause='IAC_SYNTAX')
            entry['inputRefs'][0]['pointer'] = ''
            entry['modelRefs'] = [{'path':model,'sha256':saved['modelInputManifest'][model],'key':'desired.stack.002.template'}]
    assert handoff.diagnose(parent, saved, diagnosis) == 'REPAIR_ALLOWED'
    problems = saved['workflow']['currentProblemIds']
    handoff.save(session, saved)
    problem = diagnosis['problems'][0]
    expectation = [{'stack': 'cfn-stack-app-dev-second', 'resourcePath': 'Vpc', 'operation': 'CREATE', 'status': 'CREATE_COMPLETE'}]
    if unexecuted:
        expectation[0].update(resourcePath=problem['resourcePath'], operation=problem['operation'], status='SUCCEEDED')
    if boundary == 'request':
        # Kill after the real atomic publication; the next command consumes its saved intent.
        diagnosis_path, expectation_path = tmp_path / 'diagnosis.json', tmp_path / 'expectation.json'
        diagnosis_path.write_text(json.dumps(diagnosis))
        expectation_path.write_text(json.dumps(expectation))
        command = [sys.executable, '-B', '-c',
            "import os,sys,json; from pathlib import Path; from unittest.mock import patch; "
            "from deploy_handoff import main; actual=os.replace\n"
            "def replace(a,b):\n actual(a,b)\n if Path(b)==Path(sys.argv[1]): os._exit(76)\n"
            "with patch('deploy.handoff.register_workflow'), patch.object(os,'replace',side_effect=replace): main(sys.argv[2:])", str(session),
            'request', '--state', str(session), '--repository-root', str(parent), '--expectation', str(expectation_path), '--path', relative,
            *[arg for problem in problems for arg in ('--problem', problem)]]
        interrupted = subprocess.run(command, cwd=parent, env=child_environment(), capture_output=True, text=True, timeout=90)
        assert interrupted.returncode == 76, interrupted.stdout + interrupted.stderr
        session.with_name(session.name + '.handoff-lock').rmdir()  # This test owns/reaped the writer.
        saved = json.loads(session.read_text())
        handoff.restore(parent, session, saved)
    pending = handoff.issue_request(parent, session, saved, problems, [relative], expectation)
    assert handoff.issue_request(parent, session, saved, problems, [relative], expectation) == pending
    assert saved['workflow']['reserved'] == 1
    handoff.save(session, saved)
    request, result_path = deliver(parent, session, pending, relative, model, boundary, tmp_path)
    if boundary == 'normal':
        forged = tmp_path / 'unsigned-result.json'
        forged.write_text(json.dumps({'result':'PASS','requestId':request['requestId']}))
        assert invoke(parent, session, aws, ['--resume','--repair-result',str(forged)]) == 2
        model_path = parent / model
        raw = model_path.read_bytes()
        model_path.write_bytes(raw + b'\n# dependency changed after static validation\n')
        assert invoke(parent, session, aws, ['--resume','--repair-result',str(result_path)]) == 2
        model_path.write_bytes(raw)
    if boundary in {'cleanup', 'execute', 'accept-before', 'accept-after'}:
        state = json.loads(aws.read_text())
        state['knobs'][{'cleanup': 'crash_cleanup', 'execute': 'crash_execute',
                        'accept-before': 'crash_accept_before', 'accept-after': 'crash_accept_after'}[boundary]] = True
        aws.write_text(json.dumps(state))
        helper = Path(__file__).with_name(controller_helper)
        command = [sys.executable, '-B', str(helper), str(parent), str(session), str(aws), '--resume', '--repair-result', str(result_path)]
        stopped = subprocess.run(command, cwd=parent, env=child_environment(), capture_output=True, text=True, timeout=90)
        assert stopped.returncode == {'cleanup': 74, 'execute': 73, 'accept-before': 77, 'accept-after': 78}[boundary], stopped.stdout + stopped.stderr
        intent = json.loads(session.read_text())
        assert intent['workflow']['reserved'] == 1
        if boundary == 'cleanup':
            failed = intent['states']['cfn-stack-app-dev-second']
            assert failed['cleanupStatus'] == 'DELETE_INTENT' and failed['recoveryPending']
        recover_owned_lock(parent, stopped)
    if boundary == 'repeat':
        data = json.loads(aws.read_text())
        data['knobs']['repeat_cidr'] = True
        aws.write_text(json.dumps(data))
    resumed_code = invoke(parent, session, aws, ['--resume', '--repair-result', str(result_path)])
    if boundary == 'shared-success':
        assert resumed_code == 2
        after = json.loads(session.read_text())
        assert after['workflow']['status'] == 'WAITING_HUMAN' and after['pendingRequest']
        assert after['states']['cfn-stack-app-dev-first'] == saved['states']['cfn-stack-app-dev-first']
        assert after['inputRevision'] == 0 and after['workflow']['reserved'] == 1
        return
    if boundary in {'repeat', 'new-problem', 'regression'}:
        assert resumed_code == 2
        saved = json.loads(session.read_text())
        handoff.restore(parent, session, saved)
        current = next(o for o in saved['failureObservations'] if o['observationId'] in saved['workflow']['latestObservations'])
        entry = dict(problem) if boundary == 'repeat' else {**problem, 'property':'EnableDnsSupport', 'constraint':'approved-DNS'}
        entry = json.loads(json.dumps(entry))
        entry.update(relation='SAME' if boundary == 'repeat' else 'NEW', relatedProblemIds=problems,
                     reason='CidrBlock recurred after repair.' if boundary == 'repeat' else 'AWS now identifies EnableDnsSupport, while the prior observation identified CidrBlock.')
        entry['reason'] += ' Compare the pinned prior observation and the current operation below.'
        entry['evidenceRefs'].append({'observationId':current['observationId'], 'revision':current['revision'], 'eventIndices':[0]})
        entry['observationId'] = current['observationId']
        entry['inputRefs'][0]['sha256'] = saved['infraManifest'][relative]
        entry['modelRefs'][0]['sha256'] = saved['modelInputManifest'][model]
        if boundary != 'repeat':
            entry['inputRefs'][0]['pointer'] = '/Resources/Vpc/Properties/EnableDnsSupport'
            entry['modelRefs'][0]['key'] = 'desired.row.001-004.value'
        status = handoff.diagnose(parent,saved,{'revision':saved['inputRevision'],'problems':[entry]})
        handoff.save(session,saved)
        if boundary == 'repeat':
            assert status == 'STOPPED' and saved['workflow']['reserved'] == 1
            with pytest.raises(ValueError, match='STOPPED'):
                handoff.issue_request(parent,session,saved,problems,[relative],expectation)
            return
        assert status == 'REPAIR_ALLOWED'
        next_problems = saved['workflow']['currentProblemIds']
        assert next_problems != problems
        next_request = handoff.issue_request(parent,session,saved,next_problems,[relative],expectation)
        _, second_result = deliver(parent, session, next_request, relative, model, 'dns', tmp_path)
        if boundary == 'regression':
            data=json.loads(aws.read_text())
            data['knobs']['repeat_cidr']=True
            aws.write_text(json.dumps(data))
        resumed_code = invoke(parent,session,aws,['--resume','--repair-result',str(second_result)])
        after = json.loads(session.read_text())
        assert after['workflow']['reserved'] == 2 and after['inputRevision'] == 2
        if boundary == 'regression':
            assert resumed_code == 2
            handoff.restore(parent,session,after)
            current = next(o for o in after['failureObservations'] if o['observationId'] in after['workflow']['latestObservations'])
            again = json.loads(json.dumps(problem))
            again['observationId']=current['observationId']
            again.update(relation='SAME', relatedProblemIds=problems)
            again['evidenceRefs'].append({'observationId':current['observationId'], 'revision':current['revision'], 'eventIndices':[0]})
            again['inputRefs'][0]['sha256']=after['infraManifest'][relative]
            again['modelRefs'][0]['sha256']=after['modelInputManifest'][model]
            assert handoff.diagnose(parent,after,{'revision':2,'problems':[again]}) == 'STOPPED'
            assert after['workflow']['problems'][problems[0]]['regression']
            handoff.save(session,after)
            return
        assert resumed_code == 0 and all(after['workflow']['problems'][p].get('resolvedByExecution') for p in problems + next_problems)
        return
    assert resumed_code == 0
    after = json.loads(session.read_text())
    assert after['inputRevision'] == 1 and after['workflow']['reserved'] == 1
    assert all(state['status'] == 'SUCCESS' and state['observedSynced'] for state in after['states'].values())
    assert accepted_changes(parent, (parent / 'tasks/deploy.md').read_text(), {relative}) == {relative}
    if boundary == 'normal':
        validate_parent(parent)
    assert after['workflow']['problems'][problems[0]].get('resolvedByExecution')
    before = json.loads(aws.read_text())['calls']
    copied = tmp_path / 'same-result-copy.json'
    copied.write_bytes(result_path.read_bytes())
    assert invoke(parent, session, aws, ['--resume', '--repair-result', str(copied)]) == 0
    assert invoke(parent, session, aws, ['--resume', '--repair-result', str(result_path)]) == 0
    assert not [call for call in json.loads(aws.read_text())['calls'][len(before):] if call[1] == 'execute_change_set']
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
    if boundary == 'input-decode':
        path.write_text('Resources: {Vpc: {Type: AWS::EC2::VPC, Properties: {CidrBlock: 10.0.0.0/16}}}\n')
    else:
        path.write_text(path.read_text().replace('EnableDnsSupport: false', 'EnableDnsSupport: true') if boundary == 'dns'
                        else path.read_text().replace('10.2.0.0/16', '10.0.0.0/16'))
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
