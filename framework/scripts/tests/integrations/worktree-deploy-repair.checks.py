#!/usr/bin/env python3
"""Production controller -> guards/SDK -> durable session and observed publication."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import subprocess
import tempfile

import pytest
import worktree_task as wt
from support.deploy_controller_fixtures import (
    ACCOUNT,
    child_environment,
    git,
)
from support.deploy_repair_fixtures import external_round_trip
from support.worktree_deploy_fixtures import seed
from task_contract import complete, resume
from task_contract_core import selected_task, start, suspend

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

@pytest.fixture(autouse=True)
def private_temporary_directory(tmp_path, monkeypatch):
    # Real target locks and evidence files remain active, in this fixture's OS temp area.
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    for name in ('TMPDIR', 'TMP', 'TEMP'):
        monkeypatch.setenv(name, str(tmp_path))


def _callback_external_round_trip_lifecycle(command, target, identity, *options):
    env = child_environment() | {'BLUEPRINT_TASK_FILE': 'tasks/' + identity + '.md'}
    result = subprocess.run([sys.executable, '-B', str(Path(wt.__file__)), command,
        '--repository-root', str(target), '--task-id', identity, *map(str, options)], cwd=target,
        env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _callback_external_round_trip_record_validation(diagnostics, real_run, /, command, *args, **kwargs):
    result = real_run(command, *args, **kwargs)
    if '--fresh' in command:
        diagnostics.append(result.stdout + result.stderr)
    return result


def _callback_external_round_trip_interrupted_git(actual_git, parent, /, target, *args, **kwargs):
    result = actual_git(target, *args, **kwargs)
    if target == parent and args[:2] == ('merge', '--ff-only'):
        raise InterruptedError('injected after real parent FF')
    return result




def validate_parent(parent):
    interpreter, environment = wt.python_env.runtime(parent)
    command = [str(interpreter), '-B', str(Path(wt.__file__).with_name('blueprint-loop.py')),
            '--mode','task','--task-file','tasks/deploy.md','--fresh']
    checked = subprocess.run(command, cwd=parent, env=environment, capture_output=True, text=True, timeout=90)
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize('boundary', ['normal', 'merge'])
def check_external_implement_round_trip(tmp_path, monkeypatch, boundary):
    external_round_trip(tmp_path, monkeypatch, boundary, seed=seed, deliver=managed_delivery, validate_parent=validate_parent, controller_helper='worktree_deploy_fixtures.py')




def managed_delivery(parent, session, pending, relative, model, boundary, tmp_path):
    request = _callback_external_round_trip_lifecycle('repair-checkpoint', parent, 'deploy', '--state', session) if boundary == 'normal' else wt.deploy_checkpoint(parent, 'deploy', session)
    assert request['parentTip'] == git(parent, 'rev-parse', 'HEAD').strip()
    suspend(parent, 'tasks/deploy.md', 'authorized external implement repair ' + request['requestId'])
    child_state = _callback_external_round_trip_lifecycle('create', parent, 'repair-one', '--repair-request', request['requestPath']) if boundary == 'normal' else wt.create(parent, 'repair-one', Path(request['requestPath']))
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
    (child / relative).write_text((child / relative).read_text().replace('10.2.0.0/16', '10.0.0.0/16'))
    real_run, diagnostics = subprocess.run, []
    record_validation = _bind_framework_callback(_callback_external_round_trip_record_validation, diagnostics, real_run)
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
                _callback_external_round_trip_lifecycle('repair-validate', child, 'repair-one', '--repair-request', request['requestPath'])
            else:
                wt.deploy_validate(child, 'repair-one', Path(request['requestPath']))
        except ValueError:
            raise AssertionError('Synthetic static validator: ' + ''.join(diagnostics)) from None
        complete(child, child_task)
    if boundary == 'merge':
        actual_git = wt.git
        interrupted_git = _bind_framework_callback(_callback_external_round_trip_interrupted_git, actual_git, parent)
        with patch.object(wt, 'git', side_effect=interrupted_git), pytest.raises(InterruptedError):
            wt.finalize(child, 'repair-one')
    result = _callback_external_round_trip_lifecycle('finalize', child, 'repair-one') if boundary == 'normal' else wt.finalize(child, 'repair-one')
    result_path = Path(result['repair_result'])
    assert result_path.is_file() and git(parent, 'rev-parse', 'HEAD').strip() == result['tip']
    wt.cleanup(parent, 'repair-one')
    assert not child.exists()  # Parent seal and archived contract survive cleanup.
    resume(parent, 'tasks/deploy.md')
    return request, result_path

if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
