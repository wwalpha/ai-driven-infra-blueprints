"""Read shared worktree identity and lifecycle state without Python setup dependencies."""

import json
import os
import re
import subprocess
from pathlib import Path


class Blocked(ValueError):
    pass

def git(root, *args, check=True):
    # Never route commands through an inherited worktree/private index or prompt.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_SEQUENCE_EDITOR="true")
    result = subprocess.run(["git", *map(str, args)], cwd=root, env=environment,
                            capture_output=True, encoding="utf-8")
    if check and result.returncode:
        raise Blocked(f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result

def output(root, *args, runner=None):
    runner = runner or git
    return runner(root, *args).stdout.strip()

def worktrees(root):
    records = []
    for block in git(root, "worktree", "list", "--porcelain", "-z").stdout.split("\0\0"):
        if block:
            records.append(dict(line.partition(" ")[::2] for line in block.split("\0") if line))
    return records

def repository(where):
    root = Path(output(where, "rev-parse", "--show-toplevel")).resolve()
    if output(root, "rev-parse", "--is-bare-repository") != "false":
        raise Blocked("a non-bare Git repository is required")
    common = Path(output(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    records = worktrees(root)
    primary = Path(records[0]["worktree"]).resolve()
    if not primary.is_dir() or "prunable" in records[0]:
        raise Blocked("primary worktree is missing or stale")
    return root, common, primary

def metadata_directory(primary):
    directory = primary / ".worktrees" / ".blueprint"
    for path in (directory.parent, directory, directory / "tasks"):
        if path.is_symlink():
            raise Blocked(f"worktree metadata must not use symlinks: {path}")
    return directory

def state_path(primary, task_id):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", task_id):
        raise Blocked("task-id must use the existing lower-kebab-case task naming rule")
    return metadata_directory(primary) / "tasks" / f"{task_id}.json"

def load(where, task_id):
    root, common, primary = repository(where)
    path = state_path(primary, task_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    if (state["task_id"] != task_id or state["branch"] != f"codex/worktree/{task_id}"
            or state["task_file"] != f"tasks/{task_id}.md" or state["primary"] != str(primary)
            or Path(state["worktree"]) != primary / ".worktrees" / task_id):
        raise Blocked("task lifecycle state does not match this repository")
    # Cleanup can remove the caller's checkout; control Git from a surviving root.
    return primary, common, path, state


def paths(root, *args, runner=None):
    runner = runner or git
    return set(runner(root, *args).stdout.rstrip("\0").split("\0")) - {""}

def task_start_commit(root, task_file):
    """Return the existing managed baseline, failing closed on invalid lifecycle state."""
    _, _, primary = repository(root)
    path = state_path(primary, Path(task_file).stem)
    managed = root.resolve().parent == primary / '.worktrees'
    if not path.exists():
        if managed:
            raise Blocked('managed worktree task lifecycle state missing')
        return None
    _, _, _, state = load(root, Path(task_file).stem)
    if Path(state['worktree']).resolve() != root.resolve():
        if managed:
            raise Blocked('selected task lifecycle belongs to another worktree')
        return None
    if state['task_file'] != task_file:
        raise Blocked('selected task does not match managed task_file')
    task_worktree(root, state)
    start = output(root, 'rev-parse', '--verify', state.get('validation_base', state['start']) + '^{commit}')
    if git(root, 'merge-base', '--is-ancestor', start, 'HEAD', check=False).returncode:
        raise Blocked('task lifecycle start is not an ancestor of HEAD')
    return start

def committed_task_paths(root, task_file):
    """Committed changes since Task start; retain IMPORT/finalize caller semantics."""
    start = task_start_commit(root, task_file)
    return None if start is None else paths(root, 'diff', '--no-renames', '--name-only', '-z', start, 'HEAD')

def idle_git(root, *, runner=None):
    names = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")
    arguments = [argument for name in names for argument in ("--git-path", name)]
    resolved = output(root, "rev-parse", "--path-format=absolute", *arguments, runner=runner).splitlines()
    # Newlines in a Git directory make the batched output ambiguous.
    if len(resolved) != len(names):
        resolved = [output(root, "rev-parse", "--path-format=absolute", "--git-path", name, runner=runner)
                    for name in names]
    for name, value in zip(names, resolved, strict=False):
        path = Path(value)
        if path.exists():
            raise Blocked(f"unfinished Git operation: {name}; worktree retained")
    if paths(root, "diff", "--name-only", "--diff-filter=U", "-z", runner=runner):
        raise Blocked("unresolved index conflicts; worktree retained")

def changed_paths(root):
    return (paths(root, "diff", "--no-renames", "--name-only", "-z")
            | paths(root, "diff", "--cached", "--no-renames", "--name-only", "-z")
            | paths(root, "ls-files", "--others", "--exclude-standard", "-z"))

def task_worktree(root, state):
    target = Path(state["worktree"])
    entries = [entry for entry in worktrees(root) if Path(entry["worktree"]).resolve() == target]
    if (len(entries) != 1 or "locked" in entries[0] or "prunable" in entries[0]
            or entries[0].get("branch") != f"refs/heads/{state['branch']}"
            or not target.is_dir()):
        raise Blocked("task worktree missing, locked, stale or switched; retain it for review")
    idle_git(target)
    return target


def subprocess_bytes(root, revision, relative):
    result = subprocess.run(['git', 'show', revision + ':' + relative], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError('recorded IaC blob missing')
    return result.stdout
