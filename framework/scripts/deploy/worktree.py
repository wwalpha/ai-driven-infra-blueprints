"""Deploy selection and fixed managed-worktree authority, independent of local base."""

import copy
import re
import subprocess
from pathlib import Path

import task_contract_core as tasks
import worktree_state as ws
import worktree_task as wt
from contracts.deploy import DEPLOY_SUCCESS
from contracts.target import IAC_ENGINE_KEY
from contracts.validation import VALIDATION_PASS
from utils.local_evidence import evidence_store, read_sealed, write_sealed
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


def progress_path(root, *, create=False):
    return evidence_store(root, create=create) / "deploy-progress.json"


def progress_state(backend):
    state = require(backend.root)
    if state is not None:
        return state
    return {
        "deployIdentity": {
            "taskFile": backend.run_context["taskFile"],
            "taskDigest": backend.run_context["taskDigest"],
            "target": backend.target,
            "environment": backend.environment,
            "stacks": sorted(backend.states),
        }
    }


def save_progress(backend, fields):
    if getattr(backend, "phase", None) not in {"deploy", "update"}:
        return
    context = backend.run_context
    if backend.phase == "deploy":
        identity = backend.progress_identity
        if (
            backend.root.resolve() != backend.progress_root
            or context.get("repository") != str(backend.progress_root)
            or context.get("taskFile") != identity["taskFile"]
            or context.get("taskDigest") != identity["taskDigest"]
            or context.get("target") != identity["target"]
            or context.get("environment") != identity["environment"]
            or context.get("directory") != backend.progress_directory
            or set(context["states"]) != set(identity["stacks"])
        ):
            raise ws.Blocked("Deploy progress differs from its fixed identity")
        path = progress_path(backend.root, create=True)
        if path != backend.progress_destination:
            raise ws.Blocked("Deploy progress destination changed")
        if path.exists() or path.is_symlink():
            read_progress(backend.root, {"deployIdentity": identity})
    else:
        identity = progress_state(backend)["deployIdentity"]
        path = progress_path(backend.root, create=True)
    saved = copy.deepcopy(context)
    saved.pop("gitPublication", None)
    saved["states"] = {
        name: {
            key: copy.deepcopy(value)
            for key, value in entry.items()
            if key in fields
            or key
            in {
                "checkpointed",
                "currentStack",
                "requestPending",
                "requestError",
                "endedRequest",
                "reason",
                "createUnconfirmed",
            }
        }
        for name, entry in context["states"].items()
    }
    progress = {"identity": identity, "runContext": saved}
    write_sealed(backend.root, path, progress)


def read_progress(root, state):
    path = progress_path(root)
    if not path.exists() and not path.is_symlink():
        if (
            state.get("deployCheckpoints")
            or state.get("deployCheckpointIntent")
            or state.get("deployPublication")
        ):
            raise ws.Blocked(
                "saved Deploy progress is missing; retain checkpoint and request evidence"
            )
        return None
    progress = read_sealed(root, path)
    if not isinstance(progress, dict) or progress.get("identity") != state.get(
        "deployIdentity"
    ):
        raise ws.Blocked("Deploy progress belongs to another Task/Target/snapshot")
    context = progress.get("runContext")
    if (
        not isinstance(context, dict)
        or not isinstance(context.get("states"), dict)
        or set(context["states"]) != set(progress["identity"]["stacks"])
        or any(
            not isinstance(item, dict) or not item.get("status")
            for item in context["states"].values()
        )
        or any(
            context.get(key) != progress["identity"].get(key)
            for key in ("taskFile", "taskDigest", "target", "environment")
        )
        or not isinstance(context.get("consumedInputs"), dict)
        or not isinstance(context.get("inputDigests"), dict)
        or not isinstance(context.get("stepUnits"), list)
        or any(
            key in context and not isinstance(context[key], dict)
            for key in ("pendingObserved", "pendingGeneration", "checkpointPending")
        )
    ):
        raise ws.Blocked("Deploy progress recovery context is incomplete or corrupt")
    pending = context.get("checkpointPending")
    if "checkpointPending" in context and (
        not isinstance(pending.get("stacks"), list)
        or not isinstance(pending.get("before"), dict)
        or "after" not in pending
        or pending["after"] is not None
        and not isinstance(pending["after"], dict)
        or "final" in pending
        and not isinstance(pending["final"], dict)
    ):
        raise ws.Blocked(
            "Deploy progress checkpoint candidate is incomplete or corrupt"
        )
    return progress


def attempts_finished(states, result):
    return bool(states) and all(
        saved.get("status") in {DEPLOY_SUCCESS, "FAILED", "SETTLED"}
        or saved.get("status") in {"READY", "NOT_STARTED"}
        and saved.get("unexecutedReason")
        in {
            "PREVIOUS_DEPLOY_ORDER_FAILED",
            "CURRENT_EXECUTION_CONSTRAINT",
            "DEPLOY_ENDED_WITHOUT_EXECUTION",
        }
        for saved in states.values()
    )


def end_unexecuted(context):
    units = {unit["name"]: unit for unit in context["stepUnits"]}
    failed_orders = [
        int(units[name]["deployOrder"])
        for name, item in context["states"].items()
        if item["status"] == "FAILED" and name in units
    ]
    for name, item in context["states"].items():
        if (
            item["status"] in {"READY", "NOT_STARTED", "BLOCKED", "CHANGESET_CREATING"}
            and not item.get("clientToken")
            and not item.get("requestPending")
            and not item.get("requestError")
        ):
            order = int(units[name]["deployOrder"])
            item.update(
                status="NOT_STARTED",
                unexecutedReason="PREVIOUS_DEPLOY_ORDER_FAILED"
                if any(value < order for value in failed_orders)
                else "CURRENT_EXECUTION_CONSTRAINT"
                if item.get("failure") or item.get("schedulerError")
                else "DEPLOY_ENDED_WITHOUT_EXECUTION",
            )


def final_blockers(context):
    """Candidate prerequisites do not depend on Git publication or Task status."""
    blockers = []
    for key in ("pendingObserved", "pendingGeneration", "generationError"):
        if context.get(key):
            blockers.append({"reason": key})
    states = context["states"]
    for name, item in states.items():
        for record in item.get("deferredConsumers", []):
            if record.get("approved") and not record.get("referenceSynced"):
                blockers.append(
                    {
                        "stack": record["stack"],
                        "consumer": record["consumer"],
                        "reason": "approved reference synchronization needs sync",
                    }
                )
        if not item.get("observedSynced") or not item.get("currentStack"):
            blockers.append({"stack": name, "reason": "current observation needs sync"})
        if item.get("requestPending") or item.get("requestError"):
            blockers.append({"stack": name, "reason": "current request is unresolved"})
        if current_category(item) in {"RUNNING", "UNKNOWN"}:
            blockers.append(
                {"stack": name, "reason": "current AWS is running or unreadable"}
            )
    if not attempts_finished(states, context.get("deployResult")):
        blockers.append(
            {"reason": "attempts or explicit unexecuted reasons are incomplete"}
        )
    return blockers


def current_category(item):
    return wt.module("deploy/current_state.py", "deploy.current_state").category(
        item.get("currentStack", {})
    )


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
    progress = read_progress(root, state)
    final = state.get("deployPublication", {}).get("finalCandidate")
    if (
        progress is None
        or final_blockers(progress["runContext"])
        or progress["runContext"].get("checkpointPending")
        or progress["runContext"].get("snapshotValidation") != VALIDATION_PASS
        or not final
        or final.get("taskAfter") != task.text
        or final.get("source") != state["tip"]
        or final.get("tree") != wt.output(root, "rev-parse", state["tip"] + "^{tree}")
        or final.get("taskAfter")
        != tasks.set_status(final.get("taskBefore", ""), "completed")
    ):
        raise ws.Blocked(
            "Deploy final candidate is incomplete; use sync --final or resume the saved checkpoint"
        )


def discard_progress(state):
    root = Path(state["worktree"])
    path = evidence_store(root, create=False) / "deploy-progress.json"
    if path.exists():
        progress = read_sealed(root, path)
        if (
            progress["identity"] != state["deployIdentity"]
            or progress["runContext"].get("pendingObserved")
            or progress["runContext"].get("pendingGeneration")
            or progress["runContext"].get("generationError")
            or progress["runContext"].get("checkpointPending")
        ):
            raise ws.Blocked(
                "Deploy progress changed or is incomplete; retain cleanup state"
            )
        path.unlink()
