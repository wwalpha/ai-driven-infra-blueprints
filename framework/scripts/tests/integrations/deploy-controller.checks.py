#!/usr/bin/env python3
"""Production controller -> guards/SDK -> durable session and observed publication."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import json
import os
import subprocess
import tempfile
import pytest
from support.deploy_controller_fixtures import seed, aws_state, invoke, child_environment, ACCOUNT
from model.core import properties
from model.files import read_model
from utils.json_format import fingerprint


@pytest.fixture(autouse=True)
def private_temporary_directory(tmp_path, monkeypatch):
    # Real target locks and evidence files remain active, in this fixture's OS temp area.
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    for name in ('TMPDIR', 'TMP', 'TEMP'):
        monkeypatch.setenv(name, str(tmp_path))


@pytest.fixture
def project(tmp_path, monkeypatch):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = seed(root, session)
    monkeypatch.chdir(root)
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/deploy.md')
    monkeypatch.setenv('AWS_EC2_METADATA_DISABLED', 'true')
    monkeypatch.setenv('AWS_CONFIG_FILE', os.devnull)
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE', os.devnull)
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'synthetic')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'synthetic')
    return root, session, aws


def check_orders_and_observed(project):
    root, session, aws = project
    aws_state(aws)
    assert invoke(root, session, aws, ['--skill-started-at', '1']) == 0
    saved = json.loads(session.read_text())
    assert saved['result'] == 'COMPLETE'
    assert all(s['status'] == 'SUCCESS' and s['observedSynced'] for s in saved['states'].values())
    values = properties(read_model(root / f'model/dev/{ACCOUNT}/ec2.properties'))
    assert values['observed.row.002-001.value'].strip('`') == 'subnet-fixture'
    assert values['observed.row.001-001.value'].strip('`') == 'vpc-fixture'
    assert not {'skillStartedAt', 'firstExecuteAcceptedAt', 'within120Seconds', 'skillToFirstExecuteSeconds'} & saved.keys()
    # Optional historical measurement metadata cannot invalidate a successful session.
    saved['skillStartedAt'] = 1
    saved['within120Seconds'] = False
    session.write_text(json.dumps(saved))
    before = json.loads(aws.read_text())['changes']
    assert invoke(root, session, aws, ['--resume']) == 0
    assert json.loads(aws.read_text())['changes'] == before


def check_approval_resume(project):
    root, session, aws = project
    aws_state(aws, approval=True)
    assert invoke(root, session, aws) == 2
    saved = json.loads(session.read_text())
    first = saved['states']['cfn-stack-app-dev-first']
    assert first['status'] == 'BLOCKED' and first['changeDigest']
    assert not any(op == 'execute_change_set' for _, op, _ in json.loads(aws.read_text())['calls'])
    change_id, digest = first['changeSetId'], first['changeDigest']
    assert invoke(root, session, aws, ['--resume', '--approve-change-set', change_id]) == 0
    after = json.loads(session.read_text())['states']['cfn-stack-app-dev-first']
    assert after['changeSetId'] == change_id and after['approvedChangeDigest'] == digest
    assert sum(op == 'create_change_set' and args['StackName'] == 'cfn-stack-app-dev-first'
               for _, op, args in json.loads(aws.read_text())['calls']) == 1


def check_observed_io_resume(project):
    root, session, aws = project
    aws_state(aws)
    assert invoke(root, session, aws, fail_observed=True) == 2
    saved = json.loads(session.read_text())
    first = saved['states']['cfn-stack-app-dev-first']
    assert first['status'] == 'SUCCESS' and not first.get('observedSynced')
    assert 'injected observed I/O failure' in saved['observedError']
    assert saved['states']['cfn-stack-app-dev-second']['status'] == 'NOT_STARTED'
    evidence = first['executionEvidence']
    assert invoke(root, session, aws, ['--resume']) == 0
    after = json.loads(session.read_text())
    assert after['states']['cfn-stack-app-dev-first']['observedSynced']
    assert after['states']['cfn-stack-app-dev-first']['executionEvidence'] == evidence
    assert sum(op == 'execute_change_set' and args['StackName'] == evidence['StackId']
               for _, op, args in json.loads(aws.read_text())['calls']) == 1


@pytest.mark.parametrize('failure', [False, True])
def check_group_delivery(tmp_path, monkeypatch, failure):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = seed(root, session, 'delivery')
    monkeypatch.chdir(root)
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/deploy.md')
    aws_state(aws, same_group=True, delivery=True, delivery_fail=failure)
    assert invoke(root, session, aws) == (2 if failure else 0)
    calls = json.loads(aws.read_text())['calls']
    if failure:
        assert not any(op in {'create_change_set', 'execute_change_set'} for _, op, _ in calls)
    else:
        saved = json.loads(session.read_text())
        assert all(s['observedSynced'] for s in saved['states'].values())
        first_create = next(i for i, (_, op, _) in enumerate(calls) if op == 'create_change_set')
        assert {args['Key'] for _, op, args in calls[:first_create] if op == 'put_object'} == set(json.loads(aws.read_text())['objects'])


def check_input_guard_drains_peer(tmp_path, monkeypatch):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = seed(root, session, 'same-group')
    monkeypatch.chdir(root)
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/deploy.md')
    aws_state(aws, same_group=True, edit_input=True)
    assert invoke(root, session, aws) == 2
    saved = json.loads(session.read_text())
    assert saved['states']['cfn-stack-app-dev-first']['status'] == 'SUCCESS'
    assert saved['states']['cfn-stack-app-dev-second']['status'] == 'BLOCKED'
    assert len([op for _, op, _ in json.loads(aws.read_text())['calls'] if op == 'execute_change_set']) == 1


@pytest.mark.parametrize('crash', [False, True])
def check_subprocess_execution_resume(project, crash):
    root, session, aws = project
    aws_state(aws, **({'crash_execute': True} if crash else {'lost_response': True}))
    helper = Path(__file__).resolve().parents[1] / 'support/deploy_controller_fixtures.py'
    command = [sys.executable, '-B', str(helper), str(root), str(session), str(aws)]
    first = subprocess.run(command, cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert first.returncode == (73 if crash else 2), first.stdout + first.stderr
    saved = json.loads(session.read_text())
    evidence = saved['states']['cfn-stack-app-dev-first']['executionEvidence']
    assert evidence['clientToken'] and evidence['ChangeSetId']
    if crash:
        assert saved['states']['cfn-stack-app-dev-first']['status'] == 'RUNNING'
        # The test owns and has reaped this child; only it may recover its remaining lock.
        from project_targets import load_target
        target = load_target(root, 'dev', ACCOUNT)
        import tempfile
        lock = Path(tempfile.gettempdir()) / ('blueprint-cfn-' + fingerprint(['dev', target]) + '.lock')
        assert lock.exists()
        lock.unlink()
        session.with_name(session.name + '.handoff-lock').rmdir()
    second = subprocess.run([*command, '--resume'], cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert second.returncode == 0, second.stdout + second.stderr
    final = json.loads(session.read_text())
    assert final['states']['cfn-stack-app-dev-first']['executionEvidence'] == evidence
    assert final['states']['cfn-stack-app-dev-first']['observedSynced']
    calls = json.loads(aws.read_text())['calls']
    assert sum(op == 'execute_change_set' and args['StackName'] == evidence['StackId'] for _, op, args in calls) == 1


def recover_owned_lock(root, child):
    assert child.returncode is not None  # subprocess.run has reaped this exact child.
    from project_targets import load_target
    import tempfile
    target = load_target(root, 'dev', ACCOUNT)
    lock = Path(tempfile.gettempdir()) / ('blueprint-cfn-' + fingerprint(['dev', target]) + '.lock')
    assert lock.exists()
    lock.unlink()
    state_path = Path(child.args[child.args.index(str(root)) + 1])
    state_path.with_name(state_path.name + '.handoff-lock').rmdir()


@pytest.mark.parametrize('repair', [False, True])
def check_cleanup_and_repair_process_resume(tmp_path, monkeypatch, repair):
    if repair:
        external_round_trip(tmp_path, monkeypatch, 'cleanup')
        return
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = seed(root, session, 'repair' if repair else 'orders')
    aws_state(aws, crash_cleanup=True, repair=repair)
    if not repair:
        state = json.loads(aws.read_text())
        state['stacks']['cfn-stack-app-dev-first'] = {'status': 'ROLLBACK_COMPLETE',
            'id': f'arn:aws:cloudformation:ap-northeast-1:{ACCOUNT}:stack/cfn-stack-app-dev-first/fixture'}
        aws.write_text(json.dumps(state))
    helper = Path(__file__).resolve().parents[1] / 'support/deploy_controller_fixtures.py'
    command = [sys.executable, '-B', str(helper), str(root), str(session), str(aws)]
    child = subprocess.run(command, cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert child.returncode == 74, child.stdout + child.stderr
    saved = json.loads(session.read_text())
    name = 'cfn-stack-app-dev-second' if repair else 'cfn-stack-app-dev-first'
    intent = saved['states'][name]
    assert intent['cleanupStatus'] == 'DELETE_INTENT' and intent['cleanupStackId']
    recover_owned_lock(root, child)
    resumed = subprocess.run([*command, '--resume'], cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    after = json.loads(session.read_text())
    assert after['result'] == 'COMPLETE' and after['states'][name]['observedSynced']
    calls = json.loads(aws.read_text())['calls']
    assert sum(op == 'delete_stack' and args['StackName'] == intent['cleanupStackId'] for _, op, args in calls) == 1


@pytest.mark.parametrize('external_current', [False, True])
def check_bootstrap_process_resume(tmp_path, monkeypatch, external_current):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    root = seed(root, session, 'bootstrap')
    aws_state(aws, bootstrap=True, crash_bootstrap=True)
    helper = Path(__file__).resolve().parents[1] / 'support/deploy_controller_fixtures.py'
    command = [sys.executable, '-B', str(helper), str(root), str(session), str(aws)]
    child = subprocess.run(command, cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert child.returncode == 75, child.stdout + child.stderr
    saved = json.loads(session.read_text())
    entry = saved['states']['cfn-stack-app-dev-second']['repairs'][-1]
    assert entry['stage'] == 'PUT_SUBMITTED'
    token = entry['clientRequestToken']
    current = json.loads(aws.read_text())
    assert token in current['versions']
    if external_current:
        current['versions']['external-version'] = ['AWSCURRENT']
        aws.write_text(json.dumps(current))
    recover_owned_lock(root, child)
    resumed = subprocess.run([*command, '--resume'], cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert resumed.returncode == (2 if external_current else 0), resumed.stdout + resumed.stderr
    after = json.loads(session.read_text())
    assert after['states']['cfn-stack-app-dev-second']['repairs'][-1]['clientRequestToken'] == token
    final = json.loads(aws.read_text())
    puts = [args for service, op, args in final['calls'] if op == 'put_secret_value']
    assert len(puts) == 1 and puts[0]['ClientRequestToken'] == token
    if external_current:
        assert final['versions']['external-version'] == ['AWSCURRENT']
        assert 'AWSCURRENT' not in final['versions'][token]
        assert after['states']['cfn-stack-app-dev-second']['failureClassification'] == 'HUMAN_REQUIRED'
    else:
        assert after['result'] == 'COMPLETE' and 'AWSCURRENT' in final['versions'][token]


def external_round_trip(tmp_path, monkeypatch, boundary):
    from task_contract import selected_task, suspend, resume, start, complete
    from deploy import handoff
    from deploy.contracts import sha, accepted_changes
    import worktree_task as wt
    from support.deploy_controller_fixtures import git
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
        source = Path(wt.__file__).with_name('deploy_handoff.py')
        command = [sys.executable, '-B', '-c',
            "import os,sys,json; from pathlib import Path; from unittest.mock import patch; "
            "from deploy_handoff import main; actual=os.replace\n"
            "def replace(a,b):\n actual(a,b)\n if Path(b)==Path(sys.argv[1]): os._exit(76)\n"
            "with patch.object(os,'replace',side_effect=replace): main(sys.argv[2:])", str(session),
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
    def lifecycle(command, target, identity, *options):
        env = child_environment() | {'BLUEPRINT_TASK_FILE': 'tasks/' + identity + '.md'}
        result = subprocess.run([sys.executable, '-B', str(Path(wt.__file__)), command,
            '--repository-root', str(target), '--task-id', identity, *map(str, options)], cwd=target,
            env=env, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    request = lifecycle('repair-checkpoint', parent, 'deploy', '--state', session) if boundary == 'normal' else wt.deploy_checkpoint(parent, 'deploy', session)
    assert request['parentTip'] == git(parent, 'rev-parse', 'HEAD').strip()
    suspend(parent, 'tasks/deploy.md', 'authorized external implement repair ' + request['requestId'])
    child_state = lifecycle('create', parent, 'repair-one', '--repair-request', request['requestPath']) if boundary == 'normal' else wt.create(parent, 'repair-one', Path(request['requestPath']))
    child = Path(child_state['worktree'])
    with pytest.raises(ValueError, match='another child'):
        wt.create(parent, 'repair-two', Path(request['requestPath']))
    assert git(child, 'rev-parse', 'HEAD').strip() == request['parentTip']
    child_task = child_state['task_file']
    paths = '\n'.join('- `' + p + '`' for p in [child_task, relative])
    contract = ('## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n'
        '- Infrastructure phase: `implement`\n- AWS API execution: `forbidden`\n- AWS mutation: `forbidden`\n- Deploy/apply: `forbidden`\n'
        f'- Target environment: `dev`\n- Target AWS account: `{ACCOUNT}`\n- Deploy repair request: `{request["requestPath"]}`\n'
        '## Required changes\n- [R1] Correct approved Vpc CidrBlock\n## Acceptance checks\n- [R1] `changed:' + relative + '`\n'
        '## Validation scope\n' + ''.join('- `' + scope + '`\n' for scope in request['validationScope']) +
        '## Modified files\n' + paths + '\n## Allowed paths\n' + paths + '\n')
    start(child, child_task, contract)
    if boundary == 'input-decode':
        (child / relative).write_text('Resources: {Vpc: {Type: AWS::EC2::VPC, Properties: {CidrBlock: 10.0.0.0/16}}}\n')
    else:
        (child / relative).write_text((child / relative).read_text().replace('10.2.0.0/16', '10.0.0.0/16'))
    from unittest.mock import patch
    real_run, diagnostics = subprocess.run, []
    def record_validation(command, *args, **kwargs):
        result = real_run(command, *args, **kwargs)
        if '--fresh' in command:
            diagnostics.append(result.stdout + result.stderr)
        return result
    if boundary == 'normal':
        approved = (child / relative).read_text()
        (child / relative).write_text('Resources: [invalid')
        with selected_task(child, child_task), pytest.raises((ValueError, RuntimeError)):
            wt.deploy_validate(child, 'repair-one', Path(request['requestPath']))
        rejected = json.loads(session.read_text())
        assert rejected['workflow']['reserved'] == 1
        assert rejected['workflow']['attempts'][pending['attemptId']]['staticFailures'] == 1
        (child / relative).write_text(approved)
        resume(child, child_task)
    with selected_task(child, child_task), patch.object(subprocess, 'run', side_effect=record_validation):
        try:
            if boundary == 'normal':
                lifecycle('repair-validate', child, 'repair-one', '--repair-request', request['requestPath'])
            else:
                wt.deploy_validate(child, 'repair-one', Path(request['requestPath']))
        except ValueError:
            raise AssertionError('Synthetic static validator: ' + ''.join(diagnostics)) from None
        complete(child, child_task)
    if boundary == 'merge':
        actual_git = wt.git
        def interrupted_git(target, *args, **kwargs):
            result = actual_git(target, *args, **kwargs)
            if target == parent and args[:2] == ('merge', '--ff-only'):
                raise InterruptedError('injected after real parent FF')
            return result
        with patch.object(wt, 'git', side_effect=interrupted_git), pytest.raises(InterruptedError):
            wt.finalize(child, 'repair-one')
    result = lifecycle('finalize', child, 'repair-one') if boundary == 'normal' else wt.finalize(child, 'repair-one')
    result_path = Path(result['repair_result'])
    assert result_path.is_file() and git(parent, 'rev-parse', 'HEAD').strip() == result['tip']
    wt.cleanup(parent, 'repair-one')
    assert not child.exists()  # Parent seal and archived contract survive cleanup.
    resume(parent, 'tasks/deploy.md')
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
        helper = Path(__file__).resolve().parents[1] / 'support/deploy_controller_fixtures.py'
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
        data = json.loads(aws.read_text()); data['knobs']['repeat_cidr'] = True; aws.write_text(json.dumps(data))
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
        saved = json.loads(session.read_text()); handoff.restore(parent, session, saved)
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
        next_request = wt.deploy_checkpoint(parent,'deploy',session)
        suspend(parent,'tasks/deploy.md','authorized second distinct cause')
        second_state = wt.create(parent,'repair-two',Path(next_request['requestPath']))
        second = Path(second_state['worktree'])
        second_contract = contract.replace('Correct approved Vpc CidrBlock','Correct approved Vpc EnableDnsSupport').replace('tasks/repair-one.md','tasks/repair-two.md').replace(request['requestPath'],next_request['requestPath'])
        start(second,'tasks/repair-two.md',second_contract)
        (second / relative).write_text((second / relative).read_text().replace('EnableDnsSupport: false','EnableDnsSupport: true'))
        with selected_task(second,'tasks/repair-two.md'):
            wt.deploy_validate(second,'repair-two',Path(next_request['requestPath']))
            complete(second,'tasks/repair-two.md')
        second_result = wt.finalize(second,'repair-two')
        wt.cleanup(parent,'repair-two')
        resume(parent,'tasks/deploy.md')
        if boundary == 'regression':
            data=json.loads(aws.read_text()); data['knobs']['repeat_cidr']=True; aws.write_text(json.dumps(data))
        resumed_code = invoke(parent,session,aws,['--resume','--repair-result',second_result['repair_result']])
        after = json.loads(session.read_text())
        assert after['workflow']['reserved'] == 2 and after['inputRevision'] == 2
        if boundary == 'regression':
            assert resumed_code == 2
            handoff.restore(parent,session,after)
            current = next(o for o in after['failureObservations'] if o['observationId'] in after['workflow']['latestObservations'])
            again = json.loads(json.dumps(problem)); again['observationId']=current['observationId']
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
        interpreter, environment = wt.python_env.runtime(parent)
        command = [str(interpreter), '-B', str(Path(wt.__file__).with_name('blueprint-loop.py')),
            '--mode','task','--task-file','tasks/deploy.md','--fresh']
        checked = subprocess.run(command, cwd=parent, env=environment, capture_output=True, text=True, timeout=90)
        assert checked.returncode == 0, checked.stdout + checked.stderr
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


@pytest.mark.parametrize('stage', ['REPAIR_INTENT', 'VALIDATING', 'VALIDATED'])
def check_explicit_legacy_migration(tmp_path, monkeypatch, stage):
    from deploy import controller, handoff, session as sessions
    from deploy.contracts import task_digest
    from project_targets import load_target
    from utils.cloudformation_format import decode
    import hashlib
    root = seed(tmp_path / 'project', tmp_path / 'session.json')
    path, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.chdir(root)
    monkeypatch.setenv('BLUEPRINT_TASK_FILE', 'tasks/deploy.md')
    target = load_target(root, 'dev', ACCOUNT)
    names = ['cfn-stack-app-dev-first', 'cfn-stack-app-dev-second']
    limit, units = controller.load_units(root, 'dev', ACCOUNT, names)
    backend = controller.create_runtime(root, 'dev', ACCOUNT, target)
    for unit in units:
        backend.load_inputs(unit)
    token, stack_id = 'legacy-original-token', f'arn:aws:cloudformation:ap-northeast-1:{ACCOUNT}:stack/{names[0]}/legacy'
    old_execution = fingerprint('legacy authored definitions')
    template = root / 'infra/cloudformation/templates/second.yaml'
    candidate = tmp_path / 'old-candidate.yaml'
    candidate.write_text('DO NOT APPLY legacy candidate')
    old_repair = {'classification':'AUTO_REPAIRABLE', 'stage':stage, 'failureClass':'Vpc:CidrBlock',
                  'path':template.relative_to(root).as_posix(), 'candidatePath':str(candidate), 'newFileDigest':hashlib.sha256(candidate.read_bytes()).hexdigest()}
    contract = (root / 'tasks/deploy.md').read_text()
    old_task = '\n'.join(line for line in contract.splitlines() if not line.startswith(('- Authorized delete/replacement:', '- Task status:')))
    legacy = {'version':3, 'modelFormat':2, 'snapshotVersion':2, 'referenceMeaningVersion':1,
        'repository':str(root), 'taskFile':'tasks/deploy.md', 'taskDigest':hashlib.sha256(old_task.encode()).hexdigest(),
        'inputDigest':fingerprint([str(root), target, 'dev', 'deploy', limit, units]),
        'unitDigests':{unit['name']:backend.input_digest(unit) for unit in units},
        'infraManifest':{p.relative_to(root).as_posix():backend.file_digest(p) for p in backend.deployment_input_paths(units)},
        'designDigest':sessions.design_digest(root,'dev',ACCOUNT), 'modelInputManifest':sessions.model_input_manifest(root,'dev',ACCOUNT),
        'executionDigest':old_execution,
        'states':{names[0]:{'status':'RUNNING','clientToken':token,'stackId':stack_id,'changeSetId':'legacy-cs',
                          'executionEvidence':{'StackId':stack_id,'ChangeSetId':'legacy-cs','clientToken':token}},
                  names[1]:{'status':'FAILED','stackStatus':'ROLLBACK_COMPLETE','clientToken':'other-token',
                            'cleanupStatus':'DELETE_INTENT','cleanupStackId':'old-cleanup','repairs':[old_repair]}}}
    handoff.save(path, legacy)
    aws_state(aws)
    fake = json.loads(aws.read_text())
    document = decode((root / 'infra/cloudformation/templates/first.yaml').read_bytes())[0]
    fake['stacks'][names[0]] = {'id':stack_id,'status':'CREATE_COMPLETE'}
    fake['changes'][names[0]] = {'id':'legacy-cs','alias':'legacy-cs','stackId':stack_id,'executed':True,'token':token,'document':document}
    aws.write_text(json.dumps(fake))
    inputs = {p:p.read_bytes() for p in (root / 'model').rglob('*') if p.is_file()}
    assert invoke(root,path,aws,['--resume']) == 2
    assert invoke(root,path,aws,['--resume','--observe-only']) == 0
    observed = json.loads(path.read_text())
    assert observed['states'][names[0]]['status'] == 'SUCCESS' and not observed['states'][names[0]].get('observedSynced')
    assert all(p.read_bytes() == raw for p,raw in inputs.items())
    assert observed['executionDigest'] == old_execution
    new_execution = sessions.execution_digest(root,target,backend.file_digest,{})
    from deploy_handoff import main as migrate
    assert migrate(['migrate','--state',str(path),'--repository-root',str(root),
        '--old-execution-digest',old_execution,'--new-execution-digest',new_execution,
        '--acknowledge-legacy-cycles','1','--authorization','explicit synthetic migration review']) == 0
    migrated = json.loads(path.read_text())
    assert migrated['version'] == 4 and migrated['executionDigest'] == new_execution
    assert migrated['workflow']['reserved'] == 1 and migrated['workflow']['legacyUncertain']
    assert migrated['states'][names[0]]['clientToken'] == token
    assert migrated['states'][names[1]]['cleanupStatus'] == 'DELETE_INTENT'
    assert migrated['states'][names[1]]['repairs'] == [old_repair]
    assert candidate.read_text() == 'DO NOT APPLY legacy candidate'
    assert template.read_bytes() == backend.paths(units[1])[0].read_bytes()
    assert invoke(root,path,aws,['--resume']) == 2
    assert not any(operation == 'execute_change_set' for _,operation,_ in json.loads(aws.read_text())['calls'])


@pytest.mark.parametrize('boundary', ['normal', 'request', 'merge', 'accept-before', 'accept-after', 'execute', 'repeat', 'new-problem', 'regression', 'input-decode', 'validate-template', 'create-change-set', 'changeset-review', 'shared-success'])
def check_external_implement_round_trip(tmp_path, monkeypatch, boundary):
    external_round_trip(tmp_path, monkeypatch, boundary)


FIRST = 'cfn-stack-app-dev-first'
SECOND = 'cfn-stack-app-dev-second'


def child_run(root, session, aws, options=(), fault=None):
    helper = Path(__file__).resolve().parents[1] / 'support/deploy_controller_fixtures.py'
    environment = child_environment()
    if fault:
        environment['BLUEPRINT_OBSERVED_FAULT'] = fault
    return subprocess.run([sys.executable, '-B', str(helper), str(root), str(session), str(aws), *options],
        cwd=root, env=environment, capture_output=True, text=True, timeout=90)


def assert_single_execution(aws, evidence):
    calls = json.loads(aws.read_text())['calls']
    assert sum(op == 'execute_change_set' and args['StackName'] == evidence['StackId'] for _, op, args in calls) == 1
    assert sum(op == 'create_change_set' and args['StackName'] == FIRST for _, op, args in calls) == 1


def assert_published(root, session, evidence):
    from deploy.session import model_input_manifest
    from model.render import markdown_for
    from task_contract import selected_task
    saved = json.loads(session.read_text())
    assert saved['result'] == 'COMPLETE' and 'pendingObserved' not in saved
    assert saved['repository'] == str(root) and saved['taskFile'] == 'tasks/deploy.md'
    assert saved['states'][FIRST]['executionEvidence'] == evidence
    assert all(state['status'] == 'SUCCESS' and state['observedSynced'] for state in saved['states'].values())
    with selected_task(root, 'tasks/deploy.md'):
        assert saved['modelInputManifest'] == model_input_manifest(root, 'dev', ACCOUNT)
        from sync_runtime import compare_generation
        errors = compare_generation(root, {('dev', ACCOUNT, service) for service in ('s3', 'ec2', 'cloudformation-stacks')})
        assert not errors, errors


@pytest.mark.parametrize('fault,exit_code', [
    ('plan-save', 2), ('model-io', 2), ('model-partial', 76),
    ('model-committed', 77), ('design-io', 2), ('design-committed', 78)])
def check_observed_publication_process_resume(tmp_path, monkeypatch, fault, exit_code):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'multi-observed')
    aws_state(aws)
    original = {p: p.read_bytes() for p in (root / 'model').rglob('*.properties')}
    child = child_run(root, session, aws, fault=fault)
    assert child.returncode == exit_code, child.stdout + child.stderr
    saved = json.loads(session.read_text())
    state = saved['states'][FIRST]
    assert state['status'] == 'SUCCESS' and not state.get('observedSynced')
    assert saved['states'][SECOND]['status'] == 'NOT_STARTED'
    evidence = state['executionEvidence']
    assert_single_execution(aws, evidence)
    if fault in {'plan-save', 'model-io'}:
        assert {p: p.read_bytes() for p in original} == original
    if fault != 'plan-save':
        plan = saved['pendingObserved']
        assert len(plan['outputs']) >= 2
        assert plan['evidence'][FIRST]['executionEvidence'] == evidence
        if fault in {'model-partial', 'model-committed'}:
            assert plan['stage'] == 'PREPARED'
        if fault in {'design-io', 'design-committed'}:
            assert plan['stage'] == 'MODEL_PUBLISHED'
        if fault == 'model-partial':
            from deploy.observed_resume import classify, manifest
            current = manifest({p.relative_to(root).as_posix(): p.read_bytes() for p in original})
            # project.json is an authority dependency as well as the Model sources.
            current['project.json'] = __import__('hashlib').sha256((root / 'project.json').read_bytes()).hexdigest()
            assert classify(current, plan['beforeManifest'], plan['afterManifest'], mixed=True) == 'PARTIAL'
    if exit_code > 2:
        recover_owned_lock(root, child)
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert_published(root, session, evidence)
    assert_single_execution(aws, evidence)
    if fault in {'model-io', 'design-io'}:
        assert json.loads(session.read_text())['observedFailures'][0]['cause']


def check_observed_drains_peer_then_resumes(tmp_path, monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'multi-observed', same_group=True)
    aws_state(aws, same_group=True, defer_peer=True)
    failed = child_run(root, session, aws, fault='design-io')
    assert failed.returncode == 2, failed.stdout + failed.stderr
    saved = json.loads(session.read_text())
    assert set(saved['pendingObserved']['evidence']) == {FIRST}
    assert all(state['status'] == 'SUCCESS' and not state.get('observedSynced') for state in saved['states'].values())
    evidence = {name: state['executionEvidence'] for name, state in saved['states'].items()}
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert_published(root, session, evidence[FIRST])
    after = json.loads(session.read_text())
    assert {name: state['executionEvidence'] for name, state in after['states'].items()} == evidence
    assert_single_execution(aws, evidence[FIRST])
    assert sum(op == 'execute_change_set' and args['StackName'] == evidence[SECOND]['StackId']
               for _, op, args in json.loads(aws.read_text())['calls']) == 1


@pytest.mark.parametrize('fault,change', [
    ('model-partial', 'candidate'), ('model-partial', 'file-set'),
    ('model-committed', 'other-model'), ('model-committed', 'desired'),
    ('model-committed', 'display'), ('model-committed', 'reference'),
    ('model-committed', 'dependency'), ('model-committed', 'task'),
    ('model-committed', 'iac'), ('model-committed', 'evidence'),
    ('model-committed', 'approval')])
def check_observed_external_change_rejected(tmp_path, monkeypatch, request, fault, change):
    import hashlib
    import re
    import tempfile
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'multi-observed')
    aws_state(aws)
    child = child_run(root, session, aws, fault=fault)
    assert child.returncode == (76 if fault == 'model-partial' else 77), child.stdout + child.stderr
    recover_owned_lock(root, child)
    saved = json.loads(session.read_text())
    plan = saved['pendingObserved']
    evidence = saved['states'][FIRST]['executionEvidence']
    outputs = [root / p for p in plan['outputs']]
    if change == 'candidate':
        path = next(p for p in outputs if b'observed.row.' in p.read_bytes())
        text = path.read_text()
        path.write_text(re.sub(r'(observed.row.[^=]+)=.*', r'\1=`external-id`', text, count=1))
    elif change in {'desired', 'display', 'reference'}:
        path = outputs[0]
        text = path.read_text()
        if change == 'reference':
            altered = text.replace('#resource-', '#external-', 1)
        else:
            altered = re.sub(r'(' + change + r'\.[^=]+)=.*', r'\1=external-edit', text, count=1)
        assert altered != text
        path.write_text(altered)
    elif change == 'other-model':
        path = root / f'model/dev/{ACCOUNT}/s3.properties'
        path.write_text(path.read_text() + '# external edit\n')
    elif change == 'file-set':
        (outputs[0].parent / 'part-999.properties').write_text('# external authority\n')
    elif change == 'dependency':
        path = root / 'project.json'
        path.write_text(path.read_text() + ' ')
    elif change == 'task':
        path = root / 'tasks/deploy.md'
        path.write_text(path.read_text().replace(f'- `dev/{ACCOUNT}/ec2`\n', ''))
    elif change == 'iac':
        path = root / 'infra/cloudformation/templates/second.yaml'
        path.write_text(path.read_text() + '# external IaC edit\n')
    elif change == 'evidence':
        saved['states'][FIRST]['executionEvidence']['resources'][0]['PhysicalResourceId'] = 'external'
        session.write_text(json.dumps(saved))
    elif change == 'approval':
        saved['states'][FIRST]['approvedChangeDigest'] = 'external'
        session.write_text(json.dumps(saved))
    retained = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    calls = json.loads(aws.read_text())['calls']
    journal = Path(tempfile.gettempdir()) / 'blueprint-model-publication' / (hashlib.sha256(str(root).encode()).hexdigest() + '.json')
    journal_bytes = journal.read_bytes() if journal.exists() else None
    request.addfinalizer(lambda: journal.unlink(missing_ok=True))
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == 2, resumed.stdout + resumed.stderr
    assert {p: p.read_bytes() for p in retained} == retained
    assert (journal.read_bytes() if journal.exists() else None) == journal_bytes
    after = json.loads(session.read_text())
    assert after['states'][FIRST]['status'] == 'SUCCESS' and not after['states'][FIRST].get('observedSynced')
    assert after['states'][SECOND]['status'] == 'NOT_STARTED'
    assert after['pendingObserved'] == plan
    if change not in {'evidence', 'approval'}:
        assert after['observedRecoveryError']
    else:
        assert 'signed workflow ledger' in resumed.stderr
    mutations = {'create_change_set', 'execute_change_set', 'delete_stack', 'put_object'}
    assert not any(op in mutations for _, op, _ in json.loads(aws.read_text())['calls'][len(calls):])
    if change not in {'evidence', 'approval'}:
        assert after['states'][FIRST]['executionEvidence'] == evidence
    assert_single_execution(aws, evidence)


@pytest.mark.parametrize('mismatch', [False, True])
def check_legacy_session_without_observed_plan(tmp_path, monkeypatch, mismatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'multi-observed')
    aws_state(aws)
    child = child_run(root, session, aws, fault='model-committed' if mismatch else 'plan-save')
    assert child.returncode == (77 if mismatch else 2), child.stdout + child.stderr
    if mismatch:
        recover_owned_lock(root, child)
    saved = json.loads(session.read_text())
    saved.pop('pendingObserved', None)  # Legacy sessions have no pre-publication proof.
    session.write_text(json.dumps(saved))
    before = {p: p.read_bytes() for p in (root / 'model').rglob('*.properties')}
    evidence = saved['states'][FIRST]['executionEvidence']
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == (2 if mismatch else 0), resumed.stdout + resumed.stderr
    assert_single_execution(aws, evidence)
    if mismatch:
        assert 'signed workflow ledger' in resumed.stderr
        assert {p: p.read_bytes() for p in before} == before
        assert json.loads(session.read_text())['states'][SECOND]['status'] == 'NOT_STARTED'
    else:
        assert_published(root, session, evidence)


@pytest.mark.parametrize('policy,proof,success,pending', [
    ('Delete', 'complete', True, True), ('Retain', 'complete', True, False),
    ('Delete', 'skipped', True, False), ('Delete', 'missing', False, False),
    ('Delete', 'token', False, False), ('Delete', 'stack', False, False),
    ('Delete', 'physical', False, False)])
def check_remove_controller_process_resume(tmp_path, monkeypatch, policy, proof, success, pending):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'remove')
    aws_state(aws, remove=True, policy=policy, delete_proof=proof, crash_execute=True)
    blocked = child_run(root, session, aws)
    assert blocked.returncode == 2, blocked.stdout + blocked.stderr
    saved = json.loads(session.read_text())
    state = saved['states'][FIRST]
    assert state['status'] == 'BLOCKED' and 'executionEvidence' not in state
    assert any(item['Action'] == 'Remove' for item in state['changes'])
    assert not any(op == 'execute_change_set' for _, op, _ in json.loads(aws.read_text())['calls'])
    child = child_run(root, session, aws, ['--resume', '--approve-change-set', state['changeSetId']])
    assert child.returncode == 73, child.stdout + child.stderr
    executed = json.loads(session.read_text())
    evidence = executed['states'][FIRST]['executionEvidence']
    removal = next(item for item in evidence['resources'] if item['Action'] == 'Remove')
    assert removal['PhysicalResourceId'] == 'subnet-before' and evidence['clientToken']
    assert evidence['StackId'] == state['stackId'] and evidence['ChangeSetId'] == state['changeSetId']
    assert evidence['changeDigest'] == state['changeDigest']
    assert executed['states'][SECOND]['status'] == 'NOT_STARTED'
    recover_owned_lock(root, child)
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == (0 if success else 2), resumed.stdout + resumed.stderr
    after = json.loads(session.read_text())
    assert after['states'][FIRST]['executionEvidence'] == evidence
    assert after['states'][FIRST]['status'] == 'SUCCESS'
    assert_single_execution(aws, evidence)
    observed = properties(read_model(root / f'model/dev/{ACCOUNT}/ec2.properties'))['observed.row.002-001.value'].strip('`')
    assert observed == ('PENDING_DEPLOY' if pending else 'subnet-before')
    if success:
        assert_published(root, session, evidence)
    else:
        assert not after['states'][FIRST].get('observedSynced') and after['observedError']
        assert after['states'][SECOND]['status'] == 'NOT_STARTED'
        assert 'subnet-before' in (root / f'docs/designs/dev/{ACCOUNT}/ec2.md').read_text()


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
