#!/usr/bin/env python3
"""Create and integrate isolated task worktrees; preserve work on every failure."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess

import task_contract as tasks


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


def state_path(common, task_id):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", task_id):
        raise Blocked("task-id must use the existing lower-kebab-case task naming rule")
    return common / "blueprint-worktree-tasks" / f"{task_id}.json"


def save(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def lifecycle_lock(common):
    # One short Git integration at a time; this is not a file reservation/AWS lock.
    lock = common / "blueprint-worktree-lifecycle.lock"
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
    state_file = state_path(common, task_id)
    branch = f"codex/worktree/{task_id}"
    target = primary / ".worktrees" / task_id
    with lifecycle_lock(common):
        base = base_branch(root)
        if state_file.exists() or branch_exists(root, branch):
            raise Blocked(f"task state/branch collision: {task_id}; nothing overwritten")
        if target.exists() or target.is_symlink() or target.parent.is_symlink():
            raise Blocked(f"worktree path collision: {target}; nothing overwritten")
        if any(Path(entry["worktree"]).resolve() == target for entry in worktrees(root)):
            raise Blocked(f"registered/stale worktree path collision: {target}; do not prune automatically")
        if git(primary, "check-ignore", "--quiet", str(target), check=False).returncode:
            raise Blocked("/.worktrees/ must be ignored before creating nested worktrees")
        start = output(root, "rev-parse", f"refs/heads/{base}")
        git(root, "worktree", "add", "-b", branch, str(target), start)
        state = dict(task_id=task_id, branch=branch, worktree=str(target), primary=str(primary),
                     base=base, start=start, task_file=f"tasks/{task_id}.md",
                     identity=tasks.worktree_identity(target), tip=start, commit=None, verified=False, merged=None)
        state_file.parent.mkdir(exist_ok=True)
        save(state_file, state)
        return state


def load(where, task_id):
    root, common, primary = repository(where)
    path = state_path(common, task_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    if (state["task_id"] != task_id or state["branch"] != f"codex/worktree/{task_id}"
            or state["task_file"] != f"tasks/{task_id}.md" or state["primary"] != str(primary)
            or Path(state["worktree"]) != primary / ".worktrees" / task_id):
        raise Blocked("task lifecycle state does not match this repository")
    # Cleanup can remove the caller's checkout; control Git from a surviving root.
    return primary, common, path, state


def committed_task_paths(root, task_file):
    """Reuse the managed worktree's pinned start; never read another checkout's diff."""
    common = Path(output(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    path = state_path(common, Path(task_file).stem)
    if not path.exists():
        return None  # Legacy/non-managed contracts retain their acquired file scope.
    _, _, _, state = load(root, Path(task_file).stem)
    if Path(state["worktree"]).resolve() != root.resolve():
        return None  # A same-named task in another worktree supplies no authority here.
    if state["identity"] != tasks.worktree_identity(root):
        raise Blocked("task lifecycle worktree identity mismatch")
    if git(root, "merge-base", "--is-ancestor", state["start"], "HEAD", check=False).returncode:
        raise Blocked("task lifecycle start is not an ancestor of HEAD")
    return paths(root, "diff", "--no-renames", "--name-only", "-z", state["start"], "HEAD")


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
            or not target.is_dir() or tasks.worktree_identity(target) != state["identity"]):
        raise Blocked("task worktree missing, locked, stale or switched; retain it for review")
    idle_git(target)
    return target


def integration_task(target, state, approval=None):
    # A human-approved Git integration does not turn failed validation into completion.
    records = tasks.contracts(target, include_foreign=True)
    tasks.selected_text(target, records, state["task_file"])
    entry = tasks.reservations(target, records)[state["task_file"]]
    approval = approval or state.get("validation_failure_approval")
    expected = "suspend" if approval else "completed"
    if entry.state != expected:
        raise Blocked(f"task must be {expected} for integration; current status: {entry.state}")
    if entry.files is None:
        raise Blocked("exact Modified files are required")
    if entry.files - entry.active:
        raise Blocked("unfinished Deferred files; integration refused")
    return entry


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
        # Git removes ignored files too: preserve everything except this contract/bytecode.
        ignored = paths(target, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
        extras = {p for p in ignored if p != state["task_file"] and not (
            "__pycache__" in Path(p).parts and p.endswith(".pyc"))}
        if extras:
            raise Blocked("ignored files need preservation before cleanup: " + ", ".join(sorted(extras)))
        git(root, "worktree", "remove", str(target))
    if branch_exists(root, state["branch"]):
        tip = output(root, "rev-parse", f"refs/heads/{state['branch']}")
        if tip != state["tip"] or not ancestor(root, tip, state["base"]):
            raise Blocked("temporary branch changed or is unmerged; cleanup refused")
        # -d checks against HEAD when no upstream exists. Use the verified base worktree.
        git(base_worktree(root, state), "branch", "-d", state["branch"])
    path.unlink()
    return {**state, "cleaned": True}


def cleanup(where, task_id):
    root, common, path, state = load(where, task_id)
    with lifecycle_lock(common):
        return cleanup_state(root, path, state)


def finalize(where, task_id, human_approved_validation_failure=None):
    if human_approved_validation_failure is not None and not human_approved_validation_failure.strip():
        raise Blocked("human approval must identify the accepted validation failures")
    root, common, path, state = load(where, task_id)
    with lifecycle_lock(common):
        if state["merged"]:
            return cleanup_state(root, path, state)
        target = task_worktree(root, state)
        approval = human_approved_validation_failure or state.get("validation_failure_approval")
        entry = integration_task(target, state, approval)
        changed = changed_paths(target)
        if tasks.task_changes(target, changed, state["task_file"]) != changed or changed - entry.active:
            raise Blocked("changes outside this task; nothing committed")
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
            git(target, "diff", "--check", check=not approval)
            git(target, "diff", "--cached", "--check", check=not approval)
            literal = [f":(top,literal){p}" for p in sorted(changed)]
            git(target, "add", "--", *literal)
            # Staged edits canceled by working-tree edits are an effective zero-change task.
            changed = paths(target, "diff", "--cached", "--no-renames", "--name-only", "-z")
        if changed:
            tree = output(target, "write-tree")
            message = (f"task({task_id}): human-approved validation failure" if approval
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
        expected = output(target, "rev-parse", "HEAD")
        git(base, "merge", "--ff-only", "--no-autostash", state["branch"])
        if output(base, "rev-parse", "HEAD") != expected or not ancestor(root, expected, state["base"]):
            raise Blocked("merge result differs from expected task commit; retain worktrees for review")
        state["merged"] = expected
        save(path, state)
        return cleanup_state(root, path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "finalize", "cleanup"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--human-approved-validation-failure", metavar="APPROVAL",
                        help="Finalize a suspended task only after explicit human approval of named validation failures")
    args = parser.parse_args()
    if args.human_approved_validation_failure is not None and args.command != "finalize":
        parser.error("--human-approved-validation-failure is only valid with finalize")
    where = args.repository_root
    try:
        if args.command != "create":
            where = load(where, args.task_id)[0]  # Keep diagnostics usable after task checkout removal.
        state = (finalize(where, args.task_id, args.human_approved_validation_failure)
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
