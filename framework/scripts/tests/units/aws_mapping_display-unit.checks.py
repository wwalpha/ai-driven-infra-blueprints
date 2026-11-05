#!/usr/bin/env python3
"""Focused checks; test sources define the current verification responsibilities."""

import sys
from functools import partial as _bind_framework_callback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aws_mapping_display as display
import sync_views
from design.services.codepipeline import (
    pipeline_display_rows,
    pipeline_rows,
    validate_selection,
)
from model.display import display_rows
from support.aws_mapping_display_fixtures import (
    Path,
    patch,
    sys,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def _callback_check_validation_projection_scope_projected(calls, /, values, root):
    calls.append((tuple(values.items()), root))
    if "invalid" in values:
        raise ValueError("projection failure")
    return dict(values)


def _callback_check_validation_projection_scope_fail(*args):
    assert display._validation_projections.get() == {}
    raise ValueError("validator failure")


def check_validation_projection_scope(tmp_path):
    source = {"first": "one", "second": "two"}
    provider = object()
    calls = []

    projected = _bind_framework_callback(
        _callback_check_validation_projection_scope_projected, calls
    )

    with (
        patch.object(display, "projection", side_effect=projected),
        patch.object(display, "mappings_for", return_value=provider) as providers,
    ):
        with display._validation_projection_scope():
            first = display._validation_projection(source, tmp_path)
            first["first"] = "caller mutation"
            assert display._validation_projection(source, tmp_path) == source
            assert len(calls) == 1
            for operation in ("change", "add", "delete", "order"):
                if operation == "change":
                    source["first"] = "changed"
                elif operation == "add":
                    source["third"] = "three"
                elif operation == "delete":
                    del source["third"]
                else:
                    source["first"] = source.pop("first")
                before = len(calls)
                assert list(
                    display._validation_projection(source, tmp_path).items()
                ) == list(source.items())
                assert len(calls) == before + 1
            display._validation_projection(dict(source), tmp_path)
            assert len(calls) == 6
            display._validation_projection(source, tmp_path / "other-root")
            assert len(calls) == 7
            providers.return_value = object()
            display._validation_projection(source, tmp_path)
            assert len(calls) == 8
            source["invalid"] = "yes"
            for _ in range(2):
                try:
                    display._validation_projection(source, tmp_path)
                except ValueError as error:
                    assert str(error) == "projection failure"
                else:
                    raise AssertionError("exception must propagate")
            assert len(calls) == 10
            del source["invalid"]
            # Direct callers always compute, even inside validation.
            display.projection(source, tmp_path)
            display.projection(source, tmp_path)
            assert len(calls) == 12
        assert display._validation_projections.get() is None
        with display._validation_projection_scope():
            display._validation_projection(source, tmp_path)
            assert len(calls) == 13
        display._validation_projection(source, tmp_path)
        display._validation_projection(source, tmp_path)
        assert len(calls) == 15

    fail = _callback_check_validation_projection_scope_fail

    with patch.object(sync_views, "view_validator", side_effect=fail):
        for _ in range(2):
            try:
                sync_views.validate_views(tmp_path, tmp_path, [], {})
            except ValueError as error:
                assert str(error) == "validator failure"
            else:
                raise AssertionError("validator must fail")
            assert display._validation_projections.get() is None


def check_indexed_mapping():
    for kind, field in (
        ("CodePipeline.Pipeline", "Stages[1].Name"),
        ("CloudTrail.Trail", "EventSelectors[1].ReadWriteType"),
        ("Route53.RecordSet", "ResourceRecords[1]"),
    ):
        prop = kind + "." + field
        assert display.rule(prop)
        assert "[1]" in display.display_name(prop, kind)
        assert display.selected_rows([["001-001", prop, "value", ""]])
    for field in ("Stages[0].Name", "Stages[1].Missing", "Name[1]"):
        try:
            display.rule("CodePipeline.Pipeline." + field)
        except ValueError:
            pass
        else:
            raise AssertionError(field)


def test_pipeline_hidden_fields_keep_membership():
    kind = "CodePipeline.Pipeline"
    rows = []

    def add(resource, field, value):
        rows.append(
            [f"{resource}-{len(rows) + 1:03}", kind + "." + field, f"`{value}`", ""]
        )

    for resource in ("001", "002"):
        for stage in range(4):
            for action in range(2 if stage == 1 else 1):
                add(resource, "Stages[].Actions[].Name", f"action-{stage}-{action}")
                add(resource, "Stages[].Actions[].RunOrder", str(action + 1))
                if stage == 0:
                    add(resource, "Stages[].Actions[].Namespace", "QuarantineSource")
                    add(resource, "Stages[].Actions[].RoleArn", "hidden")
            add(resource, "Stages[].Name", f"stage-{stage}")
    for resource in ("001", "002"):
        source = [row for row in rows if row[0].startswith(resource)]
        without_namespace = [row for row in source if not row[1].endswith(".Namespace")]
        validate_selection(without_namespace, display.selected_rows(without_namespace))
        assert (
            len(
                [
                    r
                    for r in display_rows(kind, without_namespace)
                    if r[1].endswith(".Name")
                ]
            )
            == 9
        )
        selected = display.selected_rows(source)
        validate_selection(source, selected)
        assert len([row for row in selected if row[1].endswith(".Name")]) == 9
        assert not any(row[1].endswith("RoleArn") for row in selected)
        rendered = display_rows(kind, source)
        assert any(
            row[1] == "Stages[1].Actions.Namespace" and row[2] == "`QuarantineSource`"
            for row in rendered
        )
        assert [
            row[2]
            for row in rendered
            if row[1].startswith("Stages[2].Actions") and row[1].endswith("RunOrder")
        ] == ["`1`", "`2`"]
        restored = pipeline_display_rows(rendered)
        assert [(row[1], row[2]) for row in restored] == [
            (row[1], row[2]) for row in selected
        ]
        assert (
            pipeline_rows(
                [[r[0], r[1].removeprefix(kind + "."), *r[2:]] for r in restored]
            )
            == rendered
        )
        for removed in ("Stages[].Name", "Stages[].Actions[].Name"):
            damaged = selected.copy()
            damaged.pop(
                next(
                    i for i, row in enumerate(damaged) if row[1] == kind + "." + removed
                )
            )
            try:
                validate_selection(source, damaged)
            except ValueError:
                pass
            else:
                raise AssertionError("missing required row accepted")
    validate_selection([], [])


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
