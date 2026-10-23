"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import tempfile

import pytest
import support.model_sources as _imports_support_model_sources
import utils.aws_mappings as _imports_utils_aws_mappings


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
    mapping_alias = _imports_utils_aws_mappings.mapping_alias
    with mapping_alias(shared_framework.parent, tmp_path):
        yield tmp_path


@pytest.fixture
def catalog_display_fixture():
    catalog_display = _imports_support_model_sources.catalog_display
    with catalog_display():
        yield
