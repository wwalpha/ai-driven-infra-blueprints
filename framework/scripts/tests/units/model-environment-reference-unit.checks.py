#!/usr/bin/env python3
"""Environment strings are literals; retired declarations fail at shared boundaries."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from model.files import trace_model
from model.format import serialize
from model.importing.approval import validate_reference_proposal
from model.references import declarations
from model.sources import load_model
from support.model_v2_fixtures import format_fixture

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_environment_literals_and_account_context(tmp_path):
    scope, values = format_fixture(tmp_path)
    key = "desired.row.007-002.value"
    values[key] = "dev-stg-qa-custom-999999999999"
    document = "desired.row.007-003.document"
    values.update(
        {
            "desired.row.007-003.property": "EC2.VPC.Tags",
            "desired.row.007-003.value": "[tags](network/tags.json)",
            "desired.row.007-003.comment": "合成タグ",
            document: json.dumps(
                [{"Key": "Environment", "Value": "dev-stg-qa-custom"}]
            ),
        }
    )
    spec = {
        "consumerKey": key,
        "text": "999999999999",
        "occurrence": "1",
        "producerKind": "context",
        "producerScope": "qa-custom/one",
        "format": "literal",
        "labelPolicy": "none",
        "contextProperty": "executionAccountId",
    }
    proposed = validate_reference_proposal({"account": spec}, values)
    scope.path.write_text(serialize(proposed), encoding="utf-8")
    before = scope.path.read_bytes()
    model = load_model(scope)
    assert not model.warnings
    assert model.authoritative == proposed
    assert trace_model(scope.path, key)["references"] == {"account": spec}
    assert "references" not in trace_model(scope.path, document)
    # Moving the selected environment changes scope, never saved names or JSON strings.
    project = tmp_path / "project.json"
    project.write_text(
        project.read_text().replace("qa-custom", "preview"), encoding="utf-8"
    )
    moved = tmp_path / "model/preview/one/network.properties"
    moved.parent.mkdir(parents=True)
    literal_values = validate_reference_proposal({}, values)
    moved.write_text(serialize(literal_values), encoding="utf-8")
    current = load_model(moved)
    assert current.scope.environment == "preview" and not current.warnings
    assert current.authoritative == literal_values
    assert scope.path.read_bytes() == before


@pytest.mark.parametrize("refid", ["migration-000001", "human-selected"])
@pytest.mark.parametrize("structured", [False, True])
def check_retired_declarations_rejected(tmp_path, refid, structured):
    scope, values = format_fixture(tmp_path)
    key = "desired.row.007-002.value"
    values[key] = '`{"name":"dev-stg"}`' if structured else "dev-stg"
    spec = {
        "consumerKey": key,
        "text": "dev",
        "occurrence": "1",
        "producerKind": "context",
        "producerScope": "qa-custom/one",
        "format": "literal",
        "labelPolicy": "none",
        "contextProperty": "environment",
        **({"pointer": "/name"} if structured else {}),
    }
    invalid = {
        **values,
        **{
            f"desired.reference.{refid}.{field}": value for field, value in spec.items()
        },
    }
    scope.path.write_text(serialize(invalid), encoding="utf-8")
    original = scope.path.read_bytes()
    for action in (
        lambda: declarations(invalid),
        lambda: load_model(scope),
        lambda: trace_model(scope.path, key),
        lambda: validate_reference_proposal({refid: spec}, values),
    ):
        with pytest.raises(
            ValueError, match="contextProperty must be executionAccountId"
        ):
            action()
        assert scope.path.read_bytes() == original


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
