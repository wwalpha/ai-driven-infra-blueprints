"""Task-local Deploy temporary inputs."""

import shutil
import sys
import tempfile
from pathlib import Path

from task_contract_core import task_snapshot
from utils.cloudformation.inputs import Blocked
from utils.local_evidence import evidence_store

from deploy import handoff, operation_journal
from deploy import progress as deploy_progress


def create(journal, stacks):
    if any(Path(name + ".json").name != name + ".json" for name in stacks):
        raise Blocked("invalid temporary template filename")
    return Path(tempfile.mkdtemp(prefix="inputs-", dir=journal.parent))


def task_directory(journal, directory):
    if directory.parent != journal.parent or not directory.name.startswith("inputs-"):
        raise Blocked("temporary directory outside Task scope")
    operation_journal.private_path(journal.parent.parent, directory=True)
    operation_journal.private_path(journal.parent, directory=True)
    operation_journal.safe_path(directory)
    if directory.exists():
        operation_journal.private_path(directory, directory=True)


def reclaim(journal, root, *, directory, backend, stacks):
    """Only the current invocation's proven directory is eligible for removal."""
    exceptional = sys.exc_info()[0] is not None
    try:
        task_directory(journal, directory)
        operation_journal.private_path(directory, directory=True)
        with handoff.repair_lock(root):
            progress = deploy_progress.read_task(root, task_snapshot(root, executable=False, live=True))
            contexts = [backend.run_context]
            if progress:
                contexts.append(progress["runContext"])
            for context in contexts:
                for state in context["states"].values():
                    delivery = state.get("delivery", {})
                    if not isinstance(delivery, dict):
                        return
                    path = delivery.get("path")
                    if path:
                        if (
                            not isinstance(path, str)
                            or not Path(path).is_absolute()
                            or ".." in Path(path).parts
                        ):
                            return
                        if Path(path).is_relative_to(directory):
                            return
            files = list(directory.iterdir())
            if not files:
                directory.rmdir()
                return
            if exceptional:
                return
            store = evidence_store(root, create=False)
            if any(
                next(store.glob(pattern), None)
                for pattern in (
                    "deploy-failure-*",
                    "deploy-repair-*",
                    "deploy-cleanup-*",
                )
            ):
                return
            for context in contexts:
                if any(
                    context.get(key)
                    for key in (
                        "currentFailure",
                        "pendingObserved",
                        "pendingGeneration",
                        "generationError",
                        "checkpointPending",
                    )
                ):
                    return
                if any(
                    state.get("attemptResult") == "UNKNOWN"
                    or state.get("status")
                    in {
                        "RUNNING",
                        "CHANGESET_CREATING",
                        "READY",
                        "BLOCKED",
                        "FAILED",
                        "UNKNOWN",
                    }
                    for state in context["states"].values()
                ):
                    return
            if any(
                file.name not in {name + ".json" for name in stacks} for file in files
            ):
                return
            for file in files:
                operation_journal.private_path(file, permissions=0o022)
            shutil.rmtree(directory)
    except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Deploy temporary files retained: {directory}: {error}", file=sys.stderr)


def diagnostic_paths(journal, backend, stacks):
    """Return only known templates in the selected Task's private input area."""
    result = set()
    candidates = []
    directory = getattr(backend, "workdir", None)
    if directory:
        candidates.extend(Path(directory) / (name + ".json") for name in stacks)
    for state in getattr(backend, "states", {}).values():
        delivery = state.get("delivery")
        if isinstance(delivery, dict) and isinstance(delivery.get("path"), str):
            candidates.append(Path(delivery["path"]))
    for path in candidates:
        try:
            if (
                path.is_absolute()
                and path.parent.parent == journal.parent
                and path.parent.name.startswith("inputs-")
                and path.name in {name + ".json" for name in stacks}
            ):
                task_directory(journal, path.parent)
                operation_journal.safe_path(path)
                result.add(str(path))
        except (OSError, ValueError, Blocked):
            continue
    return result
