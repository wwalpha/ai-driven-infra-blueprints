"""Compatibility and isolation checks for the public Model view."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from model.configuration import ConfigurationIndex
from model.core import entries, resource_row_index
from model.format import owner
from model.sources import raw_model
from support.model_v2_fixtures import format_fixture

from model import ModelView


def check_view_matches_existing_accessors_and_is_isolated(tmp_path):
    scope, values = format_fixture(tmp_path)
    values.update(
        {
            "desired.stack.001.name": "network",
            "desired.artifact.002.stack": "network",
            "desired.artifact.002.source": "file.zip",
            **{
                f"desired.reference.ref.{key}": value
                for key, value in {
                    "consumerKey": "desired.row.007-002.value",
                    "text": ' 010 \\ " ',
                    "occurrence": "1",
                    "producerKind": "resource",
                    "producerScope": "dev/cde/logs",
                    "producerLogicalId": "Logs_LogGroup_002",
                    "resourceType": "Logs.LogGroup",
                    "format": "name",
                    "property": "Logs.LogGroup.LogGroupName",
                    "labelPolicy": "none",
                }.items()
            },
        }
    )
    before = dict(values)
    index = ConfigurationIndex(values)
    view = ModelView(values)
    assert view.resources() == entries(values, "desired.resource.")
    assert view.rows("007") == resource_row_index(values)["007"]
    assert view.references("007") == index.resource_references("007")
    assert view.observed("007") == index.resource_observed("007")
    assert view.stacks() == entries(values, "desired.stack.")
    assert view.artifacts("001") == entries(values, "desired.artifact.")
    for kind, identity in (("resource", "007"), ("stack", "001"), ("artifact", "002")):
        assert view.keys(kind, identity) == tuple(
            k for k in values if owner(k, values) == (kind, identity)
        )
    assert view.owner("desired.reference.ref.text") == owner(
        "desired.reference.ref.text", values
    )
    view.resources()[0][1].clear()
    view.rows("007")[0][1].clear()
    view.references("007")["ref"].clear()
    view.observed("007").clear()
    view.stacks()[0][1].clear()
    view.artifacts("001")[0][1].clear()
    values.clear()
    assert view.resources() == entries(before, "desired.resource.")
    assert view.references("007") == index.resource_references("007")
    assert view.location("missing") is None
    with pytest.raises(KeyError):
        view.rows("missing")
    with pytest.raises(KeyError):
        view.artifacts("missing")


def check_raw_snapshot_locations_and_incomplete_model(tmp_path):
    scope, values = format_fixture(tmp_path)
    snapshot = raw_model(scope)
    view = ModelView(snapshot)
    assert view.resources() == entries(snapshot.authoritative, "desired.resource.")
    assert (
        view.location("desired.resource.007.resourceType")
        == snapshot.locations["desired.resource.007.resourceType"]
    )
    assert dict(snapshot.authoritative) == values
    assert ModelView(
        {"desired.resource.incomplete.resourceType": "S3.Bucket"}
    ).resources() == [("incomplete", {"resourceType": "S3.Bucket"})]


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
