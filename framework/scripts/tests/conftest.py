"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]


import tempfile
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp is None:
        directory = tempfile.TemporaryDirectory(prefix="model-design-pytest-")
        config.option.basetemp = directory.name
        config.add_cleanup(directory.cleanup)


@pytest.fixture
def shared_framework():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def project_workspace(tmp_path, shared_framework):
    from utils.aws_mappings import mapping_alias
    with mapping_alias(shared_framework.parent, tmp_path):
        yield tmp_path


@pytest.fixture
def catalog_display_fixture():
    from support.model_sources import catalog_display
    with catalog_display():
        yield


@pytest.fixture
def managed_project_workspace(request):
    from support.worktree_task_fixtures import fixture, start
    from task_contract import selected_task
    with fixture() as primary:
        target, state = start(primary, task_id=getattr(request, 'param', 'observation-fixture'), files=('file.txt',))
        with selected_task(target, state['task_file']):
            yield target
