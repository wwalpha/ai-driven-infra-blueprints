"""Git/Worktree state acquisition. Import decisions remain in their guarded callers."""
from pathlib import Path
import subprocess


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
    from worktree_task import task_start_commit as start
    return start(root, name)


def changed_paths(root, *, task_file=None):
    from task_contract import contracts, contract_path, task_path
    from worktree_task import changed_paths, committed_task_paths
    changed = changed_paths(root)
    if contracts(root):
        path = contract_path(root, selected=task_file) if task_file is not None else task_path(root, required=False)
        if path is not None:
            changed |= committed_task_paths(root, path.relative_to(root).as_posix()) or set()
    return changed


def task_state(root, name):
    from worktree_task import load
    return load(root, Path(name).stem)[3]


def task_worktree(root, state):
    from worktree_task import task_worktree
    return task_worktree(root, state)


def task_head(root):
    from worktree_task import output
    return output(root, 'rev-parse', 'HEAD')
