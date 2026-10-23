#!/usr/bin/env python3
"""Production controller -> guards/SDK -> durable session and observed publication."""

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import os
import subprocess
import tempfile

import deploy.contracts as repair_contracts
import deploy.handoff as _imports_deploy_handoff
import deploy.observed_resume as _imports_deploy_observed_resume
import deploy.resume as repair_resume
import deploy.session as _imports_deploy_session
import project_targets as _imports_project_targets
import pytest
import sync_runtime as _imports_sync_runtime
from deploy import controller, handoff
from deploy import session as sessions
from deploy.session import model_input_manifest
from deploy_handoff import main as migrate
from model.core import properties
from model.files import read_model
from project_targets import load_target
from support.deploy_controller_fixtures import (
    ACCOUNT,
    aws_state,
    child_environment,
    invoke,
    ordinary_base,
    recover_owned_lock,
    seed,
)
from support.deploy_repair_fixtures import external_round_trip, ordinary_delivery
from task_contract_core import selected_task
from utils.cloudformation_format import decode
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.fixture(autouse=True)
def ordinary_workflow(monkeypatch):
    monkeypatch.setattr(handoff, 'register_workflow', lambda *args, **kwargs: None)
    monkeypatch.setattr(repair_resume, 'verify_integration_owner', lambda *args: None)
    monkeypatch.setattr(repair_contracts, 'task_start_commit', ordinary_base)


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
        load_target = _imports_project_targets.load_target
        target = load_target(root, 'dev', ACCOUNT)
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




def check_cleanup_and_repair_process_resume(tmp_path, monkeypatch):
    repair = False
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










@pytest.mark.parametrize('stage', ['REPAIR_INTENT', 'VALIDATING', 'VALIDATED'])
def check_explicit_legacy_migration(tmp_path, monkeypatch, stage):

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
    saved = json.loads(session.read_text())
    assert saved['result'] == 'COMPLETE' and 'pendingObserved' not in saved
    assert saved['repository'] == str(root) and saved['taskFile'] == 'tasks/deploy.md'
    assert saved['states'][FIRST]['executionEvidence'] == evidence
    assert all(state['status'] == 'SUCCESS' and state['observedSynced'] for state in saved['states'].values())
    for service in ('s3', 'ec2', 'cloudformation-stacks'):
        assert (root / f'docs/designs/dev/{ACCOUNT}/{service}.md').is_file()
    assert (root / f'docs/designs/dev/{ACCOUNT}/s3/s3-bucket-001-bucket-policy.json').is_file()
    values = properties(read_model(root / f'model/dev/{ACCOUNT}/ec2.properties'))
    assert values['observed.row.001-001.value'].strip('`') == 'vpc-fixture'
    removed = any(item['Action'] == 'Remove' for item in evidence['resources'])
    if not removed:
        assert values['observed.row.002-001.value'].strip('`') == 'subnet-fixture'
    with selected_task(root, 'tasks/deploy.md'):
        assert saved['modelInputManifest'] == model_input_manifest(root, 'dev', ACCOUNT)
        sync = _imports_sync_runtime.sync
        assert sync(root, False, 'dev', ACCOUNT, services=['s3', 'ec2', 'cloudformation-stacks']) == 0


@pytest.mark.parametrize('fault,exit_code', [
    ('plan-save', 2), ('model-io', 2), ('model-partial', 76),
    ('model-committed', 77), ('generation-io', 2), ('design-io', 2), ('design-partial', 79), ('design-committed', 78)])
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
        if fault in {'generation-io', 'design-io', 'design-partial', 'design-committed'}:
            assert plan['stage'] == 'MODEL_PUBLISHED'
        if fault == 'model-partial':
            classify = _imports_deploy_observed_resume.classify
            manifest = _imports_deploy_observed_resume.manifest
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
    if fault in {'model-io', 'generation-io', 'design-io'}:
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


@pytest.mark.parametrize('change', ['append', 'value', 'json', 'add', 'delete', 'json-delete', 'journal', 'no-proof', 'generation-append'])
def check_generated_external_change_rejected(tmp_path, monkeypatch, change):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'multi-observed', generated_artifacts=True)
    aws_state(aws)
    fault = 'design-partial' if change == 'journal' else 'generation-io' if change == 'generation-append' else 'design-io'
    child = child_run(root, session, aws, fault=fault)
    assert child.returncode == (79 if change == 'journal' else 2), child.stdout + child.stderr
    if change == 'journal':
        recover_owned_lock(root, child)
    saved = json.loads(session.read_text())
    evidence = saved['states'][FIRST]['executionEvidence']
    generated = saved['pendingObserved']['generated']
    design = root / f'docs/designs/dev/{ACCOUNT}/ec2.md'
    artifact = root / f'docs/designs/dev/{ACCOUNT}/s3/s3-bucket-001-bucket-policy.json'
    assert artifact.relative_to(root).as_posix() in generated['originals']
    if change in {'append', 'journal', 'generation-append'}:
        design.write_bytes(design.read_bytes() + b'\nexternal append\n')
    if change == 'value':
        raw = design.read_bytes()
        altered = raw.replace(b'app-dev-subnet', b'external-subnet')
        assert altered != raw
        design.write_bytes(altered)
    if change == 'json':
        artifact.write_bytes(b'{"external": true}\n')
    if change == 'add':
        artifact.with_name('external.json').write_bytes(b'{}\n')
    if change == 'delete':
        design.unlink()
    if change == 'json-delete':
        artifact.unlink()
    if change == 'no-proof':
        # Exercise a real signed older pending-plan shape, not a tampered workflow ledger.
        handoff = _imports_deploy_handoff
        handoff.restore(root, session, saved)
        saved['pendingObserved'].pop('generated')
        save_session = _imports_deploy_session.save_session
        save_session(session, saved)
    retained = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    journal = Path(tempfile.gettempdir()) / 'blueprint-model-publication' / (hashlib.sha256(str(root).encode()).hexdigest() + '.json')
    journal_bytes = journal.read_bytes() if journal.exists() else None
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == 2, resumed.stdout + resumed.stderr
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts} == retained
    assert (journal.read_bytes() if journal.exists() else None) == journal_bytes
    after = json.loads(session.read_text())
    assert after['states'][FIRST]['status'] == 'SUCCESS' and not after['states'][FIRST].get('observedSynced')
    assert after['states'][FIRST]['executionEvidence'] == evidence
    assert after['states'][SECOND]['status'] == 'NOT_STARTED' and after['pendingObserved']
    assert after['observedRecoveryError']
    assert_single_execution(aws, evidence)


def check_generated_change_during_publication(tmp_path, monkeypatch):
    monkeypatch.delenv('BLUEPRINT_TASK_FILE', raising=False)
    session, aws = tmp_path / 'session.json', tmp_path / 'aws.json'
    root = seed(tmp_path / 'project', session, 'multi-observed')
    aws_state(aws)
    design = root / f'docs/designs/dev/{ACCOUNT}/ec2.md'
    expected = design.read_bytes() + b'\nexternal during generation\n'
    child = child_run(root, session, aws, fault='design-race')
    assert child.returncode == 2, child.stdout + child.stderr
    assert design.read_bytes() == expected
    saved = json.loads(session.read_text())
    assert 'generation inputs changed before publication' in saved['observedError']
    assert saved['states'][FIRST]['status'] == 'SUCCESS' and saved['pendingObserved']
    assert saved['states'][SECOND]['status'] == 'NOT_STARTED'
    evidence = saved['states'][FIRST]['executionEvidence']
    resumed = child_run(root, session, aws, ['--resume'])
    assert resumed.returncode == 2, resumed.stdout + resumed.stderr
    assert design.read_bytes() == expected
    assert_single_execution(aws, evidence)


@pytest.mark.parametrize('fault,change', [
    ('model-partial', 'candidate'), ('model-partial', 'file-set'),
    ('model-committed', 'other-model'), ('model-committed', 'desired'),
    ('model-committed', 'display'), ('model-committed', 'reference'),
    ('model-committed', 'dependency'), ('model-committed', 'task'),
    ('model-committed', 'iac'), ('model-committed', 'evidence'),
    ('model-committed', 'approval')])
def check_observed_external_change_rejected(tmp_path, monkeypatch, request, fault, change):
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




@pytest.mark.parametrize('boundary', ['request', 'accept-before', 'accept-after', 'execute', 'repeat', 'new-problem', 'regression',
    'input-decode', 'validate-template', 'create-change-set', 'changeset-review', 'shared-success'])
def check_external_repair_resumption(tmp_path, monkeypatch, boundary):
    external_round_trip(tmp_path, monkeypatch, boundary, seed=seed, deliver=ordinary_delivery)

@pytest.mark.parametrize('boundary', ['cleanup'])
def check_external_repair_cleanup_recovery(tmp_path, monkeypatch, boundary):
    external_round_trip(tmp_path, monkeypatch, boundary, seed=seed, deliver=ordinary_delivery)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
