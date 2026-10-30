"""Deploy selection and fixed managed-worktree authority, independent of local base."""

import copy
from pathlib import Path

import task_contract_core as tasks
import worktree_python
import worktree_state as ws
import worktree_task as wt
from utils.local_evidence import evidence_store, read_sealed, write_sealed
from utils.project_targets import load_target_directory


def is_deploy(text):
    lines = tasks.section(text, "## Task contract")
    return (
        "- Task type: `infrastructure`" in lines
        and "- Infrastructure phase: `deploy`" in lines
    )


def start(where, task_id):
    """Use the official lifecycle; never copy a dirty checkout or invent a new Task."""
    _, _, primary = ws.repository(where)
    path = ws.state_path(primary, task_id)
    if not path.exists():
        if (primary / f"tasks/{task_id}.md").exists():
            raise ws.Blocked(
                "existing Deploy contract has no managed worktree; review its ownership"
            )
        return wt.create(where, task_id)
    _, _, _, state = ws.load(where, task_id)
    target = ws.task_worktree(primary, state)
    ws.deploy_start_commit(target, state["task_file"], required=True)
    if (target / state["task_file"]).exists():
        task = tasks.read_task_snapshot(target, state["task_file"], live=True)
        if not is_deploy(task.text) or task.status == "completed":
            raise ws.Blocked("existing worktree is not an unfinished Deploy Task")
    if state.get("python_setup", {}).get("status") != "ready":
        return wt.setup(where, task_id)
    worktree_python.runtime(target)
    return state


def require(root, snapshot=None):
    snapshot = snapshot or tasks.task_snapshot(root, executable=False, live=True)
    if not is_deploy(snapshot.text):
        return None
    _, state = ws.deploy_task_state(root, snapshot.name, required=True)
    if Path(state["worktree"]) != root:
        raise ws.Blocked("source write requires its managed worktree")
    if state.get("python_setup", {}).get("status") != "ready":
        raise ws.Blocked("Deploy requires successful managed Python setup")
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
    progress = {
        "identity": identity,
        "stepwise": bool(context.get("stepwise")),
        "directory": context.get("directory"),
        "stepUnits": copy.deepcopy(context.get("stepUnits", [])),
        "checkpointPending": {"stacks": list(context["checkpointPending"]["stacks"])}
        if context.get("checkpointPending")
        else None,
        "states": {
            name: {
                key: copy.deepcopy(value)
                for key, value in saved.items()
                if key in fields
                or key
                in {"checkpointed", "currentStack", "requestPending", "requestError"}
            }
            for name, saved in context["states"].items()
        },
        "inputDigests": copy.deepcopy(context["inputDigests"]),
        "pendingObserved": bool(context.get("pendingObserved")),
        "pendingGeneration": bool(
            context.get("pendingGeneration") or context.get("generationError")
        ),
    }
    progress["runContext"] = {
        **copy.deepcopy(context),
        "states": copy.deepcopy(progress["states"]),
    }
    write_sealed(backend.root, path, progress)


def read_progress(root, state):
    path = progress_path(root)
    if not path.exists():
        return None
    progress = read_sealed(root, path)
    if progress["identity"] != state.get("deployIdentity"):
        raise ws.Blocked("Deploy progress belongs to another Task/Target/snapshot")
    return progress


def check_pending_progress(backend, records, unfinished):
    if getattr(backend, "phase", None) != "deploy":
        return
    state = require(backend.root)
    progress = read_progress(backend.root, state)
    if progress is None:
        return
    pending = {name for name, saved in progress["states"].items() if unfinished(saved)}
    owned = [
        record
        for record in records
        if record["publication"].get("repository") == str(backend.root)
        and record["publication"].get("taskDigest")
        == state["deployIdentity"]["taskDigest"]
    ]
    recorded = {name for record in owned for name in record["operations"]}
    if (
        pending - recorded
        or (progress["pendingObserved"] or progress["pendingGeneration"])
        and not any(
            record["publication"].get("pendingObserved")
            or record["publication"].get("pendingGeneration")
            for record in owned
        )
    ):
        raise ws.Blocked(
            "signed Deploy progress has unfinished work without its operation Journal; review original evidence, never resend or reset automatically"
        )


def adopt_successes(backend):
    if getattr(backend, "phase", None) != "deploy":
        return
    state = require(backend.root)
    progress = read_progress(backend.root, state)
    if progress is None:
        return
    backend.run_context["gitPublication"] = copy.deepcopy(
        state.get("deployPublication", {"status": "PENDING"})
    )
    for unit in backend.units:
        name = unit["name"]
        saved = progress["states"].get(name, {})
        if saved.get("status") != "SUCCESS" or not saved.get("observedSynced"):
            continue
        backend.claim_inputs(unit)
        if backend.input_digest(unit, fresh=True) != progress["inputDigests"].get(name):
            # Only a separately authorized repair may introduce a fresh Deploy input.
            if not state.get("iacRepair", {}).get("commit"):
                raise ws.Blocked("successful Stack snapshot input changed: " + name)
            continue
        backend.states[name] = copy.deepcopy(saved)


def attempts_finished(states, result):
    return bool(states) and all(
        saved.get("status") in {"SUCCESS", "FAILED", "SETTLED"}
        or saved.get("status") in {"READY", "NOT_STARTED"}
        and saved.get("unexecutedReason")
        in {
            "PREVIOUS_DEPLOY_ORDER_FAILED",
            "CURRENT_EXECUTION_CONSTRAINT",
            "DEPLOY_ENDED_WITHOUT_EXECUTION",
        }
        for saved in states.values()
    )


def prepare_complete(root, task):
    if not is_deploy(task.text):
        return
    state = require(root, task)
    if not state.get("deployIdentity"):
        return
    progress = read_progress(root, state)
    if not progress:
        raise ws.Blocked("Deploy progress is missing")
    context = progress.get("runContext", {})
    states = progress["states"]
    if (
        progress.get("checkpointPending")
        or progress.get("pendingObserved")
        or progress.get("pendingGeneration")
        or context.get("snapshotValidation") != "PASS"
        or state.get("deployPublication", {}).get("status") != "SUCCESS"
        or state.get("deployPublication", {}).get("publishedSource") != state.get("tip")
        or any(
            not item.get("observedSynced")
            or not item.get("currentStack")
            or item.get("requestPending")
            or item.get("attemptResult") == "UNKNOWN"
            and item.get("status") != "SETTLED"
            or item.get("status") in {"RUNNING", "CHANGESET_CREATING", "BLOCKED"}
            or item.get("currentStack", {}).get("StackStatus", "UNKNOWN")
            in {"UNKNOWN", "REVIEW_IN_PROGRESS"}
            or item.get("currentStack", {})
            .get("StackStatus", "UNKNOWN")
            .endswith("_IN_PROGRESS")
            for item in states.values()
        )
    ):
        raise ws.Blocked("Deploy snapshot, publication or AWS request is incomplete")
    if any(item.get("status") in {"READY", "NOT_STARTED"} for item in states.values()):
        if not any(item.get("status") == "FAILED" for item in states.values()):
            raise ws.Blocked(
                "unexecuted Stacks require a failed Deploy before completion"
            )
        units = {unit["name"]: unit for unit in progress.get("stepUnits", [])}
        failed_orders = [
            int(units[name]["deployOrder"])
            for name, item in states.items()
            if item.get("status") == "FAILED" and name in units
        ]
        for name, item in states.items():
            if item.get("status") in {"READY", "NOT_STARTED"}:
                order = int(units[name]["deployOrder"])
                item["unexecutedReason"] = (
                    "PREVIOUS_DEPLOY_ORDER_FAILED"
                    if any(value < order for value in failed_orders)
                    else "CURRENT_EXECUTION_CONSTRAINT"
                    if item.get("failure") or item.get("schedulerError")
                    else "DEPLOY_ENDED_WITHOUT_EXECUTION"
                )
        context["states"] = copy.deepcopy(states)
        write_sealed(root, progress_path(root, create=True), progress)
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
            and load_target_directory(root, *next(iter(targets)))["iacEngine"]
            == "terraform"
        ):
            return  # Terraform retains its existing saved-plan/output verification workflow.
    progress = read_progress(root, state)
    if (
        progress is None
        or set(progress["states"]) != set(state["deployIdentity"]["stacks"])
        or progress["pendingObserved"]
        or progress["pendingGeneration"]
        or not attempts_finished(
            progress["states"], progress.get("runContext", {}).get("deployResult")
        )
        or any(
            not saved.get("observedSynced")
            or saved.get("status") == "RUNNING"
            or saved.get("requestPending")
            or saved.get("currentStack", {}).get("classification") == "RUNNING"
            for saved in progress["states"].values()
        )
    ):
        raise ws.Blocked("Deploy snapshot is incomplete or AWS request is still active")


def discard_progress(state):
    root = Path(state["worktree"])
    path = evidence_store(root, create=False) / "deploy-progress.json"
    if path.exists():
        progress = read_sealed(root, path)
        if (
            progress["identity"] != state["deployIdentity"]
            or progress["pendingObserved"]
            or progress["pendingGeneration"]
        ):
            raise ws.Blocked(
                "Deploy progress changed or is incomplete; retain cleanup state"
            )
        path.unlink()
