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
    shutil.copytree(Path(__file__).resolve().parents[3] / "framework", tmp_path / "framework")
    return tmp_path


@pytest.fixture
def catalog_display_fixture():
    from support.model_sources import catalog_display
    with catalog_display():
        yield
