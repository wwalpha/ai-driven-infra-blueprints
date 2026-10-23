"""Ordinary Git and Task fixtures, independent of managed worktree lifecycle."""

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from task_contract_core import selected_task


def git(root, *args):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    environment.update(GIT_TERMINAL_PROMPT='0', GIT_EDITOR='true', GIT_SEQUENCE_EDITOR='true')
    result = subprocess.run(['git', *map(str, args)], cwd=root, env=environment, capture_output=True, encoding='utf-8')
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def contract(task_id, files):
    name = f'tasks/{task_id}.md'
    listed = '\n'.join(f'- `{path}`' for path in [name, *files])
    return f'''# Task
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
'''


@contextmanager
def fixture(branch='main'):
    with tempfile.TemporaryDirectory(prefix='repository-check-') as directory:
        root = Path(directory).resolve() / 'repository'
        root.mkdir()
        git(root, 'init', '-q', '-b', branch)
        git(root, 'config', 'user.name', 'Fixture')
        git(root, 'config', 'user.email', 'fixture@example.invalid')
        git(root, 'config', 'commit.gpgsign', 'false')
        (root / '.gitignore').write_text('tasks/**\n__pycache__\nsecret.bin\n', encoding='utf-8')
        (root / 'file.txt').write_text('original\n', encoding='utf-8')
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'fixture')
        yield root


def start(root, task_id='example', files=('file.txt',)):
    """Independent ordinary Git candidate; no linked checkout or lifecycle state."""
    root = root.resolve()
    target = root.with_name(root.name + '-candidate')
    git(root.parent, 'clone', '--quiet', '--local', str(root), str(target))
    git(target, 'config', 'user.name', 'Fixture')
    git(target, 'config', 'user.email', 'fixture@example.invalid')
    git(target, 'config', 'commit.gpgsign', 'false')
    name = f'tasks/{task_id}.md'
    (target / 'tasks').mkdir(exist_ok=True)
    (target / name).write_text(contract(task_id, files))
    return target, {'task_file': name, 'start': git(target, 'rev-parse', 'HEAD')}


@pytest.fixture
def publication_workspace(request):
    with fixture() as root:
        name = 'tasks/' + getattr(request, 'param', 'observation-fixture') + '.md'
        with selected_task(root, name):
            yield root
