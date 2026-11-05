"""Deploy selection and fixed managed-worktree authority, independent of local base."""

import copy
import re
import subprocess
from pathlib import Path

import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from contracts.target import IAC_ENGINE_KEY
from utils.project_targets import load_target_directory


def is_deploy(text):
    lines = tasks.section(text, "## Task contract")
    return (
        "- Task type: `infrastructure`" in lines
        and "- Infrastructure phase: `deploy`" in lines
    )


def start(where, task_id):
    """Create a new Deploy Task; existing Tasks continue through their own commands."""
    _, _, primary = ws.repository(where)
    path = ws.state_path(primary, task_id)
    target = primary / ".worktrees" / task_id
    contract = primary / f"tasks/{task_id}.md"
    if (
        path.exists()
        or path.is_symlink()
        or contract.exists()
        or contract.is_symlink()
        or wt.branch_exists(primary, f"codex/worktree/{task_id}")
        or target.exists()
        or target.is_symlink()
        or any(
            Path(entry["worktree"]).resolve() == target
            for entry in ws.worktrees(primary)
        )
    ):
        raise ws.Blocked("TASK_ID_ALREADY_USED: choose a new Deploy Task ID")
    base, head, freshness, upstream = fresh_base(primary)
    state = wt.create(
        where, task_id, expected_base=(base, head), expected_upstream=upstream
    )
    state["baseFreshness"] = freshness
    return state


def fresh_base(primary):
    base = wt.base_branch(primary)
    initial = wt.output(primary, "rev-parse", f"refs/heads/{base}")
    values = wt.base_upstream_config(primary, base)
    if values == [[], []]:
        return base, initial, "LOCAL_ONLY", values
    if any(len(value) != 1 for value in values):
        raise ws.Blocked(
            "Deploy base upstream configuration is incomplete or ambiguous"
        )
    remote, ref = values[0][0], values[1][0]
    if (
        not remote
        or remote == "."
        or remote.startswith("-")
        or not ref.startswith("refs/heads/")
        or wt.git(primary, "check-ref-format", ref, check=False).returncode
    ):
        raise ws.Blocked("Deploy base upstream must be a remote branch")
    try:
        before = wt.git(
            primary,
            "ls-remote",
            "--exit-code",
            "--heads",
            remote,
            ref,
            check=False,
            timeout=60,
        )
        fetched = (
            wt.git(
                primary,
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                remote,
                ref,
                check=False,
                timeout=60,
            )
            if before.returncode == 0
            else None
        )
        after = (
            wt.git(
                primary,
                "ls-remote",
                "--exit-code",
                "--heads",
                remote,
                ref,
                check=False,
                timeout=60,
            )
            if fetched and fetched.returncode == 0
            else None
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ws.Blocked(
            "Deploy base upstream check failed; no Task was created"
        ) from None
    match = (
        re.fullmatch(r"([0-9a-f]{40,64})\s+" + re.escape(ref), before.stdout.strip())
        if before.returncode == 0
        else None
    )
    if (
        not match
        or not fetched
        or fetched.returncode
        or not after
        or after.returncode
        or after.stdout != before.stdout
    ):
        raise ws.Blocked(
            "Deploy base upstream unavailable or changed; no Task was created"
        )
    remote_head = match.group(1)
    with wt.lifecycle_lock(primary):
        if (
            wt.base_branch(primary) != base
            or wt.output(primary, "rev-parse", f"refs/heads/{base}") != initial
            or wt.base_upstream_config(primary, base) != values
        ):
            raise ws.Blocked("Deploy base changed during upstream verification")
        if initial != remote_head:
            if wt.git(
                primary,
                "merge-base",
                "--is-ancestor",
                initial,
                remote_head,
                check=False,
            ).returncode:
                raise ws.Blocked(
                    "Deploy base is ahead of or diverged from its upstream"
                )
            if wt.output(primary, "branch", "--show-current") != base or wt.output(
                primary, "status", "--porcelain", "--untracked-files=all"
            ):
                raise ws.Blocked(
                    "Deploy base checkout must be clean and checked out in primary for fast-forward"
                )
            wt.idle_git(primary)
            wt.git(primary, "merge", "--ff-only", remote_head)
    return base, remote_head, "UPSTREAM_VERIFIED", values


def require(root, snapshot=None):
    snapshot = snapshot or tasks.task_snapshot(root, executable=False, live=True)
    if not is_deploy(snapshot.text):
        return None
    _, state = ws.deploy_task_state(root, snapshot.name, required=True)
    if Path(state["worktree"]) != root:
        raise ws.Blocked("source write requires its managed worktree")
    if state.get("python_setup", {}).get("status") != "ready":
        raise ws.Blocked("Deploy requires successful managed Python setup")
    if state.get("deployContractUpdate"):
        raise ws.Blocked(
            "unfinished Deploy contract correction; retry --correct-deploy-contract"
        )
    if (
        state.get("deployIdentity", {}).get("taskDigest", snapshot.task_digest)
        != snapshot.task_digest
    ):
        raise ws.Blocked("Deploy contract differs from its fixed snapshot authority")
    return state


def bind(root, task, target, environment, stacks):
    state = require(root, task)
    if state is None:
        return
    identity = dict(
        taskFile=task.name,
        taskDigest=task.task_digest,
        target=target,
        environment=environment,
        stacks=sorted(stacks),
        snapshot=state["start"],
    )
    primary, _, path, _ = ws.load(root, state["task_id"])
    with wt.lifecycle_lock(primary):
        state = require(root, task)
        if state.get("deployIdentity", identity) != identity:
            raise ws.Blocked("Deploy Task/Target/Stack/snapshot identity changed")
        state["deployIdentity"] = identity
        state.setdefault("deployContract", task.text)
        wt.save(path, state)
        return copy.deepcopy(identity)


def prepare_complete(root, task):
    require_complete(root, task)


def require_complete(root, task):
    if not is_deploy(task.text):
        return
    state = require(root, task)
    if not state.get("deployIdentity"):
        targets = {
            (environment, directory) for environment, directory, _ in task.scope or ()
        }
        if (
            len(targets) == 1
            and load_target_directory(root, *next(iter(targets)))[IAC_ENGINE_KEY]
            == "terraform"
        ):
            return
        raise ws.Blocked("managed Deploy has no fixed identity")
    progress = wt.module("deploy/progress.py", "deploy.progress")
    completion = wt.module("deploy/completion.py", "deploy.completion")
    saved = progress.read_progress(root, state)
    if completion.candidate_incomplete(
        task, state, saved, lambda: wt.output(root, "rev-parse", state["tip"] + "^{tree}")
    ):
        raise ws.Blocked(
            "Deploy final candidate is incomplete; use sync --final or resume the saved checkpoint"
        )
