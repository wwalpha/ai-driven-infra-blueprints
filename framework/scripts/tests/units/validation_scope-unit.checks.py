#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from functools import partial
from types import SimpleNamespace
from unittest import TestCase

import pytest
import sync_runtime
from support.fixture_cases import materialize_files
from support.regression_cases import case_ids
from support.validation_scope_fixtures import (
    VALIDATOR,
    Path,
    active_scope,
    patch,
    subprocess,
    sys,
)
from validation import project
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def generation_diagnostic(root, scope, *, findings, **kwargs):
    findings.check(False, "consumer missing: stg/team/config")
    return tuple(findings.errors)


@pytest.mark.parametrize(
    "scope", [None, {("stg", "team", "config"), ("dev", "team", "config")}]
)
@pytest.mark.parametrize("workers", [1, 4])
def check_internal_generation_dispatch(tmp_path, scope, workers):
    with (
        patch.object(
            sync_runtime,
            "compare_generation",
            side_effect=generation_diagnostic,
        ) as compare,
        patch.object(
            subprocess, "run", side_effect=AssertionError("Python subprocess")
        ),
    ):
        validator = VALIDATOR.Validator(
            tmp_path,
            scope,
            workers=workers,
            definitions_root=tmp_path / "external-definitions",
        )
        validator.check_generated_service_models()
        validator.check_generated_service_models()
    compare.assert_called_once_with(
        tmp_path,
        scope,
        jobs=workers,
        definitions_root=tmp_path / "external-definitions",
        findings=validator.findings,
    )
    assert any(
        "consumer missing: stg/team/config" in error for error in validator.errors
    )
    with patch.object(
        sync_runtime, "compare_generation", side_effect=AssertionError("hook bypassed")
    ):
        empty = VALIDATOR.Validator(tmp_path, set())
        empty.check_generated_service_models()
        assert not empty.errors


def active_scope_case(tmp_path, case):
    data = case["data"]
    materialize_files(tmp_path, case["files"])
    path = tmp_path / "tasks/example.md"
    before = path.read_bytes()
    if data["valid"]:
        scope = active_scope(tmp_path)
        if data["all"]:
            TestCase().assertIsNone(scope)
        else:
            TestCase().assertIs(type(scope), set)
            for item in scope:
                TestCase().assertIs(type(item), tuple)
            TestCase().assertEqual(scope, {tuple(item) for item in data["scope"]})
        report = {
            "scope": [list(item) for item in sorted(scope)]
            if scope is not None
            else None
        }
    else:
        with pytest.raises(ValueError) as caught:
            active_scope(tmp_path)
        report = {"error": type(caught.value).__name__, "message": str(caught.value)}
    TestCase().assertIsNone(active_scope(tmp_path, True))
    TestCase().assertEqual(path.read_bytes(), before)
    return report


@pytest.mark.parametrize("case_id", case_ids("validation_scope"))
def check_active_scope(tmp_path, case_runner, case_id):
    case_runner.run("validation_scope", case_id, partial(active_scope_case, tmp_path))


@pytest.mark.parametrize(
    "entry",
    [
        ("unknown", "cde", "ec2"),
        ("dev", "999999999999", "ec2"),
        ("dev", "cde", "missing"),
    ],
)
def check_unknown_scope_inputs(tmp_path, entry):
    findings = Findings(tmp_path)
    with (
        patch.object(
            project, "task_plan", return_value=SimpleNamespace(services=set())
        ),
        patch.object(
            project._imports_model_sources, "model_exists", return_value=False
        ),
        patch.object(
            project._imports_model_sources,
            "load_model",
            side_effect=ValueError("missing model"),
        ),
    ):
        project.check_validation_scope(
            {("dev", "cde"): {}}, set(), None, findings, tmp_path, {entry}, None
        )
    assert findings.errors
    if entry[:2] != ("dev", "cde"):
        assert any(
            "validation target is not defined" in error for error in findings.errors
        )


def check_invalid_design_artifact(tmp_path):
    view = tmp_path / "docs/designs/dev/cde/ec2.md"
    view.parent.mkdir(parents=True)
    view.write_text("# Synthetic view\n")
    artifact = view.with_suffix("") / "orphan.json"
    artifact.parent.mkdir()
    artifact.write_text("bad JSON")
    validator = VALIDATOR.Validator(tmp_path, {("dev", "cde", "ec2")})
    validator.accounts = {("dev", "cde"): {}}
    validator.check_design_artifacts()
    assert any("invalid design JSON" in error for error in validator.errors)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
