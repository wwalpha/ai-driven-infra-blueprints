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

import task_contract_core as tasks
import worktree_python as python_env
import worktree_state
from contracts.repository import PROJECT_FILENAME
from contracts.target import AWS_ACCOUNT_ID_KEY
from utils import cli_deploy
from utils.file_operations import sha
from utils.import_evidence import discard_import_proof
from utils.local_evidence import evidence_store as local_evidence_store
from utils.script_loader import module
from utils.sealed_evidence import evidence_store
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
from worktree_state import (
    worktrees as worktrees,
)


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


def base_upstream_config(root, base):
    values = []
    for key in ("remote", "merge"):
        result = git(root, "config", "--get-all", f"branch.{base}.{key}", check=False)
        if result.returncode not in {0, 1}:
            raise Blocked("Deploy base upstream configuration could not be read")
        values.append(result.stdout.splitlines())
    return values


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


def create(
    where, task_id, repair_request=None, *, expected_base=None, expected_upstream=None
):
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
        if expected_base is not None and (base, start) != expected_base:
            raise Blocked(
                "Deploy base changed between verification and worktree creation"
            )
        if (
            expected_upstream is not None
            and base_upstream_config(root, base) != expected_upstream
        ):
            raise Blocked("Deploy base upstream changed before worktree creation")
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
                f"Python setup failed; worktree retained. Retry setup --task-id {task_id}: {message}"
            ) from error
        save(path, state)
        return state
    finally:
        lock.rmdir()


def integration_task(target, state, approval=None, *, candidate_common=None):
    # A human-approved Git integration does not turn failed validation into completion.
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
    approval = approval or state.get("validation_failure_approval")
    if approval is not None and (not isinstance(approval, str) or not approval.strip()):
        raise Blocked("human approval must identify the accepted validation failures")
    expected = "suspend" if approval else "completed"
    if current != expected:
        raise Blocked(
            f"task must be {expected} for integration; current status: {current}"
        )


def base_worktree(root, state, *, records=None):
    entries = [
        entry
        for entry in (worktrees(root) if records is None else records)
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


def cleanup_missing_worktree(
    root: Path, state: dict, entry: dict, *, discard=False
) -> None:
    """Prove retained Git data is unchanged before removing a missing checkout's registration."""
    if (
        "locked" in entry
        or entry.get("branch") != f"refs/heads/{state['branch']}"
        or not discard
        and (
            entry.get("HEAD") != state["tip"]
            or not state.get("githubMerged")
            and state["merged"] != state["tip"]
            or state["commit"] is not None
            and not state.get("verified")
        )
    ):
        raise Blocked(
            "missing worktree registration is locked or differs from the verified merge; cleanup refused"
        )
    target = Path(state["worktree"])
    common = Path(
        output(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    if (common / "worktrees").is_symlink():
        raise Blocked("Git worktree administration must not be redirected")
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
        != entry["HEAD"]
        or output(root, "--git-dir", str(directory), "symbolic-ref", "HEAD")
        != f"refs/heads/{state['branch']}"
    ):
        raise Blocked("missing worktree Git identity changed; cleanup refused")
    if target.exists():
        gitfile = target / ".git"
        if gitfile.is_symlink() or not gitfile.is_file():
            raise Blocked("worktree Git registration is redirected; cleanup refused")
        pointer = gitfile.read_text(encoding="utf-8").strip()
        if (
            not pointer.startswith("gitdir: ")
            or (target / pointer[8:]).resolve() != directory.resolve()
        ):
            raise Blocked("worktree Git registration is redirected; cleanup refused")
    worktree_state.idle_operations(
        root, runner=partial(_cleanup_git, directory=directory)
    )
    # diff-index reads the retained index without requiring the removed working directory.
    if not discard and output(
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
                Path(e["worktree"]) == target or Path(e["worktree"]).resolve() == target
                for e in worktrees(root)
            ),
            "branch": branch_exists(root, state["branch"]),
            "task_state": path.exists(),
        },
        "retry_command": f"python3 -B framework/scripts/worktree_task.py cleanup --task-id {state['task_id']}",
        "next_action": "resolve_stop_reason_then_retry" if reason else "none",
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
        entries = [
            e for e in worktrees(root) if Path(e["worktree"]).resolve() == target
        ]
        if any(
            e.get("branch") == f"refs/heads/{state['branch']}"
            and Path(e["worktree"]) != target
            for e in worktrees(root)
        ):
            raise Blocked("task branch is used by another worktree; cleanup refused")
        untracked_task = None
        if target.exists():
            target = task_worktree(root, state)
            cleanup_missing_worktree(root, state, entries[0], discard=True)
            if not discard and output(target, "rev-parse", "HEAD") != state["tip"]:
                raise Blocked("task HEAD changed since merge; cleanup refused")
            if not discard:
                untracked_task = deploy_cleanup_task(target, state)
                integration_task(target, state)
                changed = changed_paths(target)
                if untracked_task is not None:
                    changed.discard(state["task_file"])
                if changed:
                    raise Blocked("task worktree is dirty; cleanup refused")
                # Preserve user artifacts before removing the owned environment or checkout.
                ignored = paths(
                    target,
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
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
            cleanup_missing_worktree(root, state, entries[0], discard=discard)
        if branch_exists(root, state["branch"]):
            tip = output(root, "rev-parse", f"refs/heads/{state['branch']}")
            if not discard and (
                tip != state["tip"]
                or not state.get("githubMerged")
                and not ancestor(root, tip, state["base"])
            ):
                raise Blocked(
                    "temporary branch changed or is unmerged; cleanup refused"
                )
        elif entries:
            raise Blocked("registered worktree branch is missing; cleanup refused")
        if target.exists() or entries:
            phase = "remove_worktree"
            if (
                target.exists()
                and untracked_task is not None
                and state["task_file"] in changed_paths(target)
            ):
                deploy_cleanup_task(target, state).unlink()
            git(
                root,
                "worktree",
                "remove",
                *(["--force"] if discard else []),
                str(target),
            )
        phase = "remove_branch"
        if branch_exists(root, state["branch"]):
            git(root, "branch", "-D", state["branch"])
        phase = "verify_removal"
        remaining = cleanup_progress(root, path, state, phase)["remaining"]
        if any(remaining[key] for key in ("worktree", "git_registration", "branch")):
            raise Blocked("local cleanup is incomplete; retain Task state and retry")
        retained_evidence = []
        if discard:
            try:
                proof = evidence_store(target, create=False) / (
                    state["task_id"] + ".json"
                )
                if proof.exists() or proof.is_symlink():
                    retained_evidence.append(str(proof))
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
            phase = "remove_import_proof"
            if not state.get("deployIdentity"):
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
            "retained_external_evidence": retained_evidence,
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


def branches(where):
    root, _, primary = repository(where)
    records = worktrees(root)
    states = {}
    for path in sorted((metadata_directory(primary) / "tasks").glob("*.json")):
        state = load(primary, path.stem)[3]
        states[state["branch"]] = str(path)
    result = []
    for branch in output(
        root, "for-each-ref", "--format=%(refname:short)", "refs/heads/codex/worktree/"
    ).splitlines():
        entries = [
            e["worktree"] for e in records if e.get("branch") == "refs/heads/" + branch
        ]
        result.append(
            dict(
                branch=branch,
                worktrees=entries,
                task_state=states.get(branch),
                orphan=not entries and branch not in states,
            )
        )
    return {"branches": result}


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
        if any(e.get("branch") == "refs/heads/" + branch for e in worktrees(root)):
            raise Blocked("branch is used by a worktree; deletion refused")
        # Also reject ambiguous ownership recorded by another lifecycle file.
        if any(
            e["branch"] == branch and not e["orphan"]
            for e in branches(root)["branches"]
        ):
            raise Blocked("branch still has Task ownership; use cleanup")
        git(root, "branch", "-D", branch)
        return {
            "deleted_branch": branch,
            "remaining_branch": branch_exists(root, branch),
        }


def _run_model_guard(
    target,
    task_file,
    approved=False,
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
        'if sys.argv[2] == "approved": options["contract_file"] = sys.argv[1]\n'
        'if sys.argv[3] != "null": options["supplied"] = set(json.loads(sys.argv[3]))\n'
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
        "    if len(sys.argv) > 4:\n"
        "        from utils.cli_deploy import validate_candidate\n"
        "        validate_candidate(root, sys.argv[1], sys.argv[4])",
        task_file,
        "approved" if approved else "normal",
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
    target, state, changed, text, parsed_operation, *, scope_paths, published_head=None
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
    if published_head is not None:
        if not ancestor(target, published_head, state["branch"]):
            raise Blocked("PR update must descend from the published HEAD")
    elif head != state["tip"]:
        raise Blocked("unexpected commits on task branch; review required")
    if published_head is None and state["commit"] and changed:
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
    approval,
    *,
    pr_update=False,
    prepare_only=False,
    recovery=False,
):
    changed = changed_paths(target)
    task_id = state["task_id"]
    task_base = state.get("recovery", {}).get("task_base") if recovery else None
    sync_base = state.get("prUpdate", {}).get("syncBase") if pr_update else None
    model_changes = (
        changed
        | paths(target, "diff", "--no-renames", "--name-only", "-z", task_base, "HEAD")
        if task_base
        else changed
        | paths(target, "diff", "--no-renames", "--name-only", "-z", sync_base, "HEAD")
        if sync_base
        else integration_changed_paths(target, state["task_file"])
    )
    contract = tasks.read_task_snapshot(target, state["task_file"], live=True).text
    _block_invalid_model_contract(contract, state["task_file"])
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
        target,
        state,
        changed,
        contract,
        parsed_operation,
        scope_paths=model_changes,
        published_head=state["prUpdate"]["previousCandidate"] if pr_update else None,
    )
    if not pr_update:
        base_worktree(root, state)
    implement = "- Infrastructure phase: `implement`" in tasks.section(
        contract, "## Task contract"
    )
    if (
        not pr_update
        and not implement
        and not task_base
        and not ancestor(
            root, state.get("validation_base", state["start"]), state["base"]
        )
    ):
        raise Blocked("base history was rewritten; task retained for review")
    if (
        not pr_update
        and not prepare_only
        and not recovery
        and state.get("integrationMode") != "pr"
    ):
        latest = output(root, "rev-parse", f"refs/heads/{state['base']}")
        if latest != state.get("validation_base", state["start"]):
            if not ancestor(
                root, state.get("validation_base", state["start"]), state["base"]
            ):
                raise Blocked("base history was rewritten; task retained for review")
            raise NeedsSync(latest)
    if (not operation or approval) and (
        "- Workflow: `import`" in tasks.section(contract, "## Task contract")
        or "## Out-of-task FAIL approvals" in contract
        or any(p.startswith("model/") or p == PROJECT_FILENAME for p in model_changes)
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
            target,
            state,
            changed,
            current,
            parsed_operation,
            scope_paths=model_changes,
            published_head=state["prUpdate"]["previousCandidate"]
            if pr_update
            else None,
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
    # Do not replay unexpected history if the base was rewritten after creation.
    if (
        not implement
        and not task_base
        and not ancestor(
            root, state.get("validation_base", state["start"]), state["base"]
        )
    ):
        raise Blocked("base history was rewritten; task retained for review")
    if recovery:
        if task_base and latest != state["recovery"]["base"]:
            raise Blocked("recovery base changed before rebase")
        result = git(
            target,
            "-c",
            "rebase.updateRefs=false",
            "rebase",
            "--no-autostash",
            *(["--onto", latest, task_base] if task_base else [latest]),
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
    elif git(
        target, "merge-base", "--is-ancestor", latest, "HEAD", check=False
    ).returncode:
        raise Blocked(
            "recorded base is not an ancestor of the candidate; review required"
        )
    if changed_paths(target):
        raise Blocked("task worktree changed during rebase; review required")
    base = base_worktree(
        root, state
    )  # Recheck dirty/operation state immediately before merge.
    current_base = output(base, "rev-parse", "HEAD")
    if current_base != latest:
        if recovery:
            raise Blocked(
                "base advanced during rebase; retry finalize with latest local base"
            )
        if not ancestor(root, latest, state["base"]):
            raise Blocked("base history was rewritten; task retained for review")
        raise NeedsSync(current_base)
    return latest


def _recovery_count(target, recovery):
    count = int(recovery["count"])
    if not recovery.get("count_excludes_merges"):
        merges = output(
            target,
            "rev-list",
            "--count",
            "--merges",
            recovery["base"] + ".." + recovery["commit"],
        )
        count -= int(merges)
    if count < 0:
        raise Blocked("invalid recovery commit count")
    return str(count)


def _recovery_candidate(target, state, text, recovery):
    """Reuse the exact history/scope boundary for finishing and explicitly re-pinning."""
    base = recovery["base"]
    head = output(target, "rev-parse", "HEAD")
    if (
        changed_paths(target)
        or tasks.status(text)
        != ("suspend" if state.get("validation_failure_approval") else "running")
        or (
            "approval" in recovery
            and (
                recovery["approval"] != state.get("validation_failure_approval")
                or recovery["contract"]
                != hashlib.sha256(text.encode("utf-8")).hexdigest()
            )
        )
        or git(
            target, "merge-base", "--is-ancestor", base, head, check=False
        ).returncode
        != 0
        or output(target, "rev-list", "--count", base + ".." + head)
        != _recovery_count(target, recovery)
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


def recover(
    where,
    task_id,
    expected_commit,
    expected_base,
    finish=False,
    repin=False,
    expected_task_base=None,
):
    """Explicit reviewed recovery; pin old task/base and never merge or validate."""
    if finish and repin:
        raise Blocked("finish and re-pin recovery are mutually exclusive")
    if expected_task_base is not None and (finish or repin):
        raise Blocked("expected task base is only valid when starting recovery")
    root, _, path, state = load(where, task_id)
    with lifecycle_lock(root):
        root, _, path, state = load(root, task_id)
        if state.get("integrationMode") == "pr":
            raise Blocked(
                "PR Task intent is immutable; reviewed PR recovery is required"
            )
        target = task_worktree(root, state)
        base = base_worktree(root, state)
        if not all(
            re.fullmatch(r"[0-9a-f]{40}", value or "")
            for value in (expected_commit, expected_base)
        ):
            raise Blocked("recovery requires full expected commit/base hashes")
        if state["merged"] or not state["verified"]:
            raise Blocked("recovery requires an unmerged verified task")
        approval = state.get("validation_failure_approval")
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
                **{k: v for k, v in recovery.items() if k in {"approval", "contract"}},
                commit=head,
                base=expected_base,
                count=_recovery_count(target, recovery),
                count_excludes_merges=True,
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
        if approval and (not isinstance(approval, str) or not approval.strip()):
            raise Blocked("invalid recorded validation failure approval")
        if tasks.status(text) not in (
            {"suspend"}
            if approval
            else {"completed", "running", "suspend"}
            if expected_task_base is not None
            else {"completed", "running"}
        ):
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
        task_base = expected_base
        if expected_task_base is not None:
            idle_git(target)
            if (
                not re.fullmatch(r"[0-9a-f]{40}", expected_task_base)
                or expected_task_base != state.get("validation_base", state["start"])
                or approval
                or state.get("deployRepair")
                or state.get("deployIdentity")
                or state.get("baseSyncIntent")
                or state.get("rewrittenBaseIntent")
                or changed_paths(target)
            ):
                raise Blocked(
                    "rewritten recovery requires the recorded task base and a clean governance candidate"
                )
            if git(
                target,
                "merge-base",
                "--is-ancestor",
                expected_task_base,
                expected_commit,
                check=False,
            ).returncode or output(
                target,
                "rev-list",
                "--merges",
                expected_task_base + ".." + expected_commit,
            ):
                raise Blocked("recorded task base must have a linear candidate history")
            if not git(
                root,
                "merge-base",
                "--is-ancestor",
                expected_task_base,
                expected_base,
                check=False,
            ).returncode:
                raise Blocked("task base was not rewritten; use ordinary recovery")
            task_changes = paths(
                target,
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                expected_task_base,
                expected_commit,
            )
            declared = tasks.paths_in(text, "## Modified files")
            allowed = tasks.paths_in(text, "## Allowed paths")
            if (
                not task_changes
                or task_changes - declared
                or any(
                    not any(tasks.matches(p, pattern) for pattern in allowed)
                    for p in task_changes
                )
            ):
                raise Blocked(
                    "rewritten recovery changes are outside the exact task contract"
                )
            task_base = expected_task_base
        count = int(
            output(
                target,
                "rev-list",
                "--count",
                "--no-merges",
                task_base + ".." + expected_commit,
            )
        )
        changed = bool(changed_paths(target))
        if approval and changed:
            raise Blocked("approved failure recovery requires a clean reviewed task")
        state["recovery"] = dict(
            commit=expected_commit,
            base=expected_base,
            count=str(count + changed),
            count_excludes_merges=True,
            **({"task_base": task_base} if expected_task_base is not None else {}),
        )
        if approval:
            state["recovery"].update(
                approval=approval,
                contract=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        else:
            tasks.atomic_files(
                {target / state["task_file"]: tasks.set_status(text, "running")},
                staging_directory=target,
            )
        # Permit only this explicitly pinned correction commit; normal finalize guards stay closed.
        if changed:
            state["commit"] = None
        try:
            _prepare_commit(root, path, state, target, approval, recovery=True)
        except Blocked as error:
            if str(error).startswith("rebase failed and was aborted"):
                save(path, state)
            raise
        return state


def finalize(
    where,
    task_id,
    human_approved_validation_failure=None,
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
            return _finalize(root, task_id, human_approved_validation_failure)
        if create_pr:
            return publication.finalize(
                root, task_id, human_approved_validation_failure, draft=draft
            )
        if state.get("integrationMode") == "pr":
            raise Blocked(
                "Task selected PR publication; retry finalize --create-pr; no automatic merge"
            )
        return _finalize(root, task_id, human_approved_validation_failure)


def _finalize(where, task_id, human_approved_validation_failure=None):
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
        return automatic_cleanup(root, task_id, publication_held=True)
    if state.get("deployRepair"):
        if human_approved_validation_failure is not None:
            raise Blocked("deploy repair result requires successful static validation")
        return deploy_finalize(where, task_id)
    if state.get("rewrittenBaseIntent"):
        raise Blocked("finish rewritten base recovery before finalize")
    if state.get("recovery"):
        raise Blocked("finish reviewed recovery and rerun validation before finalize")
    if not state["merged"]:
        target = task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        _block_invalid_model_contract(text, state["task_file"])
    if (
        not state["merged"]
        and human_approved_validation_failure is None
        and not state.get("validation_failure_approval")
    ):
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
                    "then retry; keep task status running."
                )
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
                bool(approval),
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
        current_base = output(base, "rev-parse", "HEAD")
        if current_base != latest and state.get("integrationMode") != "pr":
            if not ancestor(root, latest, state["base"]):
                raise Blocked("base history was rewritten; task retained for review")
            raise NeedsSync(current_base)
        if state.get("integrationMode") == "pr":
            return module("worktree_pr.py", "worktree_pr").prepare(
                root, path, state, latest, expected
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
        root, _, path, state = load(candidate.root, Path(candidate.task_file).stem)
        target = task_worktree(root, state)
        base = base_worktree(root, state)
        if (
            target != candidate.root
            or changed_paths(target)
            or output(target, "rev-parse", "HEAD") != candidate.candidate_head
        ):
            raise Blocked("validated candidate/base changed; no merge")
        current_base = output(base, "rev-parse", "HEAD")
        if (
            current_base != candidate.base_commit
            and state.get("integrationMode") != "pr"
        ):
            if not ancestor(root, candidate.base_commit, state["base"]):
                raise Blocked("base history was rewritten; task retained for review")
            raise NeedsSync(current_base)
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
        ):
            raise Blocked("validated state changed during task completion; no merge")
        current_base = output(base, "rev-parse", "HEAD")
        if (
            current_base != candidate.base_commit
            and state.get("integrationMode") != "pr"
        ):
            if not ancestor(root, candidate.base_commit, state["base"]):
                raise Blocked("base history was rewritten; task retained for review")
            raise NeedsSync(current_base)
        if state.get("integrationMode") == "pr":
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


def sync_latest_base(
    where, task_id, expected_base, *, recover_prepared_pr=False, expected_commit=None
):
    """Replay a reviewed local task history onto the latest base without validation."""
    root, _, path, _ = load(where, task_id)
    publication = module("worktree_pr.py", "worktree_pr")
    with publication.publication_lock(path):
        checked_state = None
        if recover_prepared_pr:
            checked_state = load(root, task_id)[3]
            prepared = checked_state.get("prPublication", {})
            target = task_worktree(root, checked_state)
            text = tasks.read_task_snapshot(
                target, checked_state["task_file"], live=True
            ).text
            if (
                checked_state.get("integrationMode") != "pr"
                or prepared.get("status") != "PREPARED"
                or any(
                    key in prepared
                    for key in ("pushIntent", "createIntent", "number", "url")
                )
                or checked_state.get("prUpdate")
                or checked_state.get("validation_failure_approval")
                or not checked_state.get("verified")
                or expected_commit != checked_state.get("tip")
                or expected_commit != checked_state.get("commit")
                or expected_commit != prepared.get("candidate")
                or prepared.get("base") != checked_state.get("base")
                or prepared.get("head") != checked_state.get("branch")
                or prepared.get("baseCommit")
                != checked_state.get("validation_base", checked_state["start"])
                or prepared.get("taskHash")
                != hashlib.sha256(text.encode("utf-8")).hexdigest()
                or changed_paths(target)
                or not checked_state.get("latestBaseSync")
                and output(target, "rev-parse", "HEAD") != expected_commit
            ):
                raise Blocked("prepared PR candidate is not safely recoverable")
            identity = publication.remote_identity(target)
            if any(prepared.get(key) != value for key, value in identity.items()):
                raise Blocked("prepared PR remote identity changed")
            refs = publication.remote_heads(target, prepared)
            branch = publication.quote(prepared["base"], safe="")
            remote_base = json.loads(
                publication.gh(
                    target,
                    prepared["host"],
                    "api",
                    "--hostname",
                    prepared["host"],
                    f"repos/{prepared['repository']}/branches/{branch}",
                )
            )["commit"]["sha"]
            if (
                refs.get(f"refs/heads/{prepared['base']}") != expected_base
                or remote_base != expected_base
                or refs.get(f"refs/heads/{prepared['head']}") is not None
            ):
                raise Blocked("prepared PR remote base changed or head exists")
            if (
                publication.existing_pr(
                    target, prepared, states=("OPEN", "CLOSED", "MERGED")
                )
                is not None
            ):
                raise Blocked("prepared PR already exists; review required")
        with lifecycle_lock(root):
            root, _, path, state = load(root, task_id)
            if checked_state is not None and state != checked_state:
                raise Blocked("prepared PR state changed during remote checks")
            if (
                (state.get("prPublication") or state.get("integrationMode") == "pr")
                and not recover_prepared_pr
                or state.get("deployIdentity")
                or state.get("deployRepair")
                or state["merged"]
                or state.get("recovery")
                or state.get("baseSyncIntent")
                or state.get("rewrittenBaseIntent")
                or state.get("validation_failure_approval")
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
            if not ancestor(
                root, state.get("validation_base", state["start"]), state["base"]
            ):
                raise Blocked("base history was rewritten; task retained for review")
            text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
            if tasks.status(text) not in {"running", "completed"}:
                raise Blocked("base sync requires a running/completed Task")
            intent = state.get("latestBaseSync")
            new_intent = intent is None
            if intent is None:
                if latest == state.get("validation_base", state["start"]):
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
                _prepare_commit(root, path, state, target, None, prepare_only=True)
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
                tree_result = git(
                    target, "merge-tree", "--write-tree", head, latest, check=False
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
            if "oldBase" not in intent or "commits" not in intent:
                raise Blocked("legacy base sync intent requires review")
            sync_base = intent["base"]
            idle_git(target)
            head = output(target, "rev-parse", "HEAD")
            if head == intent["head"]:
                if not new_intent:
                    raise Blocked(
                        "base rebase outcome is unknown; retain worktree for review"
                    )
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
            if recover_prepared_pr:
                del state["prPublication"]
            save(path, state)
            if current_base != sync_base:
                return needs_sync(current_base)
            return {
                **state,
                "status": "needs_validation",
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
            or state.get("validation_failure_approval")
            or state.get("deployIdentity")
            or state.get("deployRepair")
            or state.get("recovery")
            or state.get("latestBaseSync")
            or state.get("rewrittenBaseIntent")
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


def rewrite_base(where, task_id, expected_commit, expected_base):
    """Move a reviewed fresh task across rewritten history, retaining its candidate."""
    root, _, path, state = load(where, task_id)
    with lifecycle_lock(root):
        root, _, path, state = load(root, task_id)
        target = task_worktree(root, state)
        text = tasks.read_task_snapshot(target, state["task_file"], live=True).text
        tasks.validate_contract(target, state["task_file"], text)
        if (
            tasks.status(text) != "running"
            or "- Task type: `governance`"
            not in tasks.section(text, "## Task contract")
            or state.get("integrationMode") == "pr"
            or state.get("deployRepair")
            or state.get("deployIdentity")
            or state.get("baseSyncIntent")
            or state.get("recovery")
            or state["commit"]
            or state["verified"]
            or state["merged"]
            or state["tip"] != state.get("validation_base", state["start"])
        ):
            raise Blocked(
                "rewritten base recovery requires a fresh running governance task"
            )
        base = output(root, "rev-parse", "refs/heads/" + state["base"])
        if (
            not re.fullmatch(r"[0-9a-f]{40}", expected_commit or "")
            or not re.fullmatch(r"[0-9a-f]{40}", expected_base or "")
            or base != expected_base
            or state["tip"] != expected_commit
        ):
            raise Blocked("review the exact task tip and current base before recovery")
        idle_git(target)
        intent = state.get("rewrittenBaseIntent")
        if intent is None:
            if output(target, "rev-parse", "HEAD") != expected_commit or paths(
                target, "diff", "--cached", "--name-only", "-z"
            ):
                raise Blocked(
                    "recovery requires the expected HEAD and an unstaged index"
                )
            if not git(
                target,
                "merge-base",
                "--is-ancestor",
                expected_commit,
                base,
                check=False,
            ).returncode:
                raise Blocked("base is a descendant; use ordinary base sync")
            changed = changed_paths(target)
            if (
                not changed
                or changed - tasks.paths_in(text, "## Modified files")
                or changed - tasks.paths_in(text, "## Allowed paths")
            ):
                raise Blocked("recovery requires only declared changed files")
            upstream = paths(
                target,
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                expected_commit,
                base,
            )
            if changed & upstream or output(target, "diff", "--summary"):
                raise Blocked("overlap or file mode changes require separate review")
            backup = Path(tempfile.mkdtemp(prefix="blueprint-rewritten-base-"))
            files = {}
            for number, relative in enumerate(sorted(changed)):
                actual = tasks.safe_path(target, relative)
                if (
                    actual.is_symlink()
                    or not actual.is_file()
                    or git(
                        target,
                        "cat-file",
                        "-e",
                        expected_commit + ":" + relative,
                        check=False,
                    ).returncode
                ):
                    raise Blocked(
                        "recovery supports only existing tracked regular files"
                    )
                original = subprocess_bytes(target, expected_commit, relative)
                candidate = actual.read_bytes()
                file = backup / str(number)
                file.write_bytes(candidate)
                files[relative] = {
                    "backup": str(file),
                    "candidate": hashlib.sha256(candidate).hexdigest(),
                    "original": hashlib.sha256(original).hexdigest(),
                }
            intent = {
                "head": expected_commit,
                "base": base,
                "contract": hashlib.sha256(text.encode()).hexdigest(),
                "files": files,
            }
            state["rewrittenBaseIntent"] = intent
            save(path, state)
        if (intent["head"], intent["base"], intent["contract"]) != (
            expected_commit,
            base,
            hashlib.sha256(text.encode()).hexdigest(),
        ):
            raise Blocked("recovery intent, base or contract changed")
        head = output(target, "rev-parse", "HEAD")
        if head not in {expected_commit, base} or paths(
            target, "diff", "--cached", "--name-only", "-z"
        ):
            raise Blocked("recovery HEAD or index changed; retain candidate and backup")
        for relative, record in intent["files"].items():
            actual = tasks.safe_path(target, relative)
            if (
                actual.is_symlink()
                or not actual.is_file()
                or sha(Path(record["backup"])) != record["candidate"]
                or sha(actual) not in {record["candidate"], record["original"]}
            ):
                raise Blocked("recovery candidate or backup changed")
        if changed_paths(target) - set(intent["files"]):
            raise Blocked("unexpected changes during recovery")
        if head == expected_commit:
            for relative in intent["files"]:
                (target / relative).write_bytes(
                    subprocess_bytes(target, expected_commit, relative)
                )
            outcome = git(
                target,
                "-c",
                "rebase.updateRefs=false",
                "rebase",
                "--no-autostash",
                "--onto",
                base,
                expected_commit,
                check=False,
            )
            if outcome.returncode:
                for relative, record in intent["files"].items():
                    (target / relative).write_bytes(Path(record["backup"]).read_bytes())
                raise Blocked(
                    "rewritten base rebase failed; candidate retained: "
                    + outcome.stderr.strip()
                )
        for relative, record in intent["files"].items():
            (target / relative).write_bytes(Path(record["backup"]).read_bytes())
        if (
            output(target, "rev-parse", "HEAD") != base
            or output(root, "rev-parse", "refs/heads/" + state["base"]) != base
        ):
            raise Blocked("recovery result differs from reviewed base")
        state["tip"] = base
        state["validation_base"] = base
        state.setdefault("rewrittenBaseRecoveries", []).append(
            state.pop("rewrittenBaseIntent")
        )
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
            "branches",
            "branch-delete",
            "pr-update",
            "pr-retry-create",
            "pr-sync-base",
            "pr-merge",
            "pr-status",
            "pr-close",
            "pr-draft",
            "pr-ready",
            "recover",
            "repair-checkpoint",
            "repair-validate",
            "sync-base",
            "sync-latest-base",
            "rewrite-base",
            "deploy-start",
            "deploy-publish",
        ),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
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
    parser.add_argument(
        "--human-approved-validation-failure",
        metavar="APPROVAL",
        help="Finalize a suspended task only after explicit human approval of named validation failures",
    )
    parser.add_argument("--repair-request", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-base")
    parser.add_argument(
        "--recover-prepared-pr",
        action="store_true",
        help="Reconcile an unpushed prepared PR before syncing its base",
    )
    parser.add_argument(
        "--expected-task-base",
        help="Reviewed recorded validation base for clean governance recovery across rewritten history",
    )
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
    if (
        args.command not in {"branches", "branch-delete"}
        and not (args.command == "pr-close" and args.pr)
        and not args.task_id
    ):
        parser.error("--task-id is required for this operation")
    if args.task_id and (args.command in {"branches", "branch-delete"} or args.pr):
        parser.error("branch operations and explicit --pr do not accept --task-id")
    if args.draft and not (args.command == "finalize" and args.create_pr):
        parser.error("--draft requires finalize --create-pr")
    if (
        args.branch
        and args.command != "branch-delete"
        or args.command == "branch-delete"
        and not args.branch
    ):
        parser.error("--branch is required only for branch-delete")
    if args.command == "pr-retry-create" and (
        not args.expected_commit
        or args.expected_base
        or args.finish_recovery
        or args.repin_recovery
    ):
        parser.error("pr-retry-create requires only --expected-commit")
    if args.recover_prepared_pr and (
        args.command != "sync-latest-base"
        or not args.expected_commit
        or not args.expected_base
    ):
        parser.error(
            "--recover-prepared-pr requires sync-latest-base, --expected-commit and --expected-base"
        )
    if args.pr and args.command != "pr-close":
        parser.error("--pr requires pr-close")
    if args.merge_method and args.command != "pr-merge":
        parser.error("--merge-method requires pr-merge")
    if args.create_pr and args.command != "finalize":
        parser.error("--create-pr is only valid with finalize")
    if args.publication_resolution and args.command != "deploy-publish":
        parser.error("--publication-resolution requires deploy-publish")
    if args.expected_task_base is not None and (
        args.command != "recover" or args.finish_recovery or args.repin_recovery
    ):
        parser.error("--expected-task-base requires initial recover")
    if (
        args.human_approved_validation_failure is not None
        and args.command != "finalize"
    ):
        parser.error("--human-approved-validation-failure is only valid with finalize")
    if args.command not in {
        "recover",
        "sync-base",
        "sync-latest-base",
        "pr-retry-create",
        "pr-sync-base",
        "rewrite-base",
    } and (
        args.expected_commit
        or args.expected_base
        or args.finish_recovery
        or args.repin_recovery
    ):
        parser.error("recovery arguments require recover")
    where = args.repository_root
    try:
        if (
            args.command not in {"create", "deploy-start", "branches", "branch-delete"}
            and not args.pr
        ):
            where = load(where, args.task_id)[
                0
            ]  # Keep diagnostics usable after task checkout removal.
        if args.command == "branches":
            state = branches(where)
        elif args.command == "branch-delete":
            state = delete_branch(where, args.branch)
        elif args.command.startswith("pr-"):
            publication = module("worktree_pr.py", "worktree_pr")
            if args.pr:
                state = publication.close_existing(where, args.pr)
            elif args.command == "pr-update":
                state = publication.update(where, args.task_id)
            elif args.command == "pr-retry-create":
                state = publication.retry_create(
                    where, args.task_id, args.expected_commit
                )
            elif args.command == "pr-sync-base":
                state = publication.sync_base(where, args.task_id, args.expected_base)
            else:
                state = publication.operate(
                    where,
                    args.task_id,
                    args.command,
                    method=args.merge_method or "squash",
                )
        elif args.command == "deploy-start":
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
        elif args.command == "sync-latest-base":
            state = sync_latest_base(
                where,
                args.task_id,
                args.expected_base,
                recover_prepared_pr=args.recover_prepared_pr,
                expected_commit=args.expected_commit,
            )
        elif args.command == "rewrite-base":
            state = rewrite_base(
                where, args.task_id, args.expected_commit, args.expected_base
            )
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
                    expected_task_base=args.expected_task_base,
                )
                if args.command == "recover"
                else finalize(
                    where,
                    args.task_id,
                    args.human_approved_validation_failure,
                    create_pr=args.create_pr,
                    draft=args.draft,
                )
                if args.command == "finalize"
                else globals()[args.command](where, args.task_id)
            )
        print(json.dumps({"status": "ok", **state}, ensure_ascii=False))
        return 0
    except NeedsSync as notice:
        print(json.dumps(needs_sync(notice.base)))
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
