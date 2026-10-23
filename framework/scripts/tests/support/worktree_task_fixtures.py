"""Real temporary Git repositories exercise worktree lifecycle and failure retention."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import importlib.util
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import task_contract as tasks
import worktree_task as wt

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCRIPT = (Path(__file__).resolve().parents[2] / 'worktree_task.py')

def git(root, *args):
    return wt.output(root, *args)

def contract(task_id, files):
    name = f"tasks/{task_id}.md"
    listed = "\n".join(f"- `{path}`" for path in [name, *files])
    return f"""# Task
## Task contract
- Task type: `governance`
- Task status: `running`
## Validation scope
- `framework`
## Required changes
- [R1] Fixture change
## Acceptance checks
- [R1] `exists:{files[0]}`
## Modified files
{listed}
## Allowed paths
{listed}
"""

@contextmanager
def fixture(branch="main"):
    with tempfile.TemporaryDirectory(prefix="worktree-check-") as directory:
        root = Path(directory).resolve() / "repository"
        root.mkdir()
        git(root, "init", "-q", "-b", branch)
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "config", "commit.gpgsign", "false")
        (root / ".gitignore").write_text("tasks/**\n/.worktrees/\n__pycache__\nsecret.bin\n", encoding="utf-8")
        (root / "file.txt").write_text("original\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-qm", "fixture")
        yield root

def cli(root, command, task_id="example", success=True, approval=None):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONOPTIMIZE": "0"}
    # Package setup is covered separately; Git safety cases use an offline stub.
    result = subprocess.run([sys.executable, "-B", "-c",
                             "import sys; from unittest.mock import patch; "
                             f"sys.path.insert(0, {str(SCRIPT.parent)!r}); import worktree_task as wt; "
                             "p=patch.object(wt.python_env, 'setup', return_value={'status':'ready'}); p.start(); "
                             "raise SystemExit(wt.main())", command,
                             "--repository-root", str(root), "--task-id", task_id,
                             *(["--human-approved-validation-failure", approval] if approval is not None else [])],
                            cwd=root, env=environment, capture_output=True, encoding="utf-8")
    data = json.loads(result.stdout)
    assert result.returncode == (0 if success else 1), result.stdout + result.stderr
    assert data["status"] == ("ok" if success else "blocked"), data
    return data

def start(root, task_id="example", files=("file.txt",)):
    state = cli(root, "create", task_id)
    target = Path(state["worktree"])
    assert target == Path(state["primary"]) / ".worktrees" / task_id
    tasks.start(target, state["task_file"], contract(task_id, files))
    return target, state

def finish_contract(target, state):
    tasks.complete(target, state["task_file"])

def retained(root, target, state, base_head):
    assert git(root, "rev-parse", f"refs/heads/{state['base']}") == base_head
    assert target.is_dir() and wt.branch_exists(root, state["branch"])
    assert any(e.get("branch") == f"refs/heads/{state['branch']}" for e in wt.worktrees(root))


__all__ = ['Path', 'SCRIPT', 'cli', 'contextmanager', 'contract', 'finish_contract', 'fixture', 'git', 'importlib', 'json', 'os', 'patch', 'retained', 'start', 'subprocess', 'sys', 'tasks', 'tempfile', 'wt']


@pytest.fixture
def managed_project_workspace(request):
    selected_task = tasks.selected_task
    with fixture() as primary:
        target, state = start(primary, task_id=getattr(request, 'param', 'observation-fixture'), files=('file.txt',))
        with selected_task(target, state['task_file']):
            yield target
