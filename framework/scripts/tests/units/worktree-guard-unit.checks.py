#!/usr/bin/env python3
"""Ordinary integration guard runtime and pre-write boundaries, using synthetic inputs."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

import builtins
import json
import os
import subprocess
from unittest.mock import patch
import pytest
import worktree_task as wt
from support.worktree_task_fixtures import contract


@pytest.mark.parametrize('approved', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'reject', 'launch', 'runtime'])
def check_registered_guard_process(tmp_path, capsys, approved, outcome):
    scripts = tmp_path / 'framework/scripts'
    scripts.mkdir(parents=True)
    # Execute the real Task selection implementation with a hostile inherited selector.
    import shutil
    for name in ('task_contract.py', 'sync_files.py', 'validation_cache.py', 'iac_values.py'):
        shutil.copyfile(Path(wt.__file__).with_name(name), scripts / name)
    task = 'tasks/selected.md'
    (tmp_path / 'tasks').mkdir()
    (tmp_path / task).write_text(contract('selected', ['file.txt']))
    (scripts / 'import_guard.py').write_text('''import sys, os
from pathlib import Path
import task_contract as tasks
def require_import_changes(root, **kwargs):
    assert root == Path.cwd()
    assert tasks.contract_path(root).relative_to(root).as_posix() == sys.argv[1]
    assert kwargs == ({'contract_file': sys.argv[1]} if sys.argv[2] == 'approved' else {})
    print('stdout diagnostic')
    print('warning: synthetic reference', file=sys.stderr)
    if os.environ['GUARD_OUTCOME'] == 'reject':
        raise ValueError('guard rejection')
''', encoding='utf-8')
    environment = {**os.environ, 'BLUEPRINT_TASK_FILE': 'tasks/foreign.md', 'GUARD_OUTCOME': outcome}
    real_import = builtins.__import__
    def missing_parent_dependency(name, *args, **kwargs):
        if name in ('import_guard', 'pystache', 'yaml'):
            raise ModuleNotFoundError('parent lacks Model dependencies')
        return real_import(name, *args, **kwargs)
    with patch.object(wt.python_env, 'runtime', return_value=(Path(sys.executable), environment)) as runtime, \
         patch.object(wt.python_env, 'setup', side_effect=AssertionError('no setup')), \
         patch('builtins.__import__', side_effect=missing_parent_dependency):
        if outcome == 'runtime':
            runtime.side_effect = ValueError('stale runtime')
            with pytest.raises(ValueError, match='stale runtime'):
                wt._run_model_guard(tmp_path, task, approved)
            runtime.side_effect = None
            runtime.return_value = None
            with pytest.raises(wt.Blocked, match='registered Python runtime is missing'):
                wt._run_model_guard(tmp_path, task, approved)
        elif outcome == 'launch':
            with patch.object(wt.subprocess, 'run', side_effect=OSError('cannot launch')), pytest.raises(OSError):
                wt._run_model_guard(tmp_path, task, approved)
        elif outcome == 'reject':
            with pytest.raises(wt.Blocked) as caught:
                wt._run_model_guard(tmp_path, task, approved)
            assert caught.value.diagnostics['returncode'] == 1
            assert caught.value.diagnostics['stdout'] == 'stdout diagnostic\n'
            assert 'guard rejection' in caught.value.diagnostics['stderr']
        else:
            wt._run_model_guard(tmp_path, task, approved)
            output = capsys.readouterr()
            assert output.out == ''
            assert 'stdout diagnostic' in output.err and 'warning: synthetic reference' in output.err


@pytest.mark.parametrize('violation', ['head', 'unverified', 'committed-dirty', 'scope', 'operation', 'guard', 'task-after', 'bytes-after', 'head-after', 'paths-after', 'index-after'])
def check_prepare_rejects_before_git_write(tmp_path, violation):
    relative = 'model/dev/cde/example.properties'
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text('original')
    task = tmp_path / 'tasks/example.md'
    task.parent.mkdir()
    task.write_text(contract('example', [relative]).replace('`running`', '`completed`'))
    state = dict(task_id='example', task_file='tasks/example.md', tip='tip', start='tip', commit=None, verified=False, base='main')
    changed = {relative}
    head, index = ['tip'], ['index']
    if violation == 'head': head[0] = 'unexpected'
    if violation == 'unverified': state['commit'] = 'tip'
    if violation == 'committed-dirty': state.update(commit='tip', verified=True)
    if violation == 'scope': changed.add('foreign.txt')
    def guard(*args):
        if violation == 'guard': raise wt.Blocked('guard rejected')
        if violation == 'task-after': task.write_text(task.read_text() + '\nchanged task')
        if violation == 'bytes-after': source.write_text('changed during guard')
        if violation == 'head-after': head[0] = 'unexpected'
        if violation == 'paths-after': changed.add('foreign.txt')
        if violation == 'index-after': index[0] = 'changed index'
    with patch.object(wt, 'changed_paths', side_effect=lambda root: set(changed)), \
         patch.object(wt, 'committed_task_paths', return_value=set()), \
         patch.object(wt, 'integration_task'), patch.object(wt.tasks, 'validate_contract'), \
         patch.object(wt, 'base_worktree'), patch.object(wt, 'ancestor', return_value=True), \
         patch.object(wt, 'idle_git', side_effect=wt.Blocked('unfinished Git operation') if violation == 'operation' else None), \
         patch.object(wt, 'output', side_effect=lambda root, *args: index[0] if args[0] == 'diff' else head[0]), \
         patch.object(wt, '_run_model_guard', side_effect=guard) as called, \
         patch.object(wt, 'git', side_effect=AssertionError('Git write reached')):
        with pytest.raises(wt.Blocked):
            wt._prepare_commit(tmp_path, tmp_path / 'state.json', state, tmp_path, None)
        assert called.call_count == (0 if violation in ('head', 'unverified', 'committed-dirty', 'scope', 'operation') else 1)
    assert state['commit'] == ('tip' if violation in ('unverified', 'committed-dirty') else None)


def check_cli_failure_diagnostics(tmp_path, capsys):
    error = wt.Blocked('child failed')
    error.diagnostics = dict(returncode=23, stdout='output', stderr='error')
    with patch.object(sys, 'argv', ['worktree_task.py', 'finalize', '--task-id', 'fixture']), \
         patch.object(wt, 'load', return_value=(tmp_path, None, None, {})), \
         patch.object(wt, 'finalize', side_effect=error):
        assert wt.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'blocked' and result['diagnostics'] == error.diagnostics


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
