"""Domain publication authority supplied by ordinary Git or authored file snapshots.

Managed checkout ownership is checked separately by Worktree tests. Real Task,
Model, snapshot, publication and rollback guards remain active here.
"""
import subprocess
from contextlib import contextmanager
from unittest.mock import patch

import model.importing.repository as repository


def git_revision(root, name):
    return str(root.resolve()), name, subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True, capture_output=True, text=True).stdout.strip() if (root / '.git').exists() else None


@contextmanager
def publication_repository(revision=git_revision):
    with patch.object(repository, 'publication_revision', revision):
        yield
