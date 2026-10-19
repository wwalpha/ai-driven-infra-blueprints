#!/usr/bin/env python3
"""Create and integrate isolated task worktrees; preserve work on every failure."""

import argparse
from dataclasses import dataclass
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess

import task_contract as tasks
import worktree_python as python_env


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


def output(root, *args):
    return git(root, *args).stdout.strip()


def paths(root, *args):
    return set(git(root, *args).stdout.rstrip("\0").split("\0")) - {""}


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


def branch_exists(root, branch):
    return git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def base_branch(root):
    # Only repository-local configuration counts; init.defaultBranch is not a base.
    explicit = git(root, "config", "--local", "--get", "blueprint.baseBranch", check=False).stdout.strip()
    remote = git(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    preferred = explicit or (remote.removeprefix("refs/remotes/origin/") if remote else "")
    if preferred:
        if not branch_exists(root, preferred):
            raise Blocked(f"configured base branch does not exist locally: {preferred}")
        return preferred
    for name in ("main", "master"):
        if branch_exists(root, name):
            return name
    raise Blocked("no configured base, main or master branch exists")


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


def save(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def lifecycle_lock(primary):
    # One short Git integration at a time; AWS locking remains separate.
    directory = metadata_directory(primary)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "lifecycle.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise Blocked(f"worktree lifecycle busy; retain work and retry: {lock}") from None
    try:
        yield
    finally:
        lock.rmdir()


def create(where, task_id):
    root, common, primary = repository(where)
    state_file = state_path(primary, task_id)
    branch = f"codex/worktree/{task_id}"
    target = primary / ".worktrees" / task_id
    if git(primary, "check-ignore", "--quiet", str(target), check=False).returncode:
        raise Blocked("/.worktrees/ must be ignored before creating nested worktrees")
    with lifecycle_lock(primary):
        base = base_branch(root)
        if state_file.exists() or branch_exists(root, branch):
            raise Blocked(f"task state/branch collision: {task_id}; nothing overwritten")
        if target.exists() or target.is_symlink() or target.parent.is_symlink():
            raise Blocked(f"worktree path collision: {target}; nothing overwritten")
        if any(Path(entry["worktree"]).resolve() == target for entry in worktrees(root)):
            raise Blocked(f"registered/stale worktree path collision: {target}; do not prune automatically")
        start = output(root, "rev-parse", f"refs/heads/{base}")
        git(root, "worktree", "add", "-b", branch, str(target), start)
        state = dict(task_id=task_id, branch=branch, worktree=str(target), primary=str(primary),
                     base=base, start=start, task_file=f"tasks/{task_id}.md",
                     tip=start, commit=None, verified=False, merged=None)
        state_file.parent.mkdir(exist_ok=True)
        save(state_file, state)
    return setup(where, task_id)


def setup(where, task_id):
    root, common, path, state = load(where, task_id)
    # Per-task setup serialization does not hold the common Git lifecycle mutex.
    lock = path.with_suffix(".setup-lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise Blocked("Python setup busy; retain work and retry") from None
    try:
        with lifecycle_lock(root):
            target = task_worktree(root, state)
            if state["merged"]:
                raise Blocked("merged worktree awaits cleanup; setup refused")
            previous = state.get("python_setup", {})
            state["python_setup"] = {"status": "setting-up"}
            save(path, state)
        try:
            state["python_setup"] = python_env.setup(target, previous)
        except (Exception, KeyboardInterrupt) as error:
            message = f"{type(error).__name__}: {str(error) or 'Python setup interrupted'}"
            state["python_setup"] = {"status": "failed", "error": message}
            save(path, state)
            raise Blocked(f"Python setup failed; worktree retained. Retry setup --task-id {task_id}: {message}") from error
        save(path, state)
        return state
    finally:
        lock.rmdir()


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


def idle_git(root):
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        path = Path(output(root, "rev-parse", "--path-format=absolute", "--git-path", name))
        if path.exists():
            raise Blocked(f"unfinished Git operation: {name}; worktree retained")
    if paths(root, "diff", "--name-only", "--diff-filter=U", "-z"):
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


def integration_task(target, state, approval=None):
    # A human-approved Git integration does not turn failed validation into completion.
    text = tasks.safe_path(target, state["task_file"]).read_text(encoding="utf-8")
    current = tasks.status(text)
    approval = approval or state.get("validation_failure_approval")
    expected = "suspend" if approval else "completed"
    if current != expected:
        raise Blocked(f"task must be {expected} for integration; current status: {current}")


def base_worktree(root, state):
    entries = [entry for entry in worktrees(root) if entry.get("branch") == f"refs/heads/{state['base']}"]
    if len(entries) != 1 or "locked" in entries[0] or "prunable" in entries[0]:
        raise Blocked("local base must be checked out in one available worktree; no automatic checkout")
    target = Path(entries[0]["worktree"])
    idle_git(target)
    if git(target, "status", "--porcelain", "--untracked-files=all").stdout:
        raise Blocked(f"base worktree is dirty: {target}; task commit/worktree retained")
    return target


def ancestor(root, commit, branch):
    return git(root, "merge-base", "--is-ancestor", commit, f"refs/heads/{branch}", check=False).returncode == 0


def cleanup_state(root, path, state):
    if not state["merged"] or not ancestor(root, state["merged"], state["base"]):
        raise Blocked("cleanup requires a verified successful merge")
    if state["commit"] and not ancestor(root, state["commit"], state["base"]):
        raise Blocked("base no longer contains the task commit; cleanup refused")
    target = Path(state["worktree"])
    if target.exists() or any(Path(e["worktree"]).resolve() == target for e in worktrees(root)):
        target = task_worktree(root, state)
        integration_task(target, state)
        if output(target, "rev-parse", "HEAD") != state["tip"]:
            raise Blocked("task HEAD changed since merge; cleanup refused")
        if changed_paths(target):
            raise Blocked("task worktree is dirty; cleanup refused")
        if path.with_suffix(".setup-lock").exists():
            raise Blocked("Python setup busy; cleanup refused")
        managed_venv = python_env.venv_directory(target)
        # Preserve user artifacts before removing the owned environment or checkout.
        ignored = paths(target, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
        extras = {p for p in ignored if p != state["task_file"]
                  and not (managed_venv.exists() and Path(p).parts[0] == ".venv")
                  and not ("__pycache__" in Path(p).parts and p.endswith(".pyc"))}
        if extras:
            raise Blocked("ignored files need preservation before cleanup: " + ", ".join(sorted(extras)))
        python_env.remove(target)
        git(root, "worktree", "remove", str(target))
    if branch_exists(root, state["branch"]):
        tip = output(root, "rev-parse", f"refs/heads/{state['branch']}")
        if tip != state["tip"] or not ancestor(root, tip, state["base"]):
            raise Blocked("temporary branch changed or is unmerged; cleanup refused")
        # -d checks against HEAD when no upstream exists. Use the verified base worktree.
        git(base_worktree(root, state), "branch", "-d", state["branch"])
    from import_guard import discard_import_proof
    discard_import_proof(target, state['task_file'])
    path.unlink()
    return {**state, "cleaned": True}


def cleanup(where, task_id):
    root, common, path, state = load(where, task_id)
    with lifecycle_lock(root):
        return cleanup_state(root, path, state)


def _prepare_commit(root, path, state, target, approval):
    changed = changed_paths(target)
    task_id = state['task_id']
    text = (target / state['task_file']).read_text(encoding='utf-8')
    tasks.validate_contract(target, state['task_file'], text)
    declared = tasks.paths_in(text, '## Modified files')
    allowed = tasks.paths_in(text, '## Allowed paths')
    if changed - declared or any(not any(tasks.matches(p, pattern) for pattern in allowed) for p in changed):
        raise Blocked('integration changes are outside the exact task contract')
    model_changes = changed | (committed_task_paths(target, state['task_file']) or set())
    contract = (target / state['task_file']).read_text(encoding='utf-8')
    operation = tasks.final_model_task(contract)
    if approval and tasks.model_refactor(contract) is not None:
        raise Blocked('Model refactor integration requires successful final candidate validation')
    if not operation and ('- Workflow: `import`' in tasks.section(contract, '## Task contract') or any(p.startswith('model/') or p == 'project.json' for p in model_changes)):
        from import_guard import require_import_changes
        previous = os.environ.get(tasks.SELECTOR)
        try:
            os.environ[tasks.SELECTOR] = state['task_file']
            require_import_changes(target)
        finally:
            if previous is None:
                os.environ.pop(tasks.SELECTOR, None)
            else:
                os.environ[tasks.SELECTOR] = previous
        changed = changed_paths(target)  # Valid legacy receipts may have migrated.
    if any(p.startswith("tasks/") for p in changed):
        raise Blocked("contracts must remain ignored; nothing committed")
    head = output(target, "rev-parse", "HEAD")
    if head != state["tip"]:
        raise Blocked("unexpected commits on task branch; review required")
    if state["commit"] and not state["verified"]:
        raise Blocked("task commit verification failed; review required before any retry")
    if state["commit"] and changed:
        raise Blocked("task changed after commit; rerun its workflow before integration")
    if approval:
        state["validation_failure_approval"] = approval
    if changed:
        whitespace = git(target, "config", "--get", "core.whitespace", check=False)
        if whitespace.returncode not in (0, 1):
            raise Blocked("cannot determine Git whitespace checks")
        rules = whitespace.stdout.strip() or "blank-at-eol,blank-at-eof,space-before-tab"
        diff_check = ("-c", "core.whitespace=" + rules + ",cr-at-eol", "diff")
        git(target, *diff_check, "--check", check=not approval)
        git(target, *diff_check, "--cached", "--check", check=not approval)
        literal = [f":(top,literal){p}" for p in sorted(changed)]
        git(target, "add", "--", *literal)
        # Staged edits canceled by working-tree edits are an effective zero-change task.
        changed = paths(target, "diff", "--cached", "--no-renames", "--name-only", "-z")
    if changed:
        tree = output(target, "write-tree")
        message = (f"task({task_id}): human-approved validation failure" if approval
                   else f"task({task_id}): Model operation candidate" if operation
                   else f"task({task_id}): completed task")
        git(target, "commit", "-m", message, *(["-m", approval] if approval else []))
        state["commit"] = output(target, "rev-parse", "HEAD")
        state["tip"] = state["commit"]
        save(path, state)  # Preserve the task commit before touching the latest base.
        if output(target, "rev-parse", "HEAD^") != head or output(target, "rev-parse", "HEAD^{tree}") != tree or paths(
                target, "diff", "--no-renames", "--name-only", "-z", head, "HEAD") != changed:
            raise Blocked("commit differs from the task changes; review required")
        state["verified"] = True
        save(path, state)
    if changed_paths(target):
        raise Blocked("task worktree changed during commit; review required")
    base = base_worktree(root, state)
    latest = output(root, "rev-parse", f"refs/heads/{state['base']}")
    # Do not replay unexpected history if the base was rewritten after creation.
    if not ancestor(root, state["start"], state["base"]):
        raise Blocked("base history was rewritten; task retained for review")
    result = git(target, "-c", "rebase.updateRefs=false", "rebase", "--no-autostash", latest, check=False)
    if result.returncode:
        git(target, "rebase", "--abort")
        raise Blocked("rebase failed and was aborted; human review required: " + result.stderr.strip())
    state["tip"] = output(target, "rev-parse", "HEAD")
    if state["commit"]:
        state["commit"] = state["tip"]
    save(path, state)
    if changed_paths(target):
        raise Blocked("task worktree changed during rebase; review required")
    base = base_worktree(root, state)  # Recheck dirty/operation state immediately before merge.
    if output(base, "rev-parse", "HEAD") != latest:
        raise Blocked("base advanced during rebase; retry finalize with latest local base")
    return latest


def recover(where, task_id, expected_commit, expected_base, finish=False):
    """Explicit reviewed recovery; pin old task/base and never merge or validate."""
    root, _, path, state = load(where, task_id)
    with lifecycle_lock(root):
        target = task_worktree(root, state)
        base = base_worktree(root, state)
        if not all(re.fullmatch(r"[0-9a-f]{40}", value or "") for value in (expected_commit, expected_base)):
            raise Blocked("recovery requires full expected commit/base hashes")
        if state['merged'] or state.get('validation_failure_approval') or not state['verified']:
            raise Blocked("recovery requires an unmerged verified task without failure approval")
        if output(base, 'rev-parse', 'HEAD') != expected_base:
            raise Blocked("recovery base changed")
        text = (target / state['task_file']).read_text(encoding='utf-8')
        tasks.validate_contract(target, state['task_file'], text)
        if '- Task type: `governance`' not in tasks.section(text, '## Task contract'):
            raise Blocked("reviewed recovery is limited to governance tasks")
        if finish:
            recovery = state.get('recovery')
            if not recovery or (recovery['commit'], recovery['base']) != (expected_commit, expected_base):
                raise Blocked("recovery receipt does not match expected commit/base")
            head = output(target, 'rev-parse', 'HEAD')
            if (changed_paths(target) or tasks.status(text) != 'running' or
                    git(target, 'merge-base', '--is-ancestor', expected_base, head, check=False).returncode != 0 or
                    output(target, 'rev-list', '--count', expected_base + '..' + head) != recovery['count'] or
                    output(target, 'rev-list', '--merges', expected_base + '..' + head)):
                raise Blocked("recovery candidate is dirty, unfinished or has unexpected history")
            changed = paths(target, 'diff', '--name-only', '--no-renames', '-z', expected_base, head)
            declared = tasks.paths_in(text, '## Modified files')
            allowed = tasks.paths_in(text, '## Allowed paths')
            if changed - declared or any(not any(tasks.matches(p, pattern) for pattern in allowed) for p in changed):
                raise Blocked("recovery candidate is outside the exact task contract")
            state.update(tip=head, commit=head, verified=True, validation_base=expected_base)
            del state['recovery']
            save(path, state)
            return state
        if state.get('recovery') or state['commit'] != expected_commit or state['tip'] != expected_commit or output(target, 'rev-parse', 'HEAD') != expected_commit:
            raise Blocked("recovery task commit changed or recovery already started")
        if tasks.status(text) not in {'completed', 'running'}:
            raise Blocked("resume suspended tasks before recovery")
        if git(target, 'merge-base', '--is-ancestor', state['start'], expected_base, check=False).returncode:
            raise Blocked("recovery base history was rewritten")
        count = int(output(target, 'rev-list', '--count', expected_base + '..' + expected_commit))
        changed = bool(changed_paths(target))
        state['recovery'] = dict(commit=expected_commit, base=expected_base, count=str(count + changed))
        tasks.atomic_files({target / state['task_file']: tasks.set_status(text, 'running')}, staging_directory=target)
        # Permit only this explicitly pinned correction commit; normal finalize guards stay closed.
        if changed:
            state['commit'] = None
        try:
            _prepare_commit(root, path, state, target, None)
        except Blocked as error:
            if str(error).startswith('rebase failed and was aborted'):
                save(path, state)
            raise
        return state


def finalize(where, task_id, human_approved_validation_failure=None):
    if human_approved_validation_failure is not None and not human_approved_validation_failure.strip():
        raise Blocked("human approval must identify the accepted validation failures")
    root, common, path, state = load(where, task_id)
    if state.get("recovery"):
        raise Blocked("finish reviewed recovery and rerun validation before finalize")
    if not state['merged'] and human_approved_validation_failure is None and not state.get('validation_failure_approval'):
        target = task_worktree(root, state)
        text = (target / state['task_file']).read_text(encoding='utf-8')
        if tasks.final_model_task(text):
            interpreter, environment = python_env.runtime(target)
            command = [str(interpreter), '-B', '-c',
                       'import sys; sys.path.insert(0, "framework/scripts"); '
                       'from worktree_task import _integrate_model; '
                       '_integrate_model(sys.argv[1], sys.argv[2])', str(root), task_id]
            result = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True, encoding='utf-8')
            if result.returncode:
                raise Blocked('Model final integration failed; worktree retained: ' + result.stderr.strip() + result.stdout.strip())
            # The surviving launcher owns cleanup, after the registered child exits.
            return cleanup(root, task_id)
    with lifecycle_lock(root):
        if path.with_suffix(".setup-lock").exists():
            raise Blocked("Python setup busy; integration refused")
        if state.get("python_setup", {}).get("status") != "ready":
            raise Blocked("Python setup is incomplete; retry setup before integration")
        if state["merged"]:
            return cleanup_state(root, path, state)
        target = task_worktree(root, state)
        approval = human_approved_validation_failure or state.get("validation_failure_approval")
        integration_task(target, state, approval)
        latest = _prepare_commit(root, path, state, target, approval)
        base = base_worktree(root, state)
        expected = output(target, "rev-parse", "HEAD")
        git(base, "merge", "--ff-only", "--no-autostash", state["branch"])
        if output(base, "rev-parse", "HEAD") != expected or not ancestor(root, expected, state["base"]):
            raise Blocked("merge result differs from expected task commit; retain worktrees for review")
        state["merged"] = expected
        save(path, state)
        return cleanup_state(root, path, state)



@dataclass(frozen=True)
class FinalCandidate:
    root: Path
    definitions_root: Path
    task_file: str
    task_text: str
    base_commit: str
    candidate_head: str
    changed_paths: frozenset[str]
    scope: frozenset[tuple[str, str, str]]


@dataclass(frozen=True)
class _ValidatedCandidate:
    candidate: FinalCandidate
    returncode: int


def prepare_integration(where: Path, task_id: str) -> FinalCandidate:
    """Commit/rebase a private Model-only candidate; never validate, complete or merge."""
    root, _, path, state = load(where, task_id)
    with lifecycle_lock(root):
        if path.with_suffix('.setup-lock').exists() or state.get('python_setup', {}).get('status') != 'ready' or state['merged']:
            raise Blocked('Model integration requires ready unmerged lifecycle state')
        target = task_worktree(root, state)
        text = (target / state['task_file']).read_text(encoding='utf-8')
        if not tasks.final_model_task(text) or tasks.status(text) not in {'running', 'completed'}:
            raise Blocked('Model integration requires a running/completed Model-only task')
        if tasks.section(text, '## Suspension reason'):
            raise Blocked('running/completed task has an unexpected suspension reason')
        latest = _prepare_commit(root, path, state, target, None)
        from validation_scope import active_scope
        scope = active_scope(target, task_file=state['task_file'])
        if scope is None:
            raise Blocked('Model final candidate requires explicit service scope')
        head = output(target, 'rev-parse', 'HEAD')
        return FinalCandidate(target, target, state['task_file'], text, latest, head,
                              frozenset(paths(target, 'diff', '--no-renames', '--name-only', '-z', latest, head)), frozenset(scope))


def validate_final_candidate(candidate: FinalCandidate) -> _ValidatedCandidate:
    """Run the existing read-only final loop once, without holding the lifecycle lock."""
    from validation.loop import run_loop
    from types import SimpleNamespace
    options = SimpleNamespace(mode='task', all=False, task_file=candidate.task_file,
        log_dir=None, profile=False, jobs=2, validation_jobs=4, fresh=True, write=False,
        staged=False, base=None, affected=False)
    if (changed_paths(candidate.root) or output(candidate.root, 'rev-parse', 'HEAD') != candidate.candidate_head or
            (candidate.root / candidate.task_file).read_text(encoding='utf-8') != candidate.task_text):
        raise Blocked('final candidate changed before validation')
    code = run_loop(candidate.root, options, final_candidate=candidate)
    return _ValidatedCandidate(candidate, code)


def merge_validated_candidate(result: _ValidatedCandidate) -> dict:
    """Consume a successful in-call validation, complete status and ff-only merge.

    Rechecks exact HEAD/base/clean state and the validated task body under the
    lifecycle lock. No rebase, regeneration, validation rerun or cleanup here.
    """
    if not isinstance(result, _ValidatedCandidate) or result.returncode:
        raise Blocked('final candidate validation failed; no merge')
    candidate = result.candidate
    root, _, path, state = load(candidate.root, Path(candidate.task_file).stem)
    with lifecycle_lock(root):
        target = task_worktree(root, state)
        base = base_worktree(root, state)
        if (target != candidate.root or changed_paths(target) or
            output(target, 'rev-parse', 'HEAD') != candidate.candidate_head or
            output(base, 'rev-parse', 'HEAD') != candidate.base_commit):
            raise Blocked('validated candidate/base changed; no merge')
        if paths(target, 'ls-files', '-z', 'tasks'):
            raise Blocked('contracts must remain ignored; no status commit')
        task_path = target / candidate.task_file
        text = task_path.read_text(encoding='utf-8')
        if text != candidate.task_text:
            raise Blocked('validated task contract changed; no merge')
        completed = tasks.set_status(text, 'completed') if tasks.status(text) == 'running' else text
        if text != completed:
            tasks.atomic_files({task_path: completed}, staging_directory=target)
        if task_path.read_text(encoding='utf-8') != completed or changed_paths(target) or output(target, 'rev-parse', 'HEAD') != candidate.candidate_head or output(base, 'rev-parse', 'HEAD') != candidate.base_commit:
            raise Blocked('validated state changed during task completion; no merge')
        git(base, 'merge', '--ff-only', '--no-autostash', state['branch'])
        if output(base, 'rev-parse', 'HEAD') != candidate.candidate_head or not ancestor(root, candidate.candidate_head, state['base']):
            raise Blocked('merge result differs from validated candidate')
        state['merged'] = candidate.candidate_head
        save(path, state)
        return state


def _integrate_model(where, task_id):
    """Internal registered-runtime composition; diagnostics remain outside CLI JSON."""
    import tempfile
    from contextlib import redirect_stdout, redirect_stderr
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='blueprint-model-integration-', suffix='.log', delete=False) as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                candidate = prepare_integration(Path(where), task_id)
                result = validate_final_candidate(candidate)
                merge_validated_candidate(result)
        except (OSError, ValueError, KeyError, TypeError) as error:
            _, _, _, state = load(Path(where), task_id)
            tasks.suspend(Path(state['worktree']), state['task_file'], str(error) + '; integration log: ' + log.name)
            raise Blocked(str(error) + '; integration log: ' + log.name) from error

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "setup", "finalize", "cleanup", "recover"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--human-approved-validation-failure", metavar="APPROVAL",
                        help="Finalize a suspended task only after explicit human approval of named validation failures")
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-base")
    parser.add_argument("--finish-recovery", action="store_true")
    args = parser.parse_args()
    if args.human_approved_validation_failure is not None and args.command != "finalize":
        parser.error("--human-approved-validation-failure is only valid with finalize")
    if args.command != "recover" and (args.expected_commit or args.expected_base or args.finish_recovery):
        parser.error("recovery arguments require recover")
    where = args.repository_root
    try:
        if args.command != "create":
            where = load(where, args.task_id)[0]  # Keep diagnostics usable after task checkout removal.
        state = (recover(where, args.task_id, args.expected_commit, args.expected_base, args.finish_recovery)
                 if args.command == "recover" else finalize(where, args.task_id, args.human_approved_validation_failure)
                 if args.command == "finalize" else globals()[args.command](where, args.task_id))
        print(json.dumps({"status": "ok", **state}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        retained = {}
        try:
            root, _, _, retained = load(where, args.task_id)
            retained = {**retained, "remaining_worktree": retained["worktree"] if Path(retained["worktree"]).exists() else None,
                        "remaining_branch": retained["branch"] if branch_exists(root, retained["branch"]) else None}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        print(json.dumps({**retained, "status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
