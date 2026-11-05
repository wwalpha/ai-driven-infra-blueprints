"""Deploy progress evidence and its fixed identity."""

import copy
from pathlib import Path

import worktree_state as ws
from task_contract_core import normalize_selector
from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint
from utils.local_evidence import evidence_store, read_sealed, write_sealed

from deploy import operation_journal


def progress_path(root, task_file=None, *, create=False):
    if task_file is None:
        return evidence_store(root, create=create) / "deploy-progress.json"
    task_file = normalize_selector(task_file)
    if create:
        return operation_journal.location(root, task_file).parent / "progress.json"
    path = evidence_store(root, create=False) / ("inputs-" + fingerprint(task_file)) / "progress.json"
    operation_journal.safe_path(path)
    if path.parent.exists() or path.parent.is_symlink():
        operation_journal.private_path(path.parent, directory=True)
    return path


def identity(task, target, environment, stacks):
    return {
        "taskFile": task.name,
        "taskDigest": task.task_digest,
        "target": target,
        "environment": environment,
        "stacks": sorted(stacks),
    }


def read_task(root, task):
    path = progress_path(root, task.name)
    require_no_correction(path)
    if not path.exists():
        return None
    saved = read_sealed(root, path)
    fixed = saved["identity"]
    if (
        fixed["taskFile"] != task.name
        or fixed["taskDigest"] != task.task_digest
        or saved["runContext"].get("repository") != str(root.resolve())
    ):
        raise Blocked("saved Deploy progress differs from the selected Task")
    return read_progress(root, {"deployIdentity": fixed}, task.name)


def correction_path(path):
    return path.with_name("contract-correction.json")


def require_no_correction(path):
    intent = correction_path(path)
    if intent.exists() or intent.is_symlink():
        raise Blocked("unfinished Deploy contract correction; retry --correct-deploy-contract")


def read_legacy_task(root, task):
    path = progress_path(root)
    if not (path.exists() or path.is_symlink()):
        return None
    fixed = read_sealed(root, path)["identity"]
    if fixed["taskFile"] != task.name:
        return None
    if fixed["taskDigest"] != task.task_digest:
        raise Blocked("legacy Deploy progress differs from the selected Task")
    return read_progress(root, {"deployIdentity": fixed})


def require_no_legacy_task(root, task_file):
    legacy = progress_path(root)
    if (legacy.exists() or legacy.is_symlink()) and read_sealed(root, legacy)["identity"]["taskFile"] == task_file:
        raise Blocked("legacy Deploy evidence exists for this Task; retain it and use explicit legacy recovery")


def require_no_pending_peer(root, path, target, stacks):
    """Call while holding the repository request lock, before any new AWS request."""
    legacy = progress_path(root)
    for candidate in (legacy, *legacy.parent.glob("inputs-*/progress.json")):
        if candidate == path or not (candidate.exists() or candidate.is_symlink()):
            continue
        operation_journal.private_path(candidate.parent, directory=True)
        saved = read_sealed(root, candidate)
        context = saved["runContext"]
        other_target = saved["identity"]["target"]
        if operation_journal.target_identity(other_target) != operation_journal.target_identity(target):
            continue
        for name in set(stacks) & context["states"].keys():
            state = context["states"][name]
            if unresolved_request(state):
                raise Blocked("unresolved AWS request belongs to another Deploy Task: " + name)


def unresolved_request(state):
    status = state["status"]
    return (
        status in {"RUNNING", "CHANGESET_CREATING", "READY", "UNKNOWN"}
        or state.get("attemptResult") == "UNKNOWN" and status != "SETTLED"
        or state.get("cleanupStatus") == "DELETE_INTENT"
        or state.get("bootstrap", {}).get("stage")
        in {"BOOTSTRAP_INTENT", "VALUE_CHECKED_MISSING", "PUT_SUBMITTED"}
        or state.get("clientToken") and status not in {"SUCCESS", "FAILED", "SETTLED"}
    )


def progress_state(backend, require):
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


def save_progress(backend, fields, require=None):
    if getattr(backend, "phase", None) not in {"deploy", "update"}:
        return
    context = backend.run_context
    task_file = getattr(backend, "progress_task_file", None)
    if backend.phase == "deploy" or task_file is not None:
        identity = backend.progress_identity
        if (
            backend.root.resolve() != backend.progress_root
            or task_file is not None and task_file != identity["taskFile"]
            or context.get("repository") != str(backend.progress_root)
            or context.get("taskFile") != identity["taskFile"]
            or context.get("taskDigest") != identity["taskDigest"]
            or context.get("target") != identity["target"]
            or context.get("environment") != identity["environment"]
            or context.get("directory") != backend.progress_directory
            or set(context["states"]) != set(identity["stacks"])
        ):
            raise ws.Blocked("Deploy progress differs from its fixed identity")
        path = progress_path(backend.root, task_file, create=True)
        if path != backend.progress_destination:
            raise ws.Blocked("Deploy progress destination changed")
        if path.exists() or path.is_symlink():
            read_progress(backend.root, {"deployIdentity": identity}, task_file)
    else:
        identity = progress_state(backend, require)["deployIdentity"]
        path = progress_path(backend.root, task_file, create=True)
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
                "reason",
            }
        }
        for name, entry in context["states"].items()
    }
    progress = {"identity": identity, "runContext": saved}
    write_sealed(backend.root, path, progress)


def read_progress(root, state, task_file=None):
    path = progress_path(root, task_file)
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
            for key in ("pendingObserved", "pendingGeneration", "checkpointPending", "syncPending")
        )
    ):
        raise ws.Blocked("Deploy progress recovery context is incomplete or corrupt")
    if "syncPending" in context:
        sync = context["syncPending"]
        if (
            set(sync) != {"stacks", "final"}
            or not isinstance(sync["stacks"], list)
            or not all(isinstance(name, str) for name in sync["stacks"])
            or len(set(sync["stacks"])) != len(sync["stacks"])
            or not set(sync["stacks"]) <= set(progress["identity"]["stacks"])
            or not isinstance(sync["final"], bool)
        ):
            raise Blocked("Deploy sync intent is corrupt")
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
