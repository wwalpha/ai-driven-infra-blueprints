"""Consumer behavior using the shared Model key contract."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comparison.rules.route53 import model_property
from contracts.model import key_kind, row_has_resource_prefix
from utils.cloudformation.inputs import Blocked


def check_key_kind_preserves_prefix_semantics():
    for key in (
        "desired.row",
        "desired.row.",
        "desired.row.001.value",
        "desired.rowx.001.value",
        "observed.row.a-b.value",
        "",
    ):
        assert (key_kind(key) == ("desired", "row")) == key.startswith("desired.row.")


def check_row_prefix_preserves_nested_identity():
    assert row_has_resource_prefix("001-extra-001", "001")
    assert not row_has_resource_prefix("0010-001", "001")


def check_route53_row_owner_and_duplicate_handling():
    values = {
        "desired.resource.001.resourceType": "Route53.RecordSet",
        "desired.resource.001-extra.resourceType": "Route53.RecordSet",
        "desired.row.001-001.property": "Route53.RecordSet.Type",
        "desired.row.001-001.value": "`A`",
        "desired.row.001-extra-001.property": "Route53.RecordSet.Type",
        "desired.row.001-extra-001.value": "`CNAME`",
    }
    inputs = SimpleNamespace(
        resources={"dns": {"001": {"resourceType": "Route53.RecordSet"}}},
        model=lambda _: SimpleNamespace(authoritative=values),
    )
    assert model_property(inputs, "dns", "001", "Type") == "A"
    values.update(
        {
            "desired.row.001-002.property": "Route53.RecordSet.Type",
            "desired.row.001-002.value": "`AAAA`",
        }
    )
    with pytest.raises(Blocked, match="requires one explicit Model Type"):
        model_property(inputs, "dns", "001", "Type")


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
