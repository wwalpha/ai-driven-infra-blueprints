"""Single-case execution with individual or grouped YAML expectations."""

import os
from contextvars import ContextVar
from difflib import unified_diff
from functools import lru_cache
from pathlib import Path

import pytest
import yaml
from pytest_regressions.data_regression import RegressionYamlDumper
from support.fixture_cases import _identifier, load_case, load_suite
from utils.yaml_format import yaml_read

_EXPECTED = Path(__file__).resolve().parents[1] / "expected"
_EXPECTED_UPDATE = ContextVar("regression_expected_update", default=None)
_DESTINATIONS = pytest.StashKey[dict[tuple[Path, str | None], str]]()


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


def expected_path(suite, case_id, *, group=None):
    if not _identifier(suite) or not _identifier(case_id):
        raise ValueError("invalid regression suite/case ID")
    if group is not None and not _identifier(group):
        raise ValueError("invalid regression Expected group")
    path = _EXPECTED / suite / f"{group or case_id}.yml"
    for component in (_EXPECTED, path.parent, path):
        if component.is_symlink():
            raise ValueError("regression Expected path is a symlink")
    if not path.resolve().is_relative_to(_EXPECTED.resolve()):
        raise ValueError("regression Expected path escapes root")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("regression Expected must be an unshared regular file")
    return path


class GroupedDumper(RegressionYamlDumper):
    def ignore_aliases(self, data):
        return True


def _dump(data):
    return yaml.dump(data, Dumper=GroupedDumper, allow_unicode=True, indent=2)


@lru_cache(maxsize=16)
def _group(path, suite, group, text):
    if any(
        isinstance(token, (yaml.AnchorToken, yaml.AliasToken))
        for token in yaml.scan(text)
    ):
        raise ValueError("grouped Expected must not share YAML anchors")
    values = yaml_read(text)
    if not isinstance(values, dict) or yaml.compose(text).flow_style:
        raise ValueError("grouped Expected must be a block mapping")
    for case_id, value in values.items():
        if not _identifier(case_id) or type(value) is not dict:
            raise ValueError("invalid grouped Expected case")
        if load_case(suite, case_id).get("expected_group") != group:
            raise ValueError("Expected case belongs to another group")
    return values


def expected_text(suite, case_id):
    """Read one case for failure-injection checks, including grouped snapshots."""
    case = load_case(suite, case_id)
    group = case.get("expected_group")
    path = expected_path(suite, case_id, group=group)
    text = path.read_text(encoding="utf-8")
    if group is None:
        return text
    values = _group(path, suite, group, text)
    if case_id not in values:
        pytest.fail("missing regression Expected case: " + case_id)
    return _dump(values[case_id])


def _replace_case(text, case_id, actual):
    replacement = _dump({case_id: actual})
    if not text:
        return replacement
    lines = text.splitlines(keepends=True)
    node = yaml.compose(text)
    for index, (key, _) in enumerate(node.value):
        if key.value != case_id:
            continue
        start = key.start_mark.line
        end = (
            node.value[index + 1][0].start_mark.line
            if index + 1 < len(node.value)
            else len(lines)
        )
        while end > start + 1 and (
            not lines[end - 1].strip() or lines[end - 1].startswith("#")
        ):
            end -= 1
        return "".join(lines[:start]) + replacement + "".join(lines[end:])
    return text + ("" if text.endswith("\n") else "\n") + replacement


def _write_group(suite, case_id, group, path, before, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    # Exclusive creation also prevents overlapping updates of the same group.
    stream = temporary.open("x", encoding="utf-8", newline="")
    try:
        with stream:
            stream.write(content)
        expected_path(suite, case_id, group=group)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != before:
            raise ValueError("Expected changed during execution; update refused")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _check_group(suite, case_id, group, path, before, actual, updating):
    values = _group(path, suite, group, before) if before is not None else {}
    if case_id in values and _dump(values[case_id]) == _dump(actual):
        return
    if updating:
        content = _replace_case(before or "", case_id, actual)
        _write_group(suite, case_id, group, path, before, content)
        pytest.fail(
            "regenerating grouped Expected: " + str(path) + " [" + case_id + "]",
            pytrace=False,
        )
    if case_id not in values:
        pytest.fail("missing regression Expected case: " + case_id)
    difference = "".join(
        unified_diff(
            _dump(values[case_id]).splitlines(keepends=True),
            _dump(actual).splitlines(keepends=True),
            fromfile=str(path) + " [" + case_id + "]",
            tofile="actual [" + case_id + "]",
        )
    )
    pytest.fail("FILES DIFFER:\n" + difference, pytrace=False)


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
        group = case.get("expected_group")
        path = expected_path(suite, case_id, group=group)
        destination = (path, case_id if group is not None else None)
        owners = self.request.config.stash.setdefault(_DESTINATIONS, {})
        owner = self.request.node.nodeid
        if (group is not None and (path, None) in owners) or (
            group is None and any(p == path and key is not None for p, key in owners)
        ):
            raise ValueError("Expected file mixes grouped and individual ownership")
        if destination in owners and owners[destination] != owner:
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
            if group is not None and not owner.endswith("[" + case_id + "]"):
                selected = False
            if not selected:
                raise pytest.UsageError(
                    "--force-regen requires an explicit case node ID"
                )
        elif not path.is_file():
            pytest.fail("missing regression Expected; review an explicit local update")
        before = (
            path.read_text(encoding="utf-8")
            if group is not None and path.is_file()
            else None
        )
        if group is not None and not updating:
            values = _group(path, suite, group, before)
            if case_id not in values:
                pytest.fail("missing regression Expected case: " + case_id)
        owners[destination] = owner
        actual = execute(case)
        if type(actual) is not dict:
            raise TypeError("regression executor must return a dictionary")
        # Grant write access only after independent executor contracts pass.
        token = _EXPECTED_UPDATE.set(path if updating else None)
        try:
            if group is None:
                self.regression.check(actual, fullpath=path)
            else:
                _check_group(
                    suite,
                    case_id,
                    group,
                    path,
                    before,
                    actual,
                    updating,
                )
        finally:
            _EXPECTED_UPDATE.reset(token)
        if updating:
            pytest.fail(
                "regression update run is not validation evidence", pytrace=False
            )
