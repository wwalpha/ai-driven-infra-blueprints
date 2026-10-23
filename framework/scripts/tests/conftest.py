"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import tempfile

import pytest
import support.model_sources as _imports_support_model_sources
import utils.aws_mappings as _imports_utils_aws_mappings
from support.publication_fixtures import publication_repository
from support.worktree_test_policy import (
    audit,
    ordinary_suite,
    violations,
    worktree_suite,
)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    sys.addaudithook(audit)
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


@pytest.fixture(autouse=True)
def ordinary_publication(request):
    tests = Path(__file__).resolve().parent
    with ordinary_suite(request.path, tests):
        if worktree_suite(request.path, tests):
            yield
        else:
            with publication_repository():
                yield


def pytest_sessionstart(session):
    errors = violations(Path(__file__).resolve().parent)
    if errors:
        raise pytest.UsageError('Worktree test policy: ' + '; '.join(errors))
