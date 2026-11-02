#!/usr/bin/env python3
"""Synthetic checks for invocation-local reuse and single-service validation handoff."""

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import subprocess
from collections import defaultdict
from contextvars import ContextVar
from unittest.mock import patch

import aws_mapping
import pytest
import support.sync_model_fixtures as _fixture_generated_policy
import sync_runtime
import sync_views
import utils.aws_mappings as mapping_state
import utils.input_cache as input_cache
from model.files import load_model
from support.model_sources import write_model
from support.pytest_cli import run
from support.sync_model_fixtures import MODULE
from support.validator import MODULE as validator_module
from utils.aws_mappings import definition_root, mappings_for
from utils.function_wrapper import BoundCallback as _bind_framework_callback
from validation.findings import Findings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

generated_policy = _fixture_generated_policy.generated_policy

_CALLBACK_DEFAULT = object()


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


COMMON = (
    "check_resource_names",
    "check_design_tables",
    "check_design_overviews",
    "check_design_links",
    "check_design_artifacts",
    "check_observed_values",
)
ENTRY = ("dev", "123456789012", "iam")


def _callback_trace_validation_init(
    instrument, original_init, root, /, validator, *args, **kwargs
):
    original_init(validator, *args, **kwargs)
    if validator.root.resolve() == root.resolve():
        instrument(validator, "saved")


def _callback_trace_validation_record_call(
    current, original, records, root, /, findings, condition, *args, **kwargs
):
    key = current.get()
    if key is None and findings.canonical_root == root.resolve():
        key = ("saved", "other")
    if key:
        normalized = tuple(
            str(arg)
            .replace(str(findings.canonical_root), "<root>")
            .replace(str(root), "<root>")
            for arg in args
        )
        records[key].append((bool(condition), normalized))
    return original(findings, condition, *args, **kwargs)


def _callback_trace_validation_record(current, records, root, /, original):
    call = _bind_framework_callback(
        _callback_trace_validation_record_call, current, original, records, root
    )
    return call


def _callback_trace_validation_factory(
    instrument, original_factory, /, stage, source, definitions_root=None
):
    return instrument(original_factory(stage, source, definitions_root), "candidate")


def _callback_trace_validation_instrument_call_86(
    current,
    records,
    side,
    validator,
    _default__original,
    _default__name,
    /,
    *args,
    _original=_CALLBACK_DEFAULT,
    _name=_CALLBACK_DEFAULT,
    **kwargs,
):
    if _original is _CALLBACK_DEFAULT:
        _original = _default__original
    if _name is _CALLBACK_DEFAULT:
        _name = _default__name
    records[side, _name].append(("invoked", ()))
    token = current.set((side, _name))
    try:
        before = len(validator.errors)
        result = _original(*args, **kwargs)
        records[side, _name].extend(
            (False, (error.replace(str(validator.root), "<root>"),))
            for error in validator.errors[before:]
        )
        return result
    finally:
        current.reset(token)


def _callback_trace_validation_instrument(current, records, /, validator, side):
    for name in (*COMMON, "check_generated_service_models"):
        original = getattr(validator, name)
        call = _bind_framework_callback(
            _callback_trace_validation_instrument_call_86,
            current,
            records,
            side,
            validator,
            original,
            name,
        )
        setattr(validator, name, call)
    return validator


def trace_validation(root):
    records = defaultdict(list)
    current = ContextVar("test_check", default=None)
    original_factory = sync_views.view_validator
    instrument = _bind_framework_callback(
        _callback_trace_validation_instrument, current, records
    )
    factory = _bind_framework_callback(
        _callback_trace_validation_factory, instrument, original_factory
    )
    record = _bind_framework_callback(
        _callback_trace_validation_record, current, records, root
    )
    original_init = validator_module.Validator.__init__
    init = _bind_framework_callback(
        _callback_trace_validation_init, instrument, original_init, root
    )
    with (
        patch.object(sync_views, "view_validator", factory),
        patch.object(validator_module.Validator, "__init__", init),
        patch.object(Findings, "warn", record(Findings.warn)),
        patch.object(Findings, "check", record(Findings.check)),
        patch.object(Findings, "check_file", record(Findings.check_file)),
    ):
        validator = validator_module.Validator(root, {ENTRY})
        validator.check_project_topology()
        validator.check_scoped_designs()
    return validator, records


def check_common_conditions_preserved(generated_policy, monkeypatch):
    root, model, values, design, artifact, register = generated_policy
    values["desired.row.001-001.value"] = "`app-dev-AppRole`"
    write_model(model, values)
    design.write_text(
        design.read_text(encoding="utf-8").replace("app-dev-role", "app-dev-AppRole"),
        encoding="utf-8",
    )
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", register([])["BLUEPRINT_TASK_FILE"])
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "synthetic validation baseline",
        ],
        cwd=root,
        check=True,
    )
    after, new = trace_validation(root)
    expected = COMMON
    for name in COMMON:
        assert bool(new["saved", name]) == (name in expected), name
        assert not new["candidate", name], name
    TestCase().assertFalse(after.errors, after.errors)


def _callback_check_deferred_guard_and_cleanup_factory_call_207(
    seen,
    _default__name,
    _default__original,
    /,
    *args,
    _name=_CALLBACK_DEFAULT,
    _original=_CALLBACK_DEFAULT,
    **kwargs,
):
    if _name is _CALLBACK_DEFAULT:
        _name = _default__name
    if _original is _CALLBACK_DEFAULT:
        _original = _default__original
    seen.append(_name)
    return _original(*args, **kwargs)


def _callback_check_deferred_guard_and_cleanup_factory(
    original_factory, seen, /, *args
):
    validator = original_factory(*args)
    for name in COMMON:
        original = getattr(validator, name)
        call = _bind_framework_callback(
            _callback_check_deferred_guard_and_cleanup_factory_call_207,
            seen,
            name,
            original,
        )
        setattr(validator, name, call)
    return validator


def check_deferred_guard_and_cleanup(generated_policy, monkeypatch):
    root, _, _, design, artifact, register = generated_policy
    monkeypatch.setenv(
        "BLUEPRINT_TASK_FILE", register([design, artifact])["BLUEPRINT_TASK_FILE"]
    )
    seen = []
    original_factory = sync_views.view_validator
    factory = _bind_framework_callback(
        _callback_check_deferred_guard_and_cleanup_factory, original_factory, seen
    )
    with patch.object(sync_views, "view_validator", side_effect=factory):
        for write in (False, True):
            seen.clear()
            assert MODULE.sync(root, write, *ENTRY[:2], ["iam"]) == 0
            assert not seen, (
                "projection must leave Model quality to independent validation"
            )


def _callback_check_authorization_before_memo_and_publication_publish(model, root, /):
    loaded = load_model(model)
    assert input_cache.memo_table()
    original = model.read_bytes()
    assert MODULE.sync(root, True, *ENTRY[:2], ["iam"]) == 0
    refreshed = load_model(model)
    assert refreshed is not loaded and refreshed.authoritative == loaded.authoritative
    assert model.read_bytes() == original


def check_authorization_before_memo_and_publication(generated_policy, monkeypatch):
    root, model, _, design, artifact, register = generated_policy
    monkeypatch.setenv(
        "BLUEPRINT_TASK_FILE", register([design, artifact])["BLUEPRINT_TASK_FILE"]
    )
    publish = (input_cache.input_scope)(
        _bind_framework_callback(
            _callback_check_authorization_before_memo_and_publication_publish,
            model,
            root,
        )
    )
    publish()


def _callback_check_sync_mapping_lifetime_stage_inputs(
    original, provider, root, stages, /, stage, source, *args
):
    stages.append(stage)
    assert source == root and mappings_for(stage) is provider
    assert stage not in mapping_state._instances
    assert mappings_for(stage).get("iam") is provider.get("iam")
    return original(stage, source, *args)


def check_sync_mapping_lifetime(generated_policy, monkeypatch):
    root, _, _, _, _, register = generated_policy
    monkeypatch.setenv("BLUEPRINT_TASK_FILE", register([])["BLUEPRINT_TASK_FILE"])
    provider = mappings_for(definition_root(root))
    stages = []
    already_loaded = "iam" in provider._runtime
    original = sync_runtime.stage_inputs
    stage_inputs = _bind_framework_callback(
        _callback_check_sync_mapping_lifetime_stage_inputs,
        original,
        provider,
        root,
        stages,
    )
    with (
        patch.object(sync_runtime, "stage_inputs", side_effect=stage_inputs),
        patch.object(aws_mapping, "yaml_read", wraps=aws_mapping.yaml_read) as parse,
    ):
        TestCase().assertEqual(MODULE.sync(root, False, *ENTRY[:2], ["iam"]), 0)
        assert len(stages) == 1 and parse.call_count == (0 if already_loaded else 1)
    assert all(
        stage not in mapping_state._aliases and stage not in mapping_state._instances
        for stage in stages
    )
    assert mappings_for(definition_root(root)) is provider


if __name__ == "__main__":
    raise SystemExit(run(__file__))
