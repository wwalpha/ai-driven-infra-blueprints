"""Deploy progress evidence and its fixed identity."""

import copy

import worktree_state as ws
from task_contract_core import normalize_selector
from utils.json_format import fingerprint
from utils.local_evidence import evidence_store, read_sealed, write_sealed
from utils.script_loader import module


def progress_path(root, task_file, *, create=False):
    operation_journal = module("deploy/operation_journal.py", "deploy.operation_journal")
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
        raise ws.Blocked("saved Deploy progress differs from the selected Task")
    return read_progress(root, {"deployIdentity": fixed}, task.name)


def correction_path(path):
    return path.with_name("contract-correction.json")


def require_no_correction(path):
    intent = correction_path(path)
    if intent.exists() or intent.is_symlink():
        raise ws.Blocked("unfinished Deploy contract correction; retry --correct-deploy-contract")


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


def save_progress(backend, fields):
    if getattr(backend, "phase", None) not in {"deploy", "update"}:
        return
    context = backend.run_context
    identity = backend.progress_identity
    task_file = backend.progress_task_file
    if (
        backend.root.resolve() != backend.progress_root
        or task_file != identity["taskFile"]
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
    saved = copy.deepcopy(context)
    saved["states"] = {
        name: {
            key: copy.deepcopy(value)
            for key, value in entry.items()
            if key in fields
            or key
            in {
                "currentStack",
                "reason",
            }
        }
        for name, entry in context["states"].items()
    }
    progress = {"identity": identity, "runContext": saved}
    write_sealed(backend.root, path, progress)


def read_progress(root, state, task_file=None):
    path = progress_path(root, task_file or state["deployIdentity"]["taskFile"])
    if not path.exists() and not path.is_symlink():
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
            for key in ("pendingObserved", "pendingGeneration", "syncPending")
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
            raise ws.Blocked("Deploy sync intent is corrupt")
    return progress
