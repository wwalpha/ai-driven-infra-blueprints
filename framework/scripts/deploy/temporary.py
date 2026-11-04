"""Task-local Deploy temporary inputs."""

import shutil
import sys
import tempfile
from pathlib import Path

from utils.cloudformation.inputs import Blocked
from utils.local_evidence import evidence_store

from deploy import handoff, operation_journal, worktree


def create(journal, stacks):
    if any(Path(name + ".json").name != name + ".json" for name in stacks):
        raise Blocked("invalid temporary template filename")
    return Path(tempfile.mkdtemp(prefix="inputs-", dir=journal.parent))


def reclaim(journal, root, *, directory, backend, stacks):
    """Only the current invocation's proven directory is eligible for removal."""
    if sys.exc_info()[0] is not None:
        return
    try:
        operation_journal.private_path(directory, directory=True)
        if directory.parent != journal.parent or not directory.name.startswith(
            "inputs-"
        ):
            return
        with handoff.repair_lock(root):
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
            progress = worktree.read_progress(root, worktree.progress_state(backend))
            contexts = [backend.run_context]
            if progress:
                contexts.append(progress["runContext"])
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
                states = context["states"]
                for state in states.values():
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
                    if state.get("attemptResult") == "UNKNOWN" or state.get(
                        "status"
                    ) in {
                        "RUNNING",
                        "CHANGESET_CREATING",
                        "READY",
                        "BLOCKED",
                        "FAILED",
                        "UNKNOWN",
                    }:
                        return
            files = list(directory.iterdir())
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
                operation_journal.private_path(path.parent, directory=True)
                operation_journal.safe_path(path)
                result.add(str(path))
        except (OSError, ValueError, Blocked):
            continue
    return result
