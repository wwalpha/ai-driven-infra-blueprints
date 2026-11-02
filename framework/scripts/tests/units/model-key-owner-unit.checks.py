"""Model key ownership compatibility at the shared contract boundary."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.inputs import select_stacks, selected_stack_values
from model.core import resource_row_index
from model.format import owner
from utils.cloudformation.inputs import Blocked
from validation.diagnostics import InputValidationError

from model import ModelView, key_parts, row_resource

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_key_and_owner_compatibility():
    values = {
        "desired.resource.id-with-hyphen.resourceType": "EC2.VPC",
        "desired.row.id-with-hyphen-001.value": "v",
        "observed.row.id-with-hyphen-001.value": "v",
        "desired.reference.ref.consumerKey": "desired.row.id-with-hyphen-001.value",
        "desired.reference.ref.text": "v",
        "desired.stack.s.name": "stack",
        "desired.artifact.a.stack": "stack",
    }
    assert key_parts("desired.row.id-with-hyphen-001.value") == (
        "desired",
        "row",
        "id-with-hyphen-001",
    )
    assert row_resource("id-with-hyphen-001") == "id-with-hyphen"
    assert row_resource("no-separator") == "no"
    assert row_resource("missing") == ""
    view = ModelView(values)
    for key in values:
        assert view.owner(key) == owner(key, values)
    assert owner("desired.reference.ref.text", values) == ("resource", "id-with-hyphen")
    assert view.keys("resource", "id-with-hyphen") == tuple(
        k for k in values if owner(k, values) == ("resource", "id-with-hyphen")
    )
    assert view.keys("stack", "s") == ("desired.stack.s.name",)
    assert view.keys("artifact", "a") == ("desired.artifact.a.stack",)
    assert view.artifacts("s") == [("a", {"stack": "stack"})]
    assert resource_row_index(values)["id-with-hyphen"][0][0] == "id-with-hyphen-001"
    with pytest.raises(InputValidationError, match="invalid Model key"):
        owner("desired.row", values)
    with pytest.raises(InputValidationError, match="orphan row"):
        owner("desired.row.missing.value", values)
    with pytest.raises(
        InputValidationError, match="reference has no valid consumerKey"
    ):
        owner("desired.reference.missing.text", values)
    with pytest.raises(InputValidationError, match="orphan desired row"):
        resource_row_index({**values, "desired.row.orphan-001.value": "x"})


def check_stack_selection_preserves_order_and_owner_filter(monkeypatch):
    values = {
        "desired.stack.002.name": "second",
        "desired.stack.002.deployOrder": "2",
        "desired.stack.001.name": "first",
        "desired.stack.001.deployOrder": "1",
        "display.stack.001.comment": "first",
        "display.stack.002.comment": "second",
        "desired.artifact.b.stack": "second",
        "desired.artifact.a.stack": "first",
        "desired.reference.keep.consumerKey": "desired.artifact.a.stack",
        "desired.reference.drop.consumerKey": "desired.stack.002.name",
        "desired.deployment.maxConcurrentStacks": "1",
    }
    for name in ("validate_model_keys", "validate_stack_metadata", "declarations"):
        monkeypatch.setattr("deploy.inputs." + name, lambda *_: None)
    assert [identity for identity, _ in select_stacks(values)] == ["001", "002"]
    selected = selected_stack_values(values, ["first"])
    assert list(selected) == [
        key
        for key in values
        if key
        not in {
            "desired.stack.002.name",
            "desired.stack.002.deployOrder",
            "display.stack.002.comment",
            "desired.artifact.b.stack",
            "desired.reference.drop.consumerKey",
        }
    ]
    with pytest.raises(Blocked, match="duplicate stack name"):
        select_stacks({**values, "desired.stack.002.name": "first"})


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
