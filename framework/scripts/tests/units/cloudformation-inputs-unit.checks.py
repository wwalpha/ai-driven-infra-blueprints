"""Pure CloudFormation input evaluation; no AWS or repository Model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock

import pytest
from support.cloudformation_inputs_fixtures import condition_document
from support.regression_cases import case_ids
from utils.cloudformation.inputs import (
    Blocked,
    checked_parameters,
    condition_active,
    load_template_inputs,
)

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def parameter_case(case):
    document = case["data"]["document"]
    before = deepcopy(document)
    definition = document["Parameters"]["Extra"]
    defaults = checked_parameters(document, [])
    explicit = checked_parameters(
        document, [{"ParameterKey": "Extra", "ParameterValue": definition["Default"]}]
    )
    TestCase().assertEqual(defaults, explicit)
    TestCase().assertEqual(document, before)
    kind, value = definition["Type"], defaults["Extra"]
    if kind == "String":
        TestCase().assertIs(type(value), str)
    elif kind == "Number":
        TestCase().assertIn(type(value), (int, float))
    else:
        TestCase().assertIs(type(value), list)
        for item in value:
            TestCase().assertIn(
                type(item), (int, float) if kind == "List<Number>" else (str,)
            )
    return {"defaults": defaults, "explicit": explicit}


@pytest.mark.parametrize(
    "case_id", case_ids("cloudformation_inputs", prefix="parameter-")
)
def check_parameters(case_runner, case_id):
    case_runner.run("cloudformation_inputs", case_id, parameter_case)


def definition_error_case(case):
    data = case["data"]
    before = deepcopy(data)
    with pytest.raises(ValueError, match=data["reason"]) as caught:
        checked_parameters(data["document"], [])
    TestCase().assertEqual(data, before)
    return {"error": type(caught.value).__name__, "message": str(caught.value)}


@pytest.mark.parametrize(
    "case_id", case_ids("cloudformation_inputs", prefix="definition-error-")
)
def check_parameter_definitions(case_runner, case_id):
    case_runner.run("cloudformation_inputs", case_id, definition_error_case)


def parameter_file_error_case(case):
    data = case["data"]
    before = deepcopy(case)
    parameter_file = Mock()
    parameter_file.read_text.return_value = case["files"]["parameters.json"]
    with pytest.raises(ValueError, match=data["reason"]) as caught:
        load_template_inputs(
            None, parameter_file, strict_parameters=True, document=data["document"]
        )
    parameter_file.read_text.assert_called_once_with(encoding="utf-8")
    TestCase().assertEqual(case, before)
    return {"error": type(caught.value).__name__, "message": str(caught.value)}


@pytest.mark.parametrize(
    "case_id", case_ids("cloudformation_inputs", prefix="file-error-")
)
def check_parameter_files(case_runner, case_id):
    case_runner.run("cloudformation_inputs", case_id, parameter_file_error_case)


def check_deploy_parameter_inputs_remain_permissive():
    parameter_file = Mock()
    parameter_file.read_text.return_value = "[]"
    TestCase().assertEqual(
        load_template_inputs(
            None,
            parameter_file,
            document={"Parameters": {"Extra": {"Type": "Number", "Default": "7"}}},
        )[1],
        {"Extra": "7"},
    )


def check_conditions():
    for condition in ("IsEnabled", "Combined", "Branch", "SubOff"):
        assert (
            condition_active(
                condition_document,
                {"Enable": "false", "Other": "yes"},
                {},
                {"Condition": condition},
            )
            is False
        )
    for condition in ("IsEnabled", "Combined"):
        assert (
            condition_active(
                condition_document,
                {"Enable": "true", "Other": "yes"},
                {},
                {"Condition": condition},
            )
            is True
        )
    for expression, reason in [
        ({"Condition": "Missing"}, "unresolved"),
        ({"Condition": "Broken"}, "cyclic"),
        ("false", "non-boolean"),
        ({"Fn::Equals": [{"Ref": "Unknown"}, "x"]}, "unsupported"),
    ]:
        with pytest.raises(Blocked, match=reason):
            condition_active(
                {"Conditions": {"Broken": expression}}, {}, {}, {"Condition": "Broken"}
            )


@pytest.mark.parametrize("position", ["template", "encoded", "parameter"])
@pytest.mark.parametrize("strict", [False, True])
def check_deploy_input_rejects_design_nodes(tmp_path, position, strict):
    template = tmp_path / "template.json"
    parameters = tmp_path / "parameters.json"
    node = {"$modelRef": {"logicalId": "KMS_Key_001", "attribute": "Arn"}}
    document = {"Resources": {"Role": {"Type": "AWS::IAM::Role", "Properties": {}}}}
    inputs = []
    if position == "parameter":
        inputs = [{"ParameterKey": "Policy", "ParameterValue": json.dumps(node)}]
    else:
        document["Resources"]["Role"]["Properties"]["AssumeRolePolicyDocument"] = (
            json.dumps(node) if position == "encoded" else node
        )
    template.write_text(json.dumps(document), encoding="utf-8")
    parameters.write_text(json.dumps(inputs), encoding="utf-8")
    with pytest.raises(ValueError, match="Model reference"):
        load_template_inputs(template, parameters, strict_parameters=strict)


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__, message="CloudFormation inputs: PASS"))
