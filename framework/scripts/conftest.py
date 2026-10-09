"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import tempfile
import shutil
from pathlib import Path
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp is None:
        directory = tempfile.TemporaryDirectory(prefix="model-design-pytest-")
        config.option.basetemp = directory.name
        config.add_cleanup(directory.cleanup)


@pytest.fixture
def framework_root(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[2] / "framework", tmp_path / "framework")
    return tmp_path
