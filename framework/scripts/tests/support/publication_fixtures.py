"""Domain publication authority supplied by ordinary Git or authored file snapshots.

Managed checkout ownership is checked separately by Worktree tests. Real Task,
Model, snapshot, publication and rollback guards remain active here.
"""

import subprocess
from contextlib import contextmanager
from unittest.mock import patch

import model.importing.repository as repository
from deploy import git_publication, steps, worktree


def git_revision(root, name):
    return (
        str(root.resolve()),
        name,
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if (root / ".git").exists()
        else None,
    )


def deploy_identity(root, task, target, environment, stacks):
    return {
        "taskFile": task.name,
        "taskDigest": task.task_digest,
        "target": target,
        "environment": environment,
        "stacks": sorted(stacks),
    }


@contextmanager
def publication_repository(revision=git_revision):
    # These suites own Model/AWS behavior; dedicated Deploy Worktree UT/IT own lifecycle.
    with (
        patch.object(repository, "publication_revision", revision),
        patch.multiple(
            worktree,
            require=lambda *a, **k: None,
            bind=deploy_identity,
            require_complete=lambda *a: None,
            prepare_complete=lambda *a: None,
        ),
        patch.object(steps, "checkpoint_receipts", return_value={}),
        patch.object(steps, "publish_snapshot"),
        patch.object(git_publication, "sync"),
    ):
        yield
