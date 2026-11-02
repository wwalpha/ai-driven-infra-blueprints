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
    assert view.structural_resources() == entries(values, "desired.resource.")
    assert view.all_rows() == entries(values, "desired.row.")
    assert view.row_index() == resource_row_index(values)
    assert view.all_references() == entries(values, "desired.reference.")
    assert view.all_artifacts() == entries(values, "desired.artifact.")
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


def check_structural_and_orphan_errors_remain_separate():
    invalid = {
        "desired.resource.001.resourceType": "EC2.VPC",
        "desired.resource.001.deploymentEncryption": "default",
    }
    view = ModelView(invalid)
    assert view.structural_resources()[0][0] == "001"
    with pytest.raises(ValueError, match="deploymentEncryption"):
        view.resources()
    orphan = ModelView({"desired.row.missing-001.value": "value"})
    assert orphan.all_rows()[0][0] == "missing-001"
    with pytest.raises(ValueError, match="orphan desired row"):
        orphan.row_index()


def check_grouped_resources_preserve_order_errors_and_isolation(tmp_path):
    scope, values = format_fixture(tmp_path)
    values.update(
        {
            "desired.service.identity.lastAllocated": '{"EC2.VPC":1,"EC2.Subnet":1}',
            "desired.resource.child.resourceType": "EC2.Subnet",
            "desired.resource.child.logicalId": "EC2_Subnet_001",
            "desired.resource.child.anchor": "child",
            "desired.resource.child.parentReference": '{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}',
        }
    )
    original = dict(values)
    view = ModelView(values)
    resources, groups = view.resource_groups({"EC2.Subnet"})
    assert list(resources) == ["007", "child"]
    assert groups == {"007": {"007", "child"}}
    resources["007"].clear()
    groups["007"].clear()
    assert view.resource_groups({"EC2.Subnet"})[1] == {"007": {"007", "child"}}
    assert values == original
    values["desired.resource.child.parentReference"] = (
        '{"$modelRef":{"logicalId":"EC2_VPC_999","attribute":"VpcId"}}'
    )
    with pytest.raises(ValueError, match="grouped parent ownership unavailable: child"):
        ModelView(values).resource_groups({"EC2.Subnet"})
    values["desired.resource.child.parentReference"] = (
        '{"$modelRef":{"logicalId":"EC2_Subnet_001","attribute":"SubnetId"}}'
    )
    with pytest.raises(ValueError, match="cyclic grouped parent ownership: child"):
        ModelView(values).resource_groups({"EC2.Subnet"})


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
