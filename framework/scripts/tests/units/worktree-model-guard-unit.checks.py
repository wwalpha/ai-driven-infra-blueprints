#!/usr/bin/env python3
"""Managed ownership, Task baseline and pre-integration rejection only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import task_contract_core as tasks
import worktree_state
import worktree_task as wt
from issue_gate import require_no_issues
from support.import_model_fixtures import operation_contract
from support.repository_fixtures import contract as repository_contract
from support.resource_delete_fixtures import contract, fixture
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation.findings import Findings
from validation.task import TaskValidation

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

@pytest.mark.parametrize('problem', ['none', 'task', 'root', 'merged', 'owner'])
def check_ownership(tmp_path, problem):
    name = 'tasks/example.md'
    state = {'task_file': name, 'worktree': str(tmp_path), 'merged': None}
    owner = tmp_path
    if problem == 'task':
        state['task_file'] = 'tasks/other.md'
    elif problem == 'root':
        state['worktree'] = str(tmp_path / 'other')
    elif problem == 'merged':
        state['merged'] = 'commit'
    elif problem == 'owner':
        owner = tmp_path / 'other'
    with patch.object(worktree_state, 'load', return_value=(None, None, None, state)), patch.object(worktree_state, 'task_worktree', return_value=owner):
        if problem == 'none':
            assert worktree_state.managed_task_state(tmp_path, name) is state
        else:
            with pytest.raises(ValueError):
                worktree_state.managed_task_state(tmp_path, name)


def check_finalize_rejects_incomplete_leaves(tmp_path):
    sources = fixture(tmp_path)
    name = 'tasks/parent.md'
    (tmp_path / 'tasks').mkdir()
    (tmp_path / name).write_text(contract(sources) + '## Validation scope\n- `stg/cde/service-a`\n' +
        f'## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n')
    state = {'task_file': name, 'python_setup': {'status': 'ready'}, 'merged': None}
    with patch.object(wt, 'load', return_value=(tmp_path, None, tmp_path / 'state.json', state)), \
         patch.object(wt, 'lifecycle_lock', return_value=nullcontext()), patch.object(wt, 'task_worktree', return_value=tmp_path), \
         patch.object(wt, '_prepare_commit', side_effect=AssertionError('incomplete leaves cannot commit')):
        with pytest.raises(wt.Blocked, match='leaves incomplete'):
            wt.prepare_integration(tmp_path, 'parent')


def check_model_finalize_cannot_bypass_candidate(tmp_path):
    state = {'task_file': 'tasks/retarget.md', 'task_id': 'retarget'}
    task = tmp_path / state['task_file']
    task.parent.mkdir()
    task.write_text('- Model operation: `import-retarget`\n')
    with patch.object(wt, 'changed_paths', return_value=set()), \
         patch.object(wt, 'committed_task_paths', return_value=set()), \
         patch.object(wt.tasks, 'model_operation', return_value=SimpleNamespace(action='import-retarget')):
        with pytest.raises(wt.Blocked, match='successful final candidate'):
            wt._prepare_commit(tmp_path, tmp_path / 'unused-state.json', state, tmp_path, 'approval cannot bypass')


def _callback_check_git_baseline_fail_closed_task(tmp_path, /):
    return TaskValidation(tmp_path, Findings(tmp_path))


def _callback_check_git_baseline_fail_closed_git(root, *args, **kwargs):
    return SimpleNamespace(returncode=1 if args[0] == 'show-ref' else 128, stdout='', stderr='missing HEAD')


def check_git_baseline_fail_closed(tmp_path):

    (tmp_path / 'tasks').mkdir()
    (tmp_path / 'tasks/example.md').write_text(repository_contract('example', ['file.txt']))
    task = _bind_framework_callback(_callback_check_git_baseline_fail_closed_task, tmp_path)
    with patch('model.importing.repository.task_start_commit', return_value='task-start'), \
         patch('worktree_state.git', side_effect=AssertionError('managed fallback to HEAD')):
        current = task()
        current.fix_baseline()
        assert current.baseline == 'task-start'
    git = _callback_check_git_baseline_fail_closed_git
    with patch('model.importing.repository.task_start_commit', return_value=None), \
         patch('worktree_state.output', return_value='refs/heads/new'), patch('worktree_state.git', side_effect=git):
        current = task()
        current.fix_baseline()
        assert current.baseline_fixed and current.baseline is None
    with patch('model.importing.repository.task_start_commit', side_effect=ValueError('invalid managed state')), \
         pytest.raises(ValueError, match='invalid managed state'):
        task().fix_baseline()
    with patch('model.importing.repository.task_start_commit', return_value=None), \
         patch('worktree_state.output', side_effect=ValueError('broken Git')), \
         patch('worktree_state.git', side_effect=git), pytest.raises(ValueError, match='broken Git'):
        task().fix_baseline()


def check_issue_gate_rejects_foreign_managed_task(tmp_path):
    name = 'tasks/deletion.md'
    text = operation_contract('import-delete') + ('## Validation scope\n- `stg/cde/vpc`\n'
        f'## Modified files\n- `{name}`\n## Allowed paths\n- `{name}`\n')
    tasks.start(tmp_path, name, text)
    (tmp_path / '.git').mkdir()
    with patch.object(worktree_state, 'task_start_commit', side_effect=ValueError('selected task does not match managed task_file')):
        with pytest.raises(ValueError, match='managed task_file'):
            require_no_issues(tmp_path, {('stg', 'cde', 'vpc')}, task_file=name)


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
