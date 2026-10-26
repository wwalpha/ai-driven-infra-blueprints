"""Private Deploy input directories, reclaimed only under the account/Region lock."""

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from utils.cloudformation.inputs import Blocked
from utils.sealed_evidence import read_sealed, write_sealed

from deploy import handoff, operation_journal


def references(records):
    return {
        Path(state["delivery"]["path"])
        for record in records
        for operation in [
            *record["operations"].values(),
            *record["publication"].get("generationProducers", {}).values(),
        ]
        for state in [operation["state"]]
        if state.get("delivery", {}).get("path")
    }


def create(journal, root, task, target, stacks):
    files = sorted(name + ".json" for name in stacks)
    if any(Path(name).name != name for name in files):
        raise Blocked("invalid temporary template filename")
    path = Path(tempfile.mkdtemp(prefix="inputs-", dir=journal.parent))
    write_sealed(
        journal.parent,
        path / "owner.json",
        {
            "repository": str(root),
            "taskFile": task.name,
            "taskDigest": task.task_digest,
            "target": target,
            "files": files,
        },
    )
    return path


def reclaim(journal, root, target):
    """Unknown files survive; no PID inference, global /tmp sweep or lock removal."""
    records = operation_journal.read(journal) or []
    needed = references(records)
    for directory in journal.parent.glob("inputs-*"):
        try:
            operation_journal.private_path(directory, directory=True)
            marker = operation_journal.safe_path(directory / "owner.json")
            operation_journal.private_path(marker)
            owner = read_sealed(journal.parent, marker)
            if operation_journal.target_identity(
                owner["target"]
            ) != operation_journal.target_identity(target):
                continue
            if not operation_journal.same_repository(root, owner["repository"]):
                continue
            with handoff.repair_lock(Path(owner["repository"])):
                needed.update(
                    handoff.failure_templates(Path(owner["repository"]), target)
                )
                if any(p.is_relative_to(directory) for p in needed):
                    continue
                expected = {"owner.json", *owner["files"]}
                files = list(directory.iterdir())
                if any(
                    p.name not in expected
                    or p.is_symlink()
                    or not stat.S_ISREG(p.lstat().st_mode)
                    or os.name != "nt"
                    and p.stat().st_uid != os.getuid()
                    for p in files
                ):
                    raise Blocked("unknown temporary files need preservation")
                for file in files:
                    operation_journal.private_path(file, permissions=0o022)
                shutil.rmtree(directory)
        except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
            print(
                f"Deploy temporary files retained: {directory}: {error}",
                file=sys.stderr,
            )
