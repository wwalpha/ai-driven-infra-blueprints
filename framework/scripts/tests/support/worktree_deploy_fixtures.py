"""Managed parent setup for dedicated Worktree repair integration only."""
import os
import sys
import sysconfig
import venv
from pathlib import Path

import worktree_task as wt
from support.deploy_controller_fixtures import invoke
from support.deploy_controller_fixtures import seed as seed_project
from support.repository_fixtures import git
from support.worktree_task_fixtures import cli as worktree_cli
from task_contract_core import start


def seed(root, state_path, case='orders', **kwargs):
    seed_project(root, state_path, case, **kwargs)
    task = root / 'tasks/deploy.md'
    ignore = root / '.gitignore'
    ignore.write_text(ignore.read_text() + '/.worktrees/\n')
    git(root, 'add', '.gitignore')
    git(root, 'commit', '-qm', 'Managed fixture ignores')
    # Provision only the interpreter offline; dependencies come from this fixed test runtime.

    directory = root / '.worktrees/.blueprint/python-env'
    venv.EnvBuilder(with_pip=False).create(directory)
    version = f'python{sys.version_info.major}.{sys.version_info.minor}'
    packages = directory / 'lib' / version / 'site-packages'
    (packages / 'fixture-runtime.pth').write_text(sysconfig.get_path('purelib') + '\n')
    for marker in ('.blueprint-owner', '.blueprint-ready'):
        (directory / marker).write_text(str(directory))
    saved_contract = '\n'.join(line for line in task.read_text().splitlines() if not line.startswith('- `infra/')) + '\n'
    # Retain master's lifecycle fixture; finish its provisioning through real setup.
    state = worktree_cli(root, 'create', task_id='deploy')
    state = wt.setup(root, 'deploy')
    target = Path(state['worktree'])
    start(target, state['task_file'], saved_contract)
    return target


if __name__ == '__main__':
    root, state_path, aws_path = map(lambda arg: Path(arg).resolve(), sys.argv[1:4])
    os.chdir(root)
    raise SystemExit(invoke(root, state_path, aws_path, sys.argv[4:], fault=os.environ.get('BLUEPRINT_OBSERVED_FAULT')))
