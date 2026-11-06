"""Project input snapshots shared by Deploy completion and contract correction."""

import task_contract_core as _imports_task_contract
from utils.file_operations import sha as sha
from worktree_state import output as output
from worktree_state import paths
from worktree_state import subprocess_bytes as subprocess_bytes


def validation_snapshot(root):
    """Hash mutable Project Git inputs used by Deploy validation."""
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
            ":(top,exclude).lock",
        )
    ):
        path = safe_path(root, relative)
        result[relative] = sha(path) if path.is_file() else None
    return result
