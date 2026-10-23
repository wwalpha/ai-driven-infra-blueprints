#!/usr/bin/env python3
"""Create and integrate isolated task worktrees; preserve work on every failure."""

import argparse
from dataclasses import dataclass
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import subprocess
import sys

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


def create(where, task_id, repair_request=None):
    root, common, primary = repository(where)
    state_file = state_path(primary, task_id)
    branch = f"codex/worktree/{task_id}"
    target = primary / ".worktrees" / task_id
    if git(primary, "check-ignore", "--quiet", str(target), check=False).returncode:
        raise Blocked("/.worktrees/ must be ignored before creating nested worktrees")
    transfer = deploy_request(where, repair_request) if repair_request else None
    request = transfer[-1] if transfer else None
    if request:
        parent = Path(request['repository'])
        if tasks.status((parent / request['taskFile']).read_text()) != 'suspend':
            raise Blocked('suspend the original deploy Task before child creation')
        session = transfer[-2]
        attempt = session['workflow']['attempts'][request['attemptId']]
        if attempt.get('childTask') not in (None, task_id):
            raise Blocked('attempt already owns another child; no static retry Task reset')
    repair_lock = nullcontext()
    if request:
        from deploy.handoff import locked
        repair_lock = locked(Path(request['session']))
    with lifecycle_lock(primary), repair_lock:
        base = request['parentBranch'] if request else base_branch(root)
        if state_file.exists() or branch_exists(root, branch):
            raise Blocked(f"task state/branch collision: {task_id}; nothing overwritten")
        if target.exists() or target.is_symlink() or target.parent.is_symlink():
            raise Blocked(f"worktree path collision: {target}; nothing overwritten")
        if any(Path(entry["worktree"]).resolve() == target for entry in worktrees(root)):
            raise Blocked(f"registered/stale worktree path collision: {target}; do not prune automatically")
        start = output(root, "rev-parse", f"refs/heads/{base}")
        if request and start != request['parentTip']:
            raise Blocked('repair parent tip changed')
        git(root, "worktree", "add", "-b", branch, str(target), start)
        state = dict(task_id=task_id, branch=branch, worktree=str(target), primary=str(primary),
                     base=base, start=start, task_file=f"tasks/{task_id}.md",
                     tip=start, commit=None, verified=False, merged=None)
        if request:
            state['deployRepair'] = request['requestPath']
            attempt['childTask'] = task_id
            from deploy.handoff import save as save_session
            save_session(Path(request['session']), session)
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
    names = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")
    arguments = [argument for name in names for argument in ("--git-path", name)]
    resolved = output(root, "rev-parse", "--path-format=absolute", *arguments).splitlines()
    # Newlines in a Git directory make the batched output ambiguous.
    if len(resolved) != len(names):
        resolved = [output(root, "rev-parse", "--path-format=absolute", "--git-path", name)
                    for name in names]
    for name, value in zip(names, resolved):
        path = Path(value)
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
    selected = tasks.contract_path(target, selected=state["task_file"])
    task_start_commit(target, state["task_file"])
    text = selected.read_text(encoding="utf-8")
    current = tasks.status(text)
    approval = approval or state.get("validation_failure_approval")
    if approval is not None and (not isinstance(approval, str) or not approval.strip()):
        raise Blocked("human approval must identify the accepted validation failures")
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
        # Preserve user artifacts before removing the owned environment or checkout.
        ignored = paths(target, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
        extras = {p for p in ignored if p != state["task_file"]
                  and not ("__pycache__" in Path(p).parts and p.endswith(".pyc"))}
        if extras:
            raise Blocked("ignored files need preservation before cleanup: " + ", ".join(sorted(extras)))
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


def _run_model_guard(target, task_file, approved=False, *, sources=None):
    runtime = python_env.runtime(target)
    if runtime is None:
        raise Blocked('registered Python runtime is missing; rerun worktree setup')
    interpreter, environment = runtime
    serialized_sources = json.dumps(None)
    if sources is not None:
        serialized_sources = json.dumps(sorted(sources))
    command = [str(interpreter), '-B', '-c',
               f'import sys, json; from pathlib import Path; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); '
               'import task_contract as tasks; from import_guard import require_import_changes; '
               'root = Path.cwd()\n'
               'options = {}\n'
               'if sys.argv[2] == "approved": options["contract_file"] = sys.argv[1]\n'
               'if sys.argv[3] != "null": options["supplied"] = set(json.loads(sys.argv[3]))\n'
               'with tasks.selected_task(root, sys.argv[1]):\n'
               '    require_import_changes(root, **options)',
               task_file, 'approved' if approved else 'normal', serialized_sources]
    result = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        error = Blocked(f'Model guard failed (exit {result.returncode}); worktree retained\n'
                        f'stdout:\n{result.stdout}\nstderr:\n{result.stderr}')
        error.diagnostics = {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        raise error
    # CLI stdout is reserved for its single JSON result, including successful warnings.
    for stream in ('stdout', 'stderr'):
        diagnostic = getattr(result, stream)
        if diagnostic:
            print('Model guard ' + stream + ':\n' + diagnostic, file=sys.stderr, end='' if diagnostic.endswith('\n') else '\n')


def _commit_preconditions(target, state, changed, text, parsed_operation):
    idle_git(target)
    tasks.validate_contract(target, state['task_file'], text)
    declared = tasks.paths_in(text, '## Modified files')
    allowed = tasks.paths_in(text, '## Allowed paths')
    if changed - declared or any(not any(tasks.matches(p, pattern) for pattern in allowed) for p in changed):
        raise Blocked('integration changes are outside the exact task contract')
    if any(p.startswith('tasks/') for p in changed):
        raise Blocked('contracts must remain ignored; nothing committed')
    head = output(target, 'rev-parse', 'HEAD')
    if head != state['tip']:
        raise Blocked('unexpected commits on task branch; review required')
    if state['commit'] and not state['verified']:
        raise Blocked('task commit verification failed; review required before any retry')
    if state['commit'] and changed:
        if parsed_operation is None or parsed_operation.action != 'import-delete':
            raise Blocked('task changed after commit; rerun its workflow before integration')
    return head


def _prepare_commit(root, path, state, target, approval):
    changed = changed_paths(target)
    task_id = state['task_id']
    model_changes = changed | (committed_task_paths(target, state['task_file']) or set())
    contract = (target / state['task_file']).read_text(encoding='utf-8')
    operation = tasks.final_model_task(contract)
    parsed_operation = tasks.model_operation(contract)
    if approval and (tasks.model_refactor(contract) is not None or parsed_operation is not None and parsed_operation.action in {'import-retarget', 'import-delete'}):
        raise Blocked('Model refactor/retarget/delete integration requires successful final candidate validation')
    head = _commit_preconditions(target, state, changed, contract, parsed_operation)
    base_worktree(root, state)
    if not ancestor(root, state['start'], state['base']):
        raise Blocked('base history was rewritten; task retained for review')
    if (not operation or approval) and ('- Workflow: `import`' in tasks.section(contract, '## Task contract') or any(p.startswith('model/') or p == 'project.json' for p in model_changes)):
        integration_task(target, state, approval)
        index = output(target, 'diff', '--cached', '--raw', '--no-abbrev', '--no-renames')
        before = {p: (target / p).read_bytes() if (target / p).is_file() else None for p in changed}
        _run_model_guard(target, state['task_file'], bool(approval))
        changed = changed_paths(target)
        current = (target / state['task_file']).read_text(encoding='utf-8')
        if output(target, 'diff', '--cached', '--raw', '--no-abbrev', '--no-renames') != index:
            raise Blocked('task index changed during Model guard; retain worktree')
        if current != contract:
            raise Blocked('task contract changed during Model guard; retain worktree')
        after = {p: (target / p).read_bytes() if (target / p).is_file() else None for p in changed}
        for p in before.keys() | after.keys():
            if p not in before or p not in after or before[p] != after[p]:
                raise Blocked('task changes changed during Model guard; retain worktree: ' + p)
        integration_task(target, state, approval)
        head = _commit_preconditions(target, state, changed, current, parsed_operation)
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


def _recovery_candidate(target, state, text, recovery):
    """Reuse the exact history/scope boundary for finishing and explicitly re-pinning."""
    base = recovery['base']
    head = output(target, 'rev-parse', 'HEAD')
    if (changed_paths(target) or tasks.status(text) != 'running' or
            git(target, 'merge-base', '--is-ancestor', base, head, check=False).returncode != 0 or
            output(target, 'rev-list', '--count', base + '..' + head) != recovery['count'] or
            output(target, 'rev-list', '--merges', base + '..' + head)):
        raise Blocked("recovery candidate is dirty, unfinished or has unexpected history")
    changed = paths(target, 'diff', '--name-only', '--no-renames', '-z', base, head)
    declared = tasks.paths_in(text, '## Modified files')
    allowed = tasks.paths_in(text, '## Allowed paths')
    if changed - declared or any(not any(tasks.matches(p, pattern) for pattern in allowed) for p in changed):
        raise Blocked("recovery candidate is outside the exact task contract")
    return head


def recover(where, task_id, expected_commit, expected_base, finish=False, repin=False):
    """Explicit reviewed recovery; pin old task/base and never merge or validate."""
    if finish and repin:
        raise Blocked("finish and re-pin recovery are mutually exclusive")
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
        if repin:
            recovery = state.get('recovery')
            if not recovery:
                raise Blocked("re-pin requires an existing recovery receipt")
            head = _recovery_candidate(target, state, text, recovery)
            if head != expected_commit:
                raise Blocked("recovery candidate differs from expected commit")
            if (expected_base == recovery['base'] or
                    git(root, 'merge-base', '--is-ancestor', recovery['base'], expected_base, check=False).returncode):
                raise Blocked("recovery re-pin requires a descendant of its previous base")
            state['recovery'] = dict(commit=head, base=expected_base, count=recovery['count'], previous=recovery)
            save(path, state)
            return state
        if finish:
            recovery = state.get('recovery')
            if not recovery or (recovery['commit'], recovery['base']) != (expected_commit, expected_base):
                raise Blocked("recovery receipt does not match expected commit/base")
            head = _recovery_candidate(target, state, text, recovery)
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
    if state.get('deployRepair'):
        if human_approved_validation_failure is not None:
            raise Blocked('deploy repair result requires successful static validation')
        return deploy_finalize(where, task_id)
    if state.get("recovery"):
        raise Blocked("finish reviewed recovery and rerun validation before finalize")
    if not state['merged'] and human_approved_validation_failure is None and not state.get('validation_failure_approval'):
        target = task_worktree(root, state)
        text = (target / state['task_file']).read_text(encoding='utf-8')
        if tasks.final_model_task(text):
            interpreter, environment = python_env.runtime(target)
            command = [str(interpreter), '-B', '-c',
                       f'import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); '
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
        model_paths = paths(target, 'diff', '--name-only', '--no-renames', '-z', latest, expected)
        contract = (target / state['task_file']).read_bytes()
        if any(p.startswith('model/') or p == 'project.json' for p in model_paths) or b'- Workflow: `import`' in contract:
            _run_model_guard(target, state['task_file'], bool(approval), sources=model_paths)
            if (output(target, 'rev-parse', 'HEAD') != expected or changed_paths(target)
                    or (target / state['task_file']).read_bytes() != contract
                    or output(base, 'rev-parse', 'HEAD') != latest):
                raise Blocked('validated candidate, Task or base changed before merge; retain worktree')
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
        operation = tasks.model_operation(text)
        if operation is not None and operation.action == 'import-delete':
            from model.sources import Scope, load_model
            from model.core import entries
            for scope in sorted(operation.source_scopes):
                remaining = set(dict(entries(load_model(Scope(target, *scope)).authoritative, 'desired.resource.')))
                requested = {source.rsplit('/', 1)[1] for source in operation.delete_sources
                             if tuple(source.split('/')[:3]) == scope}
                if remaining & requested:
                    raise Blocked('deletion leaves incomplete: ' + '/'.join(scope) + ': ' + ', '.join(sorted(remaining & requested)))
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

def bind_deploy_workflow(where, session_path, session, ledger, *, activate=False):
    """Prevent a new Task from resetting an overlapping unfinished deploy workflow."""
    # Pure session units have no Git; production deploy already requires clean Git inputs.
    if not (where / '.git').exists():
        return
    from import_guard import managed_task_state, read_sealed, write_sealed
    from utils.json_format import fingerprint
    root, _, primary = repository(where)
    directory = metadata_directory(primary) / 'deploy-workflows'
    target = session['target']
    key = fingerprint([target.get('awsExecutionAccountId', target['awsAccountId']), target['awsRegion']])
    file = directory / (key + '.json')
    if directory.is_symlink() or file.is_symlink():
        raise Blocked('deploy workflow registry must not use symlinks')
    if not activate and not file.exists():
        return
    managed_task_state(root, session['taskFile'])
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / 'registry.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise Blocked('deploy workflow registry busy/interrupted; retain for review') from None
    try:
        owners = read_sealed(primary, file) if file.exists() else []
        current = {'workflowId':session['workflow']['workflowId'], 'repository':str(root),
                   'taskFile':session['taskFile'], 'session':str(session_path), 'ledger':str(ledger),
                   'scope':sorted(session['states'])}
        existing = False
        for owner in owners:
            if owner['workflowId'] == current['workflowId']:
                if owner != current:
                    raise Blocked('deploy workflow ownership/Stack scope changed')
                existing = True
                continue
            if not set(owner['scope']) & set(current['scope']):
                continue
            previous_ledger = Path(owner['ledger'])
            if previous_ledger.with_name(previous_ledger.name + '.intent').exists():
                raise Blocked('recover original workflow save intent before another Task')
            previous = read_sealed(Path(owner['repository']), previous_ledger)
            if previous['workflowId'] != owner['workflowId'] or previous['session'] != owner['session']:
                raise Blocked('previous deploy workflow identity cannot be verified')
            state = previous['state']
            finished = state['workflow'].get('status') == 'COMPLETE' and not state.get('pendingRequest')
            if (not finished or any(s['status'] == 'RUNNING' or s.get('pollError') or s.get('cleanupStatus') == 'DELETE_INTENT' or
                    s['status'] == 'SUCCESS' and not s.get('observedSynced') for s in state['states'].values())):
                raise Blocked('unfinished deploy workflow owns overlapping Stacks; resume/inherit its retained history: ' + owner['session'])
        if activate and not existing:
            owners.append(current)
            write_sealed(primary, file, owners)
    finally:
        lock.rmdir()


def deploy_request(where, request_path):
    """Read the sealed handoff through the parent seal and verify its live checkpoint."""
    from deploy.handoff import external
    from deploy.contracts import task_digest
    from import_guard import read_sealed
    request_path = external(Path(where), request_path)
    envelope = json.loads(request_path.read_text(encoding='utf-8'))
    parent = Path(envelope['payload']['repository'])
    request = read_sealed(parent, request_path)
    root, _, path, state = load(parent, Path(request['taskFile']).stem)
    if task_worktree(root, state) != parent or request.get('parentBranch') != state['branch']:
        raise Blocked('repair request parent ownership mismatch')
    session = json.loads(Path(request['session']).read_text(encoding='utf-8'))
    from deploy.handoff import restore, locked
    with locked(Path(request['session'])):
        restore(parent, Path(request['session']), session)
    if (session.get('pendingRequest') != request or session['inputRevision'] != request['revision'] or
            session['workflow']['workflowId'] != request['workflowId']):
        raise Blocked('stale/consumed repair request')
    text = (parent / request['taskFile']).read_text(encoding='utf-8')
    normalized = tasks.set_status(text, 'running')
    if task_digest(normalized) != request['taskDigest']:
        raise Blocked('parent contract changed outside suspension/resume')
    if changed_paths(parent) or output(parent, 'rev-parse', 'HEAD') != request['parentTip']:
        # An interrupted child merge is checked separately against its exact integration intent.
        if not state.get('deployIntegrationIntent'):
            raise Blocked('parent checkpoint changed')
    return root, path, state, session, request


def deploy_checkpoint(where, task_id, session_path):
    """Checkpoint only proven parent changes, without completing an unfinished deploy."""
    import hashlib
    from deploy import handoff
    from deploy.contracts import task_digest
    from import_guard import write_sealed
    root, _, path, state = load(where, task_id)
    target = task_worktree(root, state)
    session_path = handoff.external(target, session_path)
    with lifecycle_lock(root), handoff.locked(session_path):
        session = json.loads(session_path.read_text(encoding='utf-8'))
        handoff.restore(target, session_path, session)
        request = session.get('pendingRequest')
        if not request or request['repository'] != str(target) or request['taskFile'] != state['task_file']:
            raise Blocked('checkpoint needs this parent pending request')
        text = (target / state['task_file']).read_text(encoding='utf-8')
        if tasks.status(text) != 'running' or task_digest(text) != session['taskDigest']:
            raise Blocked('checkpoint requires unchanged running parent Task')
        if session.get('observedError') or any(s['status'] == 'RUNNING' or s.get('pollError') or
                s['status'] == 'SUCCESS' and not s.get('observedSynced') for s in session['states'].values()):
            raise Blocked('drain and synchronize peers before checkpoint')
        handoff.verify_inputs(target, session)
        from validation.task import TaskValidation
        from validation.findings import Findings
        with tasks.selected_task(target, state['task_file']):
            findings = Findings(target)
            check = TaskValidation(target, findings)
            check.check_task_scope()
            check.check_task_type_requirements()
            check.check_issue_gate()
            if findings.errors:
                raise Blocked('parent change authority: ' + '; '.join(findings.errors))
        changed = changed_paths(target)
        head = output(target, 'rev-parse', 'HEAD')
        intent = state.get('repairCheckpointIntent')
        if intent:
            if intent['requestId'] != request['requestId']:
                raise Blocked('checkpoint intent belongs to another request')
            if head != intent['head']:
                if (changed or output(target, 'rev-parse', 'HEAD^') != intent['head'] or
                        output(target, 'rev-parse', 'HEAD^{tree}') != intent['tree'] or
                        output(target, 'log', '-1', '--format=%s') != intent['message']):
                    raise Blocked('checkpoint commit is not the saved intent')
        else:
            if head != state['tip']:
                raise Blocked('unexpected parent commits before checkpoint')
            git(target, 'diff', '--check')
            git(target, 'diff', '--cached', '--check')
            if changed:
                git(target, 'add', '--', *[f':(top,literal){p}' for p in sorted(changed)])
            intent = {'requestId': request['requestId'], 'head': head, 'tree': output(target, 'write-tree'),
                      'message': f'task({task_id}): deploy repair checkpoint {request["requestId"]}'}
            state['repairCheckpointIntent'] = intent
            save(path, state)
        if head == intent['head'] and changed:
            git(target, 'commit', '-m', intent['message'])
        tip = output(target, 'rev-parse', 'HEAD')
        if output(target, 'rev-parse', 'HEAD^{tree}') != intent['tree'] or changed_paths(target):
            raise Blocked('checkpoint changed during commit')
        integration = state.get('deployIntegrationIntent')
        if integration:
            if integration.get('result') not in session['workflow']['accepted']:
                raise Blocked('previous child integration has not been accepted')
            state.setdefault('deployIntegrations', []).append(state.pop('deployIntegrationIntent'))
        state['tip'] = tip
        state.setdefault('deployCheckpoints', []).append(intent)
        state.pop('repairCheckpointIntent', None)
        request.update(parentTip=tip, parentBranch=state['branch'], parentStart=state['start'])
        directory = session_path.with_name(session_path.name + '.files') / ('repair-' + request['requestId'])
        directory.mkdir(parents=True, exist_ok=True)
        request['requestPath'] = str(directory / 'request.json')
        # Both files are recoverable from the persisted checkpoint/intent on retry.
        save(path, state)
        handoff.save(session_path, session)
        write_sealed(target, Path(request['requestPath']), request)
        return request


def deploy_child_contract(target, state, request):
    from deploy.contracts import task_digest
    text = (target / state['task_file']).read_text(encoding='utf-8')
    tasks.validate_contract(target, state['task_file'], text)
    lines = tasks.section(text, '## Task contract')
    for line in ('- Task type: `infrastructure`', '- Infrastructure phase: `implement`',
                 '- AWS API execution: `forbidden`', '- AWS mutation: `forbidden`', '- Deploy/apply: `forbidden`',
                 f'- Deploy repair request: `{request["requestPath"]}`',
                 f'- Target environment: `{request["environment"]}`', f'- Target AWS account: `{request["target"]["awsAccountId"]}`'):
        if line not in lines:
            raise Blocked('child repair contract must contain ' + line)
    if request['target'].get('alias') and f'- Target alias: `{request["target"]["alias"]}`' not in lines:
        raise Blocked('child target alias differs from request')
    if tasks.paths_in(text, '## Allowed paths') != set(request['allowedPaths']) | {state['task_file']}:
        raise Blocked('child repair write authority differs from request')
    if not tasks.paths_in(text, '## Modified files') <= set(request['allowedPaths']) | {state['task_file']}:
        raise Blocked('child contract contains undeclared repair paths')
    if tasks.paths_in(text, '## Validation scope') != set(request['validationScope']):
        raise Blocked('child repair Validation scope changed')
    if any(p.startswith('tasks/') for p in paths(target, 'ls-files', '-z', 'tasks')):
        raise Blocked('child must not commit Task contracts')
    return text


def deploy_snapshot(target):
    """Hash tracked validation dependencies and actual untracked inputs, never their values."""
    from deploy.contracts import sha
    result = {}
    for relative in sorted(paths(target, 'ls-files', '-z') | paths(target, 'ls-files', '--others', '--exclude-standard', '-z')):
        path = tasks.safe_path(target, relative)
        result[relative] = sha(path) if path.is_file() else None
    return result


def deploy_validate(where, task_id, request_path):
    from deploy import handoff
    from deploy.contracts import task_digest
    from import_guard import write_sealed
    root, _, path, state = load(where, task_id)
    target = task_worktree(root, state)
    _, _, parent_state, session, request = deploy_request(target, request_path)
    if state.get('deployRepair') != request['requestPath'] or state['start'] != request['parentTip']:
        raise Blocked('child lifecycle does not belong to this request')
    with lifecycle_lock(root), handoff.locked(Path(request['session'])):
        text = deploy_child_contract(target, state, request)
        if tasks.status(text) != 'running' or output(target, 'rev-parse', 'HEAD') != state['tip']:
            raise Blocked('child must be running at its lifecycle tip for validation')
        handoff.verify_inputs(target, session, child_paths=request['allowedPaths'], contract_file=state['task_file'])
        before = deploy_snapshot(target)
        attempt = session['workflow']['attempts'][request['attemptId']]
        if attempt.get('staticRuns', 0) >= 3:
            raise Blocked('implement static repair limit reached; WAITING_HUMAN')
        attempt['staticRuns'] = attempt.get('staticRuns', 0) + 1
        attempt['stage'] = 'STATIC_VALIDATING'
        handoff.save(Path(request['session']), session)
        # Provisioned interpreter, same fixed validator as ordinary implement. No shell/LLM/AWS.
        interpreter, environment = python_env.runtime(target)
        from utils.aws_mappings import definition_root
        command = [str(interpreter), '-B', str(definition_root(target) / 'framework/scripts/blueprint-loop.py'),
                   '--mode', 'task', '--task-file', state['task_file'], '--fresh']
        environment[tasks.SELECTOR] = state['task_file']
        outcome = subprocess.run(command, cwd=target, env=environment, capture_output=True, text=True)
        log = Path(request['requestPath']).with_name(f'static-{attempt["staticRuns"]}.log')
        # Validator output belongs to the same private external evidence boundary.
        from utils.json_format import fingerprint
        log.write_text(json.dumps({'command': command, 'exitCode': outcome.returncode, 'outputDigest': fingerprint([outcome.stdout, outcome.stderr])}) + '\n', encoding='utf-8')
        after = deploy_snapshot(target)
        candidate_error = None
        if not outcome.returncode and before == after:
            from deploy.inputs import load_units, paths as unit_paths, deployment_input_paths
            with tasks.selected_task(target, state['task_file']):
                _, candidate_units = load_units(target, session['environment'], session['directory'], list(session['states']))
            candidate_effective = handoff.effective(target, candidate_units,
                lambda u: unit_paths(target, session['environment'], session['directory'], session['target'], u),
                lambda us: deployment_input_paths(target, session['environment'], session['directory'], session['target'], us))
            changed_inputs = changed_paths(target)
            direct = {name for name, inputs in session['unitInputPaths'].items() if set(inputs) & changed_inputs}
            previous_ids = {o['observationId'] for p in attempt['problemIds'] for o in session['workflow']['problems'][p]['observations']}
            if not direct or any(candidate_effective[name] == session['effectiveDigests'][name] or
                    candidate_effective[name] in {o.get('effectiveDigest') for o in session.get('failureObservations', []) if o['stack'] == name and o['observationId'] in previous_ids} for name in direct):
                candidate_error = 'unchanged or known failed effective inputs for this problem'
        if outcome.returncode or before != after or candidate_error or (target / state['task_file']).read_text(encoding='utf-8') != text:
            attempt['staticFailures'] += 1
            attempt['stage'] = 'STATIC_FAILED'
            if attempt['staticRuns'] >= 3:
                session['workflow']['status'] = 'WAITING_HUMAN'
            handoff.save(Path(request['session']), session)
            tasks.suspend(target, state['task_file'], 'repair static validation failed/inputs changed; ' + str(log))
            raise Blocked((candidate_error or 'repair static validation failed or inputs changed') + '; ' + str(log))
        receipt = dict(requestId=request['requestId'], attemptId=request['attemptId'], childTask=state['task_file'],
                       contract=text, snapshot=after, command=command, log=str(log), result='PASS',
                       parentTip=request['parentTip'], childRoot=str(target))
        validation_path = Path(request['requestPath']).with_name('validation.json')
        write_sealed(Path(request['repository']), validation_path, receipt)
        state['deployValidation'] = str(validation_path)
        attempt['stage'] = 'STATIC_PASSED'
        save(path, state)
        handoff.save(Path(request['session']), session)
        return receipt


def deploy_finalize(where, task_id):
    """FF-only delivery to the pinned suspended parent, with durable merge intent/result."""
    from deploy import handoff
    from deploy.contracts import sha, task_digest, subprocess_bytes
    from import_guard import read_sealed, write_sealed
    root, _, path, state = load(where, task_id)
    target = task_worktree(root, state)
    _, parent_path, parent_state, session, request = deploy_request(target, state['deployRepair'])
    parent = Path(request['repository'])
    with lifecycle_lock(root), handoff.locked(Path(request['session'])):
        parent_text = (parent / request['taskFile']).read_text(encoding='utf-8')
        if tasks.status(parent_text) != 'suspend':
            raise Blocked('repair integration requires suspended parent')
        integration_task(target, state)
        text = deploy_child_contract(target, state, request)
        validation = read_sealed(parent, Path(state['deployValidation']))
        if (validation['requestId'] != request['requestId'] or validation['contract'] != tasks.set_status(text, 'running') or
                validation['snapshot'] != deploy_snapshot(target)):
            raise Blocked('validated child contract/inputs changed')
        handoff.verify_inputs(parent, session, child_paths=request['allowedPaths'] if parent_state.get('deployIntegrationIntent') else ())
        if not state.get('deployCommitIntent'):
            if output(target, 'rev-parse', 'HEAD') != request['parentTip']:
                raise Blocked('unexpected child commits')
            changed = changed_paths(target)
            if not changed or changed - set(request['allowedPaths']):
                raise Blocked('repair changes empty or outside request')
            git(target, 'diff', '--check')
            git(target, 'diff', '--cached', '--check')
            git(target, 'add', '--', *[f':(top,literal){p}' for p in sorted(changed)])
            state['deployCommitIntent'] = {'parent': request['parentTip'], 'tree': output(target, 'write-tree'),
                                           'message': f'task({task_id}): verified deploy repair {request["requestId"]}'}
            save(path, state)
        intent = state['deployCommitIntent']
        if output(target, 'rev-parse', 'HEAD') == intent['parent']:
            git(target, 'commit', '-m', intent['message'])
        commit = output(target, 'rev-parse', 'HEAD')
        if (output(target, 'rev-parse', 'HEAD^') != intent['parent'] or output(target, 'rev-parse', 'HEAD^{tree}') != intent['tree'] or
                output(target, 'log', '-1', '--format=%s') != intent['message'] or changed_paths(target)):
            raise Blocked('repair commit differs from recorded intent')
        changed = paths(target, 'diff', '--name-only', '--no-renames', '-z', intent['parent'], commit)
        if changed - set(request['allowedPaths']):
            raise Blocked('repair commit includes other changes')
        state.update(tip=commit, commit=commit, verified=True)
        save(path, state)
        plan = {'requestId': request['requestId'], 'parentTip': request['parentTip'], 'commit': commit}
        if parent_state.get('deployIntegrationIntent') and any(parent_state['deployIntegrationIntent'].get(key) != value for key, value in plan.items()):
            raise Blocked('another integration intent is pending')
        parent_state['deployIntegrationIntent'] = plan
        save(parent_path, parent_state)
        if changed_paths(parent) or output(parent, 'rev-parse', 'HEAD') not in {request['parentTip'], commit}:
            raise Blocked('parent changed during child integration')
        git(parent, 'merge', '--ff-only', '--no-autostash', commit)
        if output(parent, 'rev-parse', 'HEAD') != commit:
            raise Blocked('repair merge differs from intended commit')
        changes = {p: {'before': __import__('hashlib').sha256(subprocess_bytes(target, request['parentTip'], p)).hexdigest(),
                       'after': sha(target / p), 'beforeBlob': output(target, 'rev-parse', request['parentTip'] + ':' + p),
                       'afterBlob': output(target, 'rev-parse', commit + ':' + p)} for p in sorted(changed)}
        from deploy.inputs import load_units, paths as input_paths, deployment_input_paths
        with tasks.selected_task(target, state['task_file']):
            _, units = load_units(target, session['environment'], session['directory'], list(session['states']))
        effective_after = handoff.effective(target, units,
            lambda unit: input_paths(target, session['environment'], session['directory'], session['target'], unit),
            lambda selected: deployment_input_paths(target, session['environment'], session['directory'], session['target'], selected))
        result = {**request, 'effectiveInputs': {'before': session['effectiveDigests'], 'after': effective_after}, 'commit': commit, 'changes': changes, 'childTask': state['task_file'], 'childContract': text,
                  'validation': validation, 'expected': session['workflow']['attempts'][request['attemptId']].get('expectation'),
                  'result': 'VALIDATED_CANDIDATE'}
        result_path = Path(request['requestPath']).with_name('result.json')
        write_sealed(parent, result_path, result)
        parent_state['tip'] = commit
        parent_state['deployIntegrationIntent']['result'] = str(result_path)
        save(parent_path, parent_state)
        state['merged'] = commit
        save(path, state)
        return {**state, 'repair_result': str(result_path)}


def sync_base(where, task_id, expected_base):
    """Explicit fresh-task base FF, preserving reviewed uncommitted paths externally.

    No task commit is created and no own committed history is removed. Overlapping
    candidates must already contain the reviewed upstream changes; their bytes are
    preserved exactly. This is a base update, never a validation/completion receipt.
    """
    import hashlib
    import tempfile
    from deploy.contracts import sha, subprocess_bytes
    root, _, path, state = load(where, task_id)
    with lifecycle_lock(root):
        target = task_worktree(root, state)
        text = (target / state['task_file']).read_text(encoding='utf-8')
        tasks.validate_contract(target, state['task_file'], text)
        if tasks.status(text) != 'running' or '- Task type: `governance`' not in tasks.section(text, '## Task contract'):
            raise Blocked('base sync requires the running governance Task')
        base = output(root, 'rev-parse', 'refs/heads/' + state['base'])
        if not expected_base or base != expected_base:
            raise Blocked('review the exact latest base before sync')
        if state['commit'] or state['merged'] or state.get('deployRepair') or state['tip'] != state.get('validation_base', state['start']):
            raise Blocked('fresh uncommitted tasks only; committed candidates retain normal integration')
        if paths(target, 'diff', '--cached', '--name-only', '-z'):
            raise Blocked('preserve/review the staged index before base sync')
        intent = state.get('baseSyncIntent')
        if intent is None:
            head = output(target, 'rev-parse', 'HEAD')
            if head != state['tip'] or git(target, 'merge-base', '--is-ancestor', head, base, check=False).returncode:
                raise Blocked('base sync requires a proven fast-forward from the lifecycle tip')
            changed = changed_paths(target)
            if changed - tasks.paths_in(text, '## Modified files') or changed - tasks.paths_in(text, '## Allowed paths'):
                raise Blocked('unregistered dirty changes before base sync')
            upstream = paths(target, 'diff', '--name-only', '--no-renames', '-z', head, base)
            overlap = changed & upstream
            backup = Path(tempfile.mkdtemp(prefix='blueprint-base-sync-'))
            files = {}
            for number, relative in enumerate(sorted(overlap)):
                actual = tasks.safe_path(target, relative)
                if actual.exists() and not actual.is_file() or git(target, 'cat-file', '-e', head + ':' + relative, check=False).returncode != 0:
                    raise Blocked('base sync requires reviewed existing regular overlapping files')
                raw = actual.read_bytes() if actual.is_file() else None
                file = backup / str(number)
                if raw is not None:
                    file.write_bytes(raw)
                files[relative] = {'backup': str(file) if raw is not None else None, 'sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None,
                                   'old': hashlib.sha256(subprocess_bytes(target, head, relative)).hexdigest(),
                                   'base': hashlib.sha256(subprocess_bytes(target, base, relative)).hexdigest()}
            intent = {'head': head, 'base': base, 'files': files, 'contract': hashlib.sha256(text.encode()).hexdigest()}
            state['baseSyncIntent'] = intent
            save(path, state)
        if intent['base'] != base or intent['contract'] != hashlib.sha256(text.encode()).hexdigest():
            raise Blocked('base sync intent/contract changed')
        head = output(target, 'rev-parse', 'HEAD')
        if head not in {intent['head'], base}:
            raise Blocked('base sync HEAD changed outside its intent')
        for relative, record in intent['files'].items():
            actual = tasks.safe_path(target, relative)
            if (record['backup'] is not None and sha(Path(record['backup'])) != record['sha256']) or (sha(actual) if actual.is_file() else None) not in {record['sha256'], record['old'], record['base']}:
                raise Blocked('base sync candidate changed; retain external backup')
        if head == intent['head']:
            for relative in intent['files']:
                (target / relative).write_bytes(subprocess_bytes(target, head, relative))
            outcome = git(target, 'merge', '--ff-only', '--no-autostash', base, check=False)
            if outcome.returncode:
                for relative, record in intent['files'].items():
                    if record['backup'] is None:
                        (target / relative).unlink(missing_ok=True)
                    else:
                        (target / relative).write_bytes(Path(record['backup']).read_bytes())
                raise Blocked('base fast-forward failed; candidates restored: ' + outcome.stderr.strip())
        for relative, record in intent['files'].items():
            if record['backup'] is None:
                (target / relative).unlink(missing_ok=True)
            else:
                (target / relative).write_bytes(Path(record['backup']).read_bytes())
        if output(target, 'rev-parse', 'HEAD') != base:
            raise Blocked('base sync result differs from pinned base')
        state['tip'] = base
        state['validation_base'] = base
        state.setdefault('baseSyncs', []).append(state.pop('baseSyncIntent'))
        save(path, state)
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "setup", "finalize", "cleanup", "recover", "repair-checkpoint", "repair-validate", "sync-base"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--human-approved-validation-failure", metavar="APPROVAL",
                        help="Finalize a suspended task only after explicit human approval of named validation failures")
    parser.add_argument("--repair-request", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-base")
    recovery_mode = parser.add_mutually_exclusive_group()
    recovery_mode.add_argument("--finish-recovery", action="store_true")
    recovery_mode.add_argument("--repin-recovery", action="store_true",
                               help="Explicitly pin a reviewed clean recovery candidate to the latest descendant base")
    args = parser.parse_args()
    if args.human_approved_validation_failure is not None and args.command != "finalize":
        parser.error("--human-approved-validation-failure is only valid with finalize")
    if args.command not in {"recover", "sync-base"} and (args.expected_commit or args.expected_base or args.finish_recovery or args.repin_recovery):
        parser.error("recovery arguments require recover")
    where = args.repository_root
    try:
        if args.command != "create":
            where = load(where, args.task_id)[0]  # Keep diagnostics usable after task checkout removal.
        if args.command == 'sync-base':
            state = sync_base(where, args.task_id, args.expected_base)
        elif args.command == 'repair-checkpoint':
            if not args.state:
                raise Blocked('repair-checkpoint requires --state')
            state = deploy_checkpoint(where, args.task_id, args.state)
        elif args.command == 'repair-validate':
            if not args.repair_request:
                raise Blocked('repair-validate requires --repair-request')
            state = deploy_validate(where, args.task_id, args.repair_request)
        elif args.command == 'create':
            state = create(where, args.task_id, args.repair_request)
        else:
            state = (recover(where, args.task_id, args.expected_commit, args.expected_base, args.finish_recovery, args.repin_recovery)
                 if args.command == "recover" else finalize(where, args.task_id, args.human_approved_validation_failure)
                 if args.command == "finalize" else globals()[args.command](where, args.task_id))
        print(json.dumps({"status": "ok", **state}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        retained = {}
        try:
            root, _, _, retained = load(where, args.task_id)
            retained = {**retained, "remaining_worktree": retained["worktree"] if Path(retained["worktree"]).exists() else None,
                        "remaining_branch": retained["branch"] if branch_exists(root, retained["branch"]) else None}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        print(json.dumps({**retained, "status": "blocked", "error": str(error), **({"diagnostics": error.diagnostics} if hasattr(error, "diagnostics") else {})}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
