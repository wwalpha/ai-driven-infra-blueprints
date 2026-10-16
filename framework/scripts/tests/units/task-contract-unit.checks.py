#!/usr/bin/env python3
"""Managed authority and invalidation with synthetic metadata; no Git or AWS calls."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

import json
import os
from unittest.mock import patch
import pytest
from support.pytest_cli import run
from support.worktree_task_fixtures import contract
import task_contract as tasks
import worktree_task as wt

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


@pytest.fixture
def managed(tmp_path, monkeypatch):
    primary = tmp_path / 'repository'
    root = primary / '.worktrees' / 'example'
    root.mkdir(parents=True)
    common = primary / '.git'
    gitdir = common / 'worktrees' / 'example'
    gitdir.mkdir(parents=True)
    (root / '.git').write_text(f'gitdir: {gitdir}\n')
    (gitdir / 'HEAD').write_text('ref: refs/heads/codex/worktree/example\n')
    identity = tasks.directory_identity(gitdir)
    state = dict(task_id='example', branch='codex/worktree/example', worktree=str(root),
                 primary=str(primary), task_file='tasks/example.md', identity=identity,
                 base='main', start='a' * 40, tip='a' * 40, commit=None, verified=False, merged=None)
    metadata = wt.state_path(primary, 'example')
    metadata.parent.mkdir(parents=True)
    wt.save(metadata, state)
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    monkeypatch.setattr(tasks, '_managed_cache', None)
    monkeypatch.setattr(tasks, 'worktree_identity', lambda path: identity if path == root else tasks.directory_identity(path))
    monkeypatch.setattr(wt, 'repository', lambda where: (where, common, primary))
    monkeypatch.setattr(wt, 'worktrees', lambda where: [dict(worktree=str(root), branch='refs/heads/' + state['branch'])])
    monkeypatch.setattr(wt, 'idle_git', lambda where: None)
    monkeypatch.setattr(wt, 'output', lambda where, *args: str(gitdir))
    with patch.object(tasks.subprocess, 'run', side_effect=AssertionError('UT must not spawn Git')):
        yield root, state, metadata, gitdir


def register(managed):
    root, state, _, _ = managed
    tasks.start(root, state['task_file'], contract('example', ['file.txt', 'nested/second.txt']))
    return root, state['task_file']


def check_managed_lifecycle_and_hot_path(managed):
    with patch.object(tasks, 'reservations', side_effect=AssertionError('managed conflict calculation')):
        root = managed[0]
        assert tasks.task_path(root) == root / 'tasks/active.md'
        tasks.require_writable(root, [root / 'file.txt'])
        assert list(tasks.reserved_batches(root, {'free': [root / 'file.txt']})) == ['free']
        root, name = register(managed)
        tasks.require_writable(root, [root / 'file.txt'], name)
        with patch.object(tasks, 'contracts', side_effect=AssertionError('hot contract scan')), \
                patch.object(wt, 'managed_state', side_effect=AssertionError('hot lifecycle/Git validation')), \
                patch.object(tasks.time, 'sleep', side_effect=AssertionError('managed wait')):
            for index in range(20):
                tasks.require_writable(root, [root / 'file.txt'], name)
                tasks.atomic_files({root / 'file.txt': f'publication {index}\n'}, staging_directory=root)
            tasks.require_writable(root, [root / 'file.txt'], name)
            assert tasks.task_path(root) == root / name
            assert list(tasks.reserved_batches(root, {'atomic': [root / 'file.txt', root / 'nested/second.txt']}, task_file=name)) == ['atomic']
            assert tasks.wait_deferred(root, name) == set()
        assert tasks.task_changes(root, {'file.txt'}, name) == {'file.txt'}
        with pytest.raises(ValueError, match='no task reservation'):
            tasks.task_changes(root, {'outside.txt'}, name)
        tasks.suspend(root, name, 'unit check: file.txt')
        with pytest.raises(ValueError, match='suspend'):
            tasks.require_writable(root, [root / 'file.txt'], name)
        tasks.resume(root, name)
        tasks.refresh(root, name)
        tasks.require_writable(root, [root / 'file.txt'], name)
        tasks.complete(root, name)
        with pytest.raises(ValueError, match='completed'):
            tasks.require_writable(root, [root / 'file.txt'], name)
        assert wt.integration_task(root, managed[1]).active == {name, 'file.txt', 'nested/second.txt'}
        from validation.task import TaskValidation
        from types import SimpleNamespace
        errors = []
        findings = SimpleNamespace(check=lambda valid, message: errors.append(message) if not valid else None,
                                   relative=lambda path: path.relative_to(root).as_posix())
        with patch.object(tasks, 'contracts', side_effect=AssertionError('cached validation contract scan')):
            TaskValidation(root, findings).check_tasks()
            assert wt.integration_task(root, managed[1]).state == 'completed'
        assert not errors


@pytest.mark.parametrize('change', ['status', 'allowed', 'scope', 'replace', 'second-task', 'foreign-owner', 'metadata', 'HEAD', 'removed-metadata'])
def check_external_changes_invalidate(managed, change):
    root, name = register(managed)
    tasks.require_writable(root, [root / 'file.txt'], name)
    path = root / name
    if change == 'status':
        path.write_text(tasks.set_status(path.read_text(), 'completed'))
    elif change == 'allowed':
        text = path.read_text().replace('## Allowed paths\n- `tasks/example.md`\n- `file.txt`', '## Allowed paths\n- `tasks/example.md`')
        path.write_text(text)
    elif change == 'scope':
        path.write_text(path.read_text().replace('file.txt', 'new-file.txt'))
    elif change == 'replace':
        # Same-size replacement with restored mtime still changes inode/ctime.
        before = path.stat()
        replacement = path.with_suffix('.replacement')
        replacement.write_text(path.read_text().replace('file.txt', 'gone.txt'))
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(path)
    elif change == 'second-task':
        (root / 'tasks/other.md').write_text(contract('other', ['file.txt']))
    elif change == 'foreign-owner':
        path.write_text(path.read_text().replace(managed[1]['identity'], 'b' * 64))
    elif change == 'metadata':
        state = dict(managed[1], task_file='tasks/wrong.md')
        wt.save(managed[2], state)
    elif change == 'HEAD':
        (managed[3] / 'HEAD').write_text('ref: refs/heads/switched\n')
    else:
        managed[2].unlink()
    with pytest.raises(ValueError):
        tasks.require_writable(root, [root / 'file.txt'], name)


def check_scope_expansion_requires_refresh(managed):
    root, name = register(managed)
    path = root / name
    text = path.read_text()
    for heading in ('Modified files', 'Allowed paths'):
        text = text.replace(f'## {heading}\n', f'## {heading}\n- `new.txt`\n')
    path.write_text(text)
    with pytest.raises(ValueError, match='explicit refresh'):
        tasks.require_writable(root, [root / 'new.txt'], name)
    with pytest.raises(ValueError, match='explicit refresh'):
        list(tasks.reserved_batches(root, {'atomic': [root / 'file.txt', root / 'new.txt']}, task_file=name))
    with patch.object(tasks, 'reservations', side_effect=AssertionError('refresh must not calculate conflicts')):
        tasks.refresh(root, name)
        tasks.require_writable(root, [root / 'new.txt'], name)


def check_path_and_selection_guards(managed):
    root, name = register(managed)
    for relative in ('outside.txt', '../escape', '.git/config'):
        with pytest.raises(ValueError):
            tasks.require_writable(root, [root / relative], name)
    with pytest.raises(ValueError, match='task_file'):
        tasks.require_writable(root, [root / 'file.txt'], 'tasks/other.md')
    outside = root.parent / 'outside'
    outside.mkdir()
    (root / 'nested').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        tasks.require_writable(root, [root / 'nested/second.txt'], name)


@pytest.mark.parametrize('field', ['task_id', 'task_file', 'branch', 'worktree', 'identity', 'primary'])
def check_metadata_mismatch(managed, field):
    root, name = register(managed)
    record = json.loads(managed[2].read_text())
    record[field] = 'wrong'
    wt.save(managed[2], record)
    with pytest.raises(ValueError):
        tasks.require_writable(root, [root / 'file.txt'], name)


def check_contract_free_and_normal_reservations(tmp_path, monkeypatch):
    monkeypatch.delenv(tasks.SELECTOR, raising=False)
    tasks.require_writable(tmp_path, [tmp_path / 'free.txt'])
    first, second = 'tasks/first.md', 'tasks/second.md'
    tasks.start(tmp_path, first, contract('first', ['file.txt']))
    tasks.start(tmp_path, second, contract('second', ['file.txt', 'second.txt']))
    with pytest.raises(tasks.DeferredWrite):
        tasks.require_writable(tmp_path, [tmp_path / 'file.txt'], second)
    tasks.require_writable(tmp_path, [tmp_path / 'second.txt'], second)
    tasks.complete(tmp_path, first)
    tasks.refresh(tmp_path, second)
    tasks.require_writable(tmp_path, [tmp_path / 'file.txt'], second)


if __name__ == '__main__':
    raise SystemExit(run(__file__))
