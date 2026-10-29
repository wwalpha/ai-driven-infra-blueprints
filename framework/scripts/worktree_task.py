#!/usr/bin/env python3
"""Create and integrate isolated task worktrees; preserve work on every failure."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import task_contract as tasks
import worktree_python as python_env
import worktree_state
from utils.file_operations import sha
from utils.import_evidence import discard_import_proof
from utils.script_loader import module
from worktree_state import (
    Blocked as Blocked,
)
from worktree_state import changed_paths as changed_paths
from worktree_state import committed_task_paths as committed_task_paths
from worktree_state import (
    git as git,
)
from worktree_state import (
    load as load,
)
from worktree_state import (
    metadata_directory as metadata_directory,
)
from worktree_state import (
    repository as repository,
)
from worktree_state import (
    state_path as state_path,
)
from worktree_state import subprocess_bytes
from worktree_state import task_start_commit as task_start_commit
from worktree_state import task_worktree as task_worktree
from worktree_state import (
    worktrees as worktrees,
)


def paths(root, *args):
    return worktree_state.paths(root, *args, runner=git)


def idle_git(root):
    return worktree_state.idle_git(root, runner=git)


def output(root, *args):
    return worktree_state.output(root, *args, runner=git)


def branch_exists(root, branch):
    return (
        git(
            root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False
        ).returncode
        == 0
    )


def base_branch(root):
    # Only repository-local configuration counts; init.defaultBranch is not a base.
    explicit = git(
        root, "config", "--local", "--get", "blueprint.baseBranch", check=False
    ).stdout.strip()
    remote = git(
        root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False
    ).stdout.strip()
    preferred = explicit or (
        remote.removeprefix("refs/remotes/origin/") if remote else ""
    )
    if preferred:
        if not branch_exists(root, preferred):
            raise Blocked(f"configured base branch does not exist locally: {preferred}")
        return preferred
    for name in ("main", "master"):
        if branch_exists(root, name):
            return name
    raise Blocked("no configured base, main or master branch exists")


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
        raise Blocked(
            f"worktree lifecycle busy; retain work and retry: {lock}"
        ) from None
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
        parent = Path(request["repository"])
        if (
            tasks.status(
                tasks.read_task_snapshot(parent, request["taskFile"], live=True).text
            )
            != "suspend"
        ):
            raise Blocked("suspend the original deploy Task before child creation")
        parent_state = transfer[-2]
        if parent_state["iacRepair"].get("childTask") not in (None, task_id):
            raise Blocked("one-shot request already owns another implement child")
    repair_lock = nullcontext()
    if request:
        locked = _worktree_runtime().deploy_handoff.locked
        repair_lock = locked(Path(request["requestPath"]))
    with lifecycle_lock(primary), repair_lock:
        base = request["parentBranch"] if request else base_branch(root)
        if state_file.exists() or branch_exists(root, branch):
            raise Blocked(
                f"task state/branch collision: {task_id}; nothing overwritten"
            )
        if target.exists() or target.is_symlink() or target.parent.is_symlink():
            raise Blocked(f"worktree path collision: {target}; nothing overwritten")
        if any(
            Path(entry["worktree"]).resolve() == target for entry in worktrees(root)
        ):
            raise Blocked(
                f"registered/stale worktree path collision: {target}; do not prune automatically"
            )
        start = output(root, "rev-parse", f"refs/heads/{base}")
        if request and start != request["parentTip"]:
            raise Blocked("repair parent tip changed")
        git(root, "worktree", "add", "-b", branch, str(target), start)
        state = dict(
            task_id=task_id,
            branch=branch,
            worktree=str(target),
            primary=str(primary),
            base=base,
            start=start,
            task_file=f"tasks/{task_id}.md",
            tip=start,
            commit=None,
            verified=False,
            merged=None,
        )
        if request:
            state["deployRepair"] = request["requestPath"]
            parent_state["iacRepair"]["childTask"] = task_id
            save(transfer[1], parent_state)
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
            message = (
                f"{type(error).__name__}: {str(error) or 'Python setup interrupted'}"
            )
            state["python_setup"] = {"status": "failed", "error": message}
            save(path, state)
            raise Blocked(
                f"Python setup failed; worktree retained. Retry setup --task-id {task_id}: {message}"
            ) from error
        save(path, state)
        return state
    finally:
        lock.rmdir()


def integration_task(target, state, approval=None):
    # A human-approved Git integration does not turn failed validation into completion.
    snapshot = tasks.read_task_snapshot(target, state["task_file"], live=True)
    text = snapshot.text
    if "- Infrastructure phase: `deploy`" in text.splitlines():
        worktree_state.deploy_start_commit(
            target, state["task_file"], allow_merged=True
        )
    else:
        task_start_commit(target, state["task_file"])
    current = tasks.status(text)
    approval = approval or state.get("validation_failure_approval")
    if approval is not None and (not isinstance(approval, str) or not approval.strip()):
        raise Blocked("human approval must identify the accepted validation failures")
    expected = "suspend" if approval else "completed"
    if current != expected:
        raise Blocked(
            f"task must be {expected} for integration; current status: {current}"
        )


def base_worktree(root, state):
    entries = [
        entry
        for entry in worktrees(root)
        if entry.get("branch") == f"refs/heads/{state['base']}"
    ]
    if len(entries) != 1 or "locked" in entries[0] or "prunable" in entries[0]:
        raise Blocked(
            "local base must be checked out in one available worktree; no automatic checkout"
        )
    target = Path(entries[0]["worktree"])
    idle_git(target)
    if git(target, "status", "--porcelain", "--untracked-files=all").stdout:
        raise Blocked(
            f"base worktree is dirty: {target}; task commit/worktree retained"
        )
    return target


def ancestor(root, commit, branch):
    return (
        git(
            root,
            "merge-base",
            "--is-ancestor",
            commit,
            f"refs/heads/{branch}",
            check=False,
        ).returncode
        == 0
    )


def _cleanup_git(root: Path, *args: str, directory: Path):
    return git(root, "--git-dir", str(directory), *args)


def cleanup_missing_worktree(root: Path, state: dict, entry: dict) -> None:
    """Prove retained Git data is unchanged before removing a missing checkout's registration."""
    if (
        "locked" in entry
        or entry.get("branch") != f"refs/heads/{state['branch']}"
        or entry.get("HEAD") != state["tip"]
        or state["merged"] != state["tip"]
        or state["commit"] is not None
        and not state.get("verified")
    ):
        raise Blocked(
            "missing worktree registration is locked or differs from the verified merge; cleanup refused"
        )
    target = Path(state["worktree"])
    common = Path(
        output(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    directories = [
        directory
        for directory in (common / "worktrees").iterdir()
        if directory.is_dir()
        and not directory.is_symlink()
        and (directory / "gitdir").is_file()
        and not (directory / "gitdir").is_symlink()
        and Path((directory / "gitdir").read_text(encoding="utf-8").rstrip("\n"))
        == target / ".git"
    ]
    if len(directories) != 1:
        raise Blocked(
            "missing worktree Git administration cannot be identified uniquely; cleanup refused"
        )
    directory = directories[0]
    if any(
        not (directory / name).is_file() or (directory / name).is_symlink()
        for name in ("HEAD", "index")
    ) or any(directory.rglob("*.lock")):
        raise Blocked(
            "missing worktree Git HEAD/index is unavailable, redirected or locked; cleanup refused"
        )
    if (
        Path(
            output(
                root,
                "--git-dir",
                str(directory),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
        ).resolve()
        != common.resolve()
        or output(root, "--git-dir", str(directory), "rev-parse", "HEAD")
        != state["tip"]
    ):
        raise Blocked("missing worktree Git identity changed; cleanup refused")
    worktree_state.idle_operations(
        root, runner=partial(_cleanup_git, directory=directory)
    )
    # diff-index reads the retained index without requiring the removed working directory.
    if output(
        root,
        "--git-dir",
        str(directory),
        "diff-index",
        "--cached",
        "--name-only",
        "-z",
        state["tip"],
        "--",
    ):
        raise Blocked(
            "missing worktree index differs from the verified merge; cleanup refused"
        )


def cleanup_progress(
    root: Path, path: Path, state: dict, phase: str, reason: str | None = None
) -> dict:
    target = Path(state["worktree"])
    return {
        "phase": phase,
        "stop_reason": reason,
        "remaining": {
            "worktree": target.exists() or target.is_symlink(),
            "git_registration": any(
                Path(e["worktree"]).resolve() == target for e in worktrees(root)
            ),
            "branch": branch_exists(root, state["branch"]),
            "task_state": path.exists(),
        },
        "retry_command": f"python3 -B framework/scripts/worktree_task.py cleanup --task-id {state['task_id']}",
        "next_action": "resolve_stop_reason_then_retry" if reason else "none",
    }


def cleanup_state(root, path, state):
    phase = "verify_merge"
    try:
        if not state["merged"] or not ancestor(root, state["merged"], state["base"]):
            raise Blocked("cleanup requires a verified successful merge")
        if state["commit"] and not ancestor(root, state["commit"], state["base"]):
            raise Blocked("base no longer contains the task commit; cleanup refused")
        phase = "verify_worktree"
        target = Path(state["worktree"])
        if target.is_symlink():
            raise Blocked("task worktree path is a symlink; cleanup refused")
        if path.with_suffix(".setup-lock").exists():
            raise Blocked("Python setup busy; cleanup refused")
        entries = [
            e for e in worktrees(root) if Path(e["worktree"]).resolve() == target
        ]
        if target.exists():
            target = task_worktree(root, state)
            integration_task(target, state)
            if output(target, "rev-parse", "HEAD") != state["tip"]:
                raise Blocked("task HEAD changed since merge; cleanup refused")
            if changed_paths(target):
                raise Blocked("task worktree is dirty; cleanup refused")
            # Preserve user artifacts before removing the owned environment or checkout.
            ignored = paths(
                target, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"
            )
            extras = {
                p
                for p in ignored
                if p != state["task_file"]
                and not ("__pycache__" in Path(p).parts and p.endswith(".pyc"))
            }
            if extras:
                raise Blocked(
                    "ignored files need preservation before cleanup: "
                    + ", ".join(sorted(extras))
                )
        elif entries:
            if len(entries) != 1:
                raise Blocked(
                    "multiple Git registrations for the missing worktree; cleanup refused"
                )
            cleanup_missing_worktree(root, state, entries[0])
        if branch_exists(root, state["branch"]):
            tip = output(root, "rev-parse", f"refs/heads/{state['branch']}")
            if tip != state["tip"] or not ancestor(root, tip, state["base"]):
                raise Blocked(
                    "temporary branch changed or is unmerged; cleanup refused"
                )
        elif entries:
            raise Blocked("registered worktree branch is missing; cleanup refused")
        if target.exists() or entries:
            phase = "remove_worktree"
            git(root, "worktree", "remove", str(target))
        phase = "remove_branch"
        if branch_exists(root, state["branch"]):
            # -d checks against HEAD when no upstream exists. Use the verified base worktree.
            git(base_worktree(root, state), "branch", "-d", state["branch"])
        phase = "remove_import_proof"
        discard_import_proof(target, state["task_file"])
        phase = "remove_repair_proof"
        if state.get("deployRepair"):
            _worktree_runtime().deploy_handoff.discard_request(state)
        if state.get("deployIdentity"):
            phase = "remove_deploy_progress"
            module("deploy/worktree.py", "deploy.worktree").discard_progress(state)
        phase = "remove_state"
        path.unlink()
        return {
            **state,
            "cleaned": True,
            "cleanup": cleanup_progress(root, path, state, "complete"),
        }
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        error.cleanup = {"phase": phase, "stop_reason": str(error)}
        try:
            error.cleanup = cleanup_progress(root, path, state, phase, str(error))
        except (OSError, ValueError, KeyError, TypeError) as inspection_error:
            error.cleanup["inspection_error"] = str(inspection_error)
        raise


def cleanup(where, task_id):
    root, common, path, state = load(where, task_id)
    with lifecycle_lock(root):
        return cleanup_state(root, path, state)


def _run_model_guard(target, task_file, approved=False, *, sources=None):
    runtime = python_env.runtime(target)
    if runtime is None:
        raise Blocked("registered Python runtime is missing; rerun worktree setup")
    interpreter, environment = runtime
    serialized_sources = json.dumps(None)
    if sources is not None:
        serialized_sources = json.dumps(sorted(sources))
    command = [
        str(interpreter),
        "-B",
        "-c",
        f"import sys, json; from pathlib import Path; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
        "import task_contract as tasks; from import_guard import require_import_changes; "
        "root = Path.cwd()\n"
        "options = {}\n"
        'if sys.argv[2] == "approved": options["contract_file"] = sys.argv[1]\n'
        'if sys.argv[3] != "null": options["supplied"] = set(json.loads(sys.argv[3]))\n'
        "with tasks.selected_task(root, sys.argv[1]):\n"
        "    text = tasks.read_task_snapshot(root, sys.argv[1], live=True).text\n"
        "    if '- Workflow: `import`' in tasks.section(text, '## Task contract'):\n"
        "        from task_contract_runtime import check_import\n"
        "        check_import(root, sys.argv[1], supplied=options.get('supplied'), integration=True)\n"
        "    else:\n"
        "        require_import_changes(root, **options)\n"
        "    if '- Workflow: `import`' not in tasks.section(text, '## Task contract') and '## Out-of-task FAIL approvals' in text:\n"
        "        from validation.runner import Validator\n"
        "        validator = Validator(root, tasks.active_scope(root, task_file=sys.argv[1]), cache=False, model_validation='change')\n"
        "        validator.run()\n"
        "        if validator.display_report(): raise ValueError('Task Acceptance FAIL; no integration')",
        task_file,
        "approved" if approved else "normal",
        serialized_sources,
    ]
    result = subprocess.run(
        command,
        cwd=target,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        error = Blocked(
            f"Model guard failed (exit {result.returncode}); worktree retained\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        error.diagnostics = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        raise error
    # CLI stdout is reserved for its single JSON result, including successful warnings.
    for stream in ("stdout", "stderr"):
        diagnostic = getattr(result, stream)
        if diagnostic:
            print(
                "Model guard " + stream + ":\n" + diagnostic,
                file=sys.stderr,
                end="" if diagnostic.endswith("\n") else "\n",
            )


def _commit_preconditions(
    target, state, changed, text, parsed_operation, *, scope_paths
):
    idle_git(target)
    tasks.validate_contract(target, state["task_file"], text)
    if state["commit"] and not state["verified"]:
        raise Blocked(
            "task commit verification failed; review required before any retry"
        )
    declared = tasks.paths_in(text, "## Modified files")
    allowed = tasks.paths_in(text, "## Allowed paths")
    if scope_paths - declared or any(
        not any(tasks.matches(p, pattern) for pattern in allowed) for p in scope_paths
    ):
        raise Blocked("integration changes are outside the exact task contract")
    if any(p.startswith("tasks/") for p in changed):
        raise Blocked("contracts must remain ignored; nothing committed")
    head = output(target, "rev-parse", "HEAD")
    if head != state["tip"]:
        raise Blocked("unexpected commits on task branch; review required")
    if state["commit"] and changed:
        if parsed_operation is None or parsed_operation.action != "model-delete":
            raise Blocked(
                "task changed after commit; rerun its workflow before integration"
            )
    return head


def integration_changed_paths(target, task_file):
    return changed_paths(target) | (committed_task_paths(target, task_file) or set())


def _prepare_commit(root, path, state, target, approval):
    changed = changed_paths(target)
    task_id = state["task_id"]
    model_changes = integration_changed_paths(target, state["task_file"])
    contract = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    operation = tasks.final_model_task(contract, model_changes)
    parsed_operation = tasks.model_operation(contract)
    if approval and (
        tasks.model_refactor(contract) is not None
        or parsed_operation is not None
        and parsed_operation.action in {"import-retarget", "model-delete"}
    ):
        raise Blocked(
            "Model refactor/retarget/delete integration requires successful final candidate validation"
        )
    head = _commit_preconditions(
        target, state, changed, contract, parsed_operation, scope_paths=model_changes
    )
    base_worktree(root, state)
    if not ancestor(root, state["start"], state["base"]):
        raise Blocked("base history was rewritten; task retained for review")
    if (not operation or approval) and (
        "- Workflow: `import`" in tasks.section(contract, "## Task contract")
        or "## Out-of-task FAIL approvals" in contract
        or any(p.startswith("model/") or p == "project.json" for p in model_changes)
    ):
        integration_task(target, state, approval)
        index = output(
            target, "diff", "--cached", "--raw", "--no-abbrev", "--no-renames"
        )
        before = {
            p: (target / p).read_bytes() if (target / p).is_file() else None
            for p in changed
        }
        _run_model_guard(target, state["task_file"], bool(approval))
        changed = changed_paths(target)
        current = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        if (
            output(target, "diff", "--cached", "--raw", "--no-abbrev", "--no-renames")
            != index
        ):
            raise Blocked("task index changed during Model guard; retain worktree")
        if current != contract:
            raise Blocked("task contract changed during Model guard; retain worktree")
        after = {
            p: (target / p).read_bytes() if (target / p).is_file() else None
            for p in changed
        }
        for p in before.keys() | after.keys():
            if p not in before or p not in after or before[p] != after[p]:
                raise Blocked(
                    "task changes changed during Model guard; retain worktree: " + p
                )
        integration_task(target, state, approval)
        head = _commit_preconditions(
            target, state, changed, current, parsed_operation, scope_paths=model_changes
        )
    if approval:
        state["validation_failure_approval"] = approval
    if changed:
        whitespace = git(target, "config", "--get", "core.whitespace", check=False)
        if whitespace.returncode not in (0, 1):
            raise Blocked("cannot determine Git whitespace checks")
        rules = (
            whitespace.stdout.strip() or "blank-at-eol,blank-at-eof,space-before-tab"
        )
        diff_check = ("-c", "core.whitespace=" + rules + ",cr-at-eol", "diff")
        git(target, *diff_check, "--check", check=not approval)
        git(target, *diff_check, "--cached", "--check", check=not approval)
        literal = [f":(top,literal){p}" for p in sorted(changed)]
        git(target, "add", "--", *literal)
        # Staged edits canceled by working-tree edits are an effective zero-change task.
        changed = paths(target, "diff", "--cached", "--no-renames", "--name-only", "-z")
    if changed:
        tree = output(target, "write-tree")
        message = (
            f"task({task_id}): human-approved validation failure"
            if approval
            else f"task({task_id}): Model operation candidate"
            if operation
            else f"task({task_id}): completed task"
        )
        git(target, "commit", "-m", message, *(["-m", approval] if approval else []))
        state["commit"] = output(target, "rev-parse", "HEAD")
        state["tip"] = state["commit"]
        save(path, state)  # Preserve the task commit before touching the latest base.
        if (
            output(target, "rev-parse", "HEAD^") != head
            or output(target, "rev-parse", "HEAD^{tree}") != tree
            or paths(target, "diff", "--no-renames", "--name-only", "-z", head, "HEAD")
            != changed
        ):
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
    result = git(
        target,
        "-c",
        "rebase.updateRefs=false",
        "rebase",
        "--no-autostash",
        latest,
        check=False,
    )
    if result.returncode:
        git(target, "rebase", "--abort")
        raise Blocked(
            "rebase failed and was aborted; human review required: "
            + result.stderr.strip()
        )
    state["tip"] = output(target, "rev-parse", "HEAD")
    if state["commit"]:
        state["commit"] = state["tip"]
    save(path, state)
    if changed_paths(target):
        raise Blocked("task worktree changed during rebase; review required")
    base = base_worktree(
        root, state
    )  # Recheck dirty/operation state immediately before merge.
    if output(base, "rev-parse", "HEAD") != latest:
        raise Blocked(
            "base advanced during rebase; retry finalize with latest local base"
        )
    return latest


def _recovery_candidate(target, state, text, recovery):
    """Reuse the exact history/scope boundary for finishing and explicitly re-pinning."""
    base = recovery["base"]
    head = output(target, "rev-parse", "HEAD")
    if (
        changed_paths(target)
        or tasks.status(text) != "running"
        or git(
            target, "merge-base", "--is-ancestor", base, head, check=False
        ).returncode
        != 0
        or output(target, "rev-list", "--count", base + ".." + head)
        != recovery["count"]
        or output(target, "rev-list", "--merges", base + ".." + head)
    ):
        raise Blocked(
            "recovery candidate is dirty, unfinished or has unexpected history"
        )
    changed = paths(target, "diff", "--name-only", "--no-renames", "-z", base, head)
    declared = tasks.paths_in(text, "## Modified files")
    allowed = tasks.paths_in(text, "## Allowed paths")
    if changed - declared or any(
        not any(tasks.matches(p, pattern) for pattern in allowed) for p in changed
    ):
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
        if not all(
            re.fullmatch(r"[0-9a-f]{40}", value or "")
            for value in (expected_commit, expected_base)
        ):
            raise Blocked("recovery requires full expected commit/base hashes")
        if (
            state["merged"]
            or state.get("validation_failure_approval")
            or not state["verified"]
        ):
            raise Blocked(
                "recovery requires an unmerged verified task without failure approval"
            )
        if output(base, "rev-parse", "HEAD") != expected_base:
            raise Blocked("recovery base changed")
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        tasks.validate_contract(target, state["task_file"], text)
        if "- Task type: `governance`" not in tasks.section(text, "## Task contract"):
            raise Blocked("reviewed recovery is limited to governance tasks")
        if repin:
            recovery = state.get("recovery")
            if not recovery:
                raise Blocked("re-pin requires an existing recovery receipt")
            head = _recovery_candidate(target, state, text, recovery)
            if head != expected_commit:
                raise Blocked("recovery candidate differs from expected commit")
            if (
                expected_base == recovery["base"]
                or git(
                    root,
                    "merge-base",
                    "--is-ancestor",
                    recovery["base"],
                    expected_base,
                    check=False,
                ).returncode
            ):
                raise Blocked(
                    "recovery re-pin requires a descendant of its previous base"
                )
            state["recovery"] = dict(
                commit=head,
                base=expected_base,
                count=recovery["count"],
                previous=recovery,
            )
            save(path, state)
            return state
        if finish:
            recovery = state.get("recovery")
            if not recovery or (recovery["commit"], recovery["base"]) != (
                expected_commit,
                expected_base,
            ):
                raise Blocked("recovery receipt does not match expected commit/base")
            head = _recovery_candidate(target, state, text, recovery)
            state.update(
                tip=head, commit=head, verified=True, validation_base=expected_base
            )
            del state["recovery"]
            save(path, state)
            return state
        if (
            state.get("recovery")
            or state["commit"] != expected_commit
            or state["tip"] != expected_commit
            or output(target, "rev-parse", "HEAD") != expected_commit
        ):
            raise Blocked("recovery task commit changed or recovery already started")
        if tasks.status(text) not in {"completed", "running"}:
            raise Blocked("resume suspended tasks before recovery")
        if git(
            target,
            "merge-base",
            "--is-ancestor",
            state["start"],
            expected_base,
            check=False,
        ).returncode:
            raise Blocked("recovery base history was rewritten")
        count = int(
            output(
                target, "rev-list", "--count", expected_base + ".." + expected_commit
            )
        )
        changed = bool(changed_paths(target))
        state["recovery"] = dict(
            commit=expected_commit, base=expected_base, count=str(count + changed)
        )
        tasks.atomic_files(
            {target / state["task_file"]: tasks.set_status(text, "running")},
            staging_directory=target,
        )
        # Permit only this explicitly pinned correction commit; normal finalize guards stay closed.
        if changed:
            state["commit"] = None
        try:
            _prepare_commit(root, path, state, target, None)
        except Blocked as error:
            if str(error).startswith("rebase failed and was aborted"):
                save(path, state)
            raise
        return state


def finalize(where, task_id, human_approved_validation_failure=None):
    if (
        human_approved_validation_failure is not None
        and not human_approved_validation_failure.strip()
    ):
        raise Blocked("human approval must identify the accepted validation failures")
    root, common, path, state = load(where, task_id)
    if state.get("deployIdentity") and not state.get("merged"):
        if human_approved_validation_failure is not None:
            raise Blocked("Deploy publication requires its successful validation")
        run_deploy_publication(where, task_id, finish=True)
        return cleanup(root, task_id)
    if state.get("deployRepair"):
        if human_approved_validation_failure is not None:
            raise Blocked("deploy repair result requires successful static validation")
        return deploy_finalize(where, task_id)
    if state.get("recovery"):
        raise Blocked("finish reviewed recovery and rerun validation before finalize")
    if (
        not state["merged"]
        and human_approved_validation_failure is None
        and not state.get("validation_failure_approval")
    ):
        target = task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        if tasks.final_model_task(
            text,
            partial(integration_changed_paths, target, state["task_file"]),
        ) or tasks.final_framework_task(
            text,
            partial(integration_changed_paths, target, state["task_file"]),
        ):
            interpreter, environment = python_env.runtime(target)
            command = [
                str(interpreter),
                "-B",
                "-c",
                f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
                "from worktree_task import _integrate_model; "
                "_integrate_model(sys.argv[1], sys.argv[2])",
                str(root),
                task_id,
            ]
            result = subprocess.run(
                command,
                cwd=target,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode:
                raise Blocked(
                    "final candidate integration failed; worktree retained: "
                    + result.stderr.strip()
                    + result.stdout.strip()
                )
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
        approval = human_approved_validation_failure or state.get(
            "validation_failure_approval"
        )
        integration_task(target, state, approval)
        latest = _prepare_commit(root, path, state, target, approval)
        base = base_worktree(root, state)
        expected = output(target, "rev-parse", "HEAD")
        model_paths = paths(
            target, "diff", "--name-only", "--no-renames", "-z", latest, expected
        )
        contract = tasks.read_task_snapshot(target, state["task_file"], live=True).raw
        if (
            any(p.startswith("model/") or p == "project.json" for p in model_paths)
            or b"- Workflow: `import`" in contract
            or b"## Out-of-task FAIL approvals" in contract
        ):
            _run_model_guard(
                target, state["task_file"], bool(approval), sources=model_paths
            )
            if (
                output(target, "rev-parse", "HEAD") != expected
                or changed_paths(target)
                or tasks.read_task_snapshot(target, state["task_file"], live=True).raw
                != contract
                or output(base, "rev-parse", "HEAD") != latest
            ):
                raise Blocked(
                    "validated candidate, Task or base changed before merge; retain worktree"
                )
        git(base, "merge", "--ff-only", "--no-autostash", state["branch"])
        if output(base, "rev-parse", "HEAD") != expected or not ancestor(
            root, expected, state["base"]
        ):
            raise Blocked(
                "merge result differs from expected task commit; retain worktrees for review"
            )
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
    deploy_source_root: Path | None = None


@dataclass(frozen=True)
class _ValidatedCandidate:
    candidate: FinalCandidate
    returncode: int


def prepare_integration(where: Path, task_id: str) -> FinalCandidate:
    return _worktree_runtime().prepare_integration(where, task_id)


def validate_final_candidate(candidate: FinalCandidate) -> _ValidatedCandidate:
    return _worktree_runtime().validate_final_candidate(candidate)


def merge_validated_candidate(result: _ValidatedCandidate) -> dict:
    """Consume a successful in-call validation, complete status and ff-only merge.

    Rechecks exact HEAD/base/clean state and the validated task body under the
    lifecycle lock. No rebase, regeneration, validation rerun or cleanup here.
    """
    if not isinstance(result, _ValidatedCandidate) or result.returncode:
        raise Blocked("final candidate validation failed; no merge")
    candidate = result.candidate
    root, _, path, state = load(candidate.root, Path(candidate.task_file).stem)
    with lifecycle_lock(root):
        target = task_worktree(root, state)
        base = base_worktree(root, state)
        if (
            target != candidate.root
            or changed_paths(target)
            or output(target, "rev-parse", "HEAD") != candidate.candidate_head
            or output(base, "rev-parse", "HEAD") != candidate.base_commit
        ):
            raise Blocked("validated candidate/base changed; no merge")
        if paths(target, "ls-files", "-z", "tasks"):
            raise Blocked("contracts must remain ignored; no status commit")
        task_path = target / candidate.task_file
        text = tasks.read_task_snapshot(target, candidate.task_file, live=True).text
        if text != candidate.task_text:
            raise Blocked("validated task contract changed; no merge")
        completed = (
            tasks.set_status(text, "completed")
            if tasks.status(text) == "running"
            else text
        )
        if text != completed:
            tasks.atomic_files({task_path: completed}, staging_directory=target)
        if (
            tasks.read_task_snapshot(target, candidate.task_file, live=True).text
            != completed
            or changed_paths(target)
            or output(target, "rev-parse", "HEAD") != candidate.candidate_head
            or output(base, "rev-parse", "HEAD") != candidate.base_commit
        ):
            raise Blocked("validated state changed during task completion; no merge")
        git(base, "merge", "--ff-only", "--no-autostash", state["branch"])
        if output(
            base, "rev-parse", "HEAD"
        ) != candidate.candidate_head or not ancestor(
            root, candidate.candidate_head, state["base"]
        ):
            raise Blocked("merge result differs from validated candidate")
        state["merged"] = candidate.candidate_head
        save(path, state)
        return state


def _integrate_model(where, task_id):
    """Internal registered-runtime composition; diagnostics remain outside CLI JSON."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="blueprint-model-integration-",
        suffix=".log",
        delete=False,
    ) as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                candidate = prepare_integration(Path(where), task_id)
                result = validate_final_candidate(candidate)
                merge_validated_candidate(result)
        except (OSError, ValueError, KeyError, TypeError) as error:
            _, _, _, state = load(Path(where), task_id)
            tasks.suspend(
                Path(state["worktree"]),
                state["task_file"],
                str(error) + "; integration log: " + log.name,
            )
            raise Blocked(str(error) + "; integration log: " + log.name) from error


def deploy_request(where, request_path):
    return _worktree_runtime().deploy_request(where, request_path)


def deploy_checkpoint(where, task_id, session_path):
    return _worktree_runtime().deploy_checkpoint(where, task_id, session_path)


def deploy_stack_checkpoint(backend: SimpleNamespace, names: list[str]) -> dict:
    return module("worktree_checkpoint.py", "worktree_checkpoint").checkpoint(
        backend, names
    )


def deploy_child_contract(target, state, request):
    text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    tasks.validate_contract(target, state["task_file"], text)
    lines = tasks.section(text, "## Task contract")
    for line in (
        "- Task type: `infrastructure`",
        "- Infrastructure phase: `implement`",
        "- AWS API execution: `forbidden`",
        "- AWS mutation: `forbidden`",
        "- Deploy/apply: `forbidden`",
        f"- Deploy repair request: `{request['requestPath']}`",
        f"- Target environment: `{request['environment']}`",
        f"- Target AWS account: `{request['target']['awsAccountId']}`",
    ):
        if line not in lines:
            raise Blocked("child repair contract must contain " + line)
    if (
        request["target"].get("alias")
        and f"- Target alias: `{request['target']['alias']}`" not in lines
    ):
        raise Blocked("child target alias differs from request")
    if tasks.paths_in(text, "## Allowed paths") != set(request["allowedPaths"]) | {
        state["task_file"]
    }:
        raise Blocked("child repair write authority differs from request")
    if not tasks.paths_in(text, "## Modified files") <= set(request["allowedPaths"]) | {
        state["task_file"]
    }:
        raise Blocked("child contract contains undeclared repair paths")
    if tasks.paths_in(text, "## Validation scope") != set(request["validationScope"]):
        raise Blocked("child repair Validation scope changed")
    if any(p.startswith("tasks/") for p in paths(target, "ls-files", "-z", "tasks")):
        raise Blocked("child must not commit Task contracts")
    return text


def deploy_snapshot(target):
    return _worktree_runtime().deploy_snapshot(target)


def deploy_validate(where, task_id, request_path):
    return _worktree_runtime().deploy_validate(where, task_id, request_path)


def deploy_finalize(where, task_id):
    return _worktree_runtime().deploy_finalize(where, task_id)


def sync_base(where, task_id, expected_base):
    """Explicit fresh-task base FF, preserving reviewed uncommitted paths externally.

    No task commit is created and no own committed history is removed. Overlapping
    candidates must already contain the reviewed upstream changes; their bytes are
    preserved exactly. This is a base update, never a validation/completion receipt.
    """

    root, _, path, state = load(where, task_id)
    with lifecycle_lock(root):
        target = task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        tasks.validate_contract(target, state["task_file"], text)
        if tasks.status(
            text
        ) != "running" or "- Task type: `governance`" not in tasks.section(
            text, "## Task contract"
        ):
            raise Blocked("base sync requires the running governance Task")
        base = output(root, "rev-parse", "refs/heads/" + state["base"])
        if not expected_base or base != expected_base:
            raise Blocked("review the exact latest base before sync")
        if (
            state["commit"]
            or state["merged"]
            or state.get("deployRepair")
            or state["tip"] != state.get("validation_base", state["start"])
        ):
            raise Blocked(
                "fresh uncommitted tasks only; committed candidates retain normal integration"
            )
        if paths(target, "diff", "--cached", "--name-only", "-z"):
            raise Blocked("preserve/review the staged index before base sync")
        intent = state.get("baseSyncIntent")
        if intent is None:
            head = output(target, "rev-parse", "HEAD")
            if (
                head != state["tip"]
                or git(
                    target, "merge-base", "--is-ancestor", head, base, check=False
                ).returncode
            ):
                raise Blocked(
                    "base sync requires a proven fast-forward from the lifecycle tip"
                )
            changed = changed_paths(target)
            if changed - tasks.paths_in(
                text, "## Modified files"
            ) or changed - tasks.paths_in(text, "## Allowed paths"):
                raise Blocked("unregistered dirty changes before base sync")
            upstream = paths(
                target, "diff", "--name-only", "--no-renames", "-z", head, base
            )
            overlap = changed & upstream
            backup = Path(tempfile.mkdtemp(prefix="blueprint-base-sync-"))
            files = {}
            for number, relative in enumerate(sorted(overlap)):
                actual = tasks.safe_path(target, relative)
                if (
                    actual.exists()
                    and not actual.is_file()
                    or git(
                        target, "cat-file", "-e", head + ":" + relative, check=False
                    ).returncode
                    != 0
                ):
                    raise Blocked(
                        "base sync requires reviewed existing regular overlapping files"
                    )
                raw = actual.read_bytes() if actual.is_file() else None
                file = backup / str(number)
                if raw is not None:
                    file.write_bytes(raw)
                files[relative] = {
                    "backup": str(file) if raw is not None else None,
                    "sha256": hashlib.sha256(raw).hexdigest()
                    if raw is not None
                    else None,
                    "old": hashlib.sha256(
                        subprocess_bytes(target, head, relative)
                    ).hexdigest(),
                    "base": hashlib.sha256(
                        subprocess_bytes(target, base, relative)
                    ).hexdigest(),
                }
            intent = {
                "head": head,
                "base": base,
                "files": files,
                "contract": hashlib.sha256(text.encode()).hexdigest(),
            }
            state["baseSyncIntent"] = intent
            save(path, state)
        if (
            intent["base"] != base
            or intent["contract"] != hashlib.sha256(text.encode()).hexdigest()
        ):
            raise Blocked("base sync intent/contract changed")
        head = output(target, "rev-parse", "HEAD")
        if head not in {intent["head"], base}:
            raise Blocked("base sync HEAD changed outside its intent")
        for relative, record in intent["files"].items():
            actual = tasks.safe_path(target, relative)
            if (
                record["backup"] is not None
                and sha(Path(record["backup"])) != record["sha256"]
            ) or (sha(actual) if actual.is_file() else None) not in {
                record["sha256"],
                record["old"],
                record["base"],
            }:
                raise Blocked("base sync candidate changed; retain external backup")
        if head == intent["head"]:
            for relative in intent["files"]:
                (target / relative).write_bytes(
                    subprocess_bytes(target, head, relative)
                )
            outcome = git(
                target, "merge", "--ff-only", "--no-autostash", base, check=False
            )
            if outcome.returncode:
                for relative, record in intent["files"].items():
                    if record["backup"] is None:
                        (target / relative).unlink(missing_ok=True)
                    else:
                        (target / relative).write_bytes(
                            Path(record["backup"]).read_bytes()
                        )
                raise Blocked(
                    "base fast-forward failed; candidates restored: "
                    + outcome.stderr.strip()
                )
        for relative, record in intent["files"].items():
            if record["backup"] is None:
                (target / relative).unlink(missing_ok=True)
            else:
                (target / relative).write_bytes(Path(record["backup"]).read_bytes())
        if output(target, "rev-parse", "HEAD") != base:
            raise Blocked("base sync result differs from pinned base")
        state["tip"] = base
        state["validation_base"] = base
        state.setdefault("baseSyncs", []).append(state.pop("baseSyncIntent"))
        save(path, state)
        return state


def _worktree_runtime():
    return module("worktree_runtime.py", "worktree_runtime")


def run_deploy_publication(where, task_id, resolution=None, *, finish=False):
    """Keep the ordinary launcher dependency-free; publication uses registered Python."""
    state = load(where, task_id)[3]
    target = Path(state["worktree"])
    interpreter, environment = python_env.runtime(target)
    environment[tasks.SELECTOR] = state["task_file"]
    result = subprocess.run(
        [
            str(interpreter),
            "-B",
            "-c",
            f"import sys,json; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
            "from deploy import git_publication; "
            "operation=git_publication.finalize if sys.argv[1]=='finalize' else git_publication.publish; "
            "print(json.dumps(operation(sys.argv[2],sys.argv[3], *([sys.argv[4]] if sys.argv[4] else []))))",
            "finalize" if finish else "publish",
            str(where),
            task_id,
            str(resolution) if resolution else "",
        ],
        cwd=target,
        env=environment,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise Blocked(
            "Deploy Git publication retained: " + result.stderr + result.stdout
        )
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "create",
            "setup",
            "finalize",
            "cleanup",
            "recover",
            "repair-checkpoint",
            "repair-validate",
            "sync-base",
            "deploy-start",
            "deploy-publish",
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--human-approved-validation-failure",
        metavar="APPROVAL",
        help="Finalize a suspended task only after explicit human approval of named validation failures",
    )
    parser.add_argument("--repair-request", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-base")
    parser.add_argument(
        "--publication-resolution",
        type=Path,
        help="External JSON with explicit Human approval, current base/source and resolved conflict files; Git only",
    )
    recovery_mode = parser.add_mutually_exclusive_group()
    recovery_mode.add_argument("--finish-recovery", action="store_true")
    recovery_mode.add_argument(
        "--repin-recovery",
        action="store_true",
        help="Explicitly pin a reviewed clean recovery candidate to the latest descendant base",
    )
    args = parser.parse_args()
    if args.publication_resolution and args.command != "deploy-publish":
        parser.error("--publication-resolution requires deploy-publish")
    if (
        args.human_approved_validation_failure is not None
        and args.command != "finalize"
    ):
        parser.error("--human-approved-validation-failure is only valid with finalize")
    if args.command not in {"recover", "sync-base"} and (
        args.expected_commit
        or args.expected_base
        or args.finish_recovery
        or args.repin_recovery
    ):
        parser.error("recovery arguments require recover")
    where = args.repository_root
    try:
        if args.command not in {"create", "deploy-start"}:
            where = load(where, args.task_id)[
                0
            ]  # Keep diagnostics usable after task checkout removal.
        if args.command == "deploy-start":
            state = module("deploy/worktree.py", "deploy.worktree").start(
                where, args.task_id
            )
        elif args.command == "deploy-publish":
            state = {
                "git_publication": run_deploy_publication(
                    where, args.task_id, args.publication_resolution
                )
            }
        elif args.command == "sync-base":
            state = sync_base(where, args.task_id, args.expected_base)
        elif args.command == "repair-checkpoint":
            if not args.repair_request:
                raise Blocked("repair-checkpoint requires --repair-request")
            state = deploy_checkpoint(where, args.task_id, args.repair_request)
        elif args.command == "repair-validate":
            if not args.repair_request:
                raise Blocked("repair-validate requires --repair-request")
            state = deploy_validate(where, args.task_id, args.repair_request)
        elif args.command == "create":
            state = create(where, args.task_id, args.repair_request)
        else:
            state = (
                recover(
                    where,
                    args.task_id,
                    args.expected_commit,
                    args.expected_base,
                    args.finish_recovery,
                    args.repin_recovery,
                )
                if args.command == "recover"
                else finalize(
                    where, args.task_id, args.human_approved_validation_failure
                )
                if args.command == "finalize"
                else globals()[args.command](where, args.task_id)
            )
        print(json.dumps({"status": "ok", **state}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        retained = {}
        try:
            root, _, retained_path, retained = load(where, args.task_id)
            if not hasattr(error, "cleanup") and (
                args.command == "cleanup"
                or args.command == "finalize"
                and retained.get("merged")
            ):
                error.cleanup = cleanup_progress(
                    root, retained_path, retained, "preflight", str(error)
                )
            retained = {
                **retained,
                "remaining_worktree": retained["worktree"]
                if Path(retained["worktree"]).exists()
                else None,
                "remaining_branch": retained["branch"]
                if branch_exists(root, retained["branch"])
                else None,
            }
        except (OSError, ValueError, KeyError, TypeError):
            pass
        print(
            json.dumps(
                {
                    **retained,
                    "status": "blocked",
                    "error": str(error),
                    **({"cleanup": error.cleanup} if hasattr(error, "cleanup") else {}),
                    **(
                        {"diagnostics": error.diagnostics}
                        if hasattr(error, "diagnostics")
                        else {}
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
