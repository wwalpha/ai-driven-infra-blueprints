"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]


import tempfile
import shutil
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp is None:
        directory = tempfile.TemporaryDirectory(prefix="model-design-pytest-")
        config.option.basetemp = directory.name
        config.add_cleanup(directory.cleanup)


@pytest.fixture
def framework_root(tmp_path):
    from support.it_workspace import populate
    return populate("framework", tmp_path)


@pytest.fixture
def catalog_display_fixture():
    from support.model_sources import catalog_display
    with catalog_display():
        yield


@pytest.fixture
def managed_framework_root(request):
    from support.worktree_task_fixtures import fixture, git, start
    from support.it_workspace import copy_framework
    from task_contract import selected_task
    with fixture() as primary:
        copy_framework(primary / 'framework')
        git(primary, 'add', 'framework'); git(primary, 'commit', '-qm', 'synthetic Framework inputs')
        target, state = start(primary, task_id=getattr(request, 'param', 'observation-fixture'), files=('file.txt',))
        with selected_task(target, state['task_file']):
            yield target
