#!/usr/bin/env python3
"""Create and integrate isolated task worktrees; preserve work on every failure."""

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import task_contract_core as tasks
import worktree_python as python_env
import worktree_state
from contracts.repository import PROJECT_FILENAME
from contracts.target import AWS_ACCOUNT_ID_KEY
from utils import cli_deploy
from utils.file_operations import sha
from utils.local_evidence import evidence_store as local_evidence_store
from utils.script_loader import module
from worktree_state import (
    Blocked as Blocked,
)
from worktree_state import NeedsSync as NeedsSync
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


def needs_sync(base):
    return {"status": "needs_sync", "base": base}


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
            f"worktree lifecycle busy; retain work for review: {lock}"
        ) from None
    try:
        yield
    finally:
        lock.rmdir()


def _new_worktree(primary, task_name, base, start, creation):
    for _ in range(20):
        task_id = f"{task_name}-{secrets.randbelow(1_000_000):06d}"
        state_file = state_path(primary, task_id)
        branch = f"codex/worktree/{task_id}"
        target = primary / ".worktrees" / task_id
        task_file = f"tasks/{task_id}.md"
        if any(
            path.exists() or path.is_symlink()
            for path in (
                state_file, state_file.with_suffix(".tmp"),
                state_file.with_suffix(".setup-lock"), state_file.with_suffix(".pr-lock"),
                target, primary / task_file,
            )
        ) or branch_exists(primary, branch) or output(
            primary, "ls-tree", "--name-only", start, "--", task_file
        ):
            continue
        if git(primary, "check-ignore", "--quiet", str(target), check=False).returncode:
            raise Blocked("/.worktrees/ must be ignored before creating nested worktrees")
        creation.update(
            task_name=task_name, task_id=task_id, branch=branch, worktree=str(target),
            primary=str(primary), task_file=task_file, lifecycle=str(state_file),
        )
        # A stale registration is rejected by Git before a detached add writes anything.
        # Using -b here would create the branch before Git checks that registration.
        result = git(primary, "worktree", "add", "--detach", str(target), start, check=False)
        if result.returncode:
            registered = re.search(
                r"^fatal: '([^\x00]+?)' is (?:a missing but already registered worktree;|already registered as a worktree)",
                result.stderr,
                re.M,
            )
            if (
                registered
                and Path(registered[1]).resolve() == target
                and not target.exists()
                and not target.is_symlink()
            ):
                creation.clear()
                continue
            raise Blocked(f"git worktree add failed: {result.stderr.strip() or result.stdout.strip()}")
        git(target, "switch", "-c", branch)
        return state_file, {
            key: value for key, value in creation.items() if key != "lifecycle"
        } | dict(base=base, start=start, tip=start, commit=None, verified=False, merged=None)
    raise Blocked(f"could not reserve a Task ID for {task_name} after 20 collisions")


def create(where, task_name, repair_request=None):
    _, _, primary = repository(where)
    state_path(primary, task_name)  # Apply the same lower-kebab-case rule as Task IDs.
    repair_lock = nullcontext()
    if repair_request:
        transfer = deploy_request(where, repair_request)
        if transfer[0] != primary:
            raise Blocked("repair parent belongs to another repository")
        repair_lock = _worktree_runtime().deploy_handoff.locked(
            Path(transfer[-1]["requestPath"])
        )
    creation = {}
    try:
        with lifecycle_lock(primary), repair_lock:
            transfer = deploy_request(where, repair_request) if repair_request else None
            request = transfer[-1] if transfer else None
            if request:
                parent = Path(request["repository"])
                if tasks.status(
                    tasks.read_task_snapshot(parent, request["taskFile"], live=True).text
                ) != "suspend":
                    raise Blocked("suspend the original deploy Task before child creation")
                if transfer[-2]["iacRepair"].get("childTask") is not None:
                    raise Blocked("one-shot request already owns an implement child")
                if transfer[0] != primary:
                    raise Blocked("repair parent belongs to another repository")
            base = request["parentBranch"] if request else base_branch(primary)
            start = output(primary, "rev-parse", f"refs/heads/{base}")
            if request and start != request["parentTip"]:
                raise Blocked("repair parent tip changed")
            state_file, state = _new_worktree(primary, task_name, base, start, creation)
            if request:
                state["deployRepair"] = request["requestPath"]
            if request:
                parent_state = transfer[-2]
                parent_state["iacRepair"]["childTask"] = state["task_id"]
                save(transfer[1], parent_state)
            state_file.parent.mkdir(exist_ok=True)
            save(state_file, state)
        return setup(primary, state["task_id"])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, KeyboardInterrupt) as error:
        if isinstance(error, KeyboardInterrupt):
            error = Blocked("worktree creation interrupted")
        error.creation = creation
        raise error


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
            root, common, path, state = load(root, task_id)
            target = task_worktree(root, state)
            if state.get("integrationMode") == "pr":
                raise Blocked(
                    "PR Task retains its registered environment; setup refused"
                )
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
                f"Python setup failed; worktree retained: {message}"
            ) from error
        save(path, state)
        return state
    finally:
        lock.rmdir()


def integration_task(target, state, *, candidate_common=None):
    snapshot = tasks.read_task_snapshot(target, state["task_file"], live=True)
    text = snapshot.text
    if "- Infrastructure phase: `deploy`" in text.splitlines():
        worktree_state.deploy_start_commit(
            target, state["task_file"], allow_merged=True
        )
    elif candidate_common is None:
        task_start_commit(target, state["task_file"])
    else:
        _, common = worktree_state._repository_identity(target)
        if common != candidate_common:
            raise Blocked("task worktree belongs to another repository")
        worktree_state._task_history(
            target, state["task_file"], state, merge_base=False
        )
    current = tasks.status(text)
    if current != "completed":
        raise Blocked(f"task must be completed for integration; current status: {current}")


def base_worktree(root, state):
    _, _, primary = repository(root)
    if output(primary, "branch", "--show-current") != state["base"]:
        raise Blocked("local base must be checked out in the primary worktree")
    idle_git(primary)
    if git(primary, "status", "--porcelain", "--untracked-files=all").stdout:
        raise Blocked(
            f"base worktree is dirty: {primary}; task commit/worktree retained"
        )
    return primary


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


def cleanup_progress(
    root: Path, path: Path, state: dict, phase: str, reason: str | None = None,
    *, directory: Path | None = None,
) -> dict:
    target = Path(state["worktree"])
    if directory is None and target.is_dir():
        try:
            _, common = worktree_state._repository_identity(root)
            directory = worktree_state.task_git_directory(common, target)
        except (OSError, ValueError):
            pass  # An unknown registration must be reported as unknown.
    return {
        "phase": phase,
        "stop_reason": reason,
        "remaining": {
            "worktree": target.exists() or target.is_symlink(),
            "git_registration": None if directory is None else directory.exists(),
            "branch": branch_exists(root, state["branch"]),
            "task_state": path.exists(),
        },
    }


def deploy_cleanup_task(target, state):
    """Only the published final receipt may restore/remove its own untracked contract."""
    if not state.get("deployIdentity"):
        return None
    publication = state.get("deployPublication", {})
    final = publication.get("finalCandidate")
    name = state["task_file"]
    if not final or name in paths(target, "ls-files", "--cached", "-z", "--", name):
        return None
    before, after = final.get("taskBefore", ""), final.get("taskAfter", "")
    if (
        publication.get("status") != "SUCCESS"
        or publication.get("publishedSource") != state["tip"]
        or publication.get("commit") != state["merged"]
        or final.get("source") != state["tip"]
        or final.get("tree") != output(target, "rev-parse", state["tip"] + "^{tree}")
        or tasks.status(before) != "running"
        or tasks.status(after) != "completed"
        or tasks.set_status(before, "completed") != after
        or tasks.task_digest(after) != state["deployIdentity"]["taskDigest"]
    ):
        raise Blocked(
            "untracked Deploy Task differs from its published final candidate"
        )
    path = tasks.safe_path(target, name)
    if not path.exists():
        tasks.atomic_files({path: after}, staging_directory=target)
        tasks.invalidate_task_reads(target)
    if path.read_bytes() != after.encode("utf-8"):
        raise Blocked("untracked Deploy Task changed before cleanup")
    return path


def cleanup_state(root, path, state, *, discard=False):
    phase = "verify_merge"
    directory = None
    try:
        if not discard:
            if state.get("githubMerged"):
                if state.get("prPublication", {}).get("prState") != "MERGED":
                    raise Blocked("automatic cleanup requires a confirmed PR merge")
            else:
                if not state["merged"] or not ancestor(
                    root, state["merged"], state["base"]
                ):
                    raise Blocked("cleanup requires a verified successful merge")
                if state["commit"] and not ancestor(
                    root, state["commit"], state["base"]
                ):
                    raise Blocked(
                        "base no longer contains the task commit; cleanup refused"
                    )
        phase = "verify_worktree"
        target = Path(state["worktree"])
        if target.is_symlink() or target.parent.is_symlink():
            raise Blocked("task worktree path is a symlink; cleanup refused")
        if path.with_suffix(".setup-lock").exists():
            raise Blocked("Python setup busy; cleanup refused")
        if not target.is_dir():
            raise Blocked("missing worktree; exact Git registration cannot be verified")
        target = task_worktree(root, state)
        _, common = worktree_state._repository_identity(root)
        directory = worktree_state.task_git_directory(common, target)
        if any(
            not (directory / name).is_file() or (directory / name).is_symlink()
            for name in ("HEAD", "index")
        ) or any(directory.rglob("*.lock")):
            raise Blocked("task worktree Git HEAD/index is unavailable, redirected or locked")
        ref = f"refs/heads/{state['branch']}"
        checkout = output(root, "for-each-ref", "--format=%(worktreepath)", ref)
        if checkout and Path(checkout).resolve() != target:
            raise Blocked("task branch is used by another worktree; cleanup refused")
        tip = output(root, "rev-parse", "--verify", ref)
        untracked_task = None
        if not discard:
            if tip != state["tip"] or (
                not state.get("githubMerged") and not ancestor(root, tip, state["base"])
            ):
                raise Blocked("temporary branch changed or is unmerged; cleanup refused")
            untracked_task = deploy_cleanup_task(target, state)
            integration_task(target, state)
            changed = changed_paths(target)
            if untracked_task is not None:
                changed.discard(state["task_file"])
            if changed:
                raise Blocked("task worktree is dirty; cleanup refused")
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
        phase = "remove_worktree"
        if untracked_task is not None and state["task_file"] in changed_paths(target):
            deploy_cleanup_task(target, state).unlink()
        git(root, "worktree", "remove", *(["--force"] if discard else []), str(target))
        phase = "remove_branch"
        git(root, "branch", "-D", state["branch"])
        phase = "verify_removal"
        remaining = cleanup_progress(root, path, state, phase, directory=directory)["remaining"]
        if any(remaining[key] for key in ("worktree", "git_registration", "branch")):
            raise Blocked("local cleanup is incomplete; retain Task state for review")
        retained_evidence = []
        if discard:
            try:
                if state.get("deployIdentity"):
                    progress = (
                        local_evidence_store(target, create=False)
                        / "deploy-progress.json"
                    )
                    if progress.exists() or progress.is_symlink():
                        retained_evidence.append(str(progress))
            except (OSError, ValueError) as error:
                retained_evidence.append(
                    {"external_evidence_inspection_error": str(error)}
                )
            for key in ("deployRepair", "deployIdentity", "iacRepair"):
                if state.get(key):
                    retained_evidence.append({key: state[key]})
        else:
            phase = "remove_repair_proof"
            if state.get("deployRepair"):
                _worktree_runtime().deploy_handoff.discard_request(state)
            if state.get("deployIdentity"):
                phase = "remove_deploy_progress"
                module("deploy/progress.py", "deploy.progress").discard_progress(state)
        phase = "remove_state"
        path.unlink()
        return {
            **state,
            "cleaned": True,
            "retained_external_evidence": retained_evidence,
            "cleanup": cleanup_progress(root, path, state, "complete", directory=directory),
        }
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        error.cleanup = {"phase": phase, "stop_reason": str(error)}
        try:
            error.cleanup = cleanup_progress(root, path, state, phase, str(error), directory=directory)
        except (OSError, ValueError, KeyError, TypeError) as inspection_error:
            error.cleanup["inspection_error"] = str(inspection_error)
        raise


def cleanup(where, task_id):
    root, common, path, state = load(where, task_id)
    publication = module("worktree_pr.py", "worktree_pr")
    with publication.publication_lock(path), lifecycle_lock(root):
        root, _, path, state = load(root, task_id)
        return cleanup_state(root, path, state, discard=True)


def automatic_cleanup(where, task_id, *, publication_held=False):
    root, _, path, state = load(where, task_id)
    publication = module("worktree_pr.py", "worktree_pr")
    lock = nullcontext() if publication_held else publication.publication_lock(path)
    with lock, lifecycle_lock(root):
        root, _, path, state = load(root, task_id)
        return cleanup_state(root, path, state)


def delete_branch(where, branch):
    root, _, primary = repository(where)
    if not branch or not branch.startswith("codex/worktree/"):
        raise Blocked("specify one exact codex/worktree/<task-id> local branch")
    path = state_path(primary, branch.removeprefix("codex/worktree/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    publication = module("worktree_pr.py", "worktree_pr")
    with publication.publication_lock(path), lifecycle_lock(primary):
        if path.exists() or path.is_symlink():
            raise Blocked("Task lifecycle exists; use cleanup --task-id instead")
        git(root, "branch", "-D", branch)
        return {
            "deleted_branch": branch,
            "remaining_branch": branch_exists(root, branch),
        }


def _run_model_guard(
    target,
    task_file,
    *,
    sources=None,
    deploy_scope=False,
    validation_base=None,
):
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
        "import task_contract_core as tasks; from import_guard import require_import_changes; "
        + (
            "from deploy.git_publication import check_scope_in_process; "
            if deploy_scope
            else ""
        )
        + "root = Path.cwd()\n"
        "options = {}\n"
        'if sys.argv[2] != "null": options["supplied"] = set(json.loads(sys.argv[2]))\n'
        "with tasks.selected_task(root, sys.argv[1]):\n"
        + ("    check_scope_in_process(root, sys.argv[1])\n" if deploy_scope else "")
        + "    text = tasks.read_task_snapshot(root, sys.argv[1], live=True).text\n"
        "    if '- Workflow: `import`' in tasks.section(text, '## Task contract'):\n"
        "        from task_contract_runtime import check_import\n"
        "        check_import(root, sys.argv[1], supplied=options.get('supplied'), integration=True)\n"
        "    else:\n"
        "        require_import_changes(root, **options)\n"
        "    if '- Workflow: `import`' not in tasks.section(text, '## Task contract') and '## Out-of-task FAIL approvals' in text:\n"
        "        from validation.runner import Validator\n"
        "        validator = Validator(root, tasks.active_scope(root, task_file=sys.argv[1]), cache=False, model_validation='change')\n"
        "        validator.run()\n"
        "        if validator.display_report(): raise ValueError('Task Acceptance FAIL; no integration')\n"
        "    if len(sys.argv) > 3:\n"
        "        from utils.cli_deploy import validate_candidate\n"
        "        validate_candidate(root, sys.argv[1], sys.argv[3])",
        task_file,
        serialized_sources,
        *([validation_base] if validation_base is not None else []),
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
    target,
    state,
    changed,
    text,
    parsed_operation,
    *,
    scope_paths,
    published_head=None,
    ordinary_model=False,
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
        outside = sorted(
            scope_paths - declared
            | {
                p
                for p in scope_paths
                if not any(tasks.matches(p, pattern) for pattern in allowed)
            }
        )
        raise Blocked(
            "integration changes are outside the exact task contract: "
            + ", ".join(outside)
        )
    if any(p.startswith("tasks/") for p in changed):
        raise Blocked("contracts must remain ignored; nothing committed")
    head = output(target, "rev-parse", "HEAD")
    if published_head is not None:
        if not ancestor(target, published_head, state["branch"]):
            raise Blocked("PR update must descend from the published HEAD")
    elif not ordinary_model and head != state["tip"]:
        raise Blocked("unexpected commits on task branch; review required")
    if published_head is None and not ordinary_model and state["commit"] and changed:
        synchronized_framework = (
            state.get("validation_base")
            and state["commit"] == head
            and tasks.final_framework_task(text, scope_paths)
            and ancestor(target, state["validation_base"], state["branch"])
        )
        if not synchronized_framework and (
            parsed_operation is None or parsed_operation.action != "model-delete"
        ):
            raise Blocked(
                "task changed after commit; rerun its workflow before integration"
            )
    return head


def integration_changed_paths(target, task_file):
    return changed_paths(target) | (committed_task_paths(target, task_file) or set())


def _block_invalid_model_contract(text, name):
    errors = tasks.model_only_declaration_errors(text, name)
    if errors:
        raise Blocked(
            "Model-only Task contract invalid.\n\n"
            + "\n".join(errors)
            + "\n\nCorrect the existing Task contract and retry finalize. "
            "Keep the Task running and retain its worktree."
        )


def _prepare_commit(
    root,
    path,
    state,
    target,
    *,
    pr_update=False,
    prepare_only=False,
):
    if state.get("baseSyncIntent") or state.get("latestBaseSync"):
        raise Blocked("previous base synchronization did not finish; retain worktree for review")
    changed = changed_paths(target)
    task_id = state["task_id"]
    sync_base = state.get("prUpdate", {}).get("syncBase") if pr_update else None
    model_changes = (
        changed
        | paths(target, "diff", "--no-renames", "--name-only", "-z", sync_base, "HEAD")
        if sync_base
        else integration_changed_paths(target, state["task_file"])
    )
    contract = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    _block_invalid_model_contract(contract, state["task_file"])
    operation = tasks.final_model_task(contract, model_changes)
    parsed_operation = tasks.model_operation(contract)
    ordinary_model = (
        operation
        and parsed_operation is None
        and tasks.model_refactor(contract) is None
        and not pr_update
        and state.get("integrationMode") != "pr"
    )
    head = _commit_preconditions(
        target,
        state,
        changed,
        contract,
        parsed_operation,
        scope_paths=model_changes,
        published_head=state["prUpdate"]["previousCandidate"] if pr_update else None,
        ordinary_model=ordinary_model,
    )
    if ordinary_model:
        base = state.get("validation_base", state["start"])
        if git(
            target, "merge-base", "--is-ancestor", base, head, check=False
        ).returncode or output(target, "rev-list", "--merges", base + ".." + head):
            raise Blocked(
                f"cannot reconstruct a linear Task candidate: HEAD {head}, base {base}"
            )
    if not pr_update and state.get("integrationMode") != "pr":
        base_worktree(root, state)
    if (
        not pr_update
        and not prepare_only
        and state.get("integrationMode") != "pr"
    ):
        latest = output(root, "rev-parse", f"refs/heads/{state['base']}")
        if latest != state.get("validation_base", state["start"]):
            raise NeedsSync(latest)
    if not operation and (
        "- Workflow: `import`" in tasks.section(contract, "## Task contract")
        or "## Out-of-task FAIL approvals" in contract
        or any(p.startswith("model/") or p == PROJECT_FILENAME for p in model_changes)
    ):
        integration_task(target, state)
        index = output(
            target, "diff", "--cached", "--raw", "--no-abbrev", "--no-renames"
        )
        before = {
            p: (target / p).read_bytes() if (target / p).is_file() else None
            for p in changed
        }
        _run_model_guard(target, state["task_file"])
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
        integration_task(target, state)
        head = _commit_preconditions(
            target,
            state,
            changed,
            current,
            parsed_operation,
            scope_paths=model_changes,
            published_head=state["prUpdate"]["previousCandidate"]
            if pr_update
            else None,
            ordinary_model=ordinary_model,
        )
    if changed:
        whitespace = git(target, "config", "--get", "core.whitespace", check=False)
        if whitespace.returncode not in (0, 1):
            raise Blocked("cannot determine Git whitespace checks")
        rules = (
            whitespace.stdout.strip() or "blank-at-eol,blank-at-eof,space-before-tab"
        )
        diff_check = ("-c", "core.whitespace=" + rules + ",cr-at-eol", "diff")
        git(target, *diff_check, "--check")
        git(target, *diff_check, "--cached", "--check")
        literal = [f":(top,literal){p}" for p in sorted(changed)]
        git(target, "add", "--", *literal)
        # Staged edits canceled by working-tree edits are an effective zero-change task.
        changed = paths(target, "diff", "--cached", "--no-renames", "--name-only", "-z")
    if changed:
        tree = output(target, "write-tree")
        message = (
            f"task({task_id}): Model operation candidate"
            if operation
            else f"task({task_id}): completed task"
        )
        git(target, "commit", "-m", message)
        state["commit"] = output(target, "rev-parse", "HEAD")
        state["tip"] = state["commit"]
        state["verified"] = False
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
    elif ordinary_model and (state["tip"] != head or state["commit"] != head):
        state.update(tip=head, commit=head, verified=True)
        save(path, state)
    if changed_paths(target):
        raise Blocked("task worktree changed during commit; review required")
    if prepare_only:
        return None
    if state.get("integrationMode") == "pr" and not pr_update:
        return state.get("validation_base", state["start"])
    if pr_update:
        # Published history is never rebased during PR updates.
        state.update(tip=output(target, "rev-parse", "HEAD"), verified=True)
        state["commit"] = state["tip"]
        save(path, state)
        return None
    base = base_worktree(root, state)
    latest = output(root, "rev-parse", f"refs/heads/{state['base']}")
    if git(
        target, "merge-base", "--is-ancestor", latest, "HEAD", check=False
    ).returncode:
        raise Blocked(
            "recorded base is not an ancestor of the candidate; review required"
        )
    if changed_paths(target):
        raise Blocked("task worktree changed before merge; review required")
    base = base_worktree(
        root, state
    )  # Recheck dirty/operation state immediately before merge.
    current_base = output(base, "rev-parse", "HEAD")
    if current_base != latest:
        raise NeedsSync(current_base)
    return latest


def finalize(
    where,
    task_id,
    *,
    create_pr=False,
    draft=False,
):
    root, _, path, state = load(where, task_id)
    if (
        create_pr
        and not (
            state.get("deployIdentity") or state.get("deployRepair") or state["merged"]
        )
        and cli_deploy.is_cli(
            tasks.read_task_snapshot(
                Path(state["worktree"]), state["task_file"], live=True
            ).text
        )
    ):
        raise Blocked("PR publication is unavailable for Deploy tasks")
    if create_pr and (
        state.get("deployIdentity") or state.get("deployRepair") or state["merged"]
    ):
        raise Blocked(
            "PR publication is unavailable for Deploy, repair or merged tasks"
        )
    publication = module("worktree_pr.py", "worktree_pr")
    with publication.publication_lock(path):
        state = load(root, task_id)[3]
        if state.get("deployIdentity") or state.get("deployRepair") or state["merged"]:
            if create_pr:
                raise Blocked(
                    "PR publication is unavailable for Deploy, repair or merged tasks"
                )
            return _finalize(root, task_id)
        if create_pr:
            return publication.finalize(
                root, task_id, draft=draft
            )
        if state.get("integrationMode") == "pr":
            raise Blocked(
                "Task selected PR publication; use finalize --create-pr"
            )
        return _finalize(root, task_id)


def _finalize(where, task_id):
    root, common, path, state = load(where, task_id)
    if state.get("deployIdentity") and not state.get("merged"):
        run_deploy_publication(where, task_id, finish=True)
        return automatic_cleanup(root, task_id, publication_held=True)
    if state.get("deployRepair"):
        return deploy_finalize(where, task_id)
    if not state["merged"]:
        target = task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        _block_invalid_model_contract(text, state["task_file"])
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
            if result.stdout.startswith("NEEDS_SYNC="):
                return needs_sync(result.stdout.removeprefix("NEEDS_SYNC=").strip())
            if state.get("integrationMode") == "pr":
                return load(root, task_id)[3]
            # The surviving launcher owns cleanup, after the registered child exits.
            return automatic_cleanup(root, task_id, publication_held=True)
        lines = tasks.section(text, "## Task contract")
        workflows = [line for line in lines if re.match(r"-\s*Workflow\b", line)]
        if len(workflows) <= 1 and tasks.status(text) == "running":
            corrected = re.sub(
                r"(?ms)^## Task contract\n.*?(?=^## |\Z)",
                lambda _: "## Task contract\n"
                + "\n".join(line for line in lines if line not in workflows)
                + "\n- Workflow: `update`\n",
                text,
                count=1,
            )
            if tasks.final_model_task(
                corrected,
                partial(integration_changed_paths, target, state["task_file"]),
            ):
                current = (
                    workflows[0].partition(":")[2].strip().strip("`")
                    if workflows
                    else "missing"
                )
                raise Blocked(
                    f"Model-only finalize: set `Workflow: update` (current: {current}), "
                    "and keep task status running."
                )
    with lifecycle_lock(root):
        if path.with_suffix(".setup-lock").exists():
            raise Blocked("Python setup busy; integration refused")
        if state.get("python_setup", {}).get("status") != "ready":
            raise Blocked("Python setup is incomplete; retry setup before integration")
        if state["merged"]:
            return cleanup_state(root, path, state)
        target = task_worktree(root, state)
        integration_task(target, state)
        latest = _prepare_commit(root, path, state, target)
        expected = output(target, "rev-parse", "HEAD")
        model_paths = paths(
            target, "diff", "--name-only", "--no-renames", "-z", latest, expected
        )
        contract = tasks.read_task_snapshot(target, state["task_file"], live=True).raw
        direct_cli = cli_deploy.is_cli(contract.decode("utf-8"))
        if (
            any(p.startswith("model/") or p == PROJECT_FILENAME for p in model_paths)
            or b"- Workflow: `import`" in contract
            or b"## Out-of-task FAIL approvals" in contract
            or direct_cli
        ):
            _run_model_guard(
                target,
                state["task_file"],
                sources=model_paths,
                **({"validation_base": latest} if direct_cli else {}),
            )
            if (
                output(target, "rev-parse", "HEAD") != expected
                or changed_paths(target)
                or tasks.read_task_snapshot(target, state["task_file"], live=True).raw
                != contract
            ):
                raise Blocked(
                    "validated candidate, Task or base changed before merge; retain worktree"
                )
        if state.get("integrationMode") == "pr":
            return module("worktree_pr.py", "worktree_pr").prepare(
                root, path, state, latest, expected
            )
        base = base_worktree(root, state)
        current_base = output(base, "rev-parse", "HEAD")
        if current_base != latest:
            raise NeedsSync(current_base)
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
        root, _, path, state = load(candidate.root, Path(candidate.task_file).stem)
        target = task_worktree(root, state)
        if (
            target != candidate.root
            or changed_paths(target)
            or output(target, "rev-parse", "HEAD") != candidate.candidate_head
        ):
            raise Blocked("validated candidate/base changed; no merge")
        base = (
            None if state.get("integrationMode") == "pr" else base_worktree(root, state)
        )
        if (
            base is not None
            and output(base, "rev-parse", "HEAD") != candidate.base_commit
        ):
            raise NeedsSync(output(base, "rev-parse", "HEAD"))
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
        if (
            tasks.read_task_snapshot(target, candidate.task_file, live=True).text
            != text
            or changed_paths(target)
            or output(target, "rev-parse", "HEAD") != candidate.candidate_head
        ):
            raise Blocked("validated state changed during task completion; no merge")
        if (
            base is not None
            and output(base, "rev-parse", "HEAD") != candidate.base_commit
        ):
            raise NeedsSync(output(base, "rev-parse", "HEAD"))
        if state.get("integrationMode") == "pr":
            if text != completed:
                tasks.atomic_files({task_path: completed}, staging_directory=target)
            return module("worktree_pr.py", "worktree_pr").prepare(
                root, path, state, candidate.base_commit, candidate.candidate_head
            )
        git(base, "merge", "--ff-only", "--no-autostash", state["branch"])
        if output(
            base, "rev-parse", "HEAD"
        ) != candidate.candidate_head or not ancestor(
            root, candidate.candidate_head, state["base"]
        ):
            raise Blocked("merge result differs from validated candidate")
        state["merged"] = candidate.candidate_head
        save(path, state)
        if text != completed:
            tasks.atomic_files({task_path: completed}, staging_directory=target)
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
        except NeedsSync as notice:
            print("NEEDS_SYNC=" + notice.base)
            return
        except (OSError, ValueError, KeyError, TypeError) as error:
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
        f"- Target AWS account: `{request['target'][AWS_ACCOUNT_ID_KEY]}`",
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


def verify_rebase_commits(target, old_commits, new_commits, old_parent, new_parent):
    for old, new in zip(old_commits, new_commits, strict=True):
        if (
            output(target, "show", "-s", "--format=%P", old) != old_parent
            or output(target, "show", "-s", "--format=%P", new) != new_parent
        ):
            raise Blocked("base rebase has unexpected commit parents")
        # A temporary commit makes Git use the original parent as the merge base.
        synthetic = output(
            target,
            "-c",
            "user.name=Blueprint verification",
            "-c",
            "user.email=blueprint-verification@invalid",
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            new_parent + "^{tree}",
            "-p",
            old_parent,
            "-m",
            "Rebase verification",
        )
        replay = git(target, "merge-tree", "--write-tree", synthetic, old, check=False)
        if (
            replay.returncode
            or not replay.stdout.splitlines()
            or replay.stdout.splitlines()[0]
            != output(target, "rev-parse", new + "^{tree}")
        ):
            raise Blocked("base rebase commit differs from its intended replay")
        old_parent, new_parent = old, new
    return old_parent, new_parent


def sync_latest_base(where, task_id, expected_base):
    """Replay a reviewed local task history onto the latest base without validation."""
    root, _, path, _ = load(where, task_id)
    publication = module("worktree_pr.py", "worktree_pr")
    with publication.publication_lock(path):
        with lifecycle_lock(root):
            root, _, path, state = load(root, task_id)
            if (
                state.get("prPublication")
                or state.get("integrationMode") == "pr"
                or state.get("deployIdentity")
                or state.get("deployRepair")
                or state["merged"]
                or state.get("baseSyncIntent")
            ):
                raise Blocked("local base sync requires an ordinary unmerged Task")
            if (
                path.with_suffix(".setup-lock").exists()
                or state.get("python_setup", {}).get("status") != "ready"
            ):
                raise Blocked("Python setup must finish before base sync")
            target = task_worktree(root, state)
            base = base_worktree(root, state)
            latest = output(base, "rev-parse", "HEAD")
            if not expected_base or latest != expected_base:
                raise Blocked("review the exact latest base before sync")
            text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
            if tasks.status(text) not in {"running", "completed"}:
                raise Blocked("base sync requires a running/completed Task")
            if state.get("latestBaseSync"):
                raise Blocked("previous base rebase outcome is unknown; retain worktree for review")
            if latest == state.get("validation_base", state["start"]):
                ordinary_model = (
                    tasks.final_model_task(
                        text, integration_changed_paths(target, state["task_file"])
                    )
                    and tasks.model_operation(text) is None
                    and tasks.model_refactor(text) is None
                )
                if ordinary_model:
                    head = output(target, "rev-parse", "HEAD")
                    unchanged = (
                        not changed_paths(target)
                        and state["tip"] == head
                        and state["commit"] == head
                    )
                    _prepare_commit(
                        root, path, state, target, prepare_only=True
                    )
                    candidate = output(target, "rev-parse", "HEAD")
                    return {
                        **state,
                        "status": "ok" if unchanged and candidate == head else "needs_validation",
                        "candidate": candidate,
                    }
                if (
                    changed_paths(target)
                    or output(target, "rev-parse", "HEAD") != state["tip"]
                ):
                    raise Blocked("task candidate changed; review required")
                return {
                    **state,
                    "status": "ok",
                    "candidate": state["tip"],
                }
            _prepare_commit(root, path, state, target, prepare_only=True)
            head = output(target, "rev-parse", "HEAD")
            old_base = state.get("validation_base", state["start"])
            if git(
                target, "merge-base", "--is-ancestor", old_base, head, check=False
            ).returncode or output(
                target, "rev-list", "--merges", old_base + ".." + head
            ):
                raise Blocked(
                    "task history is not linear from its recorded base; review required"
                )
            commits = output(
                target, "rev-list", "--reverse", old_base + ".." + head
            ).splitlines()
            synthetic = output(
                target,
                "-c", "user.name=Blueprint verification",
                "-c", "user.email=blueprint-verification@invalid",
                "-c", "commit.gpgsign=false",
                "commit-tree", latest + "^{tree}", "-p", old_base,
                "-m", "Base sync verification",
            )
            tree_result = git(
                target, "merge-tree", "--write-tree", synthetic, head, check=False
            )
            if tree_result.returncode:
                raise Blocked(
                    "base and Task conflict; retain the committed candidate for review"
                )
            tree = tree_result.stdout.splitlines()[0]
            if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
                raise Blocked("cannot determine the base merge tree")
            candidate_paths = paths(
                target, "diff", "--no-renames", "--name-only", "-z", latest, tree
            )
            declared = tasks.paths_in(text, "## Modified files")
            allowed = tasks.paths_in(text, "## Allowed paths")
            if candidate_paths - declared or any(
                not any(tasks.matches(p, pattern) for pattern in allowed)
                for p in candidate_paths
            ):
                raise Blocked(
                    "base merge changes are outside the exact task contract"
                )
            intent = state["latestBaseSync"] = {
                "head": head,
                "oldBase": old_base,
                "commits": commits,
                "base": latest,
                "tree": tree,
                "taskHash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
            save(path, state)
            if (
                git(
                    root,
                    "merge-base",
                    "--is-ancestor",
                    intent["base"],
                    latest,
                    check=False,
                ).returncode
                or intent["taskHash"]
                != hashlib.sha256(text.encode("utf-8")).hexdigest()
                or tasks.read_task_snapshot(target, state["task_file"], live=True).text
                != text
                or changed_paths(target)
            ):
                raise Blocked("base sync intent or Task changed; review required")
            sync_base = intent["base"]
            idle_git(target)
            if output(target, "rev-parse", "HEAD") != intent["head"]:
                raise Blocked("task HEAD changed before base rebase; retain worktree for review")
            result = git(
                target,
                "-c",
                "rebase.updateRefs=false",
                "rebase",
                "--no-autostash",
                "--no-fork-point",
                "--reapply-cherry-picks",
                "--empty=keep",
                "--onto",
                sync_base,
                intent["oldBase"],
                check=False,
            )
            if result.returncode:
                raise Blocked(
                    "base rebase failed; retain worktree and Git operation for review: "
                    + (result.stderr.strip() or result.stdout.strip())
                )
            head = output(target, "rev-parse", "HEAD")
            commits = output(
                target, "rev-list", "--reverse", sync_base + ".." + head
            ).splitlines()
            if (
                git(
                    target, "merge-base", "--is-ancestor", sync_base, head, check=False
                ).returncode
                or len(commits) != len(intent["commits"])
                or any(
                    output(target, "show", "-s", "--format=%an%n%ae%n%aI%n%B", old)
                    != output(target, "show", "-s", "--format=%an%n%ae%n%aI%n%B", new)
                    for old, new in zip(intent["commits"], commits, strict=True)
                )
                or output(target, "rev-list", "--merges", sync_base + ".." + head)
                or output(target, "rev-parse", head + "^{tree}") != intent["tree"]
                or changed_paths(target)
                or tasks.read_task_snapshot(target, state["task_file"], live=True).text
                != text
            ):
                raise Blocked(
                    "base rebase differs from its recorded intent; review required"
                )
            if (
                intent["oldBase"] != state.get("validation_base", state["start"])
                or intent["head"] != state["tip"]
                or output(
                    target,
                    "rev-list",
                    "--reverse",
                    intent["oldBase"] + ".." + intent["head"],
                ).splitlines()
                != intent["commits"]
            ):
                raise Blocked("base rebase intent has unexpected Task history")
            old_parent, new_parent = verify_rebase_commits(
                target, intent["commits"], commits, intent["oldBase"], sync_base
            )
            if old_parent != intent["head"] or new_parent != head:
                raise Blocked("base rebase history differs from its recorded intent")
            idle_git(target)
            current_base = output(base_worktree(root, state), "rev-parse", "HEAD")
            if (
                git(
                    root,
                    "merge-base",
                    "--is-ancestor",
                    latest,
                    current_base,
                    check=False,
                ).returncode
                or output(target, "rev-parse", "HEAD") != head
                or changed_paths(target)
                or tasks.read_task_snapshot(target, state["task_file"], live=True).text
                != text
            ):
                raise Blocked("base or Task changed during rebase verification")
            state.update(
                tip=head, commit=head, verified=True, validation_base=sync_base
            )
            del state["latestBaseSync"]
            save(path, state)
            if current_base != sync_base:
                return needs_sync(current_base)
            unchanged_task = (
                output(target, "rev-parse", intent["head"] + "^{tree}")
                == output(target, "rev-parse", intent["oldBase"] + "^{tree}")
                and intent["tree"] == output(target, "rev-parse", sync_base + "^{tree}")
            )
            return {
                **state,
                "status": "ok" if unchanged_task else "needs_validation",
                "latest_base": sync_base,
                "candidate": head,
            }


def sync_base(where, task_id, expected_base):
    """Explicit fresh-task base FF, preserving reviewed uncommitted paths externally.

    No task commit is created and no own committed history is removed. Overlapping
    candidates must already contain the reviewed upstream changes; their bytes are
    preserved exactly. This is a base update, never a validation/completion receipt.
    """

    root, _, path, state = load(where, task_id)
    pr_mode = state.get("integrationMode") == "pr"
    publication_lock = (
        module("worktree_pr.py", "worktree_pr").publication_lock(path)
        if pr_mode
        else nullcontext()
    )
    with publication_lock, lifecycle_lock(root):
        root, _, path, state = load(root, task_id)
        if (state.get("integrationMode") == "pr") != pr_mode:
            raise Blocked("Task integration mode changed before base sync")
        if pr_mode and (
            any(key in state for key in ("prPublication", "prUpdate", "githubMerged"))
            or state.get("verified")
            or state.get("deployIdentity")
            or state.get("deployRepair")
            or state.get("latestBaseSync")
            or path.with_suffix(".setup-lock").exists()
            or state.get("python_setup", {}).get("status") != "ready"
        ):
            raise Blocked("PR Task intent is immutable; base sync refused")
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
        if state.get("baseSyncIntent"):
            raise Blocked("previous base synchronization did not finish; retain worktree for review")
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
            "branch-delete",
            "pr-select",
            "pr-update",
            "pr-sync-base",
            "pr-merge",
            "pr-status",
            "pr-close",
            "pr-draft",
            "pr-ready",
            "repair-checkpoint",
            "repair-validate",
            "sync-base",
            "sync-latest-base",
            "deploy-publish",
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--task-name")
    parser.add_argument("--task-id")
    parser.add_argument(
        "--branch", help="One explicit orphan local codex/worktree branch"
    )
    parser.add_argument(
        "--pr", help="Explicit PR number or URL for pr-close after cleanup"
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create a Draft PR; never changes an existing PR's draft state",
    )
    parser.add_argument(
        "--merge-method", choices=("merge", "squash", "rebase"), default=None
    )
    parser.add_argument(
        "--create-pr",
        action="store_true",
        help="Publish a validated PR only on explicit Human request; retain worktree without local merge",
    )
    parser.add_argument("--repair-request", type=Path)
    parser.add_argument("--expected-base")
    parser.add_argument(
        "--publication-resolution",
        type=Path,
        help="External JSON with explicit Human approval, current base/source and resolved conflict files; Git only",
    )
    args = parser.parse_args()
    creating = args.command == "create"
    if creating:
        if not args.task_name or args.task_id is not None:
            parser.error("create requires --task-name instead of --task-id")
    elif args.task_name is not None:
        parser.error("--task-name requires create")
    elif args.command == "branch-delete" or args.pr:
        if args.task_id is not None:
            parser.error("branch-delete and explicit --pr do not accept --task-id")
    elif not args.task_id:
        parser.error("--task-id is required for this operation")
    if args.draft and not (args.command == "finalize" and args.create_pr):
        parser.error("--draft requires finalize --create-pr")
    if (
        args.branch
        and args.command != "branch-delete"
        or args.command == "branch-delete"
        and not args.branch
    ):
        parser.error("--branch is required only for branch-delete")
    if args.pr and args.command != "pr-close":
        parser.error("--pr requires pr-close")
    if args.merge_method and args.command != "pr-merge":
        parser.error("--merge-method requires pr-merge")
    if args.create_pr and args.command != "finalize":
        parser.error("--create-pr is only valid with finalize")
    if args.publication_resolution and args.command != "deploy-publish":
        parser.error("--publication-resolution requires deploy-publish")
    if args.expected_base and args.command not in {"sync-base", "sync-latest-base", "pr-sync-base"}:
        parser.error("--expected-base requires a base synchronization command")
    if args.repair_request and args.command not in {"create", "repair-checkpoint", "repair-validate"}:
        parser.error("--repair-request requires create, repair-checkpoint or repair-validate")
    where = args.repository_root
    try:
        if not creating and args.command != "branch-delete" and not args.pr:
            where = load(where, args.task_id)[0]
        if args.command == "branch-delete":
            state = delete_branch(where, args.branch)
        elif args.command.startswith("pr-"):
            publication = module("worktree_pr.py", "worktree_pr")
            if args.pr:
                state = publication.close_existing(where, args.pr)
            elif args.command == "pr-select":
                state = publication.select(where, args.task_id)
            elif args.command == "pr-update":
                state = publication.update(where, args.task_id)
            elif args.command == "pr-sync-base":
                state = publication.sync_base(where, args.task_id, args.expected_base)
            else:
                state = publication.operate(
                    where,
                    args.task_id,
                    args.command,
                    method=args.merge_method or "squash",
                )
        elif args.command == "deploy-publish":
            state = {
                "git_publication": run_deploy_publication(
                    where, args.task_id, args.publication_resolution
                )
            }
        elif args.command == "sync-base":
            state = sync_base(where, args.task_id, args.expected_base)
        elif args.command == "sync-latest-base":
            state = sync_latest_base(where, args.task_id, args.expected_base)
        elif args.command == "repair-checkpoint":
            if not args.repair_request:
                raise Blocked("repair-checkpoint requires --repair-request")
            state = deploy_checkpoint(where, args.task_id, args.repair_request)
        elif args.command == "repair-validate":
            if not args.repair_request:
                raise Blocked("repair-validate requires --repair-request")
            state = deploy_validate(where, args.task_id, args.repair_request)
        elif args.command == "create":
            state = create(where, args.task_name, args.repair_request)
        elif args.command == "finalize":
            state = finalize(where, args.task_id, create_pr=args.create_pr, draft=args.draft)
        else:
            state = globals()[args.command](where, args.task_id)
        print(json.dumps({"status": "ok", **state}, ensure_ascii=False))
        return 0
    except NeedsSync as notice:
        print(json.dumps(needs_sync(notice.base)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, KeyboardInterrupt) as error:
        retained = dict(getattr(error, "creation", {}))
        task_id = retained.get("task_id", args.task_id)
        try:
            if task_id:
                root = Path(retained["primary"]) if retained else where
                try:
                    root, _, retained_path, state = load(root, task_id)
                    retained.update(state)
                    if not hasattr(error, "cleanup") and (
                        args.command == "cleanup"
                        or args.command == "finalize" and retained.get("merged")
                    ):
                        error.cleanup = cleanup_progress(root, retained_path, retained, "preflight", str(error))
                finally:
                    if retained:
                        target = Path(retained["worktree"])
                        retained["remaining_worktree"] = str(target) if target.exists() or target.is_symlink() else None
                        retained["remaining_branch"] = retained["branch"] if branch_exists(root, retained["branch"]) else None
                        contract = target / retained["task_file"]
                        retained["remaining_task_file"] = str(contract) if contract.exists() else None
                        lifecycle = state_path(root, task_id)
                        retained["remaining_lifecycle"] = str(lifecycle) if lifecycle.exists() else None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        print(
            json.dumps(
                {
                    **retained,
                    "status": "blocked",
                    "error": str(error) or type(error).__name__,
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
