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
import pytest
from support.deploy_controller_fixtures import seed, aws_state, invoke, child_environment, ACCOUNT
from model.core import properties
from model.files import read_model
from utils.json_format import fingerprint


@pytest.fixture
def project(tmp_path, monkeypatch):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    seed(root, session)
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
    seed(root, session, 'delivery')
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
    seed(root, session, 'same-group')
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


@pytest.mark.parametrize('repair', [False, True])
def check_cleanup_and_repair_process_resume(tmp_path, monkeypatch, repair):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    seed(root, session, 'repair' if repair else 'orders')
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
    if repair:
        assert intent['repairs'][-1]['classification'] == 'AUTO_REPAIRABLE'
        assert intent['repairs'][-1]['stage'] == 'VALIDATED'
    recover_owned_lock(root, child)
    resumed = subprocess.run([*command, '--resume'], cwd=root, env=child_environment(), capture_output=True, text=True, timeout=90)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    after = json.loads(session.read_text())
    assert after['result'] == 'COMPLETE' and after['states'][name]['observedSynced']
    calls = json.loads(aws.read_text())['calls']
    assert sum(op == 'delete_stack' and args['StackName'] == intent['cleanupStackId'] for _, op, args in calls) == 1
    if repair:
        assert after['states'][name]['repairs'][-1]['stage'] == 'RETRY_READY'
        assert sum(op == 'execute_change_set' and ':stack/cfn-stack-app-dev-first/' in args['StackName'] for _, op, args in calls) == 1


@pytest.mark.parametrize('external_current', [False, True])
def check_bootstrap_process_resume(tmp_path, monkeypatch, external_current):
    root, session, aws = tmp_path / 'project', tmp_path / 'session.json', tmp_path / 'aws.json'
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    seed(root, session, 'bootstrap')
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


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
