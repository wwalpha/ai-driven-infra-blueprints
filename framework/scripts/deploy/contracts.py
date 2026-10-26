"""Task identity and exact verified-child evidence shared by execution and validation."""

import hashlib
from pathlib import Path

import task_contract_core as _imports_task_contract
from task_contract_core import task_digest as task_digest
from utils.file_operations import sha as sha
from worktree_state import output, paths, task_start_commit
from worktree_state import subprocess_bytes as subprocess_bytes
from worktree_task import load


def accepted_changes(root, contract, changed):
    """Attribute exact child commit transitions; never grant the parent IaC write scope."""
    task_path = _imports_task_contract.task_path
    if not any(path.startswith("infra/") for path in changed):
        return set()
    selected = task_path(root).relative_to(root).as_posix()
    _, _, _, lifecycle = load(root, Path(selected).stem)
    record = lifecycle.get("iacRepair", {})
    if not record.get("commit"):
        return set()
    if record.get("taskDigest") != task_digest(contract):
        raise ValueError("one-shot repair current Task identity changed")
    commit, parent = record["commit"], record["parentTip"]
    if output(root, "rev-parse", commit + "^") != parent or paths(
        root, "diff", "--name-only", "--no-renames", "-z", parent, commit
    ) != set(record["changes"]):
        raise ValueError("child integration commit/path set changed")
    expected = {}
    for relative, transition in record["changes"].items():
        for revision, side in ((parent, "before"), (commit, "after")):
            if (
                hashlib.sha256(subprocess_bytes(root, revision, relative)).hexdigest()
                != transition[side]
            ):
                raise ValueError("child commit bytes differ from verified transition")
        expected[relative] = [(transition["before"], transition["after"])]
    delegated = set(expected) & set(changed)
    if not delegated:
        return set()
    baseline = task_start_commit(root, selected)
    if not baseline:
        raise ValueError("child attribution requires managed parent lifecycle")
    actual = {relative: [] for relative in delegated}
    for commit in output(
        root, "rev-list", "--reverse", baseline + "..HEAD"
    ).splitlines():
        parent = output(root, "rev-parse", commit + "^")
        for relative in delegated & paths(
            root, "diff", "--name-only", "--no-renames", "-z", parent, commit
        ):
            actual[relative].append(
                tuple(
                    hashlib.sha256(subprocess_bytes(root, rev, relative)).hexdigest()
                    for rev in (parent, commit)
                )
            )
    for relative in delegated:
        if (
            actual[relative] != expected[relative]
            or sha(root / relative) != expected[relative][-1][1]
        ):
            raise ValueError(
                "unrecorded parent IaC edits or commit sequence: " + relative
            )
    return delegated


def validation_snapshot(root):
    """Hash mutable Project Git inputs used by a validated repair candidate."""
    safe_path = _imports_task_contract.safe_path
    result = {}
    for relative in sorted(
        paths(
            root,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            ".",
            ":(top,exclude)framework",
        )
    ):
        path = safe_path(root, relative)
        result[relative] = sha(path) if path.is_file() else None
    return result
