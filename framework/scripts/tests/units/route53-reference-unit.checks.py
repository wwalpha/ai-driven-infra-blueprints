"""Endpoint DNS selection proof through real Model preparation and Export evaluation."""

import copy
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from comparison.methods import compare_values
from comparison.registry import rules
from comparison.rules import route53
from comparison.runner import Settings
from model.core import entries
from model.references import declarations, symbolic
from model.sources import Scope, load_model
from support.model_reference_fixtures import (
    FRAMEWORK,
    comparison,
    project,
    resource,
    save,
)
from utils.aws_mappings import mapping_alias
from utils.cloudformation.inputs import Blocked
from utils.iac_values import Expression

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def cached_stack(inputs, unit):
    return inputs.root / "synthetic.yaml", inputs.stack_inputs[unit["name"]]


def extraction(
    logical="Resource001", entry=0, delimiter=":", field=1, attribute="DnsEntries"
):
    return {
        "Fn::Select": [
            field,
            {
                "Fn::Split": [
                    delimiter,
                    {"Fn::Select": [entry, {"Fn::GetAtt": [logical, attribute]}]},
                ]
            },
        ]
    }


@pytest.fixture
def models(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        for service in ("iam", "kms"):
            (tmp_path / "model/qa/team" / (service + ".properties")).unlink()
        scope, values = resource(
            tmp_path, "endpoint", "EC2.VPCEndpoint", attribute="VpcEndpointType"
        )
        _, second = resource(
            tmp_path,
            "endpoint",
            "EC2.VPCEndpoint",
            attribute="VpcEndpointType",
            number="002",
        )
        values.update(second)
        values["desired.row.001-001.value"] = "`Interface`"
        values["desired.row.002-001.value"] = "`Interface`"
        save(scope, values)
        scope, values = resource(tmp_path, "dns", "Route53.RecordSet", attribute="Type")
        values["desired.resource.001.cfn-logicalId"] = "consumer-Policy"
        values["desired.row.001-001.value"] = "`CNAME`"
        values["desired.row.001-002.property"] = "Route53.RecordSet.ResourceRecords"
        values["desired.row.001-002.value"] = "[endpoint](endpoint.md#saved-001)"
        values["desired.row.001-002.comment"] = "DNS選択はコメントで証明しない"
        spec = dict(
            consumerKey="desired.row.001-002.value",
            text=values["desired.row.001-002.value"],
            occurrence="1",
            producerKind="resource",
            producerScope="qa/team/endpoint",
            producerLogicalId="EC2_VPCEndpoint_001",
            resourceType="EC2.VPCEndpoint",
            format="link",
            labelPolicy="fixed",
            valueSelector="dns-entry[0].dns-name",
        )
        values.update(
            {"desired.reference.dns." + field: value for field, value in spec.items()}
        )
        save(scope, values)
        yield tmp_path, scope, values


def prepare(models, expression=None):
    root, scope, values = models
    save(scope, values)
    inputs = comparison(root, ("endpoint", "dns"))
    inputs.stack = partial(cached_stack, inputs)
    inputs.stack_inputs["producer"][0]["Resources"] = {
        "Resource" + number: {
            "Type": "AWS::EC2::VPCEndpoint",
            "Properties": {"VpcEndpointType": "Interface"},
        }
        for number in ("001", "002")
    }
    if expression is None:
        expression = extraction()
    inputs.stack_inputs["producer"][0]["Outputs"] = {
        "Dns": {
            "Value": expression,
            "Export": {"Name": {"Fn::Sub": "EndpointDns${Suffix}"}},
        }
    }
    inputs.stack_inputs["producer"][1]["Suffix"] = "Test"
    inputs.stack_inputs["consumer"][0]["Resources"]["Policy"] = {
        "Type": "AWS::Route53::RecordSet",
        "Properties": {"Type": "CNAME"},
    }
    row = dict(entries(values, "desired.row."))["001-002"]
    prepared = inputs.prepare_value(
        "dns", row, "Route53.RecordSet", stack="consumer", row_id="001-002"
    )
    return inputs, prepared


def imported(inputs):
    return inputs.evaluate("consumer", {"Fn::ImportValue": "EndpointDnsTest"})


def route_decision(inputs, left, right, path):
    return inputs.reference_decision(left, right, "Route53.RecordSet", path)


@pytest.mark.parametrize(
    "logical,entry,expected",
    [
        ("Resource001", 0, True),
        ("Resource002", 0, False),
        ("Resource001", 1, False),
    ],
)
def test_endpoint_selection_decision(models, logical, entry, expected):
    inputs, prepared = prepare(models, extraction(logical, entry))
    (desired,) = prepared.require_value()
    actual = imported(inputs)
    for left, right in ((desired, actual), (actual, desired)):
        result = inputs.reference_decision(
            left, right, "Route53.RecordSet", "ResourceRecords[]"
        )
        assert result.equal is expected, result
        (detail,) = result.diagnostics
        assert detail["current_aws_verified"] is False
        assert detail["runtime_bounds_verified"] is False
        assert detail["exports"][0]["export_stack"] == "producer"
        assert detail["exports"][0]["unproven"].startswith(
            "Select bounds are unproven:"
        )
    assert (
        load_model(models[1]).authoritative["desired.row.001-002.value"]
        == models[2]["desired.row.001-002.value"]
    )
    with pytest.raises(Blocked, match="Select bounds are unproven"):
        inputs.evaluate("producer", extraction())
    with pytest.raises(Blocked):
        inputs.reference_literal(actual)


@pytest.mark.parametrize("delimiter,field", [("|", 1), (":", 0), (":", 2)])
def test_other_split_does_not_claim_dns_difference(models, delimiter, field):
    inputs, prepared = prepare(models, extraction(delimiter=delimiter, field=field))
    (desired,) = prepared.require_value()
    result = inputs.reference_decision(
        desired, imported(inputs), "Route53.RecordSet", "ResourceRecords[]"
    )
    assert result.equal is False
    assert "differs" in result.diagnostics[0]["reason"]


def test_missing_selector_stays_uncompared(models):
    del models[2]["desired.reference.dns.valueSelector"]
    _, prepared = prepare(models)
    with pytest.raises(Blocked, match="reference property contract unproven"):
        prepared.require_value()


@pytest.mark.parametrize(
    "prop,ticked,entry",
    [
        ("ResourceRecords", False, 1),
        ("ResourceRecords[1]", True, 0),
        ("ResourceRecords[]", False, 0),
    ],
)
def test_selected_row_shapes_and_container_comparison(models, prop, ticked, entry):
    values = models[2]
    values["desired.row.001-002.property"] = "Route53.RecordSet." + prop
    if ticked:
        values["desired.row.001-002.value"] = (
            "`" + values["desired.row.001-002.value"] + "`"
        )
    values["desired.reference.dns.valueSelector"] = f"dns-entry[{entry}].dns-name"
    inputs, prepared = prepare(models, extraction(entry=entry))
    desired = prepared.require_value()
    actual = imported(inputs)
    if isinstance(desired, Expression):
        desired = [desired]
    result = compare_values(
        desired,
        [actual],
        "ResourceRecords",
        rules=rules("Route53.RecordSet"),
        reference=partial(route_decision, inputs),
    )
    assert result.equal is True
    assert result.equivalent is True
    assert result.diagnostics[0]["runtime_bounds_verified"] is False


def test_identity_wrapper_reuses_expression_parts(models):
    inputs, prepared = prepare(models)
    (desired,) = prepared.require_value()
    actual = inputs.evaluate(
        "consumer", {"Fn::Join": ["", [{"Fn::ImportValue": "EndpointDnsTest"}]]}
    )
    assert (
        inputs.reference_same(desired, actual, "Route53.RecordSet", "ResourceRecords[]")
        is True
    )
    prefixed = inputs.evaluate(
        "consumer",
        {"Fn::Join": ["", ["prefix.", {"Fn::ImportValue": "EndpointDnsTest"}]]},
    )
    assert (
        inputs.reference_same(
            desired, prefixed, "Route53.RecordSet", "ResourceRecords[]"
        )
        is None
    )


@pytest.mark.parametrize("fault", ["producer", "scope", "overlap"])
def test_model_selection_cannot_override_saved_identity(models, fault):
    values = models[2]
    if fault == "producer":
        values["desired.reference.dns.producerLogicalId"] = "EC2_VPCEndpoint_002"
    elif fault == "scope":
        values["desired.reference.dns.producerScope"] = "qa/other/endpoint"
    else:
        values.update(
            {
                key.replace(
                    "desired.reference.dns.", "desired.reference.duplicate."
                ): value
                for key, value in tuple(values.items())
                if key.startswith("desired.reference.dns.")
            }
        )
    _, prepared = prepare(models)
    with pytest.raises(Blocked):
        prepared.require_value()


@pytest.mark.parametrize(
    "fault", ["missing", "ambiguous", "scope", "same-stack", "incomplete"]
)
def test_export_proof_required(models, fault):
    inputs, _ = prepare(models)
    if fault == "missing":
        inputs.stack_inputs["producer"][0]["Outputs"] = {}
    elif fault == "ambiguous":
        inputs.stack_inputs["consumer"][0]["Outputs"] = copy.deepcopy(
            inputs.stack_inputs["producer"][0]["Outputs"]
        )
        inputs.stack_inputs["consumer"][1]["Suffix"] = "Test"
    elif fault == "scope":
        document, parameters, pseudo = inputs.stack_inputs["consumer"]
        inputs.stack_inputs["consumer"] = (
            document,
            parameters,
            dict(pseudo, **{"AWS::AccountId": "999999999999"}),
        )
    elif fault == "same-stack":
        inputs.stack_inputs["consumer"][0]["Outputs"] = inputs.stack_inputs["producer"][
            0
        ].pop("Outputs")
        inputs.stack_inputs["consumer"][1]["Suffix"] = "Test"
    else:
        inputs.stack_inputs["producer"][0]["Transform"] = "Unresolved"
    with pytest.raises(Blocked, match="ImportValue"):
        imported(inputs)


@pytest.mark.parametrize("record_type", ["A", "TXT", "MX"])
def test_cname_only(models, record_type):
    models[2]["desired.row.001-001.value"] = "`" + record_type + "`"
    inputs, prepared = prepare(models)
    with pytest.raises(Blocked, match="Type=CNAME"):
        prepared.require_value()
    assert (
        route53.selected_decision(
            inputs,
            "literal",
            "literal",
            "ResourceRecords[]",
            export_origins=lambda *args: [],
        )
        is NotImplemented
    )


@pytest.mark.parametrize(
    "fault",
    [
        "record-type",
        "endpoint-type",
        "model-endpoint-type",
        "unproven-provenance",
        "attribute",
    ],
)
def test_runtime_contract_failures_stay_uncompared(models, fault):
    inputs, prepared = prepare(models)
    (desired,) = prepared.require_value()
    actual = imported(inputs)
    if fault == "record-type":
        inputs.stack_inputs["consumer"][0]["Resources"]["Policy"]["Properties"][
            "Type"
        ] = "A"
    elif fault == "endpoint-type":
        inputs.stack_inputs["producer"][0]["Resources"]["Resource001"]["Properties"][
            "VpcEndpointType"
        ] = "Gateway"
    elif fault == "model-endpoint-type":
        snapshot = inputs.models["endpoint"]
        inputs.models["endpoint"] = SimpleNamespace(
            authoritative=dict(
                snapshot.authoritative, **{"desired.row.001-001.value": "`Gateway`"}
            )
        )
    elif fault == "unproven-provenance":
        inputs.export_provenance.clear()
    else:
        actual = Expression(
            "Select",
            [
                1,
                Expression(
                    "Split",
                    [
                        ":",
                        Expression(
                            "Select",
                            [0, inputs.symbol("producer", "Resource001", "Id")],
                        ),
                    ],
                ),
            ],
        )
    assert (
        inputs.reference_same(desired, actual, "Route53.RecordSet", "ResourceRecords[]")
        is None
    )


@pytest.mark.parametrize(
    "selector",
    ["", "dns-entry[].dns-name", "dns-entry[-1].dns-name", "dns-entry[01].dns-name"],
)
def test_selector_validation(models, selector):
    values = dict(models[2], **{"desired.reference.dns.valueSelector": selector})
    with pytest.raises(ValueError, match="valueSelector"):
        declarations(values)


def test_selector_is_preserved_in_symbolic_meaning(models):
    root, scope, values = models
    before = symbolic(load_model(scope))
    values["desired.reference.dns.valueSelector"] = "dns-entry[1].dns-name"
    save(scope, values)
    after = symbolic(load_model(scope))
    assert before["desired.row.001-002.value"] != after["desired.row.001-002.value"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_direct_same_stack_selection(models):
    root, _, values = models
    endpoint = load_model(root / "model/qa/team/endpoint.properties").authoritative
    endpoint = dict(endpoint)
    endpoint["desired.resource.001.cfn-logicalId"] = "consumer-Resource001"
    save(Scope(root, "qa", "team", "endpoint"), endpoint)
    inputs, prepared = prepare(models)
    inputs.stack_inputs["consumer"][0]["Resources"]["Resource001"] = {
        "Type": "AWS::EC2::VPCEndpoint",
        "Properties": {"VpcEndpointType": "Interface"},
    }
    desired = prepared.require_value()[0]
    actual = inputs.evaluate_for_comparison("consumer", extraction())
    decision = inputs.reference_decision(
        desired, actual, "Route53.RecordSet", "ResourceRecords[]"
    )
    assert decision.equal is True
    settings = Settings(
        desired={"ResourceRecords": [desired]}, sources={"ResourceRecords": [{}]}
    )
    owner = inputs.stack_inputs["consumer"][0]["Resources"]["Policy"]
    owner["Properties"]["ResourceRecords"] = [extraction()]
    result = inputs.compare_setting(
        "dns",
        "001",
        "Route53.RecordSet",
        "ResourceRecords",
        [desired],
        settings,
        "consumer",
        owner,
        root / "synthetic.yaml",
    )
    assert [row["category"] for row in result.records] == ["matched"], result.records
    assert decision.diagnostics[0]["runtime_bounds_verified"] is False
    assert decision.diagnostics[0]["current_aws_verified"] is False
    assert decision.diagnostics[0]["structural_equivalence"] is True
    assert decision.diagnostics[0]["direct"][0]["stack"] == "consumer"


@pytest.mark.parametrize(
    "fault,category",
    [
        ("index", "difference"),
        ("delimiter", "difference"),
        ("field", "difference"),
        ("attribute", "difference"),
        ("producer", "difference"),
        ("endpoint-type", "uncompared"),
        ("missing-producer", "uncompared"),
    ],
)
def test_direct_comparison_setting_failures(models, fault, category):
    root, _, _ = models
    endpoint = dict(
        load_model(root / "model/qa/team/endpoint.properties").authoritative
    )
    endpoint["desired.resource.001.cfn-logicalId"] = "consumer-Resource001"
    endpoint["desired.resource.002.cfn-logicalId"] = "consumer-Resource002"
    save(Scope(root, "qa", "team", "endpoint"), endpoint)
    inputs, prepared = prepare(models)
    resources = inputs.stack_inputs["consumer"][0]["Resources"]
    resources["Resource001"] = {
        "Type": "AWS::EC2::VPCEndpoint",
        "Properties": {"VpcEndpointType": "Interface"},
    }
    resources["Resource002"] = copy.deepcopy(resources["Resource001"])
    desired = prepared.require_value()[0]
    expression = extraction(
        entry=1 if fault == "index" else 0,
        delimiter="|" if fault == "delimiter" else ":",
        field=0 if fault == "field" else 1,
        logical="Absent"
        if fault == "missing-producer"
        else "Resource002"
        if fault == "producer"
        else "Resource001",
        attribute="NetworkInterfaceIds" if fault == "attribute" else "DnsEntries",
    )
    if fault == "endpoint-type":
        resources["Resource001"]["Properties"]["VpcEndpointType"] = "Gateway"
    owner = resources["Policy"]
    owner["Properties"]["ResourceRecords"] = [expression]
    settings = Settings(
        desired={"ResourceRecords": [desired]}, sources={"ResourceRecords": [{}]}
    )
    result = inputs.compare_setting(
        "dns",
        "001",
        "Route53.RecordSet",
        "ResourceRecords",
        [desired],
        settings,
        "consumer",
        owner,
        root / "synthetic.yaml",
    )
    assert [row["category"] for row in result.records] == [category], result.records


def test_direct_cross_stack_is_unproven(models):
    inputs, prepared = prepare(models)
    desired = prepared.require_value()[0]
    actual = inputs.evaluate_for_comparison("producer", extraction())
    result = inputs.reference_decision(
        desired, actual, "Route53.RecordSet", "ResourceRecords[]"
    )
    assert result.equal is None
    assert "stack is unproven" in result.diagnostics[0]["reason"]
