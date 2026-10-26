"""Scoped current Export proof, shared boundaries, and Model/Secrets connections."""

import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import copy
import json
from unittest.mock import Mock, patch

import pytest
import support.cloudformation_deploy_fixtures as from_fixture
from deploy.controller import exports_for
from model.adapters import aws as model_aws
from support.pytest_cli import run
from utils.cloudformation import export_resolution as exports
from utils.cloudformation.inputs import Blocked

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

STACK = "arn:aws:cloudformation:ap-northeast-1:123456789012:stack/Producer/original"
ENTRIES = {
    name: {"Name": name, "Value": "value-" + name, "ExportingStackId": STACK}
    for name in ("A", "B")
}


class ExportAws:
    def __init__(self):
        self.calls = []
        self.stack = {
            "StackId": STACK,
            "StackStatus": "UPDATE_COMPLETE",
            "Outputs": [
                {"OutputKey": name, "ExportName": name, "OutputValue": entry["Value"]}
                for name, entry in ENTRIES.items()
            ],
        }
        self.inventory = list(ENTRIES.values())

    def __call__(self, operation, **arguments):
        self.calls.append((operation, arguments))
        if operation == "describe_stacks":
            return {"Stacks": [copy.deepcopy(self.stack)]}
        assert operation == "list_exports"
        return {"Exports": copy.deepcopy(self.inventory)}


@pytest.mark.parametrize("known", [False, True])
def check_scoped_resolution_and_boundary(known):
    aws, boundary = ExportAws(), {}
    hints = ENTRIES if known else {}
    assert (
        exports.resolve_exports(aws, {"A", "B"}, hints=hints, boundary=boundary)
        == ENTRIES
    )
    assert exports.resolve_exports(aws, {"A"}, hints=hints, boundary=boundary) == {
        "A": ENTRIES["A"]
    }
    assert [op for op, _ in aws.calls].count("list_exports") == (0 if known else 1)
    assert [op for op, _ in aws.calls].count("describe_stacks") == 1
    aws.stack["Outputs"][0]["OutputValue"] = "changed"
    with pytest.raises(Blocked, match="changed"):
        exports.resolve_exports(aws, {"A"}, hints=ENTRIES)


def check_current_stack_evidence_resolves_owner_without_inventory():
    aws, boundary = ExportAws(), {}
    exports.describe_exports(aws, STACK, boundary)
    assert exports.resolve_exports(aws, {"A", "B"}, boundary=boundary) == ENTRIES
    assert len(aws.calls) == 1
    assert exports.resolve_exports(aws, set()) == {}
    assert len(aws.calls) == 1


def check_known_in_progress_producer_blocks_without_discovery():
    aws, boundary = ExportAws(), {}
    aws.stack["StackStatus"] = "UPDATE_IN_PROGRESS"
    exports.describe_exports(aws, STACK, boundary, successful=False)
    with pytest.raises(Blocked, match="identity/status"):
        exports.resolve_exports(aws, {"A"}, boundary=boundary)
    assert [op for op, _ in aws.calls] == ["describe_stacks"]


@pytest.mark.parametrize(
    "defect",
    [
        "id",
        "status",
        "value",
        "missing",
        "duplicate-export",
        "duplicate-output",
        "output-type",
        "invalid-key",
    ],
)
def check_known_producer_must_be_current_and_complete(defect):
    aws = ExportAws()
    if defect == "id":
        aws.stack["StackId"] += "-replacement"
    elif defect == "status":
        aws.stack["StackStatus"] = "UPDATE_IN_PROGRESS"
    elif defect == "value":
        aws.stack["Outputs"][0]["OutputValue"] = "changed"
    elif defect == "missing":
        aws.stack["Outputs"].pop(0)
    elif defect == "duplicate-export":
        aws.stack["Outputs"][1]["ExportName"] = "A"
    elif defect == "duplicate-output":
        aws.stack["Outputs"].append(aws.stack["Outputs"][0])
    elif defect == "output-type":
        aws.stack["Outputs"] = None
    else:
        aws.stack["Outputs"][0].pop("OutputKey")
    with pytest.raises(Blocked):
        exports.resolve_exports(aws, {"A"}, hints=ENTRIES)
    assert all(op != "list_exports" for op, _ in aws.calls)


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"Exports": None},
        {"Exports": [], "NextToken": "more"},
        {"Exports": [ENTRIES["A"]] * 2},
    ],
)
def check_unknown_inventory_must_be_complete(response):
    with pytest.raises(Blocked):
        exports.resolve_exports(Mock(return_value=response), {"A"})


def check_unknown_discovery_is_reconfirmed_and_scoped():
    aws = ExportAws()
    aws.inventory += [{"Name": "Unrelated" + str(i)} for i in range(1000)]
    assert exports.resolve_exports(aws, {"A"}) == {"A": ENTRIES["A"]}
    assert [op for op, _ in aws.calls] == ["list_exports", "describe_stacks"]
    aws.stack["Outputs"][0]["OutputValue"] = "changed"
    with pytest.raises(Blocked, match="changed"):
        exports.resolve_exports(aws, {"A"})


def check_model_context_keeps_its_read_sharing(tmp_path):
    context = model_aws.Context(
        tmp_path, {"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"}
    )
    context.verified = True
    aws = ExportAws()
    resource = model_aws.Resource.__new__(model_aws.Resource)
    resource.ctx = context
    with patch.object(
        context, "_call", side_effect=lambda service, op, **args: aws(op, **args)
    ):
        assert resource.resolve_json({"Fn::ImportValue": "A"}) == ENTRIES["A"]["Value"]
        assert resource.resolve_json({"Fn::ImportValue": "B"}) == ENTRIES["B"]["Value"]
    assert [op for op, _ in aws.calls] == ["list_exports", "describe_stacks"]
    with pytest.raises(model_aws.Unresolved, match="Export name"):
        resource.resolve_json({"Fn::ImportValue": None})
    context.target["awsRegion"] = "us-east-1"
    with pytest.raises(ValueError, match="connection changed"):
        resource.resolve_json({"Fn::ImportValue": "A"})


def check_controller_uses_current_producer_output_contract():
    aws = ExportAws()
    runtime = SimpleNamespace(
        aws=aws,
        target={"awsAccountId": "123456789012", "awsRegion": "ap-northeast-1"},
        templates={
            "Consumer": ({"Outputs": {"Used": {"Value": {"Fn::ImportValue": "A"}}}}, {})
        },
        states={
            "Producer": {"stackId": STACK, "expectedOutputs": {"A": {"export": "A"}}}
        },
    )
    assert exports_for(runtime, [{"name": "Consumer"}], {}) == {"A": ENTRIES["A"]}
    assert [op for op, _ in aws.calls] == ["describe_stacks"]


@pytest.mark.parametrize("defect", ["value", "producer"])
def check_execute_export_changes_prevent_execution(tmp_path, defect):
    runtime = from_fixture.DeliveryAws(tmp_path / "repo", tmp_path / "delivery")
    unit = from_fixture.units(10)[0]
    document = {
        "Resources": {},
        "Outputs": {"Used": {"Value": {"Fn::ImportValue": "A"}}},
    }
    template, parameters = runtime.paths(unit)
    template.parent.mkdir(parents=True, exist_ok=True)
    parameters.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(json.dumps(document), encoding="utf-8")
    parameters.write_text("[]", encoding="utf-8")
    runtime.load_inputs(unit)
    runtime.states = from_fixture.states([unit])
    runtime.expected_digests = {unit["name"]: runtime.input_digest(unit)}
    runtime.export_values = {"A": "value-A"}
    runtime.prepare_delivery_group([unit], runtime.states)
    state = runtime.states[unit["name"]]
    assert runtime.prepare(unit, state) == "READY"
    state["clientToken"] = "token"
    if defect == "value":
        runtime.export_values["A"] = "changed"
    else:
        runtime.aws = partial(changed_producer, runtime.aws)
    with pytest.raises(Blocked):
        runtime.execute(unit, state)
    assert all(op != "execute_change_set" for op, _ in runtime.calls)


def changed_producer(original, operation, **arguments):
    response = original(operation, **arguments)
    if operation == "describe_stacks":
        response["Stacks"][0]["StackId"] += "-replacement"
    return response


if __name__ == "__main__":
    raise SystemExit(run(__file__))
