"""Thin fixture-case execution and explicit pytest-regressions expectations."""

import os
from contextvars import ContextVar
from pathlib import Path

import pytest
from support.fixture_cases import _identifier, load_case, load_suite

_EXPECTED = Path(__file__).resolve().parents[1] / "expected"
_EXPECTED_UPDATE = ContextVar("regression_expected_update", default=None)
_DESTINATIONS = pytest.StashKey[dict[Path, str]]()


def case_ids(suite, *, prefix=""):
    selected = [name for name in load_suite(suite)["cases"] if name.startswith(prefix)]
    if not selected:
        raise ValueError("empty regression case selection")
    return selected


def check_update_options(config):
    if config.getoption("regen_all"):
        raise pytest.UsageError("--regen-all is forbidden for regression cases")
    if config.getoption("force_regen") and (
        os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")
    ):
        raise pytest.UsageError("regression updates are forbidden in CI")


def expected_path(suite, case_id):
    if not _identifier(suite) or not _identifier(case_id):
        raise ValueError("invalid regression suite/case ID")
    path = _EXPECTED / suite / f"{case_id}.yml"
    for component in (_EXPECTED, path.parent, path):
        if component.is_symlink():
            raise ValueError("regression Expected path is a symlink")
    if not path.resolve().is_relative_to(_EXPECTED.resolve()):
        raise ValueError("regression Expected path escapes root")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("regression Expected must be an unshared regular file")
    return path


class CaseRunner:
    def __init__(self, request, data_regression):
        self.request = request
        self.regression = data_regression

    def run(self, suite, case_id, execute):
        check_update_options(self.request.config)
        if self.regression.force_regen:
            raise pytest.UsageError("use explicit --force-regen case selection")
        case = load_case(suite, case_id)
        if "expected" in case:
            raise ValueError("regression case has inline expected")
        path = expected_path(suite, case_id)
        owners = self.request.config.stash.setdefault(_DESTINATIONS, {})
        owner = self.request.node.nodeid
        if path in owners and owners[path] != owner:
            raise ValueError("regression Expected already belongs to another test")
        updating = self.request.config.getoption("force_regen")
        if updating:
            selected = False
            for argument in self.request.config.args:
                filename, separator, node = argument.partition("::")
                if (
                    separator
                    and "[" in node
                    and Path(filename).resolve() == self.request.node.path.resolve()
                    and node == owner.partition("::")[2]
                ):
                    selected = True
            if not selected:
                raise pytest.UsageError(
                    "--force-regen requires an explicit case node ID"
                )
        elif not path.is_file():
            pytest.fail("missing regression Expected; review an explicit local update")
        owners[path] = owner
        actual = execute(case)
        if type(actual) is not dict:
            raise TypeError("regression executor must return a dictionary")
        # Only the plugin write, after executor contracts pass, may update Expected.
        token = _EXPECTED_UPDATE.set(
            expected_path(suite, case_id) if updating else None
        )
        try:
            self.regression.check(actual, fullpath=path)
        finally:
            _EXPECTED_UPDATE.reset(token)
        if updating:
            pytest.fail(
                "regression update run is not validation evidence", pytrace=False
            )
