"""Resource selection retains owner order, failure timing and isolated dictionaries."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from model.core import ReferenceResolutionError, SnapshotValues

from model import format, operations, validation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

_CALLBACK_DEFAULT = object()


def _callback_selection_required(selected, /, v, *a, warnings):
    selected.append(v)
    warnings.append({"code": "fixture", "message": "warning"})
    raise ReferenceResolutionError("unresolved fixture")


def _callback_selection_mapping(mapped, /, v, *a):
    mapped.append(v)
    raise ValueError("mapping failure")


def _callback_selection_run_60(tmp_path, _default_v, /, v=_CALLBACK_DEFAULT):
    if v is _CALLBACK_DEFAULT:
        v = _default_v
    return validation.check_model_inputs(
        tmp_path / "model/dev/target/sample.properties", v, tmp_path
    )


@pytest.fixture
def selection(tmp_path, monkeypatch):
    values = {"desired.service.sample.serviceId": "sample"}
    for number in ("002", "001"):
        values.update(
            {
                f"desired.resource.{number}.resourceType": "Logs.LogGroup",
                f"desired.resource.{number}.resourceMode": "IMPORT",
                f"desired.row.{number}-001.property": "Logs.LogGroup.RetentionInDays",
                f"desired.row.{number}-001.value": "`30`",
                f"observed.row.{number}-001.value": "`30`",
                f"display.resource.{number}.comment": "合成",
            }
        )
    values.update(
        {
            "desired.reference.ref.consumerKey": "desired.row.001-001.value",
            "desired.reference.ref.producerId": "003",
        }
    )
    monkeypatch.setattr("model.references.diagnose", lambda *a, **k: ((), {}))
    monkeypatch.setattr("model.core.validate_authority", lambda v: None)
    monkeypatch.setattr("model.sources.runtime_values", dict)
    monkeypatch.setattr("model.core.validate_runtime_keys", lambda v: None)
    monkeypatch.setattr("model.files.resource_row_index", lambda v: None)
    monkeypatch.setattr(
        validation,
        "DesignSchemaCatalog",
        lambda root: type(
            "Catalog", (), {"literal_errors": lambda self, *a: ["literal failure"]}
        )(),
    )
    monkeypatch.setattr(validation, "validate_api_constraints", lambda *a, **k: None)
    monkeypatch.setattr(validation, "resource_rows", lambda *a: [])
    monkeypatch.setattr(
        validation, "validate_resource_identities", lambda *a, **k: None
    )
    monkeypatch.setattr("model.render.resource_details", lambda *a, **k: None)
    monkeypatch.setattr("validation.design.check_observed_values", lambda *a, **k: None)
    monkeypatch.setattr(validation, "catalog_outputs", lambda *a: set())
    monkeypatch.setattr(validation, "is_import_expression", lambda *a: False)
    selected, mapped = [], []
    required = _bind_framework_callback(_callback_selection_required, selected)
    mapping = _bind_framework_callback(_callback_selection_mapping, mapped)
    monkeypatch.setattr(validation, "validate_required_properties", required)
    monkeypatch.setattr("aws_mapping_display.validate_mappings", mapping)
    run = _bind_framework_callback(_callback_selection_run_60, tmp_path, values)
    return values, selected, mapped, run


def check_selection_order_findings_and_fresh_calls(selection):
    values, selected, mapped, run = selection
    before = dict(values)
    with patch.object(format, "owner", wraps=format.owner) as calls:
        findings = run()
    # Reference ownership recursively classifies its consumer; top-level order is unchanged.
    top = [call.args[0] for call in calls.call_args_list]
    expected = []
    for key in values:
        expected.append(key)
        if key.startswith("desired.reference."):
            expected.append(values["desired.reference.ref.consumerKey"])
    assert top == expected
    numbers = [n for n, _ in validation.entries(values, "desired.resource.")]
    assert [list(v.items()) for v in selected] == [
        list(operations.operation_values(values, n).items()) for n in numbers
    ]
    assert all(a is b for a, b in zip(selected, mapped, strict=False))
    assert len({id(v) for v in selected}) == len(numbers)
    assert values == before
    assert findings.errors == [
        error
        for number in numbers
        for error in (
            f"model.mapping.{number}: mapping failure",
            "provider schema violation: Logs.LogGroup.RetentionInDays: literal failure",
        )
    ]
    ids = [r.check_id for r in findings.results.values()]
    assert ids == ["model.structure", "model.json-settings", "model.references"] + [
        check
        for n in numbers
        for check in (
            "model.required." + n,
            "model.api-constraints." + n,
            "model.mapping." + n,
            "model.naming." + n,
            "model.literal." + n + "-001",
        )
    ] + ["model.observed"] + ["model.identity." + n for n in numbers] + [
        "model.presentation"
    ]
    assert [
        r.status
        for r in findings.results.values()
        if r.check_id.startswith("model.required.")
    ] == ["NOT_RUN"] * 2
    assert findings.unverified and findings.warnings
    values["desired.row.001-001.value"] = "`60`"
    run()
    assert (
        next(v for v in selected[2:] if "desired.row.001-001.value" in v)[
            "desired.row.001-001.value"
        ]
        == "`60`"
    )


def _check_catalog_failure_precedes_owner_fail(*a):
    raise ValueError("catalog first")


def check_catalog_failure_precedes_owner(selection, monkeypatch):
    _, selected, _, run = selection
    fail = _check_catalog_failure_precedes_owner_fail
    monkeypatch.setattr(validation, "DesignSchemaCatalog", fail)
    with patch.object(format, "owner", side_effect=AssertionError("too early")):
        findings = run()
        assert findings.errors == ["model.catalog: catalog first"]
        assert findings.processing_errors[0]["cause_kind"] == "check_failure"
    assert not selected


def _callback_check_first_owner_exception_precedes_resource_checks_owner(
    failing, original, trace, /, key, source
):
    trace.append(key)
    if key == failing:
        raise ValueError("first owner failure")
    return original(key, source)


def check_first_owner_exception_precedes_resource_checks(selection):
    values, selected, _, run = selection
    trace = []
    original = format.owner
    failing = list(values)[2]
    owner = _bind_framework_callback(
        _callback_check_first_owner_exception_precedes_resource_checks_owner,
        failing,
        original,
        trace,
    )
    with (
        patch.object(format, "owner", owner),
        pytest.raises(ValueError, match="^first owner failure$"),
    ):
        run()
    assert trace == list(values)[:3] and not selected


def check_zero_resources_never_classified(selection):
    _, selected, _, run = selection
    with patch.object(format, "owner", side_effect=AssertionError("zero resources")):
        run({"desired.service.sample.serviceId": "sample"})
    assert not selected


def _check_selected_mutation_is_isolated_mutate(selected, *a, **kw):
    assert type(selected) is dict
    assert "display.resource.marker.comment" not in selected
    selected["display.resource.marker.comment"] = "local mutation"
    selected.pop("desired.row.001-001.value", None)
    assert "desired.row.001-001.value" not in selected


@pytest.mark.parametrize("fixed", [True, False])
def check_selected_mutation_is_isolated(selection, monkeypatch, fixed):
    values, _, mapped, run = selection
    if fixed:
        values = SnapshotValues(values)
    before = dict(values)
    mutate = _check_selected_mutation_is_isolated_mutate
    monkeypatch.setattr(validation, "validate_required_properties", mutate)
    run(values)
    assert values == before
    assert len(mapped) == 2 and mapped[0] is not mapped[1]
    other = dict(mapped[1])
    mapped[0].clear()
    assert not mapped[0] and mapped[1] == other
    if fixed:
        with pytest.raises(TypeError, match="Snapshot values are immutable"):
            values["display.resource.marker.comment"] = "canonical mutation"
        with pytest.raises(TypeError, match="Snapshot values are immutable"):
            values.clear()


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
