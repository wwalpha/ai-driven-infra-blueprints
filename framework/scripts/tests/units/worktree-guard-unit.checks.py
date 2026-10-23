#!/usr/bin/env python3
"""Ordinary integration guard runtime and pre-write boundaries, using synthetic inputs."""

import copy
import sys
from contextlib import nullcontext
from functools import partial as _bind_framework_callback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import builtins
import json
import os
import subprocess
from unittest.mock import patch

import pytest
import worktree_task as wt
from support.worktree_task_fixtures import contract

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def _callback_check_registered_guard_process_child(guard_source, real_run, /, command, **kwargs):
    command = list(command)
    at = command.index('-c') + 1
    command[at] = (f'import sys, types; sys.path.insert(0, {str(Path(wt.__file__).parent)!r}); stub = types.ModuleType("import_guard"); '
                   + 'exec(' + repr(guard_source) + ', stub.__dict__); '
                   + 'sys.modules["import_guard"] = stub; ' + command[at])
    return real_run(command, **kwargs)


def _callback_check_registered_guard_process_missing_parent_dependency(real_import, /, name, *args, **kwargs):
    if name in ('import_guard', 'pystache', 'yaml'):
        raise ModuleNotFoundError('parent lacks Model dependencies')
    return real_import(name, *args, **kwargs)


@pytest.mark.parametrize('approved', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'reject', 'launch', 'runtime'])
def check_registered_guard_process(tmp_path, capsys, approved, outcome):
    task = 'tasks/selected.md'
    (tmp_path / 'tasks').mkdir()
    (tmp_path / task).write_text(contract('selected', ['file.txt']))
    guard_source = '''import sys, os
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
'''
    environment = {**os.environ, 'BLUEPRINT_TASK_FILE': 'tasks/foreign.md', 'GUARD_OUTCOME': outcome}
    real_run = wt.subprocess.run
    child = _bind_framework_callback(_callback_check_registered_guard_process_child, guard_source, real_run)
    real_import = builtins.__import__
    missing_parent_dependency = _bind_framework_callback(_callback_check_registered_guard_process_missing_parent_dependency, real_import)
    with patch.object(wt.python_env, 'runtime', return_value=(Path(sys.executable), environment)) as runtime, \
         patch.object(wt.python_env, 'setup', side_effect=AssertionError('no setup')), \
         patch.object(wt.subprocess, 'run', side_effect=child), \
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


def _callback_check_prepare_rejects_before_git_write_guard(changed, head, index, source, task, violation, /, *args):
    if violation == 'guard':
        raise wt.Blocked('guard rejected')
    if violation == 'task-after':
        task.write_text(task.read_text() + '\nchanged task')
    if violation == 'bytes-after':
        source.write_text('changed during guard')
    if violation == 'head-after':
        head[0] = 'unexpected'
    if violation == 'paths-after':
        changed.add('foreign.txt')
    if violation == 'index-after':
        index[0] = 'changed index'


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
    if violation == 'head':
        head[0] = 'unexpected'
    if violation == 'unverified':
        state['commit'] = 'tip'
    if violation == 'committed-dirty':
        state.update(commit='tip', verified=True)
    if violation == 'scope':
        changed.add('foreign.txt')
    guard = _bind_framework_callback(_callback_check_prepare_rejects_before_git_write_guard, changed, head, index, source, task, violation)
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


@pytest.mark.parametrize('directory', ['plain', 'space 日本語', 'line\nbreak'])
@pytest.mark.parametrize('linked', [False, True])
def check_idle_git_paths_and_state(tmp_path, directory, linked):
    root = tmp_path / directory
    root.mkdir()
    wt.git(root, 'init', '-q')
    wt.git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
           'commit', '--allow-empty', '-qm', 'initial')
    if linked:
        target = tmp_path / ('linked ' + directory)
        wt.git(root, 'worktree', 'add', '-qb', 'linked', target)
        root = target
    names = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD',
             'rebase-merge', 'rebase-apply', 'sequencer')
    markers = [Path(wt.output(root, 'rev-parse', '--path-format=absolute', '--git-path', name))
               for name in names]
    with patch.object(wt, 'git', wraps=wt.git) as calls:
        wt.idle_git(root)
        assert calls.call_count == (8 if '\n' in directory else 2)
    for name, marker in zip(names, markers, strict=False):
        marker.write_text('marker', encoding='utf-8')
        with pytest.raises(wt.Blocked) as caught:
            wt.idle_git(root)
        assert str(caught.value) == f'unfinished Git operation: {name}; worktree retained'
        marker.unlink()
        wt.idle_git(root)
    for marker in markers:
        marker.write_text('marker', encoding='utf-8')
    for name, marker in zip(names, markers, strict=False):
        with pytest.raises(wt.Blocked) as caught:
            wt.idle_git(root)
        assert str(caught.value) == f'unfinished Git operation: {name}; worktree retained'
        marker.unlink()
    # A real unmerged index, independent of operation markers.
    (root / 'conflict.txt').write_text('conflict\n', encoding='utf-8')
    blob = wt.output(root, 'hash-object', '-w', 'conflict.txt')
    index = ''.join(f'100644 {blob} {stage}\tconflict.txt\n' for stage in (1, 2, 3))
    subprocess.run(['git', 'update-index', '--index-info'], cwd=root,
                   input=index, encoding='utf-8', check=True)
    with pytest.raises(wt.Blocked, match='^unresolved index conflicts; worktree retained$'):
        wt.idle_git(root)
    markers[0].write_text('marker', encoding='utf-8')
    with pytest.raises(wt.Blocked, match='^unfinished Git operation: MERGE_HEAD; worktree retained$'):
        wt.idle_git(root)
    markers[0].unlink()
    wt.git(root, 'read-tree', 'HEAD')
    wt.idle_git(root)


def _callback_check_repin_rejects_before_state_write_output(base, candidate, latest, violation, /, root, *args):
    if args[0] == 'rev-parse':
        return ('0' * 40 if violation == 'base' else latest) if root == base else candidate
    if args[1] == '--count':
        return '2' if violation == 'count' else '1'
    return 'a merge' if violation == 'merge' else ''


@pytest.mark.parametrize('violation', ['dirty', 'suspend', 'count', 'merge', 'scope', 'history',
                                       'head', 'base', 'unverified', 'type', 'receipt', 'descendant'])
def check_repin_rejects_before_state_write(tmp_path, violation):
    old, latest, candidate = '1' * 40, '2' * 40, '3' * 40
    task = 'tasks/example.md'
    text = contract('example', ['file.txt'])
    if violation == 'suspend':
        text = text.replace('`running`', '`suspend`') + '\n## Suspension reason\nfixture\n'
    if violation == 'type':
        text = text.replace('`governance`', '`migration`')
    (tmp_path / 'tasks').mkdir()
    (tmp_path / task).write_text(text, encoding='utf-8')
    state = dict(task_file=task, merged=None, verified=violation != 'unverified',
                 recovery=dict(commit='4' * 40, base=old, count='1'))
    if violation == 'receipt':
        del state['recovery']
    original = copy.deepcopy(state)
    base = tmp_path / 'base'

    output = _bind_framework_callback(_callback_check_repin_rejects_before_state_write_output, base, candidate, latest, violation)

    with patch.object(wt, 'load', return_value=(tmp_path, None, tmp_path / 'state.json', state)), \
         patch.object(wt, 'lifecycle_lock', return_value=nullcontext()), \
         patch.object(wt, 'task_worktree', return_value=tmp_path), \
         patch.object(wt, 'base_worktree', return_value=base), \
         patch.object(wt, 'output', side_effect=output), \
         patch.object(wt, 'git', side_effect=lambda root, *args, **kwargs: SimpleNamespace(
             returncode=int(violation == 'history' and args[-1] == candidate or
                            violation == 'descendant' and args[-1] == latest))), \
         patch.object(wt, 'changed_paths', return_value={'file.txt'} if violation == 'dirty' else set()), \
         patch.object(wt, 'paths', return_value={'outside.txt'} if violation == 'scope' else {'file.txt'}), \
         patch.object(wt, 'save') as save:
        with pytest.raises(wt.Blocked):
            wt.recover(tmp_path, 'example', '0' * 40 if violation == 'head' else candidate, latest, repin=True)
        save.assert_not_called()
    assert state == original


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
