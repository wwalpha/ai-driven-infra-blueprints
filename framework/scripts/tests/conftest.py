"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import tempfile
import warnings
from unittest.mock import _patch, patch

import pytest
import support.model_sources as _imports_support_model_sources
import utils.aws_mappings as _imports_utils_aws_mappings
from support.publication_fixtures import publication_repository
from support.regression_cases import CaseRunner, check_update_options
from support.worktree_test_policy import (
    audit,
    ordinary_suite,
    violations,
    worktree_suite,
)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    check_update_options(config)
    sys.addaudithook(audit)
    if os.environ.get("BLUEPRINT_UT_TIMING_DIR"):
        config.pluginmanager.register(UnitTiming(config))
    if config.option.basetemp is None:
        directory = tempfile.TemporaryDirectory(prefix="model-design-pytest-")
        config.option.basetemp = directory.name
        config.add_cleanup(directory.cleanup)


class UnitTiming:
    def __init__(self, config):
        self.directory = Path(os.environ["BLUEPRINT_UT_TIMING_DIR"])
        self.cases = {}
        self.paths = {}

    def pytest_collection_finish(self, session):
        self.paths = {item.nodeid: str(item.path.resolve()) for item in session.items}

    def pytest_runtest_logreport(self, report):
        case = self.cases.setdefault(
            report.nodeid,
            {
                "nodeid": report.nodeid,
                "path": self.paths.get(report.nodeid),
                "phases": {},
                "status": "INCOMPLETE",
            },
        )
        case["phases"][report.when] = report.duration
        if report.failed:
            case["status"] = "FAIL"
        elif report.skipped and case["status"] != "FAIL":
            case["status"] = "SKIP"
        elif report.when == "call" and report.passed and case["status"] == "INCOMPLETE":
            case["status"] = "PASS"

    def pytest_sessionfinish(self, session, exitstatus):
        path = self.directory / f"pytest-{os.getpid()}-{uuid.uuid4().hex}.json"
        try:
            path.write_text(
                json.dumps(
                    {"collected": list(self.paths), "cases": list(self.cases.values())}
                ),
                encoding="utf-8",
            )
        except OSError as error:
            print(f"UT timing write failed: {error}", file=sys.stderr)


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
def process_state(request):
    if not getattr(request.config, "blueprint_ut_group", False):
        yield
        return
    cwd = Path.cwd()
    active_patches = tuple(_patch._active_patches)
    with (
        warnings.catch_warnings(),
        patch.object(os, "environ", os.environ),
        patch.dict(os.environ),
        patch.object(sys, "path", list(sys.path)),
        patch.object(sys, "argv", list(sys.argv)),
    ):
        try:
            yield
        finally:
            os.chdir(cwd)
            leaked = [
                item for item in _patch._active_patches if item not in active_patches
            ]
            for item in reversed(leaked):
                item.stop()
            if leaked:
                pytest.fail(
                    f"UT leaked {len(leaked)} started patches: {request.node.nodeid}"
                )


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
        raise pytest.UsageError("Worktree test policy: " + "; ".join(errors))


@pytest.fixture
def case_runner(request, data_regression):
    return CaseRunner(request, data_regression)
