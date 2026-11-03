#!/usr/bin/env python3
"""Bounded failure injection for regression paths, updates and exact snapshots."""

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import yaml
from pytest_regressions.data_regression import (
    DataRegressionFixture,
    RegressionYamlDumper,
)
from support import fixture_cases, regression_cases
from support.pytest_cli import run


@pytest.fixture
def runner_environment(tmp_path, monkeypatch, request):
    monkeypatch.setattr(fixture_cases, "_FIXTURES", tmp_path)
    monkeypatch.setattr(regression_cases, "_EXPECTED", tmp_path / "expected")
    fixture_cases._suite.cache_clear()
    (tmp_path / "example.yaml").write_text(
        "version: 1\ncases:\n  first:\n    data: {result: [true, false, 0, '1', null]}\n"
        "  second:\n    data: {result: [other]}\n",
        encoding="utf-8",
    )
    config = Mock(stash=pytest.Stash(), args=[request.node.nodeid])
    config.getoption.side_effect = {"force_regen": False, "regen_all": False}.get
    node = SimpleNamespace(
        nodeid=request.node.nodeid,
        path=request.node.path,
        cls=None,
        name=request.node.name,
    )
    fake_request = SimpleNamespace(config=config, node=node)
    obtained = tmp_path / "obtained"
    obtained.mkdir()
    regression = DataRegressionFixture(obtained, obtained, fake_request)
    runner = regression_cases.CaseRunner(fake_request, regression)
    yield runner
    fixture_cases._suite.cache_clear()


def execute(case):
    if regression_cases._EXPECTED_UPDATE.get() is not None:
        pytest.fail("Expected write permission reached executor")
    return case["data"]


def write_expected(case_id, data):
    path = regression_cases.expected_path("example", case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, Dumper=RegressionYamlDumper, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def check_ids_and_independent_reordered_runs(runner_environment):
    runner = runner_environment
    if regression_cases.case_ids("example") != ["first", "second"]:
        pytest.fail("case IDs lost authored order")
    if regression_cases.case_ids("example", prefix="sec") != ["second"]:
        pytest.fail("prefix selection changed")
    for case_id in ("second", "first", "second", "first"):
        write_expected(case_id, fixture_cases.load_case("example", case_id)["data"])
        runner.run("example", case_id, execute)
    changed = fixture_cases.load_case("example", "first")
    changed["data"]["result"].append("polluted")
    runner.run("example", "first", execute)
    with pytest.raises(ValueError, match="empty"):
        regression_cases.case_ids("example", prefix="absent-")
    with pytest.raises(ValueError, match="unknown"):
        runner.run("example", "missing", execute)
    with pytest.raises(ValueError, match="invalid"):
        regression_cases.case_ids("../example")


@pytest.mark.parametrize("case_id", ["../first", "first/child", "First", "", "a\\b"])
def check_invalid_paths(case_id):
    with pytest.raises(ValueError, match="invalid"):
        regression_cases.expected_path("example", case_id)
    with pytest.raises(ValueError, match="invalid"):
        regression_cases.expected_path(case_id, "first")


@pytest.mark.parametrize("component", ["root", "suite", "file"])
def check_symlink_paths(runner_environment, tmp_path, component):
    root = regression_cases._EXPECTED
    outside = tmp_path / "outside"
    outside.mkdir()
    path = {
        "root": root,
        "suite": root / "example",
        "file": root / "example/first.yml",
    }[component]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        runner_environment.run("example", "first", execute)
    if list(outside.iterdir()):
        pytest.fail("symlink destination was modified")


def check_output_ownership_and_hardlinks(runner_environment):
    runner = runner_environment
    path = write_expected("first", {"result": [True, False, 0, "1", None]})
    runner.run("example", "first", execute)
    runner.request.node.nodeid += "-other-test"
    with pytest.raises(ValueError, match="another test"):
        runner.run("example", "first", execute)
    path.with_name("second.yml").hardlink_to(path)
    with pytest.raises(ValueError, match="unshared"):
        regression_cases.expected_path("example", "second")


def check_missing_expected_does_not_execute_or_write(runner_environment):
    execute_mock = Mock()
    with pytest.raises(pytest.fail.Exception, match="missing regression Expected"):
        runner_environment.run("example", "first", execute_mock)
    execute_mock.assert_not_called()
    if regression_cases._EXPECTED.exists():
        pytest.fail("missing Expected was auto-created")


@pytest.mark.parametrize(
    "actual",
    [
        {"result": [1, False, 0, "1", None]},
        {"result": [True, 0, 0, "1", None]},
        {"result": [True, False, 0, 1, None]},
        {"result": [True, False, 0, "1"]},
        {"result": [False, True, 0, "1", None]},
        {"result": [True, False, 0, "1", None], "extra": 1},
    ],
    ids=["true-one", "false-zero", "string-number", "missing-null", "order", "extra"],
)
def check_snapshot_faults_fail_without_update(runner_environment, actual):
    expected = {"result": [True, False, 0, "1", None]}
    path = write_expected("first", expected)
    original = path.read_bytes()
    executor = Mock(return_value=deepcopy(actual))
    with pytest.raises(AssertionError, match="FILES DIFFER"):
        runner_environment.run("example", "first", executor)
    if path.read_bytes() != original:
        pytest.fail("normal mismatch changed Expected")


@pytest.mark.parametrize("option", ["regen_all", "force_regen"])
def check_ci_updates_rejected(runner_environment, monkeypatch, option):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    runner = runner_environment
    runner.request.config.getoption.side_effect = {option: True}.get
    executor = Mock()
    with pytest.raises(pytest.UsageError):
        runner.run("example", "first", executor)
    executor.assert_not_called()
    if regression_cases._EXPECTED.exists():
        pytest.fail("CI update wrote Expected")


def check_local_update_requires_case_and_is_never_pass(runner_environment, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    runner = runner_environment
    runner.request.config.getoption.side_effect = {"force_regen": True}.get
    with pytest.raises(pytest.UsageError, match="explicit case"):
        runner.run("example", "first", execute)
    runner.request.node.nodeid += "[first]"
    runner.request.config.args = [
        str(runner.request.node.path)
        + "::"
        + runner.request.node.nodeid.partition("::")[2]
    ]
    with pytest.raises(pytest.fail.Exception, match="created"):
        runner.run("example", "first", execute)
    if regression_cases._EXPECTED_UPDATE.get() is not None:
        pytest.fail("Expected write permission leaked after failure")
    path = regression_cases.expected_path("example", "first")
    if not path.is_file():
        pytest.fail("explicit local update did not create Expected")
    with pytest.raises(pytest.fail.Exception, match="not validation evidence"):
        runner.run("example", "first", execute)
    with pytest.raises(pytest.fail.Exception, match="regenerating"):
        runner.run("example", "first", Mock(return_value={"result": "updated"}))
    runner.request.config.getoption.side_effect = {}.get
    runner.run("example", "first", Mock(return_value={"result": "updated"}))


def check_inline_expected_and_non_dict_rejected(runner_environment):
    runner = runner_environment
    write_expected("first", {})
    with pytest.raises(TypeError, match="dictionary"):
        runner.run("example", "first", Mock(return_value=[]))
    runner.regression.force_regen = True
    with pytest.raises(pytest.UsageError, match="explicit"):
        runner.run("example", "first", execute)
    runner.regression.force_regen = False
    fixture_cases._suite.cache_clear()
    (fixture_cases._FIXTURES / "example.yaml").write_text(
        "version: 1\ncases: {first: {expected: {result: old}}}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="inline expected"):
        runner.run("example", "first", execute)


if __name__ == "__main__":
    raise SystemExit(run(__file__))
