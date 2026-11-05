"""Deploy progress evidence and its fixed identity."""

import copy
from pathlib import Path

import worktree_state as ws
from utils.local_evidence import evidence_store, read_sealed, write_sealed


def progress_path(root, *, create=False):
    return evidence_store(root, create=create) / "deploy-progress.json"


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
        identity = progress_state(backend, require)["deployIdentity"]
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
                "reason",
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
