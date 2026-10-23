"""Git/Worktree state acquisition. Import decisions remain in their guarded callers."""

import subprocess
from pathlib import Path

import worktree_state as _imports_worktree_state
from task_contract_core import contract_path, contracts, task_path


def has_baseline(root):
    return (root / '.git').exists()


def working_revision(root):
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=root, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        valid = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=root, capture_output=True)
        if valid.returncode:
            raise ValueError('cannot determine the versioned IMPORT baseline')
        return None  # Initial registration has no previous versioned configuration.
    return result.stdout.strip()


def task_start_commit(root, name):
    start = _imports_worktree_state.task_start_commit
    return start(root, name)


def changed_paths(root, *, task_file=None):
    changed_paths = _imports_worktree_state.changed_paths
    committed_task_paths = _imports_worktree_state.committed_task_paths
    changed = changed_paths(root)
    if contracts(root):
        path = contract_path(root, selected=task_file) if task_file is not None else task_path(root, required=False)
        if path is not None:
            changed |= committed_task_paths(root, path.relative_to(root).as_posix()) or set()
    return changed


def task_state(root, name):
    load = _imports_worktree_state.load
    return load(root, Path(name).stem)[3]


def task_worktree(root, state):
    task_worktree = _imports_worktree_state.task_worktree
    return task_worktree(root, state)


def task_head(root):
    output = _imports_worktree_state.output
    return output(root, 'rev-parse', 'HEAD')
