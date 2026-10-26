"""Private Deploy input directories, reclaimed only under the account/Region lock."""

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from utils.cloudformation.inputs import Blocked
from utils.sealed_evidence import read_sealed, write_sealed

from deploy import operation_journal


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


def reclaim(journal, root, task, target, *, prior=()):
    """Unknown files survive; no PID inference, global /tmp sweep or lock removal."""
    records = operation_journal.read(journal) or []
    needed = references(records)
    released = {p.parent for p in prior}
    for directory in journal.parent.glob("inputs-*"):
        try:
            operation_journal.private_path(directory, directory=True)
            marker = operation_journal.safe_path(directory / "owner.json")
            owner = read_sealed(journal.parent, marker)
            if owner["target"] != target:
                continue
            if owner["repository"] != str(root) and not (
                directory in released
                and operation_journal.same_repository(root, owner["repository"])
            ):
                continue
            if not (
                owner["taskFile"] == task.name
                and owner["taskDigest"] == task.task_digest
                or directory in released
            ):
                continue
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
            shutil.rmtree(directory)
        except (Blocked, OSError, ValueError, KeyError, TypeError) as error:
            print(
                f"Deploy temporary files retained: {directory}: {error}",
                file=sys.stderr,
            )
